`ifndef AXIS_BEAT_DEMUX_SV
`define AXIS_BEAT_DEMUX_SV

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"
`include "demux.sv"

// Beat-by-beat AXI Stream demux.
module axis_beat_demux #(
    parameter int DATA_WIDTH   = 512,
    parameter int TDEST_WIDTH  = 12,
    parameter int TID_WIDTH    = 16,
    parameter int TUSER_WIDTH  = 16,
    parameter int NUM_MASTERS  = 1,
    parameter int SELECT_WIDTH = (NUM_MASTERS <= 1) ? 1 : $clog2(NUM_MASTERS),
    parameter bit BROADCAST_DATA = 1'b0
) (
    input logic clk,
    input logic resetn,

    input logic [SELECT_WIDTH-1:0] select,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis [NUM_MASTERS]
);

    `AXIS_T_CHAN_T(s_axis, t_chan_t);

    logic m_valid [NUM_MASTERS];
    logic m_ready [NUM_MASTERS];
    t_chan_t m_data [NUM_MASTERS];

    demux #(
        .T            (t_chan_t),
        .NUM_OUTPUTS  (NUM_MASTERS),
        .SELECT_WIDTH (SELECT_WIDTH),
        .BROADCAST_DATA(BROADCAST_DATA)
    ) u_demux (
        .select  (select),
        .s_valid (s_axis.tvalid),
        .s_data  (s_axis.t),
        .s_ready (s_axis.tready),
        .m_valid (m_valid),
        .m_data  (m_data),
        .m_ready (m_ready)
    );

    for (genvar i = 0; i < NUM_MASTERS; i++) begin : g_axis
        assign m_axis[i].t      = m_data[i];
        assign m_axis[i].tvalid = m_valid[i];
        assign m_ready[i]       = m_axis[i].tready;
    end

    initial begin
        if (DATA_WIDTH % 8 != 0) begin
            $error("axis_beat_demux: DATA_WIDTH must be byte-aligned, got %0d", DATA_WIDTH);
            $finish;
        end
    end

endmodule
`endif
