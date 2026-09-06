`ifndef AXIS_PACKET_MUX_SV
`define AXIS_PACKET_MUX_SV

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"
`include "mux.sv"

// Packet-locked AXI Stream mux.
//
// The source select is sampled on the first accepted beat of a packet and held
// until the accepted beat with t.last.
module axis_packet_mux #(
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

    localparam int SEL_WIDTH = (NUM_SLAVES <= 1) ? 1 : $clog2(NUM_SLAVES);

    logic [SEL_WIDTH-1:0] active_sel_r;
    logic                 in_packet_r;
    logic [SELECT_WIDTH-1:0] route_sel_c;
    logic                 m_fire_c;

    logic s_valid [NUM_SLAVES];
    logic s_ready [NUM_SLAVES];
    t_chan_t s_data [NUM_SLAVES];
    t_chan_t m_data;

    assign route_sel_c = in_packet_r ? SELECT_WIDTH'(active_sel_r) : select;
    assign m_fire_c    = m_axis.tvalid && m_axis.tready;

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
        .select  (route_sel_c),
        .s_valid (s_valid),
        .s_data  (s_data),
        .s_ready (s_ready),
        .m_valid (m_axis.tvalid),
        .m_data  (m_data),
        .m_ready (m_axis.tready)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            active_sel_r <= '0;
            in_packet_r  <= 1'b0;
        end else if (m_fire_c) begin
            active_sel_r <= SEL_WIDTH'(route_sel_c);
            in_packet_r  <= !m_axis.t.last;
        end
    end

    initial begin
        if (DATA_WIDTH % 8 != 0) begin
            $error("axis_packet_mux: DATA_WIDTH must be byte-aligned, got %0d", DATA_WIDTH);
            $finish;
        end
    end

endmodule
`endif
