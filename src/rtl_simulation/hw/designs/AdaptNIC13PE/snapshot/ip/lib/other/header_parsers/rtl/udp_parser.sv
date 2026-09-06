`include "ifc_axis.sv"
`include "parser_pkg.sv"
import parser_pkg::*;

module udp_parser #(
    parameter int DATA_WIDTH = 512,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis_packet_in,
    ifc_axis.master m_axis_header_out,
    ifc_axis.master m_axis_payload_out
);

    localparam int TDEST_WIDTH = 1;
    localparam int TID_WIDTH = 1;
    localparam int TUSER_WIDTH = 1;
    localparam int HDR_BYTES    = 8;
    localparam int HDR_AXIS_W   = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int STRIP_W      = 8;
    localparam int BYTE_COUNT_W = 16;
    localparam int HDR_SCAN_AXIS_W = (HDR_BYTES + 1) * 8;
    localparam int PKT_Q_DEPTH  = 128;
    localparam int SCAN_IN_Q_DEPTH = 4;
    localparam int STRIP_COUNT_Q_DEPTH = 4;

    typedef logic [HDR_BYTES*8-1:0] hdr_bytes_t;

    function automatic udp_hdr_t decode_udp(input hdr_bytes_t bytes);
        udp_hdr_t hdr;
        hdr = '0;
        hdr.src_port = {bytes[8*0 +: 8], bytes[8*1 +: 8]};
        hdr.dst_port = {bytes[8*2 +: 8], bytes[8*3 +: 8]};
        hdr.length   = {bytes[8*4 +: 8], bytes[8*5 +: 8]};
        hdr.checksum = {bytes[8*6 +: 8], bytes[8*7 +: 8]};
        return hdr;
    endfunction

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_packet_in (.axis_aclk(clk)), u_payload_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(HDR_AXIS_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_header_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_in_fan [2] (.axis_aclk(clk));

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_input_rs (
        .clk(clk), .resetn(resetn), .s_axis(s_axis_packet_in), .m_axis(u_packet_in)
    );

    axis_multicast #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
        .TUSER_WIDTH(TUSER_WIDTH), .NUM_DESTS(2)
    ) u_input_fanout (
        .clk(clk), .resetn(resetn), .s_axis(u_packet_in), .m_axis(u_in_fan)
    );

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_pkt_q_out (.axis_aclk(clk)), u_scan_in (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH            (PKT_Q_DEPTH),
        .EXTRA_OUTPUT_REG (1'b1),
        .MODE             ("CONSERVATIVE")
    ) u_packet_q (
        .clk(clk), .resetn(resetn), .s_axis(u_in_fan[0]), .m_axis(u_pkt_q_out)
    );

    axis_fifo #(
        .DEPTH    (SCAN_IN_Q_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_scan_in_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_in_fan[1]), .m_axis(u_scan_in)
    );

    ifc_axis #(.DATA_WIDTH(HDR_AXIS_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_hdr_scan (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(HDR_SCAN_AXIS_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_hdr_bytes (.axis_aclk(clk));
    header_byte_scanner #(
        .DATA_WIDTH (DATA_WIDTH),
        .HDR_BYTES  (HDR_BYTES)
    ) u_header_byte_scanner (
        .clk           (clk),
        .resetn        (resetn),
        .s_axis        (u_scan_in),
        .m_axis_header (u_hdr_bytes)
    );

    hdr_bytes_t hdr_bytes_c;
    logic hdr_short_c;
    udp_hdr_t decoded_c;
    parser_pkg::l4_hdr_axis_t hdr_scan_c;

    assign hdr_bytes_c = hdr_bytes_t'(u_hdr_bytes.t.data[HDR_BYTES * 8 - 1:0]);
    assign hdr_short_c = u_hdr_bytes.t.data[HDR_BYTES * 8];
    assign decoded_c = decode_udp(hdr_bytes_c);

    always_comb begin
        hdr_scan_c = '0;
        if (hdr_short_c) begin
            hdr_scan_c.status = parser_pkg::PARSER_STATUS_SHORT;
            hdr_scan_c.kind = parser_pkg::L4_KIND_UDP;
            hdr_scan_c.protocol = 8'd17;
        end else begin
            hdr_scan_c.status = (decoded_c.length < 16'(HDR_BYTES))
                ? parser_pkg::PARSER_STATUS_MALFORMED : parser_pkg::PARSER_STATUS_OK;
            hdr_scan_c.kind = parser_pkg::L4_KIND_UDP;
            hdr_scan_c.header_len = 16'(HDR_BYTES);
            hdr_scan_c.protocol = 8'd17;
            hdr_scan_c.udp = decoded_c;
        end

        u_hdr_scan.t = '0;
        u_hdr_scan.t.data = hdr_scan_c;
        u_hdr_scan.t.keep = '1;
        u_hdr_scan.t.id = u_hdr_bytes.t.id;
        u_hdr_scan.t.dest = u_hdr_bytes.t.dest;
        u_hdr_scan.t.user = u_hdr_bytes.t.user;
        u_hdr_scan.t.last = 1'b1;
        u_hdr_scan.tvalid = u_hdr_bytes.tvalid;
    end
    assign u_hdr_bytes.tready = u_hdr_scan.tready;

    ifc_axis #(.DATA_WIDTH(HDR_AXIS_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_hdr_fan [2] (.axis_aclk(clk));

    axis_multicast #(
        .DATA_WIDTH(HDR_AXIS_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
        .TUSER_WIDTH(TUSER_WIDTH), .NUM_DESTS(2)
    ) u_header_fanout (
        .clk(clk), .resetn(resetn), .s_axis(u_hdr_scan), .m_axis(u_hdr_fan)
    );

    assign u_header_out.t = u_hdr_fan[0].t;
    assign u_header_out.tvalid = u_hdr_fan[0].tvalid;
    assign u_hdr_fan[0].tready = u_header_out.tready;

    ifc_axis #(.DATA_WIDTH(STRIP_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_strip_count (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(STRIP_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_strip_count_q (.axis_aclk(clk));

    parser_pkg::l4_hdr_axis_t strip_hdr;
    assign strip_hdr = parser_pkg::l4_hdr_axis_t'(u_hdr_fan[1].t.data);

    always_comb begin
        u_strip_count.t = '0;
        u_strip_count.t.data[STRIP_W-1:0] =
            STRIP_W'((strip_hdr.status == parser_pkg::PARSER_STATUS_SHORT) ? 16'd0 : strip_hdr.header_len);
        u_strip_count.t.keep = '1;
        u_strip_count.t.id = u_hdr_fan[1].t.id;
        u_strip_count.t.dest = u_hdr_fan[1].t.dest;
        u_strip_count.t.user = u_hdr_fan[1].t.user;
        u_strip_count.t.last = 1'b1;
        u_strip_count.tvalid = u_hdr_fan[1].tvalid;
    end
    assign u_hdr_fan[1].tready = u_strip_count.tready;

    axis_fifo #(
        .DEPTH    (STRIP_COUNT_Q_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_strip_count_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_strip_count), .m_axis(u_strip_count_q)
    );

    axis_strip_repack #(
        .DATA_WIDTH(DATA_WIDTH), .STRIP_WIDTH(STRIP_W),
        .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT)
    ) u_payload_strip (
        .clk(clk), .resetn(resetn), .s_axis(u_pkt_q_out), .s_axis_remove(u_strip_count_q),
        .m_axis(u_payload_out)
    );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_header_out_rs (
        .clk(clk), .resetn(resetn), .s_axis(u_header_out), .m_axis(m_axis_header_out)
    );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_payload_out_rs (
        .clk(clk), .resetn(resetn), .s_axis(u_payload_out), .m_axis(m_axis_payload_out)
    );

endmodule
