`include "ifc_axis.sv"
`include "_uro_interfaces.sv"

// Joins ordered lookup results with the staged payload stream. This block is
// deliberately stateless with respect to aggregation: it validates the
// software queue mapping, tags accepted packets, and drains rejected packets.
module uro_dispatch #(
    parameter int DATA_WIDTH              = 512,
    parameter int NUM_QUEUES              = 8,
    parameter int MAX_URO_QUEUE_BYTES     = 9000,
    parameter int PACKET_BEAT_COUNT_WIDTH = 8,
    parameter int PACKET_META_WIDTH       = 32
) (
    input logic clk,
    input logic resetn,

    input logic global_enable,
    input logic queue_enable [NUM_QUEUES],

    ifc_uro_lookup_result.consumer lookup_result,
    ifc_axis.slave staged_payload,
    ifc_axis.master routed_payload,

    output logic count_miss,
    output logic count_drop,
    output logic dropped_packet_done
);
    localparam int QUEUE_ID_WIDTH =
        (NUM_QUEUES <= 1) ? 1 : $clog2(NUM_QUEUES);
    localparam int MAX_AGGREGATE_BEATS =
        (MAX_URO_QUEUE_BYTES + DATA_WIDTH/8 - 1) / (DATA_WIDTH/8) + 2;
    localparam int META_QUEUE_LSB = 0;
    localparam int META_BYTES_LSB = META_QUEUE_LSB + QUEUE_ID_WIDTH;
    localparam int META_BEATS_LSB = META_BYTES_LSB + 16;
    localparam int EXPECTED_PACKET_META_WIDTH =
        META_BEATS_LSB + PACKET_BEAT_COUNT_WIDTH;

    logic command_valid_r, command_valid_n;
    logic command_drop_r, command_drop_n;
    logic [PACKET_META_WIDTH-1:0] command_meta_r, command_meta_n;
    logic packet_active_r, packet_active_n;
    logic packet_drop_r, packet_drop_n;
    logic [PACKET_META_WIDTH-1:0] packet_meta_r, packet_meta_n;

    logic lookup_queue_valid_c, lookup_queue_enabled_c;
    logic lookup_drop_c, lookup_accept_c;
    logic [QUEUE_ID_WIDTH-1:0] lookup_queue_c;
    logic [PACKET_META_WIDTH-1:0] lookup_meta_c;
    logic stream_present_c, stream_drop_c;
    logic [PACKET_META_WIDTH-1:0] stream_meta_c;
    logic payload_fire_c, command_start_c;

    initial begin
        if (PACKET_META_WIDTH != EXPECTED_PACKET_META_WIDTH) begin
            $error("uro_dispatch: packet metadata width mismatch");
            $finish;
        end
    end

    always_comb begin
        lookup_queue_c = lookup_result.value[QUEUE_ID_WIDTH-1:0];
        lookup_queue_valid_c = lookup_result.value < 32'(NUM_QUEUES);
        lookup_queue_enabled_c = 1'b0;
        if (lookup_queue_valid_c)
            lookup_queue_enabled_c = queue_enable[lookup_queue_c];

        lookup_drop_c = !(global_enable && lookup_result.eligible &&
                          lookup_result.hit && lookup_queue_valid_c &&
                          lookup_queue_enabled_c &&
                          lookup_result.payload_beats != 0 &&
                          lookup_result.payload_beats <=
                              PACKET_BEAT_COUNT_WIDTH'(MAX_AGGREGATE_BEATS));

        lookup_meta_c = '0;
        lookup_meta_c[META_QUEUE_LSB +: QUEUE_ID_WIDTH] = lookup_queue_c;
        lookup_meta_c[META_BYTES_LSB +: 16] = lookup_result.payload_bytes;
        lookup_meta_c[META_BEATS_LSB +: PACKET_BEAT_COUNT_WIDTH] =
            lookup_result.payload_beats;
    end

    always_comb begin
        stream_present_c = packet_active_r || command_valid_r;
        stream_drop_c = packet_active_r ? packet_drop_r : command_drop_r;
        stream_meta_c = packet_active_r ? packet_meta_r : command_meta_r;

        routed_payload.t = '0;
        routed_payload.t.data = staged_payload.t.data;
        routed_payload.t.keep = staged_payload.t.keep;
        routed_payload.t.last = staged_payload.t.last;
        routed_payload.t.id = staged_payload.t.id;
        routed_payload.t.dest = staged_payload.t.dest;
        routed_payload.t.user = stream_meta_c;
        routed_payload.tvalid = staged_payload.tvalid &&
                                stream_present_c && !stream_drop_c;
        staged_payload.tready = stream_present_c &&
            (stream_drop_c || routed_payload.tready);
        payload_fire_c = staged_payload.tvalid && staged_payload.tready;
        command_start_c = !packet_active_r && command_valid_r &&
                          payload_fire_c;

        // Replacement on the same cycle that a packet starts keeps the
        // command stage at one packet per cycle for single-beat traffic.
        lookup_result.ready = !command_valid_r || command_start_c;
        lookup_accept_c = lookup_result.valid && lookup_result.ready;

        count_miss = lookup_accept_c && !lookup_result.hit;
        count_drop = lookup_accept_c && lookup_drop_c;
        dropped_packet_done = payload_fire_c && staged_payload.t.last &&
                              stream_drop_c;
    end

    always_comb begin
        command_valid_n = command_valid_r;
        command_drop_n = command_drop_r;
        command_meta_n = command_meta_r;
        packet_active_n = packet_active_r;
        packet_drop_n = packet_drop_r;
        packet_meta_n = packet_meta_r;

        if (command_start_c) begin
            command_valid_n = 1'b0;
            if (!staged_payload.t.last) begin
                packet_active_n = 1'b1;
                packet_drop_n = command_drop_r;
                packet_meta_n = command_meta_r;
            end
        end

        if (packet_active_r && payload_fire_c && staged_payload.t.last) begin
            packet_active_n = 1'b0;
            packet_drop_n = 1'b0;
        end

        if (lookup_accept_c) begin
            command_valid_n = 1'b1;
            command_drop_n = lookup_drop_c;
            command_meta_n = lookup_meta_c;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            command_valid_r <= 1'b0;
            command_drop_r <= 1'b0;
            command_meta_r <= '0;
            packet_active_r <= 1'b0;
            packet_drop_r <= 1'b0;
            packet_meta_r <= '0;
        end else begin
            command_valid_r <= command_valid_n;
            command_drop_r <= command_drop_n;
            command_meta_r <= command_meta_n;
            packet_active_r <= packet_active_n;
            packet_drop_r <= packet_drop_n;
            packet_meta_r <= packet_meta_n;
        end
    end

    assert property (@(posedge clk) disable iff (!resetn)
        packet_active_r |-> !command_start_c)
        else $error("uro_dispatch: started a second packet while active");
endmodule
