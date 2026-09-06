`include "ifc_axis.sv"
`include "parser_pkg.sv"
import parser_pkg::*;

module checksum_ipv4_csum_prep #(
    parameter int DATA_WIDTH  = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_l3_header_in,
    ifc_axis.master m_axis_ipv4_for_checksum_out
);

    localparam int L3_HDR_WIDTH = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int IPV4_MAX_BYTES = 60;
    localparam int IPV4_COUNT_W   = $clog2(IPV4_MAX_BYTES + 1);

    ipv4_hdr_t ipv4_hdr;
    ipv4_hdr_t ipv4_hdr_zero_checksum;
    logic [IPV4_COUNT_W-1:0] ipv4_hdr_bytes;
    logic [IPV4_MAX_BYTES*8-1:0] ipv4_wire_data;

    initial begin
        if ($bits(s_axis_l3_header_in.t.data) != L3_HDR_WIDTH)
            $error("checksum_ipv4_csum_prep: header input width mismatch");
        if ($bits(m_axis_ipv4_for_checksum_out.t.data) != DATA_WIDTH)
            $error("checksum_ipv4_csum_prep: output width mismatch");
    end

    l3_hdr_axis_t l3_hdr;
    assign l3_hdr = l3_hdr_axis_t'(s_axis_l3_header_in.t.data);
    assign ipv4_hdr = l3_hdr.ipv4;
    assign ipv4_hdr_bytes = IPV4_COUNT_W'({ipv4_hdr.ihl, 2'b00});

    always_comb begin
        ipv4_hdr_zero_checksum = ipv4_hdr;
        ipv4_hdr_zero_checksum.header_checksum = 16'h0000;

        ipv4_wire_data = '0;
        ipv4_wire_data[parser_pkg::IPV4_HDR_BITS-1:0] = pack_ipv4_hdr_wire(ipv4_hdr_zero_checksum);
    end

    checksum_axis_byte_source #(
        .DATA_WIDTH       (DATA_WIDTH),
        .MAX_BYTES        (IPV4_MAX_BYTES),
        .BYTE_COUNT_WIDTH (IPV4_COUNT_W)
    ) u_ipv4_source (
        .clk          (clk),
        .resetn       (resetn),
        .s_data       (ipv4_wire_data),
        .s_byte_count (ipv4_hdr_bytes),
        .s_valid      (s_axis_l3_header_in.tvalid),
        .s_ready      (s_axis_l3_header_in.tready),
        .m_axis       (m_axis_ipv4_for_checksum_out)
    );

endmodule

module checksum_replace_checksums_headers #(
    parameter int DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_l3_header_in,
    ifc_axis.slave  s_axis_l4_header_in,
    ifc_axis.slave  s_axis_ipv4_checksum_in,
    ifc_axis.slave  s_axis_l4_checksum_in,
    ifc_axis.master m_axis_headers_out
);

    localparam int L3_HDR_WIDTH = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_WIDTH = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int IPV4_MAX_BYTES = 60;
    localparam int L4_MAX_BYTES = parser_pkg::TCP_HDR_BITS / 8;
    localparam int HEADER_MAX_BYTES = IPV4_MAX_BYTES + L4_MAX_BYTES;
    localparam int HEADER_COUNT_W = $clog2(HEADER_MAX_BYTES + 1);

    ifc_axis #(.DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_header_join_q_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_header_join_q_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_ipv4_checksum_join_q_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_checksum_join_q_out (.axis_aclk(clk));

    axis_ff_fifo_cut #(.DEPTH(4)) u_l3_header_join_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_l3_header_in),
        .m_axis (u_l3_header_join_q_out)
    );

    axis_ff_fifo_cut #(.DEPTH(4)) u_l4_header_join_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_l4_header_in),
        .m_axis (u_l4_header_join_q_out)
    );

    axis_ff_fifo_cut #(.DEPTH(4)) u_ipv4_checksum_join_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_ipv4_checksum_in),
        .m_axis (u_ipv4_checksum_join_q_out)
    );

    axis_ff_fifo_cut #(.DEPTH(4)) u_l4_checksum_join_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_l4_checksum_in),
        .m_axis (u_l4_checksum_join_q_out)
    );

    ipv4_hdr_t ipv4_hdr;
    ipv4_hdr_t ipv4_hdr_rewrite;
    tcp_hdr_t  tcp_hdr;
    tcp_hdr_t  tcp_hdr_rewrite;
    udp_hdr_t  udp_hdr;
    udp_hdr_t  udp_hdr_rewrite;

    l3_hdr_axis_t l3_hdr;
    l4_hdr_axis_t l4_hdr;
    logic [15:0] ipv4_checksum_raw;
    logic [15:0] ipv4_checksum;
    logic [15:0] l4_checksum_raw;
    logic [15:0] l4_checksum;
    logic [5:0] ipv4_hdr_bytes_small;
    logic [5:0] l4_hdr_bytes_small;
    logic [HEADER_COUNT_W-1:0] header_bytes;
    logic is_tcp;
    logic all_inputs_valid;
    logic out_ready;
    logic [HEADER_MAX_BYTES*8-1:0] header_wire_data;

    initial begin
        if ($bits(s_axis_l3_header_in.t.data) != L3_HDR_WIDTH)
            $error("checksum_replace_checksums_headers: L3 header input width mismatch");
        if ($bits(s_axis_l4_header_in.t.data) != L4_HDR_WIDTH)
            $error("checksum_replace_checksums_headers: L4 header input width mismatch");
        if ($bits(s_axis_ipv4_checksum_in.t.data) < 16)
            $error("checksum_replace_checksums_headers: IPv4 checksum input must expose 16 data bits");
        if ($bits(s_axis_l4_checksum_in.t.data) < 16)
            $error("checksum_replace_checksums_headers: L4 checksum input must expose 16 data bits");
    end

    assign l3_hdr = l3_hdr_axis_t'(u_l3_header_join_q_out.t.data);
    assign l4_hdr = l4_hdr_axis_t'(u_l4_header_join_q_out.t.data);
    assign ipv4_hdr = l3_hdr.ipv4;
    assign tcp_hdr = l4_hdr.tcp;
    assign udp_hdr = l4_hdr.udp;
    assign ipv4_checksum_raw = u_ipv4_checksum_join_q_out.t.data[15:0];
    assign ipv4_checksum = {ipv4_checksum_raw[7:0], ipv4_checksum_raw[15:8]};
    assign l4_checksum_raw = u_l4_checksum_join_q_out.t.data[15:0];
    assign l4_checksum = {l4_checksum_raw[7:0], l4_checksum_raw[15:8]};
    assign is_tcp = (l4_hdr.kind == L4_KIND_TCP);
    assign ipv4_hdr_bytes_small = {ipv4_hdr.ihl, 2'b00};
    assign l4_hdr_bytes_small = is_tcp ? {tcp_hdr.data_offset, 2'b00} : 6'd8;
    assign header_bytes = HEADER_COUNT_W'(ipv4_hdr_bytes_small) + HEADER_COUNT_W'(l4_hdr_bytes_small);
    assign all_inputs_valid = u_l3_header_join_q_out.tvalid
                            && u_l4_header_join_q_out.tvalid
                            && u_ipv4_checksum_join_q_out.tvalid
                            && u_l4_checksum_join_q_out.tvalid;

    always_comb begin
        ipv4_hdr_rewrite = ipv4_hdr;
        ipv4_hdr_rewrite.header_checksum = ipv4_checksum;

        tcp_hdr_rewrite = tcp_hdr;
        tcp_hdr_rewrite.checksum = l4_checksum;

        udp_hdr_rewrite = udp_hdr;
        udp_hdr_rewrite.checksum = l4_checksum;

        header_wire_data = '0;
        header_wire_data[parser_pkg::IPV4_HDR_BITS-1:0] = pack_ipv4_hdr_wire(ipv4_hdr_rewrite);

        if (is_tcp) begin
            header_wire_data[8*int'(ipv4_hdr_bytes_small) +: parser_pkg::TCP_HDR_BITS] = pack_tcp_hdr_wire(tcp_hdr_rewrite);
        end else begin
            header_wire_data[8*int'(ipv4_hdr_bytes_small) +: parser_pkg::UDP_HDR_BITS] = pack_udp_hdr_wire(udp_hdr_rewrite);
        end
    end

    checksum_axis_byte_source #(
        .DATA_WIDTH       (DATA_WIDTH),
        .MAX_BYTES        (HEADER_MAX_BYTES),
        .BYTE_COUNT_WIDTH (HEADER_COUNT_W)
    ) u_header_source (
        .clk          (clk),
        .resetn       (resetn),
        .s_data       (header_wire_data),
        .s_byte_count (header_bytes),
        .s_valid      (all_inputs_valid),
        .s_ready      (out_ready),
        .m_axis       (m_axis_headers_out)
    );

    assign u_l3_header_join_q_out.tready = all_inputs_valid && out_ready;
    assign u_l4_header_join_q_out.tready = all_inputs_valid && out_ready;
    assign u_ipv4_checksum_join_q_out.tready = all_inputs_valid && out_ready;
    assign u_l4_checksum_join_q_out.tready = all_inputs_valid && out_ready;

endmodule

module checksum_check #(
    parameter int DATA_WIDTH = 512
) (
    ifc_axis.slave  s_axis_l3_header_in,
    ifc_axis.slave  s_axis_l4_header_in,
    ifc_axis.slave  s_axis_ipv4_checksum_in,
    ifc_axis.slave  s_axis_l4_checksum_in,
    ifc_axis.master m_axis_decision_out
);

    localparam int L3_HDR_WIDTH = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_WIDTH = parser_pkg::L4_HDR_AXIS_BITS;

    ipv4_hdr_t ipv4_hdr;
    tcp_hdr_t  tcp_hdr;
    udp_hdr_t  udp_hdr;

    logic [15:0] ipv4_checksum_raw;
    logic [15:0] ipv4_checksum;
    logic [15:0] l4_checksum_raw;
    logic [15:0] l4_checksum;
    logic [15:0] l4_packet_checksum;
    logic        is_udp;
    logic        ipv4_match;
    logic        l4_match;
    logic        udp_checksum_zero;
    logic        admit;
    logic        all_inputs_valid;
    logic        fire;

    initial begin
        if ($bits(s_axis_l3_header_in.t.data) != L3_HDR_WIDTH)
            $error("checksum_check: L3 header input width mismatch");
        if ($bits(s_axis_l4_header_in.t.data) != L4_HDR_WIDTH)
            $error("checksum_check: L4 header input width mismatch");
        if ($bits(s_axis_ipv4_checksum_in.t.data) < 16)
            $error("checksum_check: IPv4 checksum input must expose 16 data bits");
        if ($bits(s_axis_l4_checksum_in.t.data) < 16)
            $error("checksum_check: L4 checksum input must expose 16 data bits");
        if ($bits(m_axis_decision_out.t.data) < 1)
            $error("checksum_check: decision output must expose at least 1 data bit");
    end

    l3_hdr_axis_t l3_hdr;
    l4_hdr_axis_t l4_hdr;
    assign l3_hdr = l3_hdr_axis_t'(s_axis_l3_header_in.t.data);
    assign l4_hdr = l4_hdr_axis_t'(s_axis_l4_header_in.t.data);
    assign ipv4_hdr = l3_hdr.ipv4;
    assign tcp_hdr  = l4_hdr.tcp;
    assign udp_hdr  = l4_hdr.udp;

    assign ipv4_checksum_raw = s_axis_ipv4_checksum_in.t.data[15:0];
    assign ipv4_checksum     = {ipv4_checksum_raw[7:0], ipv4_checksum_raw[15:8]};
    assign l4_checksum_raw   = s_axis_l4_checksum_in.t.data[15:0];
    assign l4_checksum       = {l4_checksum_raw[7:0], l4_checksum_raw[15:8]};

    assign is_udp             = (l4_hdr.kind == L4_KIND_UDP);
    assign l4_packet_checksum = is_udp ? udp_hdr.checksum : tcp_hdr.checksum;
    assign ipv4_match         = (ipv4_hdr.header_checksum == ipv4_checksum);
    assign l4_match           = (l4_packet_checksum == l4_checksum);
    assign udp_checksum_zero  = is_udp && (udp_hdr.checksum == 16'h0000);
    assign admit              = ipv4_match && (l4_match || udp_checksum_zero);
    assign all_inputs_valid   = s_axis_l3_header_in.tvalid
                              && s_axis_l4_header_in.tvalid
                              && s_axis_ipv4_checksum_in.tvalid
                              && s_axis_l4_checksum_in.tvalid;
    assign fire               = all_inputs_valid && m_axis_decision_out.tready;

    always_comb begin
        m_axis_decision_out.t         = '0;
        m_axis_decision_out.t.data[0] = admit;
        m_axis_decision_out.t.keep    = '1;
        m_axis_decision_out.t.id      = s_axis_l4_header_in.t.id;
        m_axis_decision_out.t.dest    = s_axis_l4_header_in.t.dest;
        m_axis_decision_out.t.user    = s_axis_l4_header_in.t.user;
        m_axis_decision_out.t.last    = 1'b1;
        m_axis_decision_out.tvalid    = all_inputs_valid;
    end

    assign s_axis_l3_header_in.tready     = fire;
    assign s_axis_l4_header_in.tready     = fire;
    assign s_axis_ipv4_checksum_in.tready = fire;
    assign s_axis_l4_checksum_in.tready   = fire;

endmodule

module checksum_packet_gate #(
    parameter int DATA_WIDTH  = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_packet_in,
    ifc_axis.slave  s_axis_decision_in,
    ifc_axis.master m_axis_packet_out
);

    logic have_decision_r;
    logic admit_r;
    logic active_valid;
    logic active_admit;
    logic packet_fire;
    logic decision_fire;

    assign active_valid = have_decision_r || s_axis_decision_in.tvalid;
    assign active_admit = have_decision_r ? admit_r : s_axis_decision_in.t.data[0];

    assign m_axis_packet_out.t.data = s_axis_packet_in.t.data;
    assign m_axis_packet_out.t.keep = s_axis_packet_in.t.keep;
    assign m_axis_packet_out.t.id = '0;
    assign m_axis_packet_out.t.dest = '0;
    assign m_axis_packet_out.t.user = '0;
    assign m_axis_packet_out.t.last = s_axis_packet_in.t.last;
    assign m_axis_packet_out.tvalid = active_valid && active_admit && s_axis_packet_in.tvalid;

    assign s_axis_packet_in.tready =
        !active_valid ? 1'b0 :
        active_admit ? m_axis_packet_out.tready : 1'b1;

    assign packet_fire   = s_axis_packet_in.tvalid && s_axis_packet_in.tready;
    assign decision_fire = !have_decision_r && s_axis_decision_in.tvalid && packet_fire;

    assign s_axis_decision_in.tready = decision_fire;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            have_decision_r <= 1'b0;
            admit_r         <= 1'b0;
        end else begin
            if (decision_fire) begin
                have_decision_r <= !s_axis_packet_in.t.last;
                admit_r         <= s_axis_decision_in.t.data[0];
            end else if (have_decision_r && packet_fire && s_axis_packet_in.t.last) begin
                have_decision_r <= 1'b0;
            end
        end
    end

    initial begin
        if ($bits(s_axis_packet_in.t.data) != DATA_WIDTH || $bits(m_axis_packet_out.t.data) != DATA_WIDTH)
            $error("checksum_packet_gate: packet data width mismatch");
    end

endmodule

module checksum #(
    parameter int DATA_WIDTH      = 512,
    parameter int MAX_PACKET_LEN  = 1500 * 8,
    parameter int TOTAL_HDR_BYTES_WIDTH = 16,
    parameter bit VERIFY_CHECKSUMS = 1'b0,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  packet_in,
    ifc_axis.master packet_out
);

    localparam int L2_HDR_WIDTH = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int L3_HDR_WIDTH = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_WIDTH = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int FIFO_DEPTH_RAW = (MAX_PACKET_LEN + DATA_WIDTH - 1) / DATA_WIDTH;
    localparam int FIFO_DEPTH     = (FIFO_DEPTH_RAW < 64) ? 64 : FIFO_DEPTH_RAW;
    localparam int REWRITE_ALIGN_FIFO_DEPTH = 16;
    localparam int PIPE_DECOUPLE_FIFO_DEPTH = 4;
    localparam int PAYLOAD_DECOUPLE_FIFO_DEPTH = FIFO_DEPTH;
    localparam int L4_HDR_CSUM_FIFO_DEPTH = 32;
    localparam int L4_PAYLOAD_CSUM_FIFO_DEPTH = 64;
    localparam int L4_PSEUDO_FIFO_DEPTH = 32;
    localparam int REWRITE_PACKET_FIFO_DEPTH = (FIFO_DEPTH < 16) ? FIFO_DEPTH : 16;
    localparam int VERIFY_PACKET_FIFO_DEPTH = FIFO_DEPTH * 3;
    localparam int PACK_BYTES_BASE_STAGE_WIDTH = (DATA_WIDTH < 32) ? DATA_WIDTH : 32;

    initial begin
        if (DATA_WIDTH < 16 || DATA_WIDTH % 8 != 0 || (DATA_WIDTH & (DATA_WIDTH - 1)) != 0)
            $error("checksum: DATA_WIDTH must be a byte-aligned power of two >= 16, got %0d",
                   DATA_WIDTH);
        if ($bits(packet_in.t.data) != DATA_WIDTH)
            $error("checksum: packet_in width mismatch");
        if ($bits(packet_out.t.data) != DATA_WIDTH)
            $error("checksum: packet_out width mismatch");
        if (FIFO_DEPTH < 1)
            $error("checksum: FIFO depth must be at least 1");
    end

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_packet_out_prescrub (.axis_aclk(clk));

    assign packet_out.t.data = u_packet_out_prescrub.t.data;
    assign packet_out.t.keep = u_packet_out_prescrub.t.keep;
    assign packet_out.t.id   = '0;
    assign packet_out.t.dest = '0;
    assign packet_out.t.user = '0;
    assign packet_out.t.last = u_packet_out_prescrub.t.last;
    assign packet_out.tvalid = u_packet_out_prescrub.tvalid;
    assign u_packet_out_prescrub.tready = packet_out.tready;

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_pkt_parser (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_pkt_rewrite_q_in (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_pkt_rewrite_q_out (.axis_aclk(clk));

    generate
        if (VERIFY_CHECKSUMS) begin : g_input_verify_split
            ifc_axis #(
                .DATA_WIDTH  (DATA_WIDTH),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1)
            ) u_pkt_split_out [2] (.axis_aclk(clk));

            axis_multicast #(
                .DATA_WIDTH  (DATA_WIDTH),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1),
                .NUM_DESTS   (2)
            ) u_pkt_split (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (packet_in),
                .m_axis (u_pkt_split_out)
            );

            assign u_pkt_parser.t = u_pkt_split_out[0].t;
            assign u_pkt_parser.tvalid = u_pkt_split_out[0].tvalid;
            assign u_pkt_split_out[0].tready = u_pkt_parser.tready;

            assign u_pkt_rewrite_q_in.t = u_pkt_split_out[1].t;
            assign u_pkt_rewrite_q_in.tvalid = u_pkt_split_out[1].tvalid;
            assign u_pkt_split_out[1].tready = u_pkt_rewrite_q_in.tready;

            axis_packet_fifo #(
                .DEPTH       (VERIFY_PACKET_FIFO_DEPTH),
                .DATA_WIDTH  (DATA_WIDTH),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1),
                .MODE        ("CONSERVATIVE")
            ) u_pkt_rewrite_q (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (u_pkt_rewrite_q_in),
                .m_axis (u_pkt_rewrite_q_out)
            );
        end else begin : g_input_rewrite_split
            ifc_axis #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
            ) u_pkt_split_out [2] (.axis_aclk(clk));

            axis_multicast #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
                .TUSER_WIDTH(1), .NUM_DESTS(2)
            ) u_pkt_split (
                .clk(clk), .resetn(resetn), .s_axis(packet_in), .m_axis(u_pkt_split_out)
            );

            assign u_pkt_parser.t = u_pkt_split_out[0].t;
            assign u_pkt_parser.tvalid = u_pkt_split_out[0].tvalid;
            assign u_pkt_split_out[0].tready = u_pkt_parser.tready;

            assign u_pkt_rewrite_q_in.t = u_pkt_split_out[1].t;
            assign u_pkt_rewrite_q_in.tvalid = u_pkt_split_out[1].tvalid;
            assign u_pkt_split_out[1].tready = u_pkt_rewrite_q_in.tready;

            axis_packet_fifo #(
                .DEPTH(FIFO_DEPTH), .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
                .TID_WIDTH(1), .TUSER_WIDTH(1), .MODE("CONSERVATIVE")
            ) u_pkt_rewrite_q (
                .clk(clk), .resetn(resetn),
                .s_axis(u_pkt_rewrite_q_in), .m_axis(u_pkt_rewrite_q_out)
            );
        end
    endgenerate

    ifc_axis #(.DATA_WIDTH(L2_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_parser_l2_unused (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_parser_l3_header (.axis_aclk(clk)), u_l3_hdr_split_0_out [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_parser_l4_header (.axis_aclk(clk)), u_l4_hdr_split_0_out [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_parser_payload (.axis_aclk(clk)), u_payload_split_out [2] (.axis_aclk(clk)),
        u_payload_l4_q_in (.axis_aclk(clk)), u_payload_l4_q_out (.axis_aclk(clk)),
        u_payload_l4_aligned (.axis_aclk(clk)), u_payload_rewrite_q_in (.axis_aclk(clk));

    parser #(
        .DATA_WIDTH        (DATA_WIDTH),
        .INTER_STAGE_FIFO_DEPTH(24),
        .SKIP_L2           (1'b1),
        .HEADER_ONLY       (!VERIFY_CHECKSUMS),
        .REPACK_PAYLOAD_OUT(1'b0),
        .DEFAULT_ETHERTYPE (16'h0800)
    ) u_parser (
        .clk                 (clk),
        .resetn              (resetn),
        .s_axis_packet_in    (u_pkt_parser.slave),
        .m_axis_l2_header_out(u_parser_l2_unused),
        .m_axis_l3_header_out(u_parser_l3_header),
        .m_axis_l4_header_out(u_parser_l4_header),
        .m_axis_payload_out  (u_parser_payload)
    );

    assign u_parser_l2_unused.tready = 1'b1;

    ifc_axis #(.DATA_WIDTH(TOTAL_HDR_BYTES_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_total_hdr_bytes (.axis_aclk(clk));

    generate
        if (VERIFY_CHECKSUMS) begin : g_parser_payload_verify
            assign u_payload_l4_q_in.t = u_parser_payload.t;
            assign u_payload_l4_q_in.tvalid = u_parser_payload.tvalid;
            assign u_parser_payload.tready = u_payload_l4_q_in.tready;
            assign u_payload_rewrite_q_in.tvalid = 1'b0;
            assign u_payload_rewrite_q_in.t = '0;
            assign u_total_hdr_bytes.tready = 1'b1;
        end else begin : g_original_payload_rewrite
            ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
                u_stripped_payload (.axis_aclk(clk));

            assign u_parser_payload.tready = 1'b1;

            axis_strip_bytes #(
                .DATA_WIDTH(DATA_WIDTH), .STRIP_WIDTH(TOTAL_HDR_BYTES_WIDTH)
            ) u_strip_original_packet (
                .clk(clk), .resetn(resetn),
                .s_axis(u_pkt_rewrite_q_out),
                .s_axis_remove(u_total_hdr_bytes),
                .m_axis(u_stripped_payload)
            );

            axis_multicast #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
                .TUSER_WIDTH(1), .NUM_DESTS(2)
            ) u_payload_split (
                .clk(clk), .resetn(resetn),
                .s_axis(u_stripped_payload), .m_axis(u_payload_split_out)
            );

            assign u_payload_l4_q_in.t = u_payload_split_out[0].t;
            assign u_payload_l4_q_in.tvalid = u_payload_split_out[0].tvalid;
            assign u_payload_split_out[0].tready = u_payload_l4_q_in.tready;

            assign u_payload_rewrite_q_in.t = u_payload_split_out[1].t;
            assign u_payload_rewrite_q_in.tvalid = u_payload_split_out[1].tvalid;
            assign u_payload_split_out[1].tready = u_payload_rewrite_q_in.tready;
        end
    endgenerate

    axis_fifo #(
        .DEPTH     (L4_PAYLOAD_CSUM_FIFO_DEPTH),
        .MODE      ("CONSERVATIVE")
    ) u_payload_l4_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_payload_l4_q_in),
        .m_axis (u_payload_l4_q_out)
    );

    assign u_payload_l4_aligned.t.data  = u_payload_l4_q_out.t.data;
    assign u_payload_l4_aligned.t.keep  = u_payload_l4_q_out.t.keep;
    assign u_payload_l4_aligned.t.id    = '0;
    assign u_payload_l4_aligned.t.dest  = '0;
    assign u_payload_l4_aligned.t.user  = '0;
    assign u_payload_l4_aligned.t.last  = u_payload_l4_q_out.t.last;
    assign u_payload_l4_aligned.tvalid  = u_payload_l4_q_out.tvalid;
    assign u_payload_l4_q_out.tready    = u_payload_l4_aligned.tready;

    axis_multicast #(
        .DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(1), .NUM_DESTS(2)
    ) u_l3_hdr_split_0 (
        .clk(clk), .resetn(resetn), .s_axis(u_parser_l3_header), .m_axis(u_l3_hdr_split_0_out)
    );
    axis_multicast #(
        .DATA_WIDTH(L4_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(1), .NUM_DESTS(2)
    ) u_l4_hdr_split_0 (
        .clk(clk), .resetn(resetn), .s_axis(u_parser_l4_header), .m_axis(u_l4_hdr_split_0_out)
    );

    ifc_axis #(.DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_hdr_l4 (.axis_aclk(clk)), u_l3_hdr_other (.axis_aclk(clk)),
        u_l3_hdr_ipv4 (.axis_aclk(clk)), u_l3_hdr_rewrite_other_q_in (.axis_aclk(clk)),
        u_l3_hdr_rewrite_q_in (.axis_aclk(clk)), u_l3_hdr_rewrite_q_out (.axis_aclk(clk)),
        u_l3_hdr_l4_q_out (.axis_aclk(clk)), u_l3_hdr_l4_aligned (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_hdr_l4 (.axis_aclk(clk)), u_l4_hdr_other (.axis_aclk(clk)),
        u_l4_hdr_rewrite_q_in (.axis_aclk(clk)), u_l4_hdr_rewrite_q_out (.axis_aclk(clk)),
        u_l4_hdr_l4_q_out (.axis_aclk(clk)), u_l4_hdr_l4_aligned (.axis_aclk(clk));

    assign u_l3_hdr_l4.t = u_l3_hdr_split_0_out[0].t;
    assign u_l3_hdr_l4.tvalid = u_l3_hdr_split_0_out[0].tvalid;
    assign u_l3_hdr_split_0_out[0].tready = u_l3_hdr_l4.tready;
    assign u_l3_hdr_other.t = u_l3_hdr_split_0_out[1].t;
    assign u_l3_hdr_other.tvalid = u_l3_hdr_split_0_out[1].tvalid;
    assign u_l3_hdr_split_0_out[1].tready = u_l3_hdr_other.tready;
    assign u_l4_hdr_l4.t = u_l4_hdr_split_0_out[0].t;
    assign u_l4_hdr_l4.tvalid = u_l4_hdr_split_0_out[0].tvalid;
    assign u_l4_hdr_split_0_out[0].tready = u_l4_hdr_l4.tready;
    assign u_l4_hdr_other.t = u_l4_hdr_split_0_out[1].t;
    assign u_l4_hdr_other.tvalid = u_l4_hdr_split_0_out[1].tvalid;
    assign u_l4_hdr_split_0_out[1].tready = u_l4_hdr_other.tready;

    ifc_axis #(.DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_hdr_split_1_out [2] (.axis_aclk(clk));
    axis_multicast #(
        .DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(1), .NUM_DESTS(2)
    ) u_l3_hdr_split_1 (
        .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_other), .m_axis(u_l3_hdr_split_1_out)
    );
    assign u_l3_hdr_ipv4.t = u_l3_hdr_split_1_out[0].t;
    assign u_l3_hdr_ipv4.tvalid = u_l3_hdr_split_1_out[0].tvalid;
    assign u_l3_hdr_split_1_out[0].tready = u_l3_hdr_ipv4.tready;
    assign u_l3_hdr_rewrite_other_q_in.t = u_l3_hdr_split_1_out[1].t;
    assign u_l3_hdr_rewrite_other_q_in.tvalid = u_l3_hdr_split_1_out[1].tvalid;
    assign u_l3_hdr_split_1_out[1].tready = u_l3_hdr_rewrite_other_q_in.tready;

    assign u_l3_hdr_rewrite_q_in.t = u_l3_hdr_rewrite_other_q_in.t;
    assign u_l3_hdr_rewrite_q_in.tvalid = u_l3_hdr_rewrite_other_q_in.tvalid;
    assign u_l3_hdr_rewrite_other_q_in.tready = u_l3_hdr_rewrite_q_in.tready;

    assign u_l4_hdr_rewrite_q_in.t = u_l4_hdr_other.t;
    assign u_l4_hdr_rewrite_q_in.tvalid = u_l4_hdr_other.tvalid;
    assign u_l4_hdr_other.tready = u_l4_hdr_rewrite_q_in.tready;

    axis_fifo #(
        .DEPTH (FIFO_DEPTH),
        .MODE  ("CONSERVATIVE")
    ) u_l3_hdr_rewrite_q (
        .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_rewrite_q_in), .m_axis(u_l3_hdr_rewrite_q_out)
    );
    axis_fifo #(
        .DEPTH (FIFO_DEPTH),
        .MODE  ("CONSERVATIVE")
    ) u_l4_hdr_rewrite_q (
        .clk(clk), .resetn(resetn), .s_axis(u_l4_hdr_rewrite_q_in), .m_axis(u_l4_hdr_rewrite_q_out)
    );
    axis_fifo #(
        .DEPTH (L4_HDR_CSUM_FIFO_DEPTH),
        .MODE  ("CONSERVATIVE")
    ) u_l3_hdr_l4_q (
        .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_l4), .m_axis(u_l3_hdr_l4_q_out)
    );
    axis_fifo #(
        .DEPTH (L4_HDR_CSUM_FIFO_DEPTH),
        .MODE  ("CONSERVATIVE")
    ) u_l4_hdr_l4_q (
        .clk(clk), .resetn(resetn), .s_axis(u_l4_hdr_l4), .m_axis(u_l4_hdr_l4_q_out)
    );

    assign u_l3_hdr_l4_aligned.t = u_l3_hdr_l4_q_out.t;
    assign u_l3_hdr_l4_aligned.tvalid = u_l3_hdr_l4_q_out.tvalid;
    assign u_l3_hdr_l4_q_out.tready = u_l3_hdr_l4_aligned.tready;
    assign u_l4_hdr_l4_aligned.t = u_l4_hdr_l4_q_out.t;
    assign u_l4_hdr_l4_aligned.tvalid = u_l4_hdr_l4_q_out.tvalid;
    assign u_l4_hdr_l4_q_out.tready = u_l4_hdr_l4_aligned.tready;

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_ipv4_csum_operands (.axis_aclk(clk));

    checksum_ipv4_csum_prep #(
        .DATA_WIDTH  (DATA_WIDTH)
    ) u_ipv4_csum_prep (
        .clk                            (clk),
        .resetn                         (resetn),
        .s_axis_l3_header_in            (u_l3_hdr_ipv4),
        .m_axis_ipv4_for_checksum_out   (u_ipv4_csum_operands)
    );

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_ipv4_checksum (.axis_aclk(clk));

    oc_adder_tree_axis #(
        .IN_DATA_WIDTH     (DATA_WIDTH),
        .TDEST_WIDTH       (1),
        .TID_WIDTH         (1),
        .TUSER_WIDTH       (1),
        .SUM_WIDTH         (16),
        .M_AXIS_DATA_WIDTH (DATA_WIDTH)
    ) u_ipv4_checksum_tree (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_ipv4_csum_operands),
        .m_axis (u_ipv4_checksum)
    );

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_ipv4_checksum_q_out (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH     (FIFO_DEPTH),
        .MODE      ("CONSERVATIVE")
    ) u_ipv4_checksum_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_ipv4_checksum),
        .m_axis (u_ipv4_checksum_q_out)
    );

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_ipv4_checksum_align_q_out (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH     (REWRITE_ALIGN_FIFO_DEPTH),
        .USE_BRAM  (1'b0),
        .MODE      ("CONSERVATIVE")
    ) u_ipv4_checksum_align_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_ipv4_checksum_q_out),
        .m_axis (u_ipv4_checksum_align_q_out)
    );

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_l4_csum_operands (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_l4_csum_operands_q_out (.axis_aclk(clk));

    build_pseudo_hdr #(
        .PACKET_DATA_WIDTH           (DATA_WIDTH),
        .CHECKSUM_OPERANDS_WIDTH     (DATA_WIDTH),
        .PACK_BYTES_BASE_STAGE_WIDTH (PACK_BYTES_BASE_STAGE_WIDTH),
        .TOTAL_HDR_BYTES_WIDTH       (TOTAL_HDR_BYTES_WIDTH),
        .PSEUDO_FIFO_DEPTH           (L4_PSEUDO_FIFO_DEPTH),
        .FRAGMENT_PACKER_PAGE_COUNT  (FRAGMENT_PACKER_PAGE_COUNT)
    ) u_build_pseudo_hdr (
        .clk                        (clk),
        .resetn                     (resetn),
        .s_axis_l3_header_in        (u_l3_hdr_l4_aligned),
        .s_axis_l4_header_in        (u_l4_hdr_l4_aligned),
        .s_axis_packet_in           (u_payload_l4_aligned),
        .m_axis_total_hdr_bytes_out (u_total_hdr_bytes),
        .m_axis_checksum_operands_out (u_l4_csum_operands)
    );

    axis_fifo #(
        .DEPTH     (PIPE_DECOUPLE_FIFO_DEPTH),
        .MODE      ("CONSERVATIVE"),
        .USE_BRAM  (1'b0)
    ) u_l4_csum_operands_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_l4_csum_operands),
        .m_axis (u_l4_csum_operands_q_out)
    );

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_l4_checksum (.axis_aclk(clk));

    oc_adder_tree_axis #(
        .IN_DATA_WIDTH     (DATA_WIDTH),
        .TDEST_WIDTH       (1),
        .TID_WIDTH         (1),
        .TUSER_WIDTH       (1),
        .SUM_WIDTH         (16),
        .M_AXIS_DATA_WIDTH (DATA_WIDTH)
    ) u_l4_checksum_tree (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_l4_csum_operands_q_out),
        .m_axis (u_l4_checksum)
    );

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_l4_checksum_q_out (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH     (FIFO_DEPTH),
        .MODE      ("CONSERVATIVE")
    ) u_l4_checksum_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_l4_checksum),
        .m_axis (u_l4_checksum_q_out)
    );

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_ipv4_rewrite_hdr (.axis_aclk(clk));

    ifc_axis #(.DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_hdr_rewrite_align_q_out (.axis_aclk(clk)), u_l3_hdr_rewrite_align_pre_split (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_hdr_rewrite_align_q_out (.axis_aclk(clk)), u_l4_hdr_rewrite_align_pre_split (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH    (REWRITE_ALIGN_FIFO_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_l3_hdr_rewrite_align_q (
        .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_rewrite_q_out), .m_axis(u_l3_hdr_rewrite_align_q_out)
    );
    axis_fifo #(
        .DEPTH    (REWRITE_ALIGN_FIFO_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_l4_hdr_rewrite_align_q (
        .clk(clk), .resetn(resetn), .s_axis(u_l4_hdr_rewrite_q_out), .m_axis(u_l4_hdr_rewrite_align_q_out)
    );
    axis_ff_fifo_cut #(.DEPTH(4)) u_l3_hdr_rewrite_align_pre_split_rs (
        .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_rewrite_align_q_out), .m_axis(u_l3_hdr_rewrite_align_pre_split)
    );
    axis_ff_fifo_cut #(.DEPTH(4)) u_l4_hdr_rewrite_align_pre_split_rs (
        .clk(clk), .resetn(resetn), .s_axis(u_l4_hdr_rewrite_align_q_out), .m_axis(u_l4_hdr_rewrite_align_pre_split)
    );

    generate
        if (VERIFY_CHECKSUMS) begin : g_checksum_verify
            ifc_axis #(
                .DATA_WIDTH  (8),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1)
            ) u_checksum_decision (.axis_aclk(clk));

            ifc_axis #(
                .DATA_WIDTH  (8),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1)
            ) u_checksum_decision_rs (.axis_aclk(clk));

            checksum_check #(
                .DATA_WIDTH (DATA_WIDTH)
            ) u_checksum_check (
                .s_axis_l3_header_in     (u_l3_hdr_rewrite_align_pre_split),
                .s_axis_l4_header_in     (u_l4_hdr_rewrite_align_pre_split),
                .s_axis_ipv4_checksum_in (u_ipv4_checksum_align_q_out),
                .s_axis_l4_checksum_in   (u_l4_checksum_q_out),
                .m_axis_decision_out     (u_checksum_decision)
            );

            axis_ff_fifo_cut #(.DEPTH(4)) u_checksum_decision_rs_stage (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (u_checksum_decision),
                .m_axis (u_checksum_decision_rs)
            );

            checksum_packet_gate #(
                .DATA_WIDTH  (DATA_WIDTH)
            ) u_packet_gate (
                .clk                (clk),
                .resetn             (resetn),
                .s_axis_packet_in   (u_pkt_rewrite_q_out),
                .s_axis_decision_in (u_checksum_decision_rs),
                .m_axis_packet_out  (u_packet_out_prescrub)
            );

            assign u_payload_rewrite_q_in.tready = 1'b1;
        end else begin : g_checksum_rewrite
            ifc_axis #(
                .DATA_WIDTH  (DATA_WIDTH),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1)
            ) u_new_headers (.axis_aclk(clk));

            checksum_replace_checksums_headers #(
                .DATA_WIDTH (DATA_WIDTH)
            ) u_replace_checksums_headers (
                .clk                    (clk),
                .resetn                 (resetn),
                .s_axis_l3_header_in     (u_l3_hdr_rewrite_align_pre_split),
                .s_axis_l4_header_in     (u_l4_hdr_rewrite_align_pre_split),
                .s_axis_ipv4_checksum_in (u_ipv4_checksum_align_q_out),
                .s_axis_l4_checksum_in   (u_l4_checksum_q_out),
                .m_axis_headers_out      (u_new_headers)
            );

            ifc_axis #(
                .DATA_WIDTH  (DATA_WIDTH),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1)
            ) u_new_headers_q_out (.axis_aclk(clk));

            axis_fifo #(
                .DEPTH     (PIPE_DECOUPLE_FIFO_DEPTH),
                .USE_BRAM  (1'b0),
                .MODE      ("CONSERVATIVE")
            ) u_new_headers_q (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (u_new_headers),
                .m_axis (u_new_headers_q_out)
            );

            ifc_axis #(
                .DATA_WIDTH  (DATA_WIDTH),
                .TDEST_WIDTH (1),
                .TID_WIDTH   (1),
                .TUSER_WIDTH (1)
            ) u_payload_no_headers_q_out (.axis_aclk(clk));

            axis_fifo #(
                .DEPTH     (PAYLOAD_DECOUPLE_FIFO_DEPTH),
                .MODE      ("CONSERVATIVE")
            ) u_payload_no_headers_q (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (u_payload_rewrite_q_in),
                .m_axis (u_payload_no_headers_q_out)
            );

            axis_combine_repack #(
                .FIRST_STREAM_IS_A          (1),
                .DATA_WIDTH                 (DATA_WIDTH),
                .FRAGMENT_PACKER_PAGE_COUNT (FRAGMENT_PACKER_PAGE_COUNT)
            ) u_rebuild_packet (
                .clk      (clk),
                .resetn   (resetn),
                .s_axis_a (u_new_headers_q_out),
                .s_axis_b (u_payload_no_headers_q_out),
                .m_axis   (u_packet_out_prescrub)
            );

            // synthesis translate_off
            logic bp_debug_en;
            int unsigned bp_cycle_r;
            int unsigned bp_consec [24];
            int unsigned bp_total [24];
            bit bp_reported [24];

            initial begin
                bp_debug_en = $test$plusargs("checksum_bp_debug");
                for (int i = 0; i < 24; i++) begin
                    bp_consec[i] = 0;
                    bp_total[i] = 0;
                    bp_reported[i] = 1'b0;
                end
            end

            task automatic bp_watch(
                input int unsigned idx,
                input string name,
                input logic valid,
                input logic ready
            );
                if (valid && !ready) begin
                    bp_consec[idx]++;
                    bp_total[idx]++;
                    if (bp_debug_en && !bp_reported[idx] && bp_consec[idx] == 8) begin
                        bp_reported[idx] = 1'b1;
                        $display("[checksum_bp] first sustained stall %-34s cycle=%0d total=%0d",
                                 name, bp_cycle_r, bp_total[idx]);
                    end
                end else begin
                    bp_consec[idx] = 0;
                end
            endtask

            always_ff @(posedge clk) begin
                if (!resetn) begin
                    bp_cycle_r <= 0;
                    for (int i = 0; i < 24; i++) begin
                        bp_consec[i] <= 0;
                        bp_total[i] <= 0;
                        bp_reported[i] <= 1'b0;
                    end
                end else begin
                    bp_cycle_r <= bp_cycle_r + 1;
                    bp_watch(0,  "packet_in", packet_in.tvalid, packet_in.tready);
                    bp_watch(1,  "u_pkt_parser", u_pkt_parser.tvalid, u_pkt_parser.tready);
                    bp_watch(2,  "u_parser_payload", u_parser_payload.tvalid, u_parser_payload.tready);
                    bp_watch(3,  "u_payload_l4_q_in", u_payload_l4_q_in.tvalid, u_payload_l4_q_in.tready);
                    bp_watch(4,  "u_payload_l4_q_out", u_payload_l4_q_out.tvalid, u_payload_l4_q_out.tready);
                    bp_watch(5,  "u_payload_l4_aligned", u_payload_l4_aligned.tvalid, u_payload_l4_aligned.tready);
                    bp_watch(6,  "u_payload_rewrite_q_in", u_payload_rewrite_q_in.tvalid, u_payload_rewrite_q_in.tready);
                    bp_watch(7,  "u_payload_no_headers_q_out", u_payload_no_headers_q_out.tvalid, u_payload_no_headers_q_out.tready);
                    bp_watch(8,  "u_l3_hdr_l4", u_l3_hdr_l4.tvalid, u_l3_hdr_l4.tready);
                    bp_watch(9,  "u_l4_hdr_l4", u_l4_hdr_l4.tvalid, u_l4_hdr_l4.tready);
                    bp_watch(10, "u_l3_hdr_l4_q_out", u_l3_hdr_l4_q_out.tvalid, u_l3_hdr_l4_q_out.tready);
                    bp_watch(11, "u_l4_hdr_l4_q_out", u_l4_hdr_l4_q_out.tvalid, u_l4_hdr_l4_q_out.tready);
                    bp_watch(12, "u_l3_hdr_rewrite_q_in", u_l3_hdr_rewrite_q_in.tvalid, u_l3_hdr_rewrite_q_in.tready);
                    bp_watch(13, "u_l4_hdr_rewrite_q_in", u_l4_hdr_rewrite_q_in.tvalid, u_l4_hdr_rewrite_q_in.tready);
                    bp_watch(14, "u_l3_hdr_rewrite_q_out", u_l3_hdr_rewrite_q_out.tvalid, u_l3_hdr_rewrite_q_out.tready);
                    bp_watch(15, "u_l4_hdr_rewrite_q_out", u_l4_hdr_rewrite_q_out.tvalid, u_l4_hdr_rewrite_q_out.tready);
                    bp_watch(16, "u_l4_csum_operands", u_l4_csum_operands.tvalid, u_l4_csum_operands.tready);
                    bp_watch(17, "u_l4_csum_operands_q_out", u_l4_csum_operands_q_out.tvalid, u_l4_csum_operands_q_out.tready);
                    bp_watch(18, "u_l4_checksum", u_l4_checksum.tvalid, u_l4_checksum.tready);
                    bp_watch(19, "u_l4_checksum_q_out", u_l4_checksum_q_out.tvalid, u_l4_checksum_q_out.tready);
                    bp_watch(20, "u_ipv4_checksum_align_q_out", u_ipv4_checksum_align_q_out.tvalid, u_ipv4_checksum_align_q_out.tready);
                    bp_watch(21, "u_new_headers", u_new_headers.tvalid, u_new_headers.tready);
                    bp_watch(22, "u_new_headers_q_out", u_new_headers_q_out.tvalid, u_new_headers_q_out.tready);
                    bp_watch(23, "u_packet_out_prescrub", u_packet_out_prescrub.tvalid, u_packet_out_prescrub.tready);
                end
            end

            final begin
                if (bp_debug_en) begin
                    $display("[checksum_bp] summary cycle=%0d", bp_cycle_r);
                    $display("[checksum_bp] packet_in=%0d parser=%0d parser_payload=%0d payload_l4_in=%0d payload_l4_out=%0d payload_l4_aligned=%0d payload_rewrite_in=%0d payload_rewrite_out=%0d",
                             bp_total[0], bp_total[1], bp_total[2], bp_total[3], bp_total[4], bp_total[5], bp_total[6], bp_total[7]);
                    $display("[checksum_bp] l3_l4=%0d l4_l4=%0d l3_l4_q=%0d l4_l4_q=%0d l3_rewrite_in=%0d l4_rewrite_in=%0d l3_rewrite_q=%0d l4_rewrite_q=%0d",
                             bp_total[8], bp_total[9], bp_total[10], bp_total[11], bp_total[12], bp_total[13], bp_total[14], bp_total[15]);
                    $display("[checksum_bp] l4_operands=%0d l4_operands_q=%0d l4_checksum=%0d l4_checksum_q=%0d ipv4_checksum_align=%0d new_headers=%0d new_headers_q=%0d output=%0d",
                             bp_total[16], bp_total[17], bp_total[18], bp_total[19], bp_total[20], bp_total[21], bp_total[22], bp_total[23]);
                end
            end
            // synthesis translate_on
        end
    endgenerate

endmodule
