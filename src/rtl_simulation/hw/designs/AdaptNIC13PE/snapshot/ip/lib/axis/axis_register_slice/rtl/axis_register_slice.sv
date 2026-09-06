// AXI Stream register slice. Uses generic register_slice; supports backpressure.

`include "axi_struct_macros.svh"

module axis_register_slice #(
    parameter string MODE = "STANDARD",
    parameter int NUM_STAGES = 1
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    `AXIS_T_CHAN_T(s_axis, t_chan_t);

    register_slice #(
        .T          (t_chan_t),
        .MODE       (MODE),
        .NUM_STAGES (NUM_STAGES)
    ) u_reg (
        .clk        (clk),
        .resetn      (resetn),
        .push_valid (s_axis.tvalid),
        .push_data  (s_axis.t),
        .push_ready (s_axis.tready),
        .pop_valid  (m_axis.tvalid),
        .pop_data   (m_axis.t),
        .pop_ready  (m_axis.tready)
    );

endmodule
