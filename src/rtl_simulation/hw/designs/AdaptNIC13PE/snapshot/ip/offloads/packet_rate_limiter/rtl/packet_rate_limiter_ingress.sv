`include "parser_pkg.sv"
import parser_pkg::*;

// Packet capture, parsing, hashing, and flow lookup.
module packet_rate_limiter_ingress #(
    parameter int unsigned DATA_WIDTH        = 512,
    parameter int unsigned PACKET_FIFO_DEPTH = 128,
    parameter int unsigned PARSER_FIFO_DEPTH = 128,
    parameter int unsigned META_FIFO_DEPTH = 128,
    parameter int unsigned MAX_FLOWS = 4096,
    parameter int unsigned TABLE_ASSOCIATIVITY = 4,
    parameter int unsigned MAX_PACKET_BEATS = 24
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave  packet_in,
    ifc_axis.master packet_buffer_out,
    ifc_axil.slave table_ctrl,
    output logic lookup_meta_valid,
    input  logic lookup_meta_ready,
    output logic [$clog2(MAX_FLOWS) + 19:0] lookup_meta_data,
    output logic config_write_commit,
    output logic [$clog2(MAX_FLOWS)-1:0] config_write_idx
);

    localparam int TUPLE_W = 104;
    localparam int TABLE_VALUE_W = 32;
    localparam int LOOKUP_REQUEST_W = 32 + TUPLE_W;
    localparam int TABLE_DEPTH = MAX_FLOWS / TABLE_ASSOCIATIVITY;
    localparam int TABLE_ADDR_W = $clog2(TABLE_DEPTH);
    localparam int WAY_W = $clog2(TABLE_ASSOCIATIVITY);
    localparam int FLOW_STATE_W = $clog2(MAX_FLOWS);
    localparam int HASH_ERROR_W = TUPLE_W + TABLE_ADDR_W;
    localparam int HASH_ERROR_AXIS_W = ((HASH_ERROR_W + 7) / 8) * 8;
    localparam int L2_HDR_W = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int L3_HDR_W = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_W = parser_pkg::L4_HDR_AXIS_BITS;

    typedef struct packed {
        logic invalid;
        logic [TABLE_ADDR_W-1:0] set_idx;
    } lookup_desc_t;

    localparam int BEAT_COUNT_W = 5;

    typedef struct packed {
        logic hit;
        logic [FLOW_STATE_W-1:0] state_idx;
        logic [6:0] max_burst;
        logic [6:0] scalar_mask;
    } table_meta_t;

    typedef struct packed {
        logic hit;
        logic [FLOW_STATE_W-1:0] state_idx;
        logic [6:0] max_burst;
        logic [6:0] scalar_mask;
        logic [BEAT_COUNT_W-1:0] packet_beats;
    } packet_meta_t;
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(12), .TID_WIDTH(16), .TUSER_WIDTH(16)
    ) packet_fifo_in (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) parser_fifo_in (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) parser_out (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH(PACKET_FIFO_DEPTH),
        .USE_BRAM(1'b1),
        .EXTRA_OUTPUT_REG(1'b1),
        .MODE("CONSERVATIVE")
    ) u_packet_fifo (
        .clk(clk), .resetn(resetn),
        .s_axis(packet_fifo_in), .m_axis(packet_buffer_out)
    );

    axis_fifo #(
        .DEPTH(PARSER_FIFO_DEPTH),
        .USE_BRAM(1'b0),
        .EXTRA_OUTPUT_REG(1'b0),
        .MODE("CONSERVATIVE")
    ) u_parser_fifo (
        .clk(clk), .resetn(resetn),
        .s_axis(parser_fifo_in), .m_axis(parser_out)
    );

    logic [BEAT_COUNT_W-1:0] packet_beat_count_r;
    logic beat_count_push_valid;
    logic beat_count_push_ready;
    logic [BEAT_COUNT_W-1:0] beat_count_push_data;
    logic beat_count_pop_valid;
    logic beat_count_pop_ready;
    logic [BEAT_COUNT_W-1:0] beat_count_pop_data;

    sync_bram_fifo #(
        .DEPTH(META_FIFO_DEPTH),
        .T(logic [BEAT_COUNT_W-1:0]),
        .EXTRA_OUTPUT_REG(1'b0),
        .MODE("CONSERVATIVE")
    ) u_beat_count_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(beat_count_push_valid),
        .push_data(beat_count_push_data),
        .push_ready(beat_count_push_ready),
        .pop_valid(beat_count_pop_valid),
        .pop_data(beat_count_pop_data),
        .pop_ready(beat_count_pop_ready)
    );

    // A beat advances only when both retained and parser copies can accept it.
    assign packet_in.tready = packet_fifo_in.tready && parser_fifo_in.tready &&
                              (!packet_in.t.last || beat_count_push_ready);

    wire packet_input_fire = packet_in.tvalid && packet_in.tready;
    assign beat_count_push_valid = packet_input_fire && packet_in.t.last;
    assign beat_count_push_data = packet_beat_count_r + 1'b1;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            packet_beat_count_r <= '0;
        end else if (packet_input_fire) begin
            if (packet_in.t.last)
                packet_beat_count_r <= '0;
            else
                packet_beat_count_r <= packet_beat_count_r + 1'b1;

            if (packet_beat_count_r + 1'b1 > MAX_PACKET_BEATS) begin
                $error("packet_rate_limiter_ingress: packet exceeds MAX_PACKET_BEATS (%0d)",
                       MAX_PACKET_BEATS);
            end
        end
    end

    always_comb begin
        packet_fifo_in.t = '0;
        packet_fifo_in.t.data = packet_in.t.data;
        packet_fifo_in.t.keep = packet_in.t.keep;
        packet_fifo_in.t.id = packet_in.t.id;
        packet_fifo_in.t.dest = packet_in.t.dest;
        packet_fifo_in.t.user = packet_in.t.user;
        packet_fifo_in.t.last = packet_in.t.last;
        packet_fifo_in.tvalid = packet_in.tvalid && parser_fifo_in.tready &&
                                (!packet_in.t.last || beat_count_push_ready);

        parser_fifo_in.t = '0;
        parser_fifo_in.t.data = packet_in.t.data;
        parser_fifo_in.t.keep = packet_in.t.keep;
        parser_fifo_in.t.last = packet_in.t.last;
        parser_fifo_in.tvalid = packet_in.tvalid && packet_fifo_in.tready &&
                                (!packet_in.t.last || beat_count_push_ready);
    end
    // -------------------------------------------------------------------------
    // Parser, tuple construction, and Toeplitz set index.
    // -------------------------------------------------------------------------

    ifc_axis #(.DATA_WIDTH(L2_HDR_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l2_header_unused (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_HDR_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_header_raw (.axis_aclk(clk)),
        u_l3_header (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_header (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_unused (.axis_aclk(clk));

    parser #(
        .DATA_WIDTH(DATA_WIDTH),
        .SKIP_L2(1'b1),
        .HEADER_ONLY(1'b1),
        .REPACK_PAYLOAD_OUT(1'b0),
        .DEFAULT_ETHERTYPE(16'h0800)
    ) u_parser (
        .clk(clk),
        .resetn(resetn),
        .s_axis_packet_in(parser_out),
        .m_axis_l2_header_out(u_l2_header_unused),
        .m_axis_l3_header_out(u_l3_header_raw),
        .m_axis_l4_header_out(u_l4_header),
        .m_axis_payload_out(u_payload_unused)
    );


    axis_fifo #(
        .DEPTH(64),
        .USE_BRAM(1'b1),
        .EXTRA_OUTPUT_REG(1'b0),
        .MODE("CONSERVATIVE")
    ) u_l3_header_fifo (
        .clk(clk), .resetn(resetn),
        .s_axis(u_l3_header_raw), .m_axis(u_l3_header)
    );

    assign u_l2_header_unused.tready = 1'b1;
    assign u_payload_unused.tready = 1'b1;

    parser_pkg::l3_hdr_axis_t parsed_l3;
    parser_pkg::l4_hdr_axis_t parsed_l4;
    parser_pkg::ipv4_hdr_t parsed_ipv4;
    parser_pkg::tcp_hdr_t parsed_tcp;
    parser_pkg::udp_hdr_t parsed_udp;

    assign parsed_l3 = parser_pkg::l3_hdr_axis_t'(u_l3_header.t.data);
    assign parsed_l4 = parser_pkg::l4_hdr_axis_t'(u_l4_header.t.data);
    assign parsed_ipv4 = parsed_l3.ipv4;
    assign parsed_tcp = parsed_l4.tcp;
    assign parsed_udp = parsed_l4.udp;

    wire header_pair_valid = u_l3_header.tvalid && u_l4_header.tvalid;
    wire header_is_tcp = parsed_l4.kind == parser_pkg::L4_KIND_TCP;
    wire header_eligible =
        (parsed_l3.status == parser_pkg::PARSER_STATUS_OK) &&
        (parsed_l3.kind == parser_pkg::L3_KIND_IPV4) &&
        (parsed_l4.status == parser_pkg::PARSER_STATUS_OK) &&
        ((parsed_l4.kind == parser_pkg::L4_KIND_TCP) ||
         (parsed_l4.kind == parser_pkg::L4_KIND_UDP));

    logic [15:0] tuple_src_port;
    logic [15:0] tuple_dst_port;
    logic [TUPLE_W-1:0] tuple_bits;
    logic [TABLE_ADDR_W-1:0] tuple_hash;

    assign tuple_src_port = header_is_tcp ? parsed_tcp.src_port : parsed_udp.src_port;
    assign tuple_dst_port = header_is_tcp ? parsed_tcp.dst_port : parsed_udp.dst_port;
    assign tuple_bits = {
        parsed_ipv4.protocol,
        tuple_dst_port,
        tuple_src_port,
        parsed_ipv4.dst_addr,
        parsed_ipv4.src_addr
    };

    toeplitz_hash #(
        .HASH_WIDTH(TABLE_ADDR_W),
        .TUPLE_WIDTH(TUPLE_W)
    ) u_tuple_hash (
        .tuple_bits(tuple_bits),
        .hash_value(tuple_hash)
    );

    // -------------------------------------------------------------------------
    // Associative flow configuration lookup.
    // -------------------------------------------------------------------------

    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_table_index (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(TUPLE_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_table_key (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(TABLE_VALUE_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_table_value (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(HASH_ERROR_AXIS_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_table_error (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(LOOKUP_REQUEST_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_lookup_request_in (.axis_aclk(clk)),
        u_lookup_request_out (.axis_aclk(clk));

    // Cut the lookup-result backpressure path before it reaches the parser.
    // CONSERVATIVE mode reserves one entry so the FIFO's registered ready can
    // deassert without accepting more requests than the four-entry FF store.
    axis_fifo #(
        .DEPTH(4),
        .USE_BRAM(1'b0),
        .EXTRA_OUTPUT_REG(1'b0),
        .MODE("CONSERVATIVE")
    ) u_lookup_request_fifo (
        .clk(clk), .resetn(resetn),
        .s_axis(u_lookup_request_in),
        .m_axis(u_lookup_request_out)
    );

    logic [WAY_W-1:0] table_value_way;
    logic runtime_update_ready_unused;
    logic table_mgmt_write_commit;
    logic [TABLE_ADDR_W-1:0] table_mgmt_write_set;
    logic [WAY_W-1:0] table_mgmt_write_way;
    axil_hash_table #(
        .TABLE_DEPTH(TABLE_DEPTH),
        .KEY_WIDTH(TUPLE_W),
        .VALUE_WIDTH(TABLE_VALUE_W),
        .RUNTIME_VALUE_WIDTH(0),
        .ASSOCIATIVITY(TABLE_ASSOCIATIVITY)
    ) u_flow_table (
        .clk(clk),
        .resetn(resetn),
        .ctrl_in(table_ctrl),
        .s_axis_lookup_index(u_table_index),
        .s_axis_key(u_table_key),
        .m_axis_value(u_table_value),
        .m_axis_error(u_table_error),
        .m_axis_value_way(table_value_way),
        .runtime_update_valid(1'b0),
        .runtime_update_ready(runtime_update_ready_unused),
        .runtime_update_set('0),
        .runtime_update_way('0),
        .runtime_update_data('0),
        .mgmt_write_commit(table_mgmt_write_commit),
        .mgmt_write_set(table_mgmt_write_set),
        .mgmt_write_way(table_mgmt_write_way)
    );

    assign config_write_commit = table_mgmt_write_commit;
    assign config_write_idx = {table_mgmt_write_way, table_mgmt_write_set};

    lookup_desc_t desc_push_data;
    lookup_desc_t desc_pop_data;
    logic desc_push_valid;
    logic desc_push_ready;
    logic desc_pop_valid;
    logic desc_pop_ready;

    sync_bram_fifo #(
        .DEPTH(META_FIFO_DEPTH),
        .T(lookup_desc_t),
        .EXTRA_OUTPUT_REG(1'b0),
        .MODE("CONSERVATIVE")
    ) u_desc_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(desc_push_valid), .push_data(desc_push_data), .push_ready(desc_push_ready),
        .pop_valid(desc_pop_valid), .pop_data(desc_pop_data), .pop_ready(desc_pop_ready)
    );

    wire header_commit_ready = desc_push_ready &&
                               (!header_eligible || u_lookup_request_in.tready);
    wire header_fire = header_pair_valid && header_commit_ready;
    wire eligible_header_fire = header_fire && header_eligible;

    assign u_l3_header.tready = u_l4_header.tvalid && header_commit_ready;
    assign u_l4_header.tready = u_l3_header.tvalid && header_commit_ready;

    always_comb begin
        desc_push_data = '0;
        desc_push_data.invalid = !header_eligible;
        desc_push_data.set_idx = tuple_hash;
    end
    assign desc_push_valid = header_fire;

    always_comb begin
        u_lookup_request_in.t = '0;
        u_lookup_request_in.t.data = {tuple_bits, 32'(tuple_hash)};
        u_lookup_request_in.t.keep = '1;
        u_lookup_request_in.t.last = 1'b1;
        u_lookup_request_in.tvalid = eligible_header_fire;

        u_table_index.t = '0;
        u_table_index.t.data = u_lookup_request_out.t.data[31:0];
        u_table_index.t.keep = '1;
        u_table_index.t.last = 1'b1;
        u_table_index.tvalid = u_lookup_request_out.tvalid &&
                               u_table_key.tready;

        u_table_key.t = '0;
        u_table_key.t.data =
            u_lookup_request_out.t.data[32 +: TUPLE_W];
        u_table_key.t.keep = '1;
        u_table_key.t.last = 1'b1;
        u_table_key.tvalid = u_lookup_request_out.tvalid &&
                             u_table_index.tready;

        u_lookup_request_out.tready = u_table_index.tready &&
                                      u_table_key.tready;
    end

    table_meta_t meta_push_data;
    table_meta_t meta_pop_data;
    logic meta_push_valid;
    logic meta_push_ready;
    logic meta_pop_valid;
    logic meta_pop_ready;

    sync_bram_fifo #(
        .DEPTH(META_FIFO_DEPTH),
        .T(table_meta_t),
        .EXTRA_OUTPUT_REG(1'b0),
        .MODE("CONSERVATIVE")
    ) u_meta_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(meta_push_valid), .push_data(meta_push_data), .push_ready(meta_push_ready),
        .pop_valid(meta_pop_valid), .pop_data(meta_pop_data), .pop_ready(meta_pop_ready)
    );

    wire desc_invalid = desc_pop_valid && desc_pop_data.invalid;
    wire table_hit_valid = u_table_value.tvalid;
    wire table_miss_valid = u_table_error.tvalid;
    wire table_result_valid = table_hit_valid || table_miss_valid;
    wire meta_input_valid = desc_pop_valid &&
                            (desc_pop_data.invalid || table_result_valid);

    always_comb begin
        meta_push_data = '0;
        meta_push_data.hit = !desc_invalid && table_hit_valid;
        meta_push_data.state_idx =
            FLOW_STATE_W'({table_value_way, desc_pop_data.set_idx});
        meta_push_data.max_burst = u_table_value.t.data[6:0];
        meta_push_data.scalar_mask = u_table_value.t.data[30:24];
    end

    assign meta_push_valid = meta_input_valid;
    assign desc_pop_ready = meta_push_ready &&
                            (desc_pop_data.invalid || table_result_valid);
    assign u_table_value.tready = meta_push_ready &&
                                  desc_pop_valid && !desc_pop_data.invalid;
    assign u_table_error.tready = meta_push_ready &&
                                  desc_pop_valid && !desc_pop_data.invalid;


    always_comb begin
        packet_meta_t joined_meta;
        joined_meta = '0;
        joined_meta.hit = meta_pop_data.hit;
        joined_meta.state_idx = meta_pop_data.state_idx;
        joined_meta.max_burst = meta_pop_data.max_burst;
        joined_meta.scalar_mask = meta_pop_data.scalar_mask;
        joined_meta.packet_beats = beat_count_pop_data;
        lookup_meta_data = joined_meta;
    end

    assign lookup_meta_valid = meta_pop_valid && beat_count_pop_valid;
    assign meta_pop_ready = lookup_meta_ready && beat_count_pop_valid;
    assign beat_count_pop_ready = lookup_meta_ready && meta_pop_valid;
endmodule
