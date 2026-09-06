`include "ifc_axis.sv"
`include "parser_pkg.sv"

module parse_and_hash_packet #(
    parameter int DATA_WIDTH = 512,
    parameter int OUTPUT_DATA_WIDTH = DATA_WIDTH,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16,
    parameter int TUSER_WIDTH = 16,
    parameter int HASH_WIDTH = 12,
    parameter int TUPLE_WIDTH = 104,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8,
    parameter int TOEPLITZ_KEY_W = 320,
    parameter logic [TOEPLITZ_KEY_W-1:0] TOEPLITZ_KEY =
        320'h6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  packet_in,
    ifc_axis.master packet_out
);

    localparam int L2_HDR_W = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int L3_HDR_W = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_W = parser_pkg::L4_HDR_AXIS_BITS;

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) parser_packet_in (.axis_aclk(clk));

    assign parser_packet_in.t.data = packet_in.t.data;
    assign parser_packet_in.t.keep = packet_in.t.keep;
    assign parser_packet_in.t.id = '0;
    assign parser_packet_in.t.dest = '0;
    assign parser_packet_in.t.user = '0;
    assign parser_packet_in.t.last = packet_in.t.last;
    assign parser_packet_in.tvalid = packet_in.tvalid;
    assign packet_in.tready = parser_packet_in.tready;

    ifc_axis #(
        .DATA_WIDTH  (L2_HDR_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l2_header_unused (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (L3_HDR_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l3_header (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (L4_HDR_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l4_header (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (L3_HDR_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l3_header_q (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (L4_HDR_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l4_header_q (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) payload_unused (.axis_aclk(clk));

    parser #(
        .DATA_WIDTH        (DATA_WIDTH),
        .REPACK_PAYLOAD_OUT(1'b0),
        .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT),
        .SKIP_L2           (1'b1),
        .DEFAULT_ETHERTYPE (16'h0800)
    ) u_parser (
        .clk                 (clk),
        .resetn              (resetn),
        .s_axis_packet_in    (parser_packet_in),
        .m_axis_l2_header_out(l2_header_unused),
        .m_axis_l3_header_out(l3_header),
        .m_axis_l4_header_out(l4_header),
        .m_axis_payload_out  (payload_unused)
    );

    assign l2_header_unused.tready = 1'b1;
    assign payload_unused.tready = 1'b1;

    axis_fifo #(.DEPTH(128), .MODE("CONSERVATIVE")) u_l3_header_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (l3_header),
        .m_axis (l3_header_q)
    );

    axis_fifo #(.DEPTH(128), .MODE("CONSERVATIVE")) u_l4_header_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (l4_header),
        .m_axis (l4_header_q)
    );

    hash_packet_headers #(
        .OUTPUT_DATA_WIDTH (OUTPUT_DATA_WIDTH),
        .TDEST_WIDTH       (TDEST_WIDTH),
        .TID_WIDTH         (TID_WIDTH),
        .TUSER_WIDTH       (TUSER_WIDTH),
        .HASH_WIDTH        (HASH_WIDTH),
        .TUPLE_WIDTH       (TUPLE_WIDTH),
        .TOEPLITZ_KEY_W    (TOEPLITZ_KEY_W),
        .TOEPLITZ_KEY      (TOEPLITZ_KEY)
    ) u_hash_packet_headers (
        .clk                (clk),
        .resetn             (resetn),
        .s_axis_l3_header_in(l3_header_q.slave),
        .s_axis_l4_header_in(l4_header_q.slave),
        .packet_out         (packet_out)
    );

endmodule
