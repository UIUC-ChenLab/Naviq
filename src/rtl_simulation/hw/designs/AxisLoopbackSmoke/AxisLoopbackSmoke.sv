// Small functional AXIS fixture for the RTL automation smoke test.
//
// The XPM instances are structural discovery markers.  The direct loopback is
// intentionally simple: it verifies that the generated Verilator model can
// carry a complete AXIS beat and propagate backpressure deterministically.
module AxisLoopbackSmoke (
    input  logic        clk,
    input  logic [31:0] s_axis_tdata,
    input  logic [3:0]  s_axis_tkeep,
    input  logic [3:0]  s_axis_tid,
    input  logic [7:0]  s_axis_tdest,
    input  logic        s_axis_tlast,
    input  logic        s_axis_tvalid,
    output logic        s_axis_tready,
    output logic [31:0] m_axis_tdata,
    output logic [3:0]  m_axis_tkeep,
    output logic [3:0]  m_axis_tid,
    output logic [7:0]  m_axis_tdest,
    output logic        m_axis_tlast,
    output logic        m_axis_tvalid,
    input  logic        m_axis_tready
);
    assign m_axis_tdata = s_axis_tdata;
    assign m_axis_tkeep = s_axis_tkeep;
    assign m_axis_tid = s_axis_tid;
    assign m_axis_tdest = s_axis_tdest;
    assign m_axis_tlast = s_axis_tlast;
    assign m_axis_tvalid = s_axis_tvalid;
    assign s_axis_tready = m_axis_tready;

    // Keep one producer and one consumer XPM endpoint visible to hierarchy
    // discovery without coupling their placeholder implementation to the
    // functional loopback signals above.
    xpm_nmu_strm u_nmu_axis (.s_axis_aclk(clk));
    xpm_nsu_strm u_nsu_axis (.m_axis_aclk(clk));
endmodule
