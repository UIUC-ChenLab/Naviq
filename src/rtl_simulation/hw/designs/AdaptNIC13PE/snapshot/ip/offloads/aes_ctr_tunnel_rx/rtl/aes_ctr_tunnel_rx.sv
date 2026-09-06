`include "ifc_axis.sv"
`include "ifc_axil.sv"

module aes_ctr_tunnel_rx #(
    parameter int DATA_WIDTH = 512,
    parameter int SA_TABLE_DEPTH = 1024,
    parameter int SA_ID_WIDTH = (SA_TABLE_DEPTH <= 1) ? 1 : $clog2(SA_TABLE_DEPTH),
    parameter int MAX_PACKET_BYTES = 2048
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave packet_in,
    ifc_axil.slave ctrl_in,
    ifc_axis.master packet_out
);
    localparam int AES_META_WIDTH = ((SA_ID_WIDTH + 1 + 64 + 7) / 8) * 8;
    localparam int AES_OUT_META_WIDTH = ((1 + SA_ID_WIDTH + 64 + 7) / 8) * 8;
    localparam int DESC_WIDTH = 16;
    localparam logic [0:0][31:0] CTRL_BASE_ADDR = '{32'h0000_0000};
    localparam logic [0:0][31:0] CTRL_ADDR_SIZE = '{32'h0004_0000};

    ifc_axis #(.DATA_WIDTH(128), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        aes_s_packet(clk), aes_m_packet(clk);
    ifc_axis #(.DATA_WIDTH(AES_META_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)) aes_s_meta(clk);
    ifc_axis #(.DATA_WIDTH(AES_OUT_META_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)) aes_m_meta(clk);
    ifc_axis #(.DATA_WIDTH(DESC_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        rx_desc_s(clk), rx_desc(clk);
    ifc_axil #(.ADDR_WIDTH(32), .DATA_WIDTH(32), .TUSER_WIDTH(1)) ctrl_bus[1](clk);

    axil_crossbar #(.ADDR_WIDTH(32), .DATA_WIDTH(32), .TUSER_WIDTH(1), .NUM_SLAVES(1),
        .SLAVE_BASE_ADDR(CTRL_BASE_ADDR), .SLAVE_ADDR_SIZE(CTRL_ADDR_SIZE)) u_ctrl_crossbar (
        .clk(clk), .resetn(resetn), .s_axil(ctrl_in), .m_axil(ctrl_bus));

    aes_ctr_rx_ingress #(.DATA_WIDTH(DATA_WIDTH), .SA_TABLE_DEPTH(SA_TABLE_DEPTH),
        .SA_ID_WIDTH(SA_ID_WIDTH), .DESC_WIDTH(DESC_WIDTH)) u_ingress (
        .clk(clk), .resetn(resetn), .packet_in(packet_in), .aes_packet_out(aes_s_packet),
        .aes_meta_out(aes_s_meta), .rx_desc_out(rx_desc_s));

    // The descriptor belongs to the decrypted packet, but the egress cannot
    // consume it until the corresponding AES result reaches the head of the
    // pipeline.  Buffering it here lets ingress submit following packet
    // contexts instead of holding the AES input idle for the full round-pipe
    // latency at every packet boundary.
    axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .MODE("FULL_CAPACITY")) u_rx_desc_fifo (
        .clk(clk), .resetn(resetn), .s_axis(rx_desc_s), .m_axis(rx_desc));

    aes_ctr #(.KEY_BITS(256), .PACKET_DATA_WIDTH(128), .SA_TABLE_DEPTH(SA_TABLE_DEPTH),
        .SA_ID_WIDTH(SA_ID_WIDTH)) u_core (
        .clk(clk), .resetn(resetn), .s_axis_packet(aes_s_packet), .s_axis_meta(aes_s_meta),
        .ctrl_in(ctrl_bus[0]), .m_axis_packet(aes_m_packet), .m_axis_meta(aes_m_meta));

    aes_ctr_rx_egress #(.DATA_WIDTH(DATA_WIDTH), .SA_ID_WIDTH(SA_ID_WIDTH),
        .MAX_PACKET_BYTES(MAX_PACKET_BYTES), .DESC_WIDTH(DESC_WIDTH)) u_egress (
        .clk(clk), .resetn(resetn), .aes_packet_in(aes_m_packet), .aes_meta_in(aes_m_meta),
        .rx_desc_in(rx_desc), .packet_out(packet_out));
endmodule
