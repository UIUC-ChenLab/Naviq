// Minimal structural fixture for XPM endpoint discovery.
//
// This design is not a functional accelerator.  It intentionally instantiates
// one endpoint of each supported XPM kind so the Verilator-to-gem5 wrapper
// generation path has a small, checked-in contract test.
module EndpointDiscoverySmoke (
    input logic clk
);
    xpm_nmu_mm u_nmu_mm (.s_axi_aclk(clk));
    xpm_nsu_mm u_nsu_mm (.m_axi_aclk(clk));
    xpm_nmu_strm u_nmu_axis (.s_axis_aclk(clk));
    xpm_nsu_strm u_nsu_axis (.m_axis_aclk(clk));
endmodule
