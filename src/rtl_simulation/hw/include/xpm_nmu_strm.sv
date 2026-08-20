module xpm_nmu_strm #(
    parameter int DATA_WIDTH = 256,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16
) (
    input logic s_axis_aclk /* verilator public_flat */,
    input logic [DATA_WIDTH-1:0] s_axis_tdata /* verilator public_flat */,
    input logic [DATA_WIDTH/8-1:0] s_axis_tkeep /* verilator public_flat */,
    input logic [TID_WIDTH-1:0] s_axis_tid /* verilator public_flat */,
    input logic [TDEST_WIDTH-1:0] s_axis_tdest /* verilator public_flat */,
    input logic s_axis_tlast /* verilator public_flat */,
    input logic s_axis_tvalid /* verilator public_flat */,
    output logic s_axis_tready /* verilator public_flat */
);


endmodule
