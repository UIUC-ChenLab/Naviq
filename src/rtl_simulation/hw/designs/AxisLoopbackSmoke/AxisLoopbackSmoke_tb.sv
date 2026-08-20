module AxisLoopbackSmoke_tb;
    logic clk = 0;
    logic [31:0] s_axis_tdata;
    logic [3:0] s_axis_tkeep;
    logic [3:0] s_axis_tid;
    logic [7:0] s_axis_tdest;
    logic s_axis_tlast;
    logic s_axis_tvalid;
    logic s_axis_tready;
    logic [31:0] m_axis_tdata;
    logic [3:0] m_axis_tkeep;
    logic [3:0] m_axis_tid;
    logic [7:0] m_axis_tdest;
    logic m_axis_tlast;
    logic m_axis_tvalid;
    logic m_axis_tready;

    AxisLoopbackSmoke dut (.*);

    always #1 clk = ~clk;

    initial begin
        s_axis_tdata = 32'hdeadc0de;
        s_axis_tkeep = 4'hf;
        s_axis_tid = 4'h3;
        s_axis_tdest = 8'h5a;
        s_axis_tlast = 1'b1;
        s_axis_tvalid = 1'b1;
        m_axis_tready = 1'b1;
        #1;
        assert (s_axis_tready && m_axis_tvalid);
        assert (m_axis_tdata == 32'hdeadc0de);
        assert (m_axis_tkeep == 4'hf && m_axis_tid == 4'h3);
        assert (m_axis_tdest == 8'h5a && m_axis_tlast);

        m_axis_tready = 1'b0;
        #1;
        assert (!s_axis_tready);
        $display("AXIS_LOOPBACK_PASS");
        $finish;
    end
endmodule
