`include "ifc_axis.sv"
`include "parser_pkg.sv"
import parser_pkg::*;

module hash_packet_headers #(
    parameter int OUTPUT_DATA_WIDTH = 512,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16,
    parameter int TUSER_WIDTH = 16,
    parameter int HASH_WIDTH = 12,
    parameter int TUPLE_WIDTH = 104,
    parameter int TOEPLITZ_KEY_W = 320,
    parameter logic [TOEPLITZ_KEY_W-1:0] TOEPLITZ_KEY =
        320'h6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_l3_header_in,
    ifc_axis.slave  s_axis_l4_header_in,
    ifc_axis.master packet_out
);

    localparam int L3_W = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_W = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int OUTPUT_TUSER_WIDTH = parser_pkg::IPV4_PROTOCOL_W;

    initial begin
        if (OUTPUT_DATA_WIDTH < HASH_WIDTH || OUTPUT_DATA_WIDTH % 8 != 0 ||
            (OUTPUT_DATA_WIDTH & (OUTPUT_DATA_WIDTH - 1)) != 0) begin
            $error("hash_packet_headers: OUTPUT_DATA_WIDTH must be a byte-aligned power of two >= HASH_WIDTH (%0d), got %0d",
                   HASH_WIDTH, OUTPUT_DATA_WIDTH);
            $finish;
        end
        if ($bits(s_axis_l3_header_in.t.data) != L3_W) begin
            $error("hash_packet_headers: L3 header width (%0d) must equal parser L3 header width (%0d)",
                   $bits(s_axis_l3_header_in.t.data), L3_W);
            $finish;
        end
        if ($bits(s_axis_l4_header_in.t.data) != L4_W) begin
            $error("hash_packet_headers: L4 header width (%0d) must equal parser L4 header width (%0d)",
                   $bits(s_axis_l4_header_in.t.data), L4_W);
            $finish;
        end
        if ($bits(packet_out.t.data) != OUTPUT_DATA_WIDTH) begin
            $error("hash_packet_headers: packet_out.t.data width (%0d) must equal OUTPUT_DATA_WIDTH (%0d)",
                   $bits(packet_out.t.data), OUTPUT_DATA_WIDTH);
            $finish;
        end
    end

    // Tuple layout must match toeplitz_hash::virtual_tuple_bit (DPDK RSS order):
    //   [31:0] src_ip, [63:32] dst_ip, [79:64] src_port, [95:80] dst_port, [103:96] protocol
    logic [TUPLE_WIDTH-1:0] tuple_bits;
    logic [HASH_WIDTH-1:0] hash_value;

    parser_pkg::l3_hdr_axis_t l3_hdr;
    parser_pkg::l4_hdr_axis_t l4_hdr;
    parser_pkg::ipv4_hdr_t    ipv4_hdr;
    parser_pkg::tcp_hdr_t     tcp_hdr;
    parser_pkg::udp_hdr_t     udp_hdr;

    assign l3_hdr   = parser_pkg::l3_hdr_axis_t'(s_axis_l3_header_in.t.data);
    assign l4_hdr   = parser_pkg::l4_hdr_axis_t'(s_axis_l4_header_in.t.data);
    assign ipv4_hdr = l3_hdr.ipv4;
    assign tcp_hdr  = l4_hdr.tcp;
    assign udp_hdr  = l4_hdr.udp;

    logic is_tcp;
    logic eligible;
    logic headers_valid;
    logic headers_ready;
    logic [15:0] tuple_src_port;
    logic [15:0] tuple_dst_port;

    assign is_tcp = (l4_hdr.kind == parser_pkg::L4_KIND_TCP);
    assign eligible = (l3_hdr.status == parser_pkg::PARSER_STATUS_OK)
        && (l3_hdr.kind == parser_pkg::L3_KIND_IPV4)
        && (l4_hdr.status == parser_pkg::PARSER_STATUS_OK)
        && ((l4_hdr.kind == parser_pkg::L4_KIND_TCP) || (l4_hdr.kind == parser_pkg::L4_KIND_UDP));
    assign headers_valid = s_axis_l3_header_in.tvalid && s_axis_l4_header_in.tvalid;
    assign tuple_src_port = is_tcp ? tcp_hdr.src_port : udp_hdr.src_port;
    assign tuple_dst_port = is_tcp ? tcp_hdr.dst_port : udp_hdr.dst_port;

    always_comb begin
        tuple_bits = {
            ipv4_hdr.protocol,
            tuple_dst_port,
            tuple_src_port,
            ipv4_hdr.dst_addr,
            ipv4_hdr.src_addr
        };
    end

    logic [TUPLE_WIDTH-1:0] tuple_bits_reg;
    logic                   tuple_push_valid;
    logic                   tuple_push_ready;
    logic                   tuple_to_hash_valid;
    logic                   tuple_to_hash_ready;

    assign tuple_push_valid = headers_valid && eligible;
    assign headers_ready = headers_valid && (eligible ? tuple_push_ready : 1'b1);
    assign s_axis_l3_header_in.tready = headers_ready;
    assign s_axis_l4_header_in.tready = headers_ready;

    register_slice #(
        .T (logic [TUPLE_WIDTH-1:0])
    ) u_tuple_reg (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (tuple_push_valid),
        .push_data  (tuple_bits),
        .push_ready (tuple_push_ready),
        .pop_valid  (tuple_to_hash_valid),
        .pop_data   (tuple_bits_reg),
        .pop_ready  (tuple_to_hash_ready)
    );

    toeplitz_hash #(
        .HASH_WIDTH     (HASH_WIDTH),
        .TUPLE_WIDTH    (TUPLE_WIDTH),
        .TOEPLITZ_KEY_W (TOEPLITZ_KEY_W),
        .TOEPLITZ_KEY   (TOEPLITZ_KEY)
    ) u_toeplitz_hash (
        .tuple_bits (tuple_bits_reg),
        .hash_value (hash_value)
    );

    typedef struct packed {
        logic [HASH_WIDTH-1:0] hash;
        logic [OUTPUT_TUSER_WIDTH-1:0] protocol;
    } packet_data_t;

    packet_data_t packet_data_reg;
    logic         packet_data_valid;

    packet_data_t packet_data;
    assign packet_data.hash = hash_value;
    assign packet_data.protocol = tuple_bits_reg[TUPLE_WIDTH - 1 : TUPLE_WIDTH - OUTPUT_TUSER_WIDTH];

    register_slice #(
        .T (packet_data_t)
    ) u_hash_reg (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (tuple_to_hash_valid),
        .push_data  (packet_data),
        .push_ready (tuple_to_hash_ready),
        .pop_valid  (packet_data_valid),
        .pop_data   (packet_data_reg),
        .pop_ready  (packet_out.tready)
    );

    assign packet_out.t.data = packet_data_reg.hash;
    assign packet_out.t.keep = '1;
    assign packet_out.t.id = '0;
    assign packet_out.t.dest = '0;
    assign packet_out.t.user = $bits(packet_out.t.user)'(packet_data_reg.protocol);
    assign packet_out.t.last = 1'b1;
    assign packet_out.tvalid = packet_data_valid;

endmodule
