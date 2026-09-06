`ifndef AXIS_MULTICAST_SV
`define AXIS_MULTICAST_SV

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"

// Registered AXI Stream multicast: one sink beat is duplicated to every master.
//
// - Upstream (s_axis) is registered; s_axis.tready is high only when the slot is
//   empty or the current beat has been fully accepted by every master.
// - Each m_axis[i].tvalid is deasserted after that master completes a handshake
//   for the current beat, so outputs can resolve valid/ready at different times.
module axis_multicast #(
    parameter int DATA_WIDTH  = 512,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH   = 16,
    parameter int TUSER_WIDTH = 16,
    parameter int NUM_DESTS = 2
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis [NUM_DESTS]
);

    `AXIS_T_CHAN_T(s_axis, t_chan_t);

    t_chan_t buf_r;
    logic    buf_valid_r;
    logic [NUM_DESTS-1:0] done_r;
    logic [NUM_DESTS-1:0] m_hs;
    logic                   all_taken;

    for (genvar i = 0; i < NUM_DESTS; i++) begin : g_master
        assign m_hs[i]          = m_axis[i].tvalid && m_axis[i].tready;
        assign m_axis[i].t      = buf_r;
        assign m_axis[i].tvalid = buf_valid_r && !done_r[i];
    end

    assign all_taken = &(done_r | m_hs);
    assign s_axis.tready = !buf_valid_r || all_taken;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            buf_valid_r <= 1'b0;
            done_r      <= '0;
        end else if (s_axis.tready && s_axis.tvalid) begin
            buf_r       <= s_axis.t;
            buf_valid_r <= 1'b1;
            done_r      <= '0;
        end else begin
            done_r <= done_r | m_hs;
            if (buf_valid_r && all_taken) buf_valid_r <= 1'b0;
        end
    end

    initial begin
        if (NUM_DESTS < 1) begin
            $error("axis_multicast: NUM_DESTS must be >= 1, got %0d", NUM_DESTS);
            $finish;
        end

        if (DATA_WIDTH % 8 != 0) begin
            $error("axis_multicast: DATA_WIDTH must be byte-aligned, got %0d", DATA_WIDTH);
            $finish;
        end
    end

endmodule
`endif
