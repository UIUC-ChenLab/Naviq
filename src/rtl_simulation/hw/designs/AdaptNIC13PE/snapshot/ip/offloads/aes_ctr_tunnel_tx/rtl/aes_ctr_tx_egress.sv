`include "ifc_axis.sv"
`include "aes_ctr_tunnel_tx_pkg.sv"

module aes_ctr_tx_egress #(
    parameter int DATA_WIDTH=512,
    parameter int SA_ID_WIDTH=10,
    parameter int DESC_WIDTH=((SA_ID_WIDTH+16+64+7)/8)*8
) (
    input logic clk,input logic resetn,
    ifc_axis.slave aes_packet_in,
    ifc_axis.slave aes_meta_in,
    ifc_axis.slave tx_desc_in,
    ifc_axis.master packet_out
);
    import aes_ctr_tunnel_tx_pkg::*;
    localparam int DESC_LEN_LSB=SA_ID_WIDTH;
    localparam int DESC_SRC_LSB=DESC_LEN_LSB+16;
    localparam int DESC_DST_LSB=DESC_SRC_LSB+32;
    localparam int CTX_WIDTH=DESC_WIDTH+64;

    ifc_axis #(.DATA_WIDTH(CTX_WIDTH),.TDEST_WIDTH(1),.TID_WIDTH(1),.TUSER_WIDTH(1)) ctx_in(clk),ctx_q(clk);
    always_comb begin
        ctx_in.t='0;ctx_in.t.data={aes_meta_in.t.data[63:0],tx_desc_in.t.data};ctx_in.t.keep='1;ctx_in.t.last=1;
        ctx_in.tvalid=aes_meta_in.tvalid&&tx_desc_in.tvalid;
        aes_meta_in.tready=ctx_in.tready&&tx_desc_in.tvalid;
        tx_desc_in.tready=ctx_in.tready&&aes_meta_in.tvalid;
    end
    axis_fifo #(.DEPTH(TX_DESC_FIFO_DEPTH),.USE_BRAM(1'b0),.MODE("CONSERVATIVE")) u_ctx_fifo(.clk(clk),.resetn(resetn),.s_axis(ctx_in),.m_axis(ctx_q));

    logic active_r,first_r;
    logic [DESC_WIDTH-1:0] desc_r;
    logic [63:0] seq_r;
    wire aes_packet_fire=aes_packet_in.tvalid && aes_packet_in.tready;
    wire aes_packet_done=aes_packet_fire && aes_packet_in.t.last;
    wire ctx_slot_available=!active_r || aes_packet_done;
    assign ctx_q.tready=ctx_slot_available;
    always_ff @(posedge clk) begin
        if(!resetn) begin active_r<=0;first_r<=1; end else begin
            if(aes_packet_fire) begin first_r<=0;if(aes_packet_in.t.last)active_r<=0;end
            // Let a new context win over simultaneous packet completion so
            // the next ciphertext block can be accepted without a dead cycle.
            if(ctx_q.tvalid&&ctx_q.tready) begin desc_r<=ctx_q.t.data[DESC_WIDTH-1:0];seq_r<=ctx_q.t.data[DESC_WIDTH +:64];active_r<=1;first_r<=1;end
        end
    end

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH),.TDEST_WIDTH(1),.TID_WIDTH(1),.TUSER_WIDTH(1)) fragment_in(clk),packed_axis(clk);
    logic [15:0] inner_len,total_len;
    logic [1:0] pad_len;
    logic [31:0] outer_src,outer_dst,sa_word;
    logic [SA_ID_WIDTH-1:0] sa_id;
    always_comb begin
        inner_len=desc_r[DESC_LEN_LSB +:16];pad_len=2'((4-((inner_len+2)&3))&3);
        total_len=16'(32+inner_len+pad_len+2);outer_src=desc_r[DESC_SRC_LSB +:32];outer_dst=desc_r[DESC_DST_LSB +:32];sa_id=desc_r[SA_ID_WIDTH-1:0];sa_word=32'(sa_id);
        fragment_in.t='0;fragment_in.tvalid=aes_packet_in.tvalid&&active_r;
        if(first_r) begin
            fragment_in.t.data[8*0 +:8]=8'h45;fragment_in.t.data[8*1 +:8]=0;
            fragment_in.t.data[8*2 +:8]=total_len[15:8];fragment_in.t.data[8*3 +:8]=total_len[7:0];
            fragment_in.t.data[8*6 +:8]=8'h40;fragment_in.t.data[8*8 +:8]=8'd64;fragment_in.t.data[8*9 +:8]=8'(ESP_PROTO);
            fragment_in.t.data[8*10 +:16]=16'h0000;
            for(int i=0;i<4;i++) begin fragment_in.t.data[8*(12+i)+:8]=outer_src[8*(3-i)+:8];fragment_in.t.data[8*(16+i)+:8]=outer_dst[8*(3-i)+:8];end
            for(int i=0;i<4;i++) fragment_in.t.data[8*(20+i)+:8]=sa_word[8*(3-i)+:8];
            for(int i=0;i<8;i++) fragment_in.t.data[8*(24+i)+:8]=seq_r[8*(7-i)+:8];
            fragment_in.t.data[8*32 +:128]=aes_packet_in.t.data;fragment_in.t.keep[47:0]='1;
        end else begin fragment_in.t.data[127:0]=aes_packet_in.t.data;fragment_in.t.keep[15:0]=aes_packet_in.t.keep;end
        fragment_in.t.last=aes_packet_in.t.last;
        aes_packet_in.tready=fragment_in.tready&&active_r;
    end
    axis_fragment_packer #(.DATA_WIDTH(DATA_WIDTH),.PAGE_COUNT(8)) u_pack(.clk(clk),.resetn(resetn),.s_axis(fragment_in),.m_axis(packed_axis));
    always_comb begin
        packet_out.t='0;packet_out.t.data=packed_axis.t.data;packet_out.t.keep=packed_axis.t.keep;packet_out.t.last=packed_axis.t.last;
    end
    assign packet_out.tvalid=packed_axis.tvalid;
    assign packed_axis.tready=packet_out.tready;
endmodule
