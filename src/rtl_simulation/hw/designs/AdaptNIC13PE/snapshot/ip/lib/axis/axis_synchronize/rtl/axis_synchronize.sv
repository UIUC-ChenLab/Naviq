`ifndef AXIS_SYNCHRONIZE_SV
`define AXIS_SYNCHRONIZE_SV

`include "ifc_axis.sv"

// Registered AXI-Stream synchronizer.
//
// SYNC_PACKET_MODE=0 synchronizes by beat across lanes that are still active in
// the current packet group. Lanes that finish early on tlast wait for every
// other lane to finish its packet before accepting the next packet group.
//
// SYNC_PACKET_MODE=1 synchronizes packet starts only. Each lane must buffer the
// first beat of the current packet before any lane is released; after release,
// lanes stream independently until tlast. A lane that finishes early waits
// before accepting the next packet until every lane has finished.
module axis_synchronize #(
    parameter int DATA_WIDTH  = 512,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH   = 16,
    parameter int TUSER_WIDTH = 16,
    parameter int NUM_INTERFACES = 2,
    parameter bit SYNC_PACKET_MODE = 1'b0
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis [NUM_INTERFACES],
    ifc_axis.master m_axis [NUM_INTERFACES]
);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) u_slice_in [NUM_INTERFACES] (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) u_slice_out [NUM_INTERFACES] (.axis_aclk(clk));

    logic [NUM_INTERFACES-1:0] pkt_done_r;
    logic [NUM_INTERFACES-1:0] beat_done_r;
    logic                      packet_released_r;

    logic [NUM_INTERFACES-1:0] lane_required;
    logic [NUM_INTERFACES-1:0] lane_buffered;
    logic [NUM_INTERFACES-1:0] lane_last;
    logic [NUM_INTERFACES-1:0] lane_ready;
    logic [NUM_INTERFACES-1:0] lane_can_accept;
    logic [NUM_INTERFACES-1:0] lane_output_enable;
    logic [NUM_INTERFACES-1:0] lane_hs;
    logic [NUM_INTERFACES-1:0] beat_done_next_pre;
    logic [NUM_INTERFACES-1:0] pkt_done_next_pre;

    logic all_required_buffered;
    logic beat_round_complete;
    logic packet_round_complete;
    logic packet_release_now;

    always_comb begin
        lane_required        = ~pkt_done_r;
        lane_can_accept      = '0;
        lane_output_enable   = '0;
        lane_hs              = '0;
        beat_done_next_pre   = beat_done_r;
        pkt_done_next_pre    = pkt_done_r;
        all_required_buffered = 1'b1;

        for (int i = 0; i < NUM_INTERFACES; i++) begin
            if (lane_required[i]) begin
                if (SYNC_PACKET_MODE) begin
                    if (!lane_buffered[i]) begin
                        all_required_buffered = 1'b0;
                    end
                end else begin
                    if (!beat_done_r[i] && !lane_buffered[i]) begin
                        all_required_buffered = 1'b0;
                    end
                end
            end
        end

        if (SYNC_PACKET_MODE) begin
            packet_release_now = packet_released_r || all_required_buffered;

            for (int i = 0; i < NUM_INTERFACES; i++) begin
                lane_output_enable[i] = packet_release_now && lane_required[i];
                lane_hs[i] = lane_output_enable[i] && lane_buffered[i] && lane_ready[i];
                pkt_done_next_pre[i] = pkt_done_r[i] || (lane_hs[i] && lane_last[i]);
            end

            packet_round_complete = &pkt_done_next_pre;
            beat_round_complete   = 1'b0;

            for (int i = 0; i < NUM_INTERFACES; i++) begin
                if (pkt_done_r[i]) begin
                    lane_can_accept[i] = packet_round_complete;
                end else if (!packet_release_now) begin
                    lane_can_accept[i] = !lane_buffered[i];
                end else if (!lane_buffered[i]) begin
                    lane_can_accept[i] = 1'b1;
                end else begin
                    lane_can_accept[i] = lane_hs[i] &&
                        (!lane_last[i] || packet_round_complete);
                end
            end
        end else begin
            packet_release_now = 1'b0;

            for (int i = 0; i < NUM_INTERFACES; i++) begin
                lane_output_enable[i] =
                    lane_required[i] && all_required_buffered && !beat_done_r[i];
                lane_hs[i] = lane_output_enable[i] && lane_buffered[i] && lane_ready[i];
                beat_done_next_pre[i] = beat_done_r[i] || lane_hs[i];
                pkt_done_next_pre[i] = pkt_done_r[i] || (lane_hs[i] && lane_last[i]);
            end

            beat_round_complete = 1'b1;
            for (int i = 0; i < NUM_INTERFACES; i++) begin
                if (lane_required[i] && !beat_done_next_pre[i]) begin
                    beat_round_complete = 1'b0;
                end
            end
            packet_round_complete = &pkt_done_next_pre;

            for (int i = 0; i < NUM_INTERFACES; i++) begin
                if (lane_required[i]) begin
                    if (lane_buffered[i]) begin
                        lane_can_accept[i] = lane_hs[i] && beat_round_complete;
                    end else begin
                        lane_can_accept[i] = !beat_done_r[i] || beat_round_complete;
                    end
                end else begin
                    lane_can_accept[i] = packet_round_complete;
                end
            end
        end
    end

    for (genvar i = 0; i < NUM_INTERFACES; i++) begin : g_lanes
        assign u_slice_in[i].t       = s_axis[i].t;
        assign u_slice_in[i].tvalid  = s_axis[i].tvalid && lane_can_accept[i];
        assign s_axis[i].tready      = u_slice_in[i].tready && lane_can_accept[i];

        assign lane_buffered[i] = u_slice_out[i].tvalid;
        assign lane_last[i]     = u_slice_out[i].t.last;
        assign lane_ready[i]    = m_axis[i].tready;

        axis_register_slice u_slice (
            .clk    (clk),
            .resetn (resetn),
            .s_axis (u_slice_in[i]),
            .m_axis (u_slice_out[i])
        );

        assign m_axis[i].t       = u_slice_out[i].t;
        assign m_axis[i].tvalid  = u_slice_out[i].tvalid && lane_output_enable[i];
        assign u_slice_out[i].tready = m_axis[i].tready && lane_output_enable[i];
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            pkt_done_r        <= '0;
            beat_done_r       <= '0;
            packet_released_r <= 1'b0;
        end else if (SYNC_PACKET_MODE) begin
            beat_done_r <= '0;
            if (packet_round_complete) begin
                pkt_done_r        <= '0;
                packet_released_r <= 1'b0;
            end else begin
                pkt_done_r        <= pkt_done_next_pre;
                packet_released_r <= packet_release_now;
            end
        end else begin
            packet_released_r <= 1'b0;
            if (packet_round_complete) begin
                pkt_done_r  <= '0;
                beat_done_r <= '0;
            end else begin
                pkt_done_r <= pkt_done_next_pre;
                if (beat_round_complete) begin
                    beat_done_r <= '0;
                end else begin
                    beat_done_r <= beat_done_next_pre;
                end
            end
        end
    end

    initial begin
        if (NUM_INTERFACES < 1) begin
            $error("axis_synchronize: NUM_INTERFACES must be >= 1, got %0d", NUM_INTERFACES);
            $finish;
        end
        if (DATA_WIDTH % 8 != 0) begin
            $error("axis_synchronize: DATA_WIDTH must be byte-aligned, got %0d", DATA_WIDTH);
            $finish;
        end
    end

endmodule

`endif
