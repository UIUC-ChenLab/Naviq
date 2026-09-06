`include "ifc_axis.sv"

// Routes admitted payloads, owns the independent aggregation queues, and
// arbitrates completed aggregates. Queue-local state removes all flow-entry
// completion feedback from this block.
module uro_queue_bank #(
    parameter int DATA_WIDTH               = 512,
    parameter int NUM_QUEUES               = 8,
    parameter int INPUT_SELECTOR_DEPTH     = 2,
    parameter int OUTPUT_SELECTOR_DEPTH    = 3,
    parameter int PACKET_META_WIDTH        = 32,
    parameter int META_BYTES_LSB           = 3,
    parameter int META_BEATS_LSB           = 19,
    parameter int TIMEOUT_COUNTER_WIDTH    = 16,
    parameter int TIMEOUT_PRESCALER_WIDTH  = 16,
    parameter int MAX_URO_QUEUE_BYTES      = 9000,
    parameter int PACKET_BEAT_COUNT_WIDTH  = 8,
    parameter int BYTE_COUNT_WIDTH         =
        $clog2(MAX_URO_QUEUE_BYTES + 1),
    parameter int BEAT_COUNT_WIDTH         =
        $clog2((MAX_URO_QUEUE_BYTES + DATA_WIDTH/8 - 1) /
               (DATA_WIDTH/8) + 3),
    parameter int AGGREGATE_META_WIDTH     = 8*28 + BYTE_COUNT_WIDTH,
    parameter int COMPLETION_COUNT_WIDTH   = $clog2(NUM_QUEUES + 1)
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave routed_payload,
    ifc_axis.master aggregate_payload,

    input logic [8*28-1:0] queue_header [NUM_QUEUES],
    input logic [BEAT_COUNT_WIDTH-1:0] queue_target_beats [NUM_QUEUES],
    input logic [TIMEOUT_COUNTER_WIDTH-1:0]
        queue_timeout_threshold [NUM_QUEUES],
    input logic [TIMEOUT_PRESCALER_WIDTH-1:0]
        queue_timeout_prescale [NUM_QUEUES],
    input logic force_close,

    output logic [COMPLETION_COUNT_WIDTH-1:0] completed_packets,
    output logic queues_empty,
    output logic [5:0] queue_bank_status [NUM_QUEUES],
    output logic [BYTE_COUNT_WIDTH-1:0] queue_bank0_bytes [NUM_QUEUES],
    output logic [BYTE_COUNT_WIDTH-1:0] queue_bank1_bytes [NUM_QUEUES],
    output logic count_aggregate
);
    localparam int QUEUE_ID_WIDTH =
        (NUM_QUEUES <= 1) ? 1 : $clog2(NUM_QUEUES);

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(PACKET_META_WIDTH)
    ) queue_payload_in [NUM_QUEUES] (clk);
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(AGGREGATE_META_WIDTH)
    ) queue_payload_out [NUM_QUEUES] (clk);

    logic queue_input_done [NUM_QUEUES];
    logic queue_input_done_r [NUM_QUEUES];
    logic queue_aggregate_done [NUM_QUEUES];
    logic queue_empty [NUM_QUEUES];
    (* dont_touch = "yes" *) logic force_close_q_r [NUM_QUEUES];
    logic aggregate_selector_pending;

    // Replicate the management barrier at the queue boundary. Besides keeping
    // the control-plane fanout local, this is an intentional timing boundary:
    // the global in-flight counter cannot enter queue aggregation arithmetic.
    always_ff @(posedge clk) begin
        if (!resetn) begin
            for (int q = 0; q < NUM_QUEUES; q++) begin
                force_close_q_r[q] <= 1'b0;
                queue_input_done_r[q] <= 1'b0;
            end
        end else begin
            for (int q = 0; q < NUM_QUEUES; q++) begin
                force_close_q_r[q] <= force_close;
                // Register each completion at the queue boundary before the
                // population count. This keeps payload-state timing local to
                // its queue instead of routing it through the global barrier.
                queue_input_done_r[q] <= queue_input_done[q];
            end
        end
    end

    uro_payload_router #(
        .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(1),
        .TID_WIDTH(1),
        .NUM_QUEUES(NUM_QUEUES),
        .TREE_DEPTH(INPUT_SELECTOR_DEPTH),
        .ROUTE_WIDTH(PACKET_META_WIDTH),
        .ISOLATE_STAGES(2)
    ) u_payload_router (
        .clk(clk), .resetn(resetn),
        .s_axis(routed_payload), .m_axis(queue_payload_in)
    );

    for (genvar q = 0; q < NUM_QUEUES; q++) begin : g_queue
        uro_queue #(
            .DATA_WIDTH(DATA_WIDTH),
            .PACKET_META_WIDTH(PACKET_META_WIDTH),
            .META_BYTES_LSB(META_BYTES_LSB),
            .META_BEATS_LSB(META_BEATS_LSB),
            .PACKET_BEAT_COUNT_WIDTH(PACKET_BEAT_COUNT_WIDTH),
            .TIMEOUT_COUNTER_WIDTH(TIMEOUT_COUNTER_WIDTH),
            .TIMEOUT_PRESCALER_WIDTH(TIMEOUT_PRESCALER_WIDTH),
            .MAX_URO_QUEUE_BYTES(MAX_URO_QUEUE_BYTES),
            .BYTE_COUNT_WIDTH(BYTE_COUNT_WIDTH),
            .BEAT_COUNT_WIDTH(BEAT_COUNT_WIDTH)
        ) u_queue (
            .clk(clk), .resetn(resetn),
            .config_header(queue_header[q]),
            .config_target_beats(queue_target_beats[q]),
            .config_timeout_threshold(queue_timeout_threshold[q]),
            .config_timeout_prescale(queue_timeout_prescale[q]),
            .force_close(force_close_q_r[q]),
            .payload_in(queue_payload_in[q]),
            .payload_out(queue_payload_out[q]),
            .input_done(queue_input_done[q]),
            .aggregate_done(queue_aggregate_done[q]),
            .queue_empty(queue_empty[q]),
            .bank_status(queue_bank_status[q]),
            .bank0_bytes(queue_bank0_bytes[q]),
            .bank1_bytes(queue_bank1_bytes[q])
        );
    end

    axis_hierarchical_packet_arbiter #(
        .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(1),
        .TID_WIDTH(1),
        .TUSER_WIDTH(AGGREGATE_META_WIDTH),
        .NUM_SLAVES(NUM_QUEUES),
        .TREE_DEPTH(OUTPUT_SELECTOR_DEPTH),
        .BRANCH_FACTOR(4),
        .PIPELINE_STAGES(2)
    ) u_queue_arbiter (
        .clk(clk), .resetn(resetn),
        .s_axis(queue_payload_out),
        .m_axis(aggregate_payload),
        .pending(aggregate_selector_pending)
    );

    always_comb begin
        completed_packets = '0;
        queues_empty = 1'b1;
        count_aggregate = 1'b0;
        for (int q = 0; q < NUM_QUEUES; q++) begin
            completed_packets = completed_packets + queue_input_done_r[q];
            queues_empty &= queue_empty[q];
            count_aggregate |= queue_aggregate_done[q];
        end
        queues_empty &= !aggregate_selector_pending;
    end

    initial begin
        if (PACKET_META_WIDTH < QUEUE_ID_WIDTH)
            $error("uro_queue_bank: packet metadata lacks a queue ID");
    end
endmodule
