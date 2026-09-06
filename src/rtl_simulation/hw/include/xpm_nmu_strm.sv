module xpm_nmu_strm #(
    parameter int DATA_WIDTH = 256,
    parameter int DST_ID_WIDTH = 12,
    parameter int ID_WIDTH = 16,
    parameter string NOC_FABRIC = "VNOC",
    parameter int TDEST_WIDTH = DST_ID_WIDTH,
    parameter int TID_WIDTH = ID_WIDTH
) (
    input logic s_axis_aclk /* verilator public_flat */,
    input logic [DATA_WIDTH-1:0] s_axis_tdata /* verilator public_flat */,
    input logic [DATA_WIDTH/8-1:0] s_axis_tkeep /* verilator public_flat */,
    input logic [TID_WIDTH-1:0] s_axis_tid /* verilator public_flat */,
    input logic [TDEST_WIDTH-1:0] s_axis_tdest /* verilator public_flat */,
    input logic s_axis_tlast /* verilator public_flat */,
    input logic s_axis_tvalid /* verilator public_flat */,
    output logic s_axis_tready /* verilator public_flat */,
    output wire dst_id_err
);


assign dst_id_err = 1'b0;
endmodule
