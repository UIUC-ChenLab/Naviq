// Overloaded NAT / PAT block with explicit TX and RX packet streams.

`include "ifc_axis.sv"
`include "ifc_axil.sv"
`include "parser_pkg.sv"

import parser_pkg::*;
import pat_pkg::*;

module overloaded_nat #(
    parameter int TABLE_DEPTH   = 1024,
    parameter int TABLE_ENTRIES = 256,
    parameter int DATA_WIDTH    = 512,
    parameter int PKT_BUF_DEPTH = 0,
    parameter int PKT_BUF_BYTES = 4096,
    parameter int ASSOCIATIVITY = 4,
    parameter bit EXTRA_OUTPUT_REG = 1'b0
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  tx_packet_in,
    ifc_axis.slave  rx_packet_in,
    ifc_axil.slave  ctrl_in,
    ifc_axis.master tx_packet_out,
    ifc_axis.master rx_packet_out
);

    /* verilator lint_off VARHIDDEN */
    localparam int NUM_ENTRIES  = TABLE_ENTRIES;
    localparam int ENTRY_ID_W   = $clog2(NUM_ENTRIES);
    localparam int BUCKET_IDX_W = $clog2(TABLE_DEPTH);
    /* verilator lint_on VARHIDDEN */
    localparam int KEEP_WIDTH   = DATA_WIDTH / 8;
    localparam int RAW_AUTO_PKT_BUF_DEPTH = (PKT_BUF_BYTES + KEEP_WIDTH - 1) / KEEP_WIDTH;
    localparam int AUTO_PKT_BUF_DEPTH = (RAW_AUTO_PKT_BUF_DEPTH < 2) ? 2 : RAW_AUTO_PKT_BUF_DEPTH;
    localparam int EFFECTIVE_PKT_BUF_DEPTH = (PKT_BUF_DEPTH > 0) ? PKT_BUF_DEPTH : AUTO_PKT_BUF_DEPTH;
    localparam int TUPLE_BITS   = 104;
    localparam int L2_HDR_W     = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int L3_HDR_W     = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_W     = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int AXIS_SIDEBAND_WIDTH = 1;
    // CONSERVATIVE mode reserves one physical entry for registered-ready
    // safety. Add that entry while preserving the configured usable depth.
    localparam int FIFO_DEPTH_MARGIN = 1;

    initial begin
        if (DATA_WIDTH != 256 && DATA_WIDTH != 512) begin
            $error("overloaded_nat: DATA_WIDTH must be 256 or 512, got %0d", DATA_WIDTH);
            $finish;
        end
        if ($bits(tx_packet_in.t.data) != DATA_WIDTH || $bits(rx_packet_in.t.data) != DATA_WIDTH ||
            $bits(tx_packet_out.t.data) != DATA_WIDTH || $bits(rx_packet_out.t.data) != DATA_WIDTH) begin
            $error("overloaded_nat: packet AXIS data widths must equal DATA_WIDTH");
            $finish;
        end
        if ($bits(tx_packet_in.t.keep) != KEEP_WIDTH || $bits(rx_packet_in.t.keep) != KEEP_WIDTH) begin
            $error("overloaded_nat: packet AXIS keep widths must equal DATA_WIDTH/8");
            $finish;
        end
        if ($bits(tx_packet_in.t.id) != AXIS_SIDEBAND_WIDTH ||
            $bits(rx_packet_in.t.id) != AXIS_SIDEBAND_WIDTH ||
            $bits(tx_packet_out.t.id) != AXIS_SIDEBAND_WIDTH ||
            $bits(rx_packet_out.t.id) != AXIS_SIDEBAND_WIDTH ||
            $bits(tx_packet_in.t.dest) != AXIS_SIDEBAND_WIDTH ||
            $bits(rx_packet_in.t.dest) != AXIS_SIDEBAND_WIDTH ||
            $bits(tx_packet_out.t.dest) != AXIS_SIDEBAND_WIDTH ||
            $bits(rx_packet_out.t.dest) != AXIS_SIDEBAND_WIDTH ||
            $bits(tx_packet_in.t.user) != AXIS_SIDEBAND_WIDTH ||
            $bits(rx_packet_in.t.user) != AXIS_SIDEBAND_WIDTH ||
            $bits(tx_packet_out.t.user) != AXIS_SIDEBAND_WIDTH ||
            $bits(rx_packet_out.t.user) != AXIS_SIDEBAND_WIDTH) begin
            $error("overloaded_nat: packet AXIS id/dest/user widths must all equal 1");
            $finish;
        end
        if (EFFECTIVE_PKT_BUF_DEPTH < 2) begin
            $error("overloaded_nat: effective packet buffer depth must be >= 2");
            $finish;
        end
    end

    // ---------------------------------------------------------------------
    // CSR
    // ---------------------------------------------------------------------
    logic [31:0] csr_public_ip;
    logic [15:0] csr_base_port;
    logic [15:0] csr_timeout;
    logic        csr_enable;
    logic [15:0] csr_timestamp;
    logic        status_free_empty;
    logic [11:0] status_active_entries;
    logic        cnt_fwd_hit, cnt_fwd_miss, cnt_rev_hit, cnt_rev_miss;
    logic        cnt_bypass_tx, cnt_bypass_rx;

    pat_csr u_csr (
        .clk                  (clk),
        .resetn               (resetn),
        .ctrl                 (ctrl_in),
        .csr_public_ip        (csr_public_ip),
        .csr_base_port        (csr_base_port),
        .csr_timeout          (csr_timeout),
        .csr_enable           (csr_enable),
        .status_free_empty    (status_free_empty),
        .status_active_entries(status_active_entries),
        .cnt_fwd_hit          (cnt_fwd_hit),
        .cnt_fwd_miss         (cnt_fwd_miss),
        .cnt_rev_hit          (cnt_rev_hit),
        .cnt_rev_miss         (cnt_rev_miss),
        .cnt_bypass           (cnt_bypass_tx || cnt_bypass_rx),
        .csr_timestamp        (csr_timestamp)
    );

    assign status_active_entries = '0;

    // ---------------------------------------------------------------------
    // Packet fanout: raw packet buffer + parser + IPv4 classifier.
    // ---------------------------------------------------------------------
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        tx_fanout [2] (.axis_aclk(clk)), rx_fanout [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        tx_buf_out (.axis_aclk(clk)), rx_buf_out (.axis_aclk(clk));

    axis_multicast #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1), .NUM_DESTS(2)
    ) u_tx_fanout (
        .clk(clk), .resetn(resetn), .s_axis(tx_packet_in), .m_axis(tx_fanout)
    );

    axis_multicast #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1), .NUM_DESTS(2)
    ) u_rx_fanout (
        .clk(clk), .resetn(resetn), .s_axis(rx_packet_in), .m_axis(rx_fanout)
    );

    axis_fifo #(
        .DEPTH(EFFECTIVE_PKT_BUF_DEPTH + FIFO_DEPTH_MARGIN),
        .USE_BRAM(1'b1), .MODE("CONSERVATIVE")
    ) u_tx_pkt_buf (
        .clk(clk), .resetn(resetn), .s_axis(tx_fanout[0]), .m_axis(tx_buf_out.master)
    );
    axis_fifo #(
        .DEPTH(EFFECTIVE_PKT_BUF_DEPTH + FIFO_DEPTH_MARGIN),
        .USE_BRAM(1'b1), .MODE("CONSERVATIVE")
    ) u_rx_pkt_buf (
        .clk(clk), .resetn(resetn), .s_axis(rx_fanout[0]), .m_axis(rx_buf_out.master)
    );

    ifc_axis #(.DATA_WIDTH(L2_HDR_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        tx_l2_header_unused (.axis_aclk(clk)), rx_l2_header_unused (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_HDR_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        tx_l3_header_raw (.axis_aclk(clk)), rx_l3_header_raw (.axis_aclk(clk)),
        tx_l3_header (.axis_aclk(clk)), rx_l3_header (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        tx_l4_header_raw (.axis_aclk(clk)), rx_l4_header_raw (.axis_aclk(clk)),
        tx_l4_header (.axis_aclk(clk)), rx_l4_header (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        tx_parser_payload_unused (.axis_aclk(clk)), rx_parser_payload_unused (.axis_aclk(clk));

    parser #(
        .DATA_WIDTH        (DATA_WIDTH),
        .SKIP_L2           (1'b1),
        .DEFAULT_ETHERTYPE (16'h0800)
    ) u_tx_parser (
        .clk(clk), .resetn(resetn),
        .s_axis_packet_in(tx_fanout[1]),
        .m_axis_l2_header_out(tx_l2_header_unused),
        .m_axis_l3_header_out(tx_l3_header_raw),
        .m_axis_l4_header_out(tx_l4_header_raw),
        .m_axis_payload_out(tx_parser_payload_unused)
    );
    parser #(
        .DATA_WIDTH        (DATA_WIDTH),
        .SKIP_L2           (1'b1),
        .DEFAULT_ETHERTYPE (16'h0800)
    ) u_rx_parser (
        .clk(clk), .resetn(resetn),
        .s_axis_packet_in(rx_fanout[1]),
        .m_axis_l2_header_out(rx_l2_header_unused),
        .m_axis_l3_header_out(rx_l3_header_raw),
        .m_axis_l4_header_out(rx_l4_header_raw),
        .m_axis_payload_out(rx_parser_payload_unused)
    );

    axis_fifo #(
        .DEPTH(128 + FIFO_DEPTH_MARGIN), .USE_BRAM(1'b1), .MODE("CONSERVATIVE")
    ) u_tx_l3_header_fifo (
        .clk(clk), .resetn(resetn), .s_axis(tx_l3_header_raw.slave), .m_axis(tx_l3_header.master)
    );
    axis_fifo #(
        .DEPTH(128 + FIFO_DEPTH_MARGIN), .USE_BRAM(1'b1), .MODE("CONSERVATIVE")
    ) u_tx_l4_header_fifo (
        .clk(clk), .resetn(resetn), .s_axis(tx_l4_header_raw.slave), .m_axis(tx_l4_header.master)
    );
    axis_fifo #(
        .DEPTH(128 + FIFO_DEPTH_MARGIN), .USE_BRAM(1'b1), .MODE("CONSERVATIVE")
    ) u_rx_l3_header_fifo (
        .clk(clk), .resetn(resetn), .s_axis(rx_l3_header_raw.slave), .m_axis(rx_l3_header.master)
    );
    axis_fifo #(
        .DEPTH(128 + FIFO_DEPTH_MARGIN), .USE_BRAM(1'b1), .MODE("CONSERVATIVE")
    ) u_rx_l4_header_fifo (
        .clk(clk), .resetn(resetn), .s_axis(rx_l4_header_raw.slave), .m_axis(rx_l4_header.master)
    );

    assign tx_l2_header_unused.tready = 1'b1;
    assign rx_l2_header_unused.tready = 1'b1;
    assign tx_parser_payload_unused.tready = 1'b1;
    assign rx_parser_payload_unused.tready = 1'b1;

    // ---------------------------------------------------------------------
    // Header decode, strict lookup pipelines, and rewrite commands.
    // ---------------------------------------------------------------------
    localparam int CTRL_FIFO_DEPTH = 32;

    typedef struct packed {
        logic        bypass;
        logic [7:0]  protocol;
        logic [31:0] src_ip;
        logic [15:0] src_port;
        logic [31:0] dst_ip;
        logic [15:0] dst_port;
        logic [TUPLE_BITS-1:0] key;
        logic [BUCKET_IDX_W-1:0] hash;
    } req_t;

    typedef struct packed {
        logic        bypass;
        logic        hit;
        logic [31:0] ip;
        logic [15:0] port;
    } cmd_t;

    typedef struct packed {
        logic [ENTRY_ID_W-1:0] entry_id;
        logic [31:0]           private_ip;
        logic [15:0]           private_port;
    } rev_value_t;

    localparam int REV_VALUE_W = $bits(rev_value_t);

    l3_hdr_axis_t tx_l3_dec, rx_l3_dec;
    l4_hdr_axis_t tx_l4_dec, rx_l4_dec;
    ipv4_hdr_t tx_ipv4_dec, rx_ipv4_dec;
    tcp_hdr_t  tx_tcp_dec,  rx_tcp_dec;
    udp_hdr_t  tx_udp_dec,  rx_udp_dec;

    assign tx_l3_dec   = l3_hdr_axis_t'(tx_l3_header.t.data);
    assign tx_l4_dec   = l4_hdr_axis_t'(tx_l4_header.t.data);
    assign rx_l3_dec   = l3_hdr_axis_t'(rx_l3_header.t.data);
    assign rx_l4_dec   = l4_hdr_axis_t'(rx_l4_header.t.data);
    assign tx_ipv4_dec = tx_l3_dec.ipv4;
    assign tx_tcp_dec  = tx_l4_dec.tcp;
    assign tx_udp_dec  = tx_l4_dec.udp;
    assign rx_ipv4_dec = rx_l3_dec.ipv4;
    assign rx_tcp_dec  = rx_l4_dec.tcp;
    assign rx_udp_dec  = rx_l4_dec.udp;

    logic [15:0] tx_hdr_src_port, tx_hdr_dst_port, rx_hdr_src_port, rx_hdr_dst_port;
    assign tx_hdr_src_port = (tx_l4_dec.kind == L4_KIND_TCP) ? tx_tcp_dec.src_port : tx_udp_dec.src_port;
    assign tx_hdr_dst_port = (tx_l4_dec.kind == L4_KIND_TCP) ? tx_tcp_dec.dst_port : tx_udp_dec.dst_port;
    assign rx_hdr_src_port = (rx_l4_dec.kind == L4_KIND_TCP) ? rx_tcp_dec.src_port : rx_udp_dec.src_port;
    assign rx_hdr_dst_port = (rx_l4_dec.kind == L4_KIND_TCP) ? rx_tcp_dec.dst_port : rx_udp_dec.dst_port;

    logic [TUPLE_BITS-1:0] tx_tuple_w, rx_tuple_w, tx_rev_tuple_w;
    logic [BUCKET_IDX_W-1:0] tx_hash_w, rx_hash_w, tx_rev_hash_w;
    assign tx_tuple_w = {tx_ipv4_dec.protocol, tx_hdr_dst_port, tx_hdr_src_port,
                         tx_ipv4_dec.dst_addr, tx_ipv4_dec.src_addr};
    assign rx_tuple_w = {rx_ipv4_dec.protocol, rx_hdr_dst_port, rx_hdr_src_port,
                         rx_ipv4_dec.dst_addr, rx_ipv4_dec.src_addr};

    toeplitz_hash #(.HASH_WIDTH(BUCKET_IDX_W), .TUPLE_WIDTH(TUPLE_BITS)) u_tx_hash (
        .tuple_bits(tx_tuple_w), .hash_value(tx_hash_w)
    );
    toeplitz_hash #(.HASH_WIDTH(BUCKET_IDX_W), .TUPLE_WIDTH(TUPLE_BITS)) u_rx_hash (
        .tuple_bits(rx_tuple_w), .hash_value(rx_hash_w)
    );

    wire tx_header_eligible = (tx_l3_dec.status == PARSER_STATUS_OK)
        && (tx_l3_dec.kind == L3_KIND_IPV4)
        && (tx_l4_dec.status != PARSER_STATUS_SHORT)
        && ((tx_l4_dec.kind == L4_KIND_TCP) || (tx_l4_dec.kind == L4_KIND_UDP));
    wire rx_header_eligible = (rx_l3_dec.status == PARSER_STATUS_OK)
        && (rx_l3_dec.kind == L3_KIND_IPV4)
        && (rx_l4_dec.status != PARSER_STATUS_SHORT)
        && ((rx_l4_dec.kind == L4_KIND_TCP) || (rx_l4_dec.kind == L4_KIND_UDP));

    req_t tx_req_push_data, rx_req_push_data;
    logic tx_req_push_valid, tx_req_push_ready, rx_req_push_valid, rx_req_push_ready;
    req_t tx_req_pop_data, rx_req_pop_data;
    logic tx_req_pop_valid, tx_req_pop_ready, rx_req_pop_valid, rx_req_pop_ready;
    req_t tx_ctx_push_data, rx_ctx_push_data;
    logic tx_ctx_push_valid, tx_ctx_push_ready, rx_ctx_push_valid, rx_ctx_push_ready;
    req_t tx_ctx_pop_data, rx_ctx_pop_data;
    logic tx_ctx_pop_valid, tx_ctx_pop_ready, rx_ctx_pop_valid, rx_ctx_pop_ready;
    cmd_t tx_cmd_push_data, rx_cmd_push_data;
    logic tx_cmd_push_valid, tx_cmd_push_ready, rx_cmd_push_valid, rx_cmd_push_ready;
    cmd_t tx_cmd_pop_data, rx_cmd_pop_data;
    logic tx_cmd_pop_valid, tx_cmd_pop_ready, rx_cmd_pop_valid, rx_cmd_pop_ready;
    logic fwd_lookup_valid, fwd_lookup_ready, fwd_result_valid, fwd_result_ready, fwd_result_hit;
    logic [ENTRY_ID_W-1:0] fwd_result_value;
    logic rev_lookup_valid, rev_lookup_ready, rev_result_valid, rev_result_ready, rev_result_hit;
    logic [REV_VALUE_W-1:0] rev_result_value;
    rev_value_t rev_result_dec;
    logic [NUM_ENTRIES-1:0] entry_active_r;
    logic tx_miss_active;
    logic ag_busy;

    wire tx_req_bypass_w = !tx_header_eligible || !csr_enable || (tx_ipv4_dec.ihl != 4'd5) ||
                           (tx_ipv4_dec.fragment_offset != '0);
    wire rx_req_bypass_w = !rx_header_eligible || !csr_enable || (rx_ipv4_dec.ihl != 4'd5) ||
                           (rx_ipv4_dec.fragment_offset != '0);

    wire tx_headers_valid = tx_l3_header.tvalid && tx_l4_header.tvalid;
    wire rx_headers_valid = rx_l3_header.tvalid && rx_l4_header.tvalid;
    wire tx_headers_fire = tx_headers_valid && tx_req_push_ready;
    wire rx_headers_fire = rx_headers_valid && rx_req_push_ready;

    assign tx_l3_header.tready = tx_headers_fire;
    assign tx_l4_header.tready = tx_headers_fire;
    assign rx_l3_header.tready = rx_headers_fire;
    assign rx_l4_header.tready = rx_headers_fire;

    always_comb begin
        tx_req_push_data.bypass   = tx_req_bypass_w;
        tx_req_push_data.protocol = tx_ipv4_dec.protocol;
        tx_req_push_data.src_ip   = tx_ipv4_dec.src_addr;
        tx_req_push_data.src_port = tx_hdr_src_port;
        tx_req_push_data.dst_ip   = tx_ipv4_dec.dst_addr;
        tx_req_push_data.dst_port = tx_hdr_dst_port;
        tx_req_push_data.key      = tx_tuple_w;
        tx_req_push_data.hash     = tx_hash_w;

        rx_req_push_data.bypass   = rx_req_bypass_w;
        rx_req_push_data.protocol = rx_ipv4_dec.protocol;
        rx_req_push_data.src_ip   = rx_ipv4_dec.src_addr;
        rx_req_push_data.src_port = rx_hdr_src_port;
        rx_req_push_data.dst_ip   = rx_ipv4_dec.dst_addr;
        rx_req_push_data.dst_port = rx_hdr_dst_port;
        rx_req_push_data.key      = rx_tuple_w;
        rx_req_push_data.hash     = rx_hash_w;
    end

    assign tx_req_push_valid = tx_headers_valid;
    assign rx_req_push_valid = rx_headers_valid;

    sync_ff_fifo #(
        .DEPTH(CTRL_FIFO_DEPTH + FIFO_DEPTH_MARGIN), .T(req_t),
        .EXTRA_OUTPUT_REG(EXTRA_OUTPUT_REG),
        .MODE("CONSERVATIVE")
    ) u_tx_req_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(tx_req_push_valid), .push_data(tx_req_push_data), .push_ready(tx_req_push_ready),
        .pop_valid(tx_req_pop_valid), .pop_data(tx_req_pop_data), .pop_ready(tx_req_pop_ready)
    );
    sync_ff_fifo #(
        .DEPTH(CTRL_FIFO_DEPTH + FIFO_DEPTH_MARGIN), .T(req_t),
        .EXTRA_OUTPUT_REG(EXTRA_OUTPUT_REG),
        .MODE("CONSERVATIVE")
    ) u_rx_req_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(rx_req_push_valid), .push_data(rx_req_push_data), .push_ready(rx_req_push_ready),
        .pop_valid(rx_req_pop_valid), .pop_data(rx_req_pop_data), .pop_ready(rx_req_pop_ready)
    );
    sync_ff_fifo #(
        .DEPTH(CTRL_FIFO_DEPTH + FIFO_DEPTH_MARGIN), .T(req_t),
        .EXTRA_OUTPUT_REG(EXTRA_OUTPUT_REG),
        .MODE("CONSERVATIVE")
    ) u_tx_ctx_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(tx_ctx_push_valid), .push_data(tx_ctx_push_data), .push_ready(tx_ctx_push_ready),
        .pop_valid(tx_ctx_pop_valid), .pop_data(tx_ctx_pop_data), .pop_ready(tx_ctx_pop_ready)
    );
    sync_ff_fifo #(
        .DEPTH(CTRL_FIFO_DEPTH + FIFO_DEPTH_MARGIN), .T(req_t),
        .EXTRA_OUTPUT_REG(EXTRA_OUTPUT_REG),
        .MODE("CONSERVATIVE")
    ) u_rx_ctx_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(rx_ctx_push_valid), .push_data(rx_ctx_push_data), .push_ready(rx_ctx_push_ready),
        .pop_valid(rx_ctx_pop_valid), .pop_data(rx_ctx_pop_data), .pop_ready(rx_ctx_pop_ready)
    );

    assign rev_result_dec = rev_value_t'(rev_result_value);

    logic fwd_insert_valid, fwd_insert_ready, fwd_insert_done, fwd_insert_fail;
    logic [TUPLE_BITS-1:0] fwd_insert_key;
    logic [BUCKET_IDX_W-1:0] fwd_insert_hash;
    logic [ENTRY_ID_W-1:0] fwd_insert_value;
    logic rev_insert_valid, rev_insert_ready, rev_insert_done, rev_insert_fail;
    logic [TUPLE_BITS-1:0] rev_insert_key;
    logic [BUCKET_IDX_W-1:0] rev_insert_hash;
    logic [REV_VALUE_W-1:0] rev_insert_value;

    logic fwd_delete_valid, fwd_delete_ready, fwd_delete_done;
    logic [TUPLE_BITS-1:0] fwd_delete_key;
    logic [BUCKET_IDX_W-1:0] fwd_delete_hash;
    logic rev_delete_valid, rev_delete_ready, rev_delete_done;
    logic [TUPLE_BITS-1:0] rev_delete_key;
    logic [BUCKET_IDX_W-1:0] rev_delete_hash;

    pat_managed_hash_table #(
        .TABLE_DEPTH(TABLE_DEPTH), .KEY_WIDTH(TUPLE_BITS),
        .VALUE_WIDTH(ENTRY_ID_W), .ASSOCIATIVITY(ASSOCIATIVITY)
    ) u_fwd_table (
        .clk(clk), .resetn(resetn),
        .lookup_valid(fwd_lookup_valid), .lookup_ready(fwd_lookup_ready),
        .lookup_key(tx_req_pop_data.key), .lookup_hash(tx_req_pop_data.hash),
        .result_valid(fwd_result_valid), .result_ready(fwd_result_ready),
        .result_hit(fwd_result_hit), .result_value(fwd_result_value),
        .insert_valid(fwd_insert_valid), .insert_ready(fwd_insert_ready),
        .insert_key(fwd_insert_key), .insert_hash(fwd_insert_hash),
        .insert_value(fwd_insert_value), .insert_done(fwd_insert_done),
        .insert_fail(fwd_insert_fail),
        .delete_valid(fwd_delete_valid), .delete_ready(fwd_delete_ready),
        .delete_key(fwd_delete_key), .delete_hash(fwd_delete_hash),
        .delete_done(fwd_delete_done)
    );

    pat_managed_hash_table #(
        .TABLE_DEPTH(TABLE_DEPTH), .KEY_WIDTH(TUPLE_BITS),
        .VALUE_WIDTH(REV_VALUE_W), .ASSOCIATIVITY(ASSOCIATIVITY)
    ) u_rev_table (
        .clk(clk), .resetn(resetn),
        .lookup_valid(rev_lookup_valid), .lookup_ready(rev_lookup_ready),
        .lookup_key(rx_req_pop_data.key), .lookup_hash(rx_req_pop_data.hash),
        .result_valid(rev_result_valid), .result_ready(rev_result_ready),
        .result_hit(rev_result_hit), .result_value(rev_result_value),
        .insert_valid(rev_insert_valid), .insert_ready(rev_insert_ready),
        .insert_key(rev_insert_key), .insert_hash(rev_insert_hash),
        .insert_value(rev_insert_value), .insert_done(rev_insert_done),
        .insert_fail(rev_insert_fail),
        .delete_valid(rev_delete_valid), .delete_ready(rev_delete_ready),
        .delete_key(rev_delete_key), .delete_hash(rev_delete_hash),
        .delete_done(rev_delete_done)
    );

    localparam int META_BITS = $bits(entry_meta_t);

    logic                   meta_clear_active_r;
    logic [ENTRY_ID_W-1:0]  meta_clear_addr_r;
    logic [META_BITS-1:0]   meta_a_rdata_unused, meta_b_rdata_bits;
    logic                   meta_b_we;
    logic [ENTRY_ID_W-1:0]  meta_b_addr;
    entry_meta_t            meta_b_wdata, meta_b_rdata;

    true_dual_port_bram #(
        .BRAM_WIDTH(META_BITS), .BRAM_DEPTH(NUM_ENTRIES),
        .INIT_VALID_ZERO(1'b1), .VALID_BIT_INDEX(META_BITS - 1)
    ) u_entry_meta (
        .clk(clk),
        .we_a(resetn && meta_clear_active_r), .addr_a(meta_clear_addr_r),
        .din_a('0), .dout_a(meta_a_rdata_unused),
        .we_b(meta_b_we && !meta_clear_active_r), .addr_b(meta_b_addr),
        .din_b(meta_b_wdata), .dout_b(meta_b_rdata_bits)
    );

    assign meta_b_rdata = entry_meta_t'(meta_b_rdata_bits);

    // Preserve soft-reset behavior by clearing one metadata entry per cycle.
    // Port A can be reused for lookup-side timestamp refresh once the sweep ends.
    always_ff @(posedge clk) begin
        if (!resetn) begin
            meta_clear_active_r <= 1'b1;
            meta_clear_addr_r <= '0;
        end else if (meta_clear_active_r) begin
            if (meta_clear_addr_r == ENTRY_ID_W'(NUM_ENTRIES - 1)) begin
                meta_clear_active_r <= 1'b0;
            end else begin
                meta_clear_addr_r <= meta_clear_addr_r + 1'b1;
            end
        end
    end

    logic fl_alloc_valid, fl_alloc_ready;
    logic [ENTRY_ID_W-1:0] fl_alloc_id;
    logic fl_free_valid, fl_free_ready;
    logic [ENTRY_ID_W-1:0] fl_free_id;

    pat_free_list #(.NUM_ENTRIES(NUM_ENTRIES)) u_free_list (
        .clk(clk), .resetn(resetn),
        .alloc_valid(fl_alloc_valid), .alloc_ready(fl_alloc_ready),
        .alloc_id(fl_alloc_id),
        .free_valid(fl_free_valid), .free_ready(fl_free_ready),
        .free_id(fl_free_id),
        .empty(status_free_empty)
    );

    typedef enum logic [2:0] {
        TXM_IDLE, TXM_ALLOC, TXM_WRITE_META, TXM_INS_FWD, TXM_INS_REV, TXM_ISSUE
    } tx_miss_state_t;
    tx_miss_state_t tx_miss_state_r;
    req_t tx_miss_req_r;
    logic [ENTRY_ID_W-1:0] tx_miss_eid_r;
    logic tx_miss_drop_r;
    logic [15:0] tx_public_port_w;
    logic [31:0] tx_public_ip_r;
    rev_value_t tx_rev_insert_value_w;

    assign tx_public_port_w = csr_base_port + {{(16-ENTRY_ID_W){1'b0}}, tx_miss_eid_r};
    assign tx_rev_tuple_w = {tx_miss_req_r.protocol, tx_public_port_w, tx_miss_req_r.dst_port,
                             tx_public_ip_r, tx_miss_req_r.dst_ip};
    assign tx_rev_insert_value_w = '{
        entry_id: tx_miss_eid_r,
        private_ip: tx_miss_req_r.src_ip,
        private_port: tx_miss_req_r.src_port
    };

    toeplitz_hash #(.HASH_WIDTH(BUCKET_IDX_W), .TUPLE_WIDTH(TUPLE_BITS)) u_tx_rev_hash (
        .tuple_bits(tx_rev_tuple_w), .hash_value(tx_rev_hash_w)
    );

    logic tx_rw_valid, tx_rw_ready, tx_rw_bypass, tx_rw_hit;
    logic [31:0] tx_rw_ip;
    logic [15:0] tx_rw_port;
    logic rx_rw_valid, rx_rw_ready, rx_rw_bypass, rx_rw_hit;
    logic [31:0] rx_rw_ip;
    logic [15:0] rx_rw_port;

    pat_rewrite #(.DATA_WIDTH(DATA_WIDTH)) u_tx_rewrite (
        .clk(clk), .resetn(resetn), .pkt_in(tx_buf_out.slave),
        .rw_valid(tx_rw_valid), .rw_ready(tx_rw_ready),
        .rw_is_outbound(1'b1), .rw_is_bypass(tx_rw_bypass),
        .rw_hit(tx_rw_hit), .rw_new_ip(tx_rw_ip),
        .rw_new_port(tx_rw_port), .pkt_out(tx_packet_out)
    );
    pat_rewrite #(.DATA_WIDTH(DATA_WIDTH)) u_rx_rewrite (
        .clk(clk), .resetn(resetn), .pkt_in(rx_buf_out.slave),
        .rw_valid(rx_rw_valid), .rw_ready(rx_rw_ready),
        .rw_is_outbound(1'b0), .rw_is_bypass(rx_rw_bypass),
        .rw_hit(rx_rw_hit), .rw_new_ip(rx_rw_ip),
        .rw_new_port(rx_rw_port), .pkt_out(rx_packet_out)
    );

    assign tx_miss_active = (tx_miss_state_r != TXM_IDLE);
    wire tx_lookup_issue_ok = !tx_miss_active && !ag_busy;
    wire rx_lookup_issue_ok = !ag_busy;

    assign fwd_lookup_valid = tx_req_pop_valid && tx_ctx_push_ready && tx_lookup_issue_ok;
    assign tx_req_pop_ready = fwd_lookup_ready && tx_ctx_push_ready && tx_lookup_issue_ok;
    assign tx_ctx_push_valid = tx_req_pop_valid && fwd_lookup_ready && tx_lookup_issue_ok;
    assign tx_ctx_push_data = tx_req_pop_data;

    assign rev_lookup_valid = rx_req_pop_valid && rx_ctx_push_ready && rx_lookup_issue_ok;
    assign rx_req_pop_ready = rev_lookup_ready && rx_ctx_push_ready && rx_lookup_issue_ok;
    assign rx_ctx_push_valid = rx_req_pop_valid && rev_lookup_ready && rx_lookup_issue_ok;
    assign rx_ctx_push_data = rx_req_pop_data;

    cmd_t tx_result_cmd_data, tx_miss_cmd_data;
    wire tx_miss_cmd_valid = (tx_miss_state_r == TXM_ISSUE);
    wire tx_result_hit_active = fwd_result_hit && entry_active_r[fwd_result_value];
    wire tx_result_completes = tx_ctx_pop_data.bypass || tx_result_hit_active;
    assign fwd_result_ready = tx_ctx_pop_valid &&
                              (tx_result_completes ? (tx_cmd_push_ready && !tx_miss_cmd_valid) :
                                                     !tx_miss_active);
    wire tx_result_fire = fwd_result_valid && fwd_result_ready;
    wire tx_result_cmd_valid = fwd_result_valid && tx_ctx_pop_valid && tx_result_completes &&
                               !tx_miss_cmd_valid;
    wire tx_result_cmd_fire = tx_result_cmd_valid && tx_cmd_push_ready;
    wire tx_miss_start = tx_result_fire && !tx_ctx_pop_data.bypass && !tx_result_hit_active;
    wire tx_miss_cmd_fire = tx_miss_cmd_valid && tx_cmd_push_ready;
    assign tx_ctx_pop_ready = tx_result_fire;

    always_comb begin
        tx_result_cmd_data = '0;
        tx_result_cmd_data.bypass = tx_ctx_pop_data.bypass;
        tx_result_cmd_data.hit = 1'b1;
        tx_result_cmd_data.ip = csr_public_ip;
        tx_result_cmd_data.port = csr_base_port + {{(16-ENTRY_ID_W){1'b0}}, fwd_result_value};

        tx_miss_cmd_data = '0;
        tx_miss_cmd_data.hit = !tx_miss_drop_r;
        tx_miss_cmd_data.ip = csr_public_ip;
        tx_miss_cmd_data.port = tx_public_port_w;
    end

    assign tx_cmd_push_valid = tx_miss_cmd_valid || tx_result_cmd_valid;
    assign tx_cmd_push_data = tx_miss_cmd_valid ? tx_miss_cmd_data : tx_result_cmd_data;

    assign rev_result_ready = rx_ctx_pop_valid && rx_cmd_push_ready;
    wire rx_result_fire = rev_result_valid && rev_result_ready;
    wire rx_result_hit_active = rev_result_hit && entry_active_r[rev_result_dec.entry_id];
    assign rx_ctx_pop_ready = rx_result_fire;

    assign rx_cmd_push_valid = rev_result_valid && rx_ctx_pop_valid;
    always_comb begin
        rx_cmd_push_data = '0;
        rx_cmd_push_data.bypass = rx_ctx_pop_data.bypass;
        rx_cmd_push_data.hit = rx_ctx_pop_data.bypass || rx_result_hit_active;
        rx_cmd_push_data.ip = rev_result_dec.private_ip;
        rx_cmd_push_data.port = rev_result_dec.private_port;
    end

    assign fwd_insert_valid = (tx_miss_state_r == TXM_INS_FWD) && !ag_busy;
    assign fwd_insert_key   = tx_miss_req_r.key;
    assign fwd_insert_hash  = tx_miss_req_r.hash;
    assign fwd_insert_value = tx_miss_eid_r;
    assign rev_insert_valid = (tx_miss_state_r == TXM_INS_REV) && !ag_busy;
    assign rev_insert_key   = tx_rev_tuple_w;
    assign rev_insert_hash  = tx_rev_hash_w;
    assign rev_insert_value = tx_rev_insert_value_w;

    logic                   ag_meta_we;
    logic [ENTRY_ID_W-1:0]  ag_meta_addr, ag_meta_waddr;
    entry_meta_t            ag_meta_wdata;
    logic                   tx_meta_we;
    assign tx_meta_we = (tx_miss_state_r == TXM_WRITE_META);

    assign meta_b_we = tx_meta_we || ag_meta_we;
    assign meta_b_addr = tx_meta_we ? tx_miss_eid_r : (ag_meta_we ? ag_meta_waddr : ag_meta_addr);
    always_comb begin
        if (tx_meta_we) begin
            meta_b_wdata = '0;
            meta_b_wdata.valid = 1'b1;
            meta_b_wdata.protocol = tx_miss_req_r.protocol;
            meta_b_wdata.private_ip = tx_miss_req_r.src_ip;
            meta_b_wdata.private_port = tx_miss_req_r.src_port;
            meta_b_wdata.remote_ip = tx_miss_req_r.dst_ip;
            meta_b_wdata.remote_port = tx_miss_req_r.dst_port;
            meta_b_wdata.last_used = csr_timestamp;
        end else begin
            meta_b_wdata = ag_meta_wdata;
        end
    end

    assign fl_alloc_ready = (tx_miss_state_r == TXM_ALLOC);

    always_ff @(posedge clk) begin
        if (!resetn) begin
            tx_miss_state_r <= TXM_IDLE;
            tx_miss_req_r <= '0;
            tx_miss_eid_r <= '0;
            tx_miss_drop_r <= 1'b0;
            tx_public_ip_r <= '0;
        end else begin
            unique case (tx_miss_state_r)
                TXM_IDLE: begin
                    if (tx_miss_start) begin
                        tx_miss_req_r <= tx_ctx_pop_data;
                        tx_public_ip_r <= csr_public_ip;
                        tx_miss_drop_r <= 1'b0;
                        tx_miss_state_r <= TXM_ALLOC;
                    end
                end
                TXM_ALLOC: begin
                    if (fl_alloc_valid) begin
                        tx_miss_eid_r <= fl_alloc_id;
                        tx_miss_state_r <= TXM_WRITE_META;
                    end else begin
                        tx_miss_drop_r <= 1'b1;
                        tx_miss_state_r <= TXM_ISSUE;
                    end
                end
                TXM_WRITE_META: tx_miss_state_r <= TXM_INS_FWD;
                TXM_INS_FWD: begin
                    if (fwd_insert_done) tx_miss_state_r <= TXM_INS_REV;
                    else if (fwd_insert_fail) begin
                        tx_miss_drop_r <= 1'b1;
                        tx_miss_state_r <= TXM_ISSUE;
                    end
                end
                TXM_INS_REV: begin
                    if (rev_insert_done) begin
                        tx_miss_drop_r <= 1'b0;
                        tx_miss_state_r <= TXM_ISSUE;
                    end else if (rev_insert_fail) begin
                        tx_miss_drop_r <= 1'b1;
                        tx_miss_state_r <= TXM_ISSUE;
                    end
                end
                TXM_ISSUE: begin
                    if (tx_miss_cmd_fire)
                        tx_miss_state_r <= TXM_IDLE;
                end
                default: tx_miss_state_r <= TXM_IDLE;
            endcase
        end
    end

    assign cnt_fwd_hit = tx_result_cmd_fire && !tx_ctx_pop_data.bypass && tx_result_hit_active;
    assign cnt_fwd_miss = tx_miss_start;
    assign cnt_rev_hit = rx_result_fire && !rx_ctx_pop_data.bypass && rx_result_hit_active;
    assign cnt_rev_miss = rx_result_fire && !rx_ctx_pop_data.bypass && !rx_result_hit_active;
    assign cnt_bypass_tx = tx_result_cmd_fire && tx_ctx_pop_data.bypass;
    assign cnt_bypass_rx = rx_result_fire && rx_ctx_pop_data.bypass;

    // Commands are narrow and latency-sensitive: a fall-through register FIFO
    // lets a returned hit reach the rewrite stage without waiting for a BRAM
    // read whenever the command queue was empty.
    sync_ff_fifo #(
        .DEPTH(CTRL_FIFO_DEPTH + FIFO_DEPTH_MARGIN), .T(cmd_t),
        .EXTRA_OUTPUT_REG(EXTRA_OUTPUT_REG),
        .MODE("CONSERVATIVE")
    ) u_tx_cmd_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(tx_cmd_push_valid), .push_data(tx_cmd_push_data), .push_ready(tx_cmd_push_ready),
        .pop_valid(tx_cmd_pop_valid), .pop_data(tx_cmd_pop_data), .pop_ready(tx_cmd_pop_ready)
    );
    sync_ff_fifo #(
        .DEPTH(CTRL_FIFO_DEPTH + FIFO_DEPTH_MARGIN), .T(cmd_t),
        .EXTRA_OUTPUT_REG(EXTRA_OUTPUT_REG),
        .MODE("CONSERVATIVE")
    ) u_rx_cmd_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(rx_cmd_push_valid), .push_data(rx_cmd_push_data), .push_ready(rx_cmd_push_ready),
        .pop_valid(rx_cmd_pop_valid), .pop_data(rx_cmd_pop_data), .pop_ready(rx_cmd_pop_ready)
    );

    assign tx_cmd_pop_ready = tx_rw_ready;
    assign tx_rw_valid = tx_cmd_pop_valid;
    assign tx_rw_bypass = tx_cmd_pop_data.bypass;
    assign tx_rw_hit = tx_cmd_pop_data.hit;
    assign tx_rw_ip = tx_cmd_pop_data.ip;
    assign tx_rw_port = tx_cmd_pop_data.port;

    assign rx_cmd_pop_ready = rx_rw_ready;
    assign rx_rw_valid = rx_cmd_pop_valid;
    assign rx_rw_bypass = rx_cmd_pop_data.bypass;
    assign rx_rw_hit = rx_cmd_pop_data.hit;
    assign rx_rw_ip = rx_cmd_pop_data.ip;
    assign rx_rw_port = rx_cmd_pop_data.port;

    // ---------------------------------------------------------------------
    // Aging: scan metadata entries, then ask each generic table wrapper to
    // delete by key in the hashed set.  The wrapper searches all ways in that
    // set; there is no table-wide or bucket round-robin probing here.
    // ---------------------------------------------------------------------
    typedef enum logic [3:0] {
        AG_IDLE,
        AG_READ,
        AG_WAIT,
        AG_CHECK,
        AG_HASH,
        AG_DEL_FWD,
        AG_DEL_REV,
        AG_CLEAR,
        AG_FREE
    } ag_state_t;

    ag_state_t ag_state_r;
    logic [ENTRY_ID_W-1:0] ag_scan_r;
    entry_meta_t ag_entry_r;
    logic [TUPLE_BITS-1:0] ag_fwd_tuple_w, ag_rev_tuple_w;
    logic [BUCKET_IDX_W-1:0] ag_fwd_hash_w, ag_rev_hash_w;
    logic [TUPLE_BITS-1:0] ag_fwd_key_r, ag_rev_key_r;
    logic [BUCKET_IDX_W-1:0] ag_fwd_hash_r, ag_rev_hash_r;
    logic [15:0] ag_public_port_w;
    logic [7:0] ag_quiet_count_r;

    assign ag_busy = (ag_state_r != AG_IDLE);
    assign ag_public_port_w = csr_base_port + {{(16-ENTRY_ID_W){1'b0}}, ag_scan_r};
    assign ag_fwd_tuple_w = {ag_entry_r.protocol, ag_entry_r.remote_port, ag_entry_r.private_port,
                             ag_entry_r.remote_ip, ag_entry_r.private_ip};
    assign ag_rev_tuple_w = {ag_entry_r.protocol, ag_public_port_w, ag_entry_r.remote_port,
                             csr_public_ip, ag_entry_r.remote_ip};

    toeplitz_hash #(.HASH_WIDTH(BUCKET_IDX_W), .TUPLE_WIDTH(TUPLE_BITS)) u_ag_fwd_hash (
        .tuple_bits(ag_fwd_tuple_w), .hash_value(ag_fwd_hash_w)
    );
    toeplitz_hash #(.HASH_WIDTH(BUCKET_IDX_W), .TUPLE_WIDTH(TUPLE_BITS)) u_ag_rev_hash (
        .tuple_bits(ag_rev_tuple_w), .hash_value(ag_rev_hash_w)
    );

    wire ag_timed_out = ((csr_timestamp - ag_entry_r.last_used) >= csr_timeout);
    wire tx_mutating_tables = (tx_miss_state_r == TXM_WRITE_META) ||
                              (tx_miss_state_r == TXM_INS_FWD) ||
                              (tx_miss_state_r == TXM_INS_REV);
    wire tx_pipeline_idle = !tx_req_pop_valid && !tx_ctx_pop_valid && !tx_cmd_pop_valid &&
                            !tx_miss_active && !fwd_result_valid;
    wire rx_pipeline_idle = !rx_req_pop_valid && !rx_ctx_pop_valid && !rx_cmd_pop_valid &&
                            !rev_result_valid;
    wire packet_activity = (tx_packet_in.tvalid && tx_packet_in.tready) ||
                           (rx_packet_in.tvalid && rx_packet_in.tready) ||
                           (tx_packet_out.tvalid && tx_packet_out.tready) ||
                           (rx_packet_out.tvalid && rx_packet_out.tready);
    wire pipelines_idle = tx_pipeline_idle && rx_pipeline_idle;
    wire aging_quiet = (ag_quiet_count_r == 8'hff);
    wire ag_start_ok = csr_enable && !meta_clear_active_r && !tx_mutating_tables &&
                       pipelines_idle && aging_quiet;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            ag_quiet_count_r <= '0;
        end else if (!pipelines_idle || packet_activity) begin
            ag_quiet_count_r <= '0;
        end else if (ag_quiet_count_r != 8'hff) begin
            ag_quiet_count_r <= ag_quiet_count_r + 1'b1;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            entry_active_r <= '0;
        end else begin
            if ((tx_miss_state_r == TXM_INS_REV) && rev_insert_done && !rev_insert_fail)
                entry_active_r[tx_miss_eid_r] <= 1'b1;
            if (ag_state_r == AG_CLEAR)
                entry_active_r[ag_scan_r] <= 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            ag_state_r <= AG_IDLE;
            ag_scan_r <= '0;
            ag_entry_r <= '0;
            ag_fwd_key_r <= '0;
            ag_rev_key_r <= '0;
            ag_fwd_hash_r <= '0;
            ag_rev_hash_r <= '0;
        end else begin
            unique case (ag_state_r)
                AG_IDLE: begin
                    if (ag_start_ok)
                        ag_state_r <= AG_READ;
                end
                AG_READ: ag_state_r <= AG_WAIT;
                AG_WAIT: begin
                    ag_entry_r <= meta_b_rdata;
                    ag_state_r <= AG_CHECK;
                end
                AG_CHECK: begin
                    if (ag_entry_r.valid && ag_timed_out) begin
                        ag_state_r <= AG_HASH;
                    end else begin
                        ag_scan_r <= (ag_scan_r == ENTRY_ID_W'(NUM_ENTRIES - 1)) ? '0 : ag_scan_r + 1'b1;
                        ag_state_r <= AG_IDLE;
                    end
                end
                AG_HASH: begin
                    ag_fwd_key_r <= ag_fwd_tuple_w;
                    ag_rev_key_r <= ag_rev_tuple_w;
                    ag_fwd_hash_r <= ag_fwd_hash_w;
                    ag_rev_hash_r <= ag_rev_hash_w;
                    ag_state_r <= AG_DEL_FWD;
                end
                AG_DEL_FWD: if (fwd_delete_done) ag_state_r <= AG_DEL_REV;
                AG_DEL_REV: if (rev_delete_done) ag_state_r <= AG_CLEAR;
                AG_CLEAR: ag_state_r <= AG_FREE;
                AG_FREE: begin
                    if (fl_free_ready) begin
                        ag_scan_r <= (ag_scan_r == ENTRY_ID_W'(NUM_ENTRIES - 1)) ? '0 : ag_scan_r + 1'b1;
                        ag_state_r <= AG_IDLE;
                    end
                end
                default: ag_state_r <= AG_IDLE;
            endcase
        end
    end

    assign ag_meta_addr = ag_scan_r;
    assign ag_meta_we = (ag_state_r == AG_CLEAR);
    assign ag_meta_waddr = ag_scan_r;
    assign ag_meta_wdata = '0;

    assign fwd_delete_valid = (ag_state_r == AG_DEL_FWD);
    assign fwd_delete_key = ag_fwd_key_r;
    assign fwd_delete_hash = ag_fwd_hash_r;
    assign rev_delete_valid = (ag_state_r == AG_DEL_REV);
    assign rev_delete_key = ag_rev_key_r;
    assign rev_delete_hash = ag_rev_hash_r;

    assign fl_free_valid = (ag_state_r == AG_FREE);
    assign fl_free_id = ag_scan_r;

endmodule
