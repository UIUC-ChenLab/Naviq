module xpm_nsu_strm #(
    parameter int DATA_WIDTH = 256,
    parameter int DST_ID_WIDTH = 12,
    parameter int ID_WIDTH = 16,
    parameter string NOC_FABRIC = "VNOC",
    parameter int TDEST_WIDTH = DST_ID_WIDTH,
    parameter int TID_WIDTH = ID_WIDTH
) (
    input logic m_axis_aclk /* verilator public_flat */,
    output logic [DATA_WIDTH-1:0] m_axis_tdata /* verilator public_flat */,
    output logic [DATA_WIDTH/8-1:0] m_axis_tkeep /* verilator public_flat */,
    output logic [TID_WIDTH-1:0] m_axis_tid /* verilator public_flat */,
    output logic [TDEST_WIDTH-1:0] m_axis_tdest /* verilator public_flat */,
    output logic m_axis_tlast /* verilator public_flat */,
    output logic m_axis_tvalid /* verilator public_flat */,
    input logic m_axis_tready /* verilator public_flat */
);

endmodule
