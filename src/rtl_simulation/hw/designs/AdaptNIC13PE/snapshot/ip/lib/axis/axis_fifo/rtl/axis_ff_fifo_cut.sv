`ifndef AXIS_FF_FIFO_CUT_SV
`define AXIS_FF_FIFO_CUT_SV

`include "ifc_axis.sv"

module axis_ff_fifo_cut #(
    parameter int DEPTH = 4
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    axis_fifo #(
        .DEPTH    (DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_fifo (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis),
        .m_axis (m_axis)
    );

endmodule

`endif
