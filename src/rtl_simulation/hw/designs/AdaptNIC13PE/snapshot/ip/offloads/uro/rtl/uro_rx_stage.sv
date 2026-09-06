`include "_uro_pkg.sv"
`include "parser_pkg.sv"

module uro_rx_stage #(
    parameter int TABLE_ADDR_WIDTH  = 4
) (
    input  parser_pkg::l3_hdr_axis_t l3,
    input  parser_pkg::l4_hdr_axis_t l4,
    output logic                         eligible,
    output logic [15:0]                  payload_bytes,
    output uro_pkg::uro_key_t            key,
    output logic [TABLE_ADDR_WIDTH-1:0]  hash
);
    parser_pkg::ipv4_hdr_t ipv4;
    parser_pkg::udp_hdr_t  udp;
    logic [uro_pkg::URO_KEY_BITS-1:0] key_bits;
    localparam int TOEPLITZ_HASH_WIDTH = (TABLE_ADDR_WIDTH < 4) ? 4 : TABLE_ADDR_WIDTH;
    logic [TOEPLITZ_HASH_WIDTH-1:0] full_hash;

    assign ipv4 = l3.ipv4;
    assign udp  = l4.udp;

    always_comb begin
        key = '0;
        key.protocol = ipv4.protocol;
        key.src_addr = ipv4.src_addr;
        key.dst_addr = ipv4.dst_addr;
        key.src_port = udp.src_port;
        key.dst_port = udp.dst_port;

        payload_bytes = (udp.length > 16'(uro_pkg::UDP_HDR_BYTES))
                      ? udp.length - 16'(uro_pkg::UDP_HDR_BYTES) : 16'd0;

        eligible = (l3.status == parser_pkg::PARSER_STATUS_OK) &&
                   (l3.kind == parser_pkg::L3_KIND_IPV4) &&
                   (l4.status == parser_pkg::PARSER_STATUS_OK) &&
                   (l4.kind == parser_pkg::L4_KIND_UDP) &&
                   (ipv4.version == 4'd4) && (ipv4.ihl == 4'd5) &&
                   (ipv4.protocol == 8'd17) &&
                   (ipv4.flags[0] == 1'b0) &&
                   (ipv4.fragment_offset == 13'd0) &&
                   (udp.length > 16'(uro_pkg::UDP_HDR_BYTES)) &&
                   (ipv4.total_length == udp.length + 16'(uro_pkg::IPV4_HDR_BYTES));
    end

    assign key_bits = key;

    toeplitz_hash #(
        .HASH_WIDTH         (TOEPLITZ_HASH_WIDTH),
        .TUPLE_WIDTH        (uro_pkg::URO_KEY_BITS),
        .GENERIC_TUPLE_MODE (1'b1)
    ) u_hash (
        .tuple_bits (key_bits),
        .hash_value (full_hash)
    );
    assign hash = full_hash[TABLE_ADDR_WIDTH-1:0];
endmodule
