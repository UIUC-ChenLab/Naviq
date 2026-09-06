`ifndef AXIS_PACKET_DEMUX_SV
`define AXIS_PACKET_DEMUX_SV

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"
`include "demux.sv"

// Packet-locked AXI Stream demux.
//
// The destination select is sampled on the first accepted beat of a packet and
// held until the accepted beat with t.last.
module axis_packet_demux #(
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

    localparam int SEL_WIDTH = (NUM_MASTERS <= 1) ? 1 : $clog2(NUM_MASTERS);

    logic [SEL_WIDTH-1:0] active_sel_r;
    logic                 in_packet_r;
    logic [SELECT_WIDTH-1:0] route_sel_c;
    logic                 s_fire_c;

    logic m_valid [NUM_MASTERS];
    logic m_ready [NUM_MASTERS];
    t_chan_t m_data [NUM_MASTERS];

    assign route_sel_c = in_packet_r ? SELECT_WIDTH'(active_sel_r) : select;
    assign s_fire_c    = s_axis.tvalid && s_axis.tready;

    demux #(
        .T            (t_chan_t),
        .NUM_OUTPUTS  (NUM_MASTERS),
        .SELECT_WIDTH (SELECT_WIDTH),
        .BROADCAST_DATA(BROADCAST_DATA)
    ) u_demux (
        .select  (route_sel_c),
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

    always_ff @(posedge clk) begin
        if (!resetn) begin
            active_sel_r <= '0;
            in_packet_r  <= 1'b0;
        end else if (s_fire_c) begin
            active_sel_r <= SEL_WIDTH'(route_sel_c);
            in_packet_r  <= !s_axis.t.last;
        end
    end

    initial begin
        if (DATA_WIDTH % 8 != 0) begin
            $error("axis_packet_demux: DATA_WIDTH must be byte-aligned, got %0d", DATA_WIDTH);
            $finish;
        end
    end

endmodule
`endif
