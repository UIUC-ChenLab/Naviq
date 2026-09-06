`include "ifc_axis.sv"
`include "ifc_axil.sv"
`include "aes_ctr_tunnel_tx_pkg.sv"

module aes_ctr_tunnel_tx #(
    parameter int DATA_WIDTH=512,
    parameter int SA_TABLE_DEPTH=1024,parameter int SA_ID_WIDTH=(SA_TABLE_DEPTH<=1)?1:$clog2(SA_TABLE_DEPTH),parameter int HASH_WIDTH=12
) (input logic clk,input logic resetn,ifc_axis.slave packet_in,ifc_axil.slave ctrl_in,ifc_axis.master packet_out);
    import aes_ctr_tunnel_tx_pkg::*;
    localparam int AES_META_WIDTH=(((SA_ID_WIDTH+1+64)+7)/8)*8;
    localparam int AES_OUT_META_WIDTH=(((1+SA_ID_WIDTH+64)+7)/8)*8;
    localparam int DESC_WIDTH=((SA_ID_WIDTH+16+64+7)/8)*8;
    ifc_axis #(.DATA_WIDTH(128),.TDEST_WIDTH(1),.TID_WIDTH(1),.TUSER_WIDTH(1)) aes_s_packet(clk),aes_m_packet(clk);
    ifc_axis #(.DATA_WIDTH(AES_META_WIDTH),.TDEST_WIDTH(1),.TID_WIDTH(1),.TUSER_WIDTH(1)) aes_s_meta(clk);
    ifc_axis #(.DATA_WIDTH(AES_OUT_META_WIDTH),.TDEST_WIDTH(1),.TID_WIDTH(1),.TUSER_WIDTH(1)) aes_m_meta(clk);
    ifc_axis #(.DATA_WIDTH(DESC_WIDTH),.TDEST_WIDTH(1),.TID_WIDTH(1),.TUSER_WIDTH(1)) tx_desc(clk);
    localparam logic [2:0][31:0] CTRL_BASE_ADDR = {
        TX_TUNNEL_BASE_ADDR, TX_MATCH_BASE_ADDR, TX_SA_BASE_ADDR
    };
    localparam logic [2:0][31:0] CTRL_ADDR_SIZE = {
        32'h0001_0000, 32'h0001_0000, 32'h0001_0000
    };
    ifc_axil #(.ADDR_WIDTH(32),.DATA_WIDTH(32),.TUSER_WIDTH(1)) ctrl_bus[3](clk);

    axil_crossbar #(
      .ADDR_WIDTH(32),.DATA_WIDTH(32),.TUSER_WIDTH(1),.NUM_SLAVES(3),
      .SLAVE_BASE_ADDR(CTRL_BASE_ADDR),.SLAVE_ADDR_SIZE(CTRL_ADDR_SIZE)
    ) u_ctrl_crossbar(.clk(clk),.resetn(resetn),.s_axil(ctrl_in),.m_axil(ctrl_bus));

    aes_ctr_tx_ingress #(.DATA_WIDTH(DATA_WIDTH),
      .SA_TABLE_DEPTH(SA_TABLE_DEPTH),.SA_ID_WIDTH(SA_ID_WIDTH),.HASH_WIDTH(HASH_WIDTH),.DESC_WIDTH(DESC_WIDTH)) u_ingress(
      .clk(clk),.resetn(resetn),.packet_in(packet_in),.hash_ctrl(ctrl_bus[1]),.tunnel_ctrl(ctrl_bus[2]),
      .aes_packet_out(aes_s_packet),.aes_meta_out(aes_s_meta),.tx_desc_out(tx_desc));
    aes_ctr #(.KEY_BITS(256),.PACKET_DATA_WIDTH(128),.SA_TABLE_DEPTH(SA_TABLE_DEPTH),
      .SA_ID_WIDTH(SA_ID_WIDTH),.SA_STRIDE(TX_SA_STRIDE)) u_core(
      .clk(clk),.resetn(resetn),.s_axis_packet(aes_s_packet),.s_axis_meta(aes_s_meta),.ctrl_in(ctrl_bus[0]),.m_axis_packet(aes_m_packet),.m_axis_meta(aes_m_meta));
    aes_ctr_tx_egress #(.DATA_WIDTH(DATA_WIDTH),
      .SA_ID_WIDTH(SA_ID_WIDTH),.DESC_WIDTH(DESC_WIDTH)) u_egress(.clk(clk),.resetn(resetn),.aes_packet_in(aes_m_packet),.aes_meta_in(aes_m_meta),.tx_desc_in(tx_desc),.packet_out(packet_out));

endmodule
