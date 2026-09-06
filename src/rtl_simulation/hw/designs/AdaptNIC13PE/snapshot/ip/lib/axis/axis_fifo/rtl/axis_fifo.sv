// AXI-Stream FIFO. Selects BRAM or FF-backed synchronous storage; backpressure when full.

`include "axi_struct_macros.svh"

module axis_fifo #(
    parameter int DEPTH = 16,
    parameter bit USE_BRAM = 1,
    parameter bit EXTRA_OUTPUT_REG = 1'b0,
    parameter string MODE = "FULL_CAPACITY"
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    `AXIS_T_CHAN_T(s_axis, t_chan_t);

    generate
        if (USE_BRAM) begin : g_bram_fifo
            sync_bram_fifo #(
                .DEPTH            (DEPTH),
                .T                (t_chan_t),
                .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
                .MODE             (MODE)
            ) u_fifo (
                .clk        (clk),
                .resetn      (resetn),
                .push_valid (s_axis.tvalid),
                .push_data  (s_axis.t),
                .push_ready (s_axis.tready),
                .pop_valid  (m_axis.tvalid),
                .pop_data   (m_axis.t),
                .pop_ready  (m_axis.tready)
            );
        end else begin : g_ff_fifo
            sync_ff_fifo #(
                .DEPTH            (DEPTH),
                .T                (t_chan_t),
                .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
                .MODE             (MODE)
            ) u_fifo (
                .clk        (clk),
                .resetn      (resetn),
                .push_valid (s_axis.tvalid),
                .push_data  (s_axis.t),
                .push_ready (s_axis.tready),
                .pop_valid  (m_axis.tvalid),
                .pop_data   (m_axis.t),
                .pop_ready  (m_axis.tready)
            );
        end
    endgenerate

endmodule
