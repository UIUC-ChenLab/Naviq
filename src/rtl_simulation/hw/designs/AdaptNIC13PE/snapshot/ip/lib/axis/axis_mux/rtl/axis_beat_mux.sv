`ifndef AXIS_BEAT_MUX_SV
`define AXIS_BEAT_MUX_SV

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"
`include "mux.sv"

// Beat-by-beat AXI Stream mux.
module axis_beat_mux #(
    parameter int DATA_WIDTH   = 512,
    parameter int TDEST_WIDTH  = 12,
    parameter int TID_WIDTH    = 16,
    parameter int TUSER_WIDTH  = 16,
    parameter int NUM_SLAVES   = 1,
    parameter int SELECT_WIDTH = (NUM_SLAVES <= 1) ? 1 : $clog2(NUM_SLAVES)
) (
    input logic clk,
    input logic resetn,

    input logic [SELECT_WIDTH-1:0] select,

    ifc_axis.slave  s_axis [NUM_SLAVES],
    ifc_axis.master m_axis
);

    `AXIS_T_CHAN_T(m_axis, t_chan_t);

    logic s_valid [NUM_SLAVES];
    logic s_ready [NUM_SLAVES];
    t_chan_t s_data [NUM_SLAVES];
    t_chan_t m_data;

    for (genvar i = 0; i < NUM_SLAVES; i++) begin : g_inputs
        assign s_valid[i]       = s_axis[i].tvalid;
        assign s_data[i]        = s_axis[i].t;
        assign s_axis[i].tready = s_ready[i];
    end

    assign m_axis.t = m_data;

    mux #(
        .T            (t_chan_t),
        .NUM_INPUTS   (NUM_SLAVES),
        .SELECT_WIDTH (SELECT_WIDTH)
    ) u_mux (
        .select  (select),
        .s_valid (s_valid),
        .s_data  (s_data),
        .s_ready (s_ready),
        .m_valid (m_axis.tvalid),
        .m_data  (m_data),
        .m_ready (m_axis.tready)
    );

    initial begin
        if (DATA_WIDTH % 8 != 0) begin
            $error("axis_beat_mux: DATA_WIDTH must be byte-aligned, got %0d", DATA_WIDTH);
            $finish;
        end
    end

endmodule
`endif
