`include "ifc_axis.sv"
`include "parser_pkg.sv"
import parser_pkg::*;

module ethernet_parser #(
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
    localparam int HDR_BYTES    = 14;
    localparam int HDR_AXIS_W   = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int STRIP_W      = 8;
    localparam int HDR_SCAN_AXIS_W = (HDR_BYTES + 1) * 8;
    localparam int PKT_Q_DEPTH  = 128;
    localparam int STRIP_COUNT_Q_DEPTH = 4;

    typedef logic [HDR_BYTES*8-1:0] hdr_bytes_t;

    initial begin
        if (DATA_WIDTH < 8 || DATA_WIDTH % 8 != 0 || (DATA_WIDTH & (DATA_WIDTH - 1)) != 0)
            $error("ethernet_parser: DATA_WIDTH must be a byte-aligned power of two >= 8");
        if ($bits(m_axis_header_out.t.data) != HDR_AXIS_W)
            $error("ethernet_parser: m_axis_header_out width mismatch");
    end

    function automatic ethernet_hdr_t decode_ethernet(input hdr_bytes_t bytes);
        ethernet_hdr_t hdr;
        hdr = '0;
        for (int i = 0; i < 6; i++) begin
            hdr.dst_mac[47 - 8*i -: 8] = bytes[8*i +: 8];
            hdr.src_mac[47 - 8*i -: 8] = bytes[8*(6 + i) +: 8];
        end
        hdr.ethertype = {bytes[8*12 +: 8], bytes[8*13 +: 8]};
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
        u_pkt_q_out (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH            (PKT_Q_DEPTH),
        .EXTRA_OUTPUT_REG (1'b1),
        .MODE             ("CONSERVATIVE")
    ) u_packet_q (
        .clk(clk), .resetn(resetn), .s_axis(u_in_fan[0]), .m_axis(u_pkt_q_out)
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
        .s_axis        (u_in_fan[1]),
        .m_axis_header (u_hdr_bytes)
    );

    hdr_bytes_t hdr_bytes_c;
    logic hdr_short_c;
    ethernet_hdr_t decoded_c;
    parser_pkg::l2_hdr_axis_t hdr_scan_c;

    assign hdr_bytes_c = hdr_bytes_t'(u_hdr_bytes.t.data[HDR_BYTES * 8 - 1:0]);
    assign hdr_short_c = u_hdr_bytes.t.data[HDR_BYTES * 8];
    assign decoded_c = decode_ethernet(hdr_bytes_c);

    always_comb begin
        hdr_scan_c = '0;
        if (hdr_short_c) begin
            hdr_scan_c.status = parser_pkg::PARSER_STATUS_SHORT;
            hdr_scan_c.kind = parser_pkg::L2_KIND_ETHERNET;
        end else begin
            hdr_scan_c.status = parser_pkg::PARSER_STATUS_OK;
            hdr_scan_c.kind = parser_pkg::L2_KIND_ETHERNET;
            hdr_scan_c.header_len = 16'(HDR_BYTES);
            hdr_scan_c.ethernet = decoded_c;
            hdr_scan_c.ethertype = decoded_c.ethertype;
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

    parser_pkg::l2_hdr_axis_t strip_hdr;
    assign strip_hdr = parser_pkg::l2_hdr_axis_t'(u_hdr_fan[1].t.data);

    always_comb begin
        u_strip_count.t = '0;
        u_strip_count.t.data[STRIP_W-1:0] =
            STRIP_W'(strip_hdr.status == parser_pkg::PARSER_STATUS_OK ? strip_hdr.header_len : 16'd0);
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
