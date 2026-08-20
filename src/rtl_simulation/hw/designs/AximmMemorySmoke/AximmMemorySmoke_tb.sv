// Direct RTL contract test for the AXI-MM V1 reference fixture.
//
// The fixture's xpm_nsu_mm is intentionally a marker module.  Drive the
// marker-connected AXI wires here, then verify a full write, partial-WSTRB
// update, and read-data response.
module AximmMemorySmoke_tb;
    logic clk = 0;
    logic resetn = 0;
    logic [511:0] initial_data;
    logic [511:0] partial_data;
    logic [511:0] expected_data;
    logic [511:0] read_data;
    integer lane;

    AximmMemorySmoke dut (.clk(clk), .resetn(resetn));

    always #1 clk = ~clk;

    task automatic write_beat(
        input logic [511:0] data,
        input logic [63:0] strb
    );
        force dut.awaddr = 32'h0;
        force dut.awlen = 8'h0;
        force dut.awsize = 3'd6;
        force dut.awburst = 2'b01;
        force dut.awid = 4'h3;
        force dut.awvalid = 1'b1;
        while (!dut.awready) @(negedge clk);
        @(posedge clk);
        force dut.awvalid = 1'b0;

        force dut.wdata = data;
        force dut.wstrb = strb;
        force dut.wid = 4'h3;
        force dut.wlast = 1'b1;
        force dut.wvalid = 1'b1;
        while (!dut.wready) @(negedge clk);
        @(posedge clk);
        force dut.wvalid = 1'b0;

        while (!dut.bvalid) @(negedge clk);
        assert (dut.bresp == 2'b00);
        assert (dut.bid == 4'h3);
        force dut.bready = 1'b1;
        @(posedge clk);
        force dut.bready = 1'b0;
    endtask

    task automatic read_beat(output logic [511:0] data);
        force dut.araddr = 32'h0;
        force dut.arlen = 8'h0;
        force dut.arsize = 3'd6;
        force dut.arburst = 2'b01;
        force dut.arid = 4'ha;
        force dut.arvalid = 1'b1;
        while (!dut.arready) @(negedge clk);
        @(posedge clk);
        force dut.arvalid = 1'b0;

        while (!dut.rvalid) @(negedge clk);
        assert (dut.rresp == 2'b00);
        assert (dut.rid == 4'ha);
        assert (dut.rlast);
        data = dut.rdata;
        force dut.rready = 1'b1;
        @(posedge clk);
        force dut.rready = 1'b0;
    endtask

    initial begin
        force dut.awvalid = 1'b0;
        force dut.wvalid = 1'b0;
        force dut.arvalid = 1'b0;
        force dut.bready = 1'b0;
        force dut.rready = 1'b0;

        for (lane = 0; lane < 64; lane = lane + 1) begin
            initial_data[lane * 8 +: 8] = lane;
            partial_data[lane * 8 +: 8] = 8'h80 + lane;
            expected_data[lane * 8 +: 8] = lane < 8 ? 8'h80 + lane : lane;
        end

        repeat (4) @(posedge clk);
        resetn = 1'b1;
        @(posedge clk);

        write_beat(initial_data, 64'hffff_ffff_ffff_ffff);
        write_beat(partial_data, 64'h0000_0000_0000_00ff);
        read_beat(read_data);
        assert (read_data === expected_data)
            else $fatal(1, "partial WSTRB/readback mismatch");

        $display("AXIMM_MEMORY_SMOKE_PASS");
        $finish;
    end

    initial begin
        #1000;
        $fatal(1, "AXI-MM fixture timed out waiting for a handshake");
    end
endmodule
