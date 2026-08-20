// Deterministic AXI-MM NSU fixture for the generated RTL wrapper V1.
//
// The xpm_nsu_mm instance exposes a NoC destination port.  This module is a
// one-beat, AW-before-W memory-like slave: partial WSTRB writes update a
// 512-bit word and AR returns that word.  It intentionally keeps one write
// and one read response outstanding so ready/valid backpressure is visible.
module AximmMemorySmoke (
    input logic clk,
    input logic resetn
);
    localparam int DATA_WIDTH = 512;
    localparam int ADDR_WIDTH = 32;
    localparam int ID_WIDTH = 4;

    logic [ADDR_WIDTH-1:0] awaddr, araddr;
    logic [7:0] awlen, arlen;
    logic [2:0] awsize, arsize, awprot, arprot;
    logic [1:0] awburst, arburst, awlock, arlock;
    logic [3:0] awcache, arcache, awqos, arqos, awregion, arregion;
    logic [ID_WIDTH-1:0] awid, arid, wid, bid, rid;
    logic awvalid, awready, wvalid, wready, wlast;
    logic [DATA_WIDTH-1:0] wdata, rdata;
    logic [DATA_WIDTH/8-1:0] wstrb;
    logic bvalid, bready, rvalid, rready, rlast;
    logic [1:0] bresp, rresp;
    logic [0:0] awuser, wuser, buser, aruser, ruser;

    xpm_nsu_mm #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH),
        .ID_WIDTH(ID_WIDTH)
    ) u_nsu (
        .m_axi_aclk(clk),
        .m_axi_awaddr(awaddr), .m_axi_awlen(awlen),
        .m_axi_awsize(awsize), .m_axi_awburst(awburst),
        .m_axi_awprot(awprot), .m_axi_awcache(awcache),
        .m_axi_awid(awid), .m_axi_awlock(awlock),
        .m_axi_awqos(awqos), .m_axi_awregion(awregion),
        .m_axi_awuser(awuser), .m_axi_awvalid(awvalid),
        .m_axi_awready(awready),
        .m_axi_wdata(wdata), .m_axi_wstrb(wstrb),
        .m_axi_wuser(wuser), .m_axi_wid(wid), .m_axi_wlast(wlast),
        .m_axi_wvalid(wvalid), .m_axi_wready(wready),
        .m_axi_bresp(bresp), .m_axi_bid(bid), .m_axi_buser(buser),
        .m_axi_bvalid(bvalid), .m_axi_bready(bready),
        .m_axi_araddr(araddr), .m_axi_arlen(arlen),
        .m_axi_arsize(arsize), .m_axi_arburst(arburst),
        .m_axi_arprot(arprot), .m_axi_arcache(arcache),
        .m_axi_arid(arid), .m_axi_arlock(arlock),
        .m_axi_arqos(arqos), .m_axi_arregion(arregion),
        .m_axi_aruser(aruser), .m_axi_arvalid(arvalid),
        .m_axi_arready(arready),
        .m_axi_rdata(rdata), .m_axi_rresp(rresp), .m_axi_rid(rid),
        .m_axi_ruser(ruser), .m_axi_rlast(rlast),
        .m_axi_rvalid(rvalid), .m_axi_rready(rready)
    );

    logic [DATA_WIDTH-1:0] memory_word;
    logic [ID_WIDTH-1:0] pending_awid;
    logic pending_aw;
    integer lane;

    assign awready = !pending_aw && !bvalid;
    assign wready = pending_aw && !bvalid;
    assign arready = !rvalid;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            memory_word <= '0;
            pending_aw <= 1'b0;
            pending_awid <= '0;
            bvalid <= 1'b0;
            bresp <= 2'b00;
            bid <= '0;
            buser <= '0;
            rvalid <= 1'b0;
            rdata <= '0;
            rresp <= 2'b00;
            rid <= '0;
            ruser <= '0;
            rlast <= 1'b0;
        end else begin
            if (awvalid && awready) begin
                pending_aw <= 1'b1;
                pending_awid <= awid;
            end
            if (wvalid && wready) begin
                for (lane = 0; lane < DATA_WIDTH / 8; lane = lane + 1) begin
                    if (wstrb[lane])
                        memory_word[lane * 8 +: 8] <= wdata[lane * 8 +: 8];
                end
                pending_aw <= 1'b0;
                bvalid <= 1'b1;
                bresp <= 2'b00;
                bid <= pending_awid;
                buser <= '0;
            end else if (bvalid && bready) begin
                bvalid <= 1'b0;
            end
            if (arvalid && arready) begin
                rvalid <= 1'b1;
                rdata <= memory_word;
                rresp <= 2'b00;
                rid <= arid;
                ruser <= '0;
                rlast <= 1'b1;
            end else if (rvalid && rready) begin
                rvalid <= 1'b0;
            end
        end
    end
endmodule
