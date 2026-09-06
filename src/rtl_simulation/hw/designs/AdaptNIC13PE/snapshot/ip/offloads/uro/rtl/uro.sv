`include "ifc_axis.sv"
`include "ifc_axil.sv"
`include "_uro_pkg.sv"
`include "_uro_interfaces.sv"

// URO top-level composition. Parsing and lookup select a queue; aggregation
// state lives exclusively in that queue. Flow-table writes use a global drain
// barrier so management never needs physical-entry state in the datapath.
module uro #(
    parameter int DATA_WIDTH                 = 512,
    parameter int NUM_URO_QUEUES             = 32,
    parameter int TIMEOUT_COUNTER_WIDTH      = 16,
    parameter int TIMEOUT_PRESCALER_WIDTH    = 16,
    parameter int MAX_URO_QUEUE_BYTES        = 9000,
    parameter int INPUT_SELECTOR_DEPTH       = 2,
    parameter int OUTPUT_SELECTOR_DEPTH      = 3,
    parameter int PARSER_FRAGMENT_PACKER_PAGE_COUNT = 8
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave packet_in,
    ifc_axil.slave ctrl_in,
    ifc_axis.master packet_out
);
    localparam int DATA_BYTES = DATA_WIDTH / 8;
    localparam int QUEUE_ID_WIDTH =
        (NUM_URO_QUEUES <= 1) ? 1 : $clog2(NUM_URO_QUEUES);
    localparam int TABLE_DEPTH = NUM_URO_QUEUES / 4;
    localparam int TABLE_ADDR_WIDTH = $clog2(TABLE_DEPTH);
    localparam int BYTE_COUNT_WIDTH = $clog2(MAX_URO_QUEUE_BYTES + 1);
    localparam int MAX_AGGREGATE_BEATS =
        (MAX_URO_QUEUE_BYTES + DATA_BYTES - 1) / DATA_BYTES + 2;
    localparam int BEAT_COUNT_WIDTH = $clog2(MAX_AGGREGATE_BEATS + 1);
    localparam int MAX_PACKET_BEATS =
        (65535 + DATA_BYTES - 1) / DATA_BYTES + 2;
    localparam int PACKET_BEAT_COUNT_WIDTH = $clog2(MAX_PACKET_BEATS + 1);
    localparam int AGGREGATE_META_WIDTH = 8*28 + BYTE_COUNT_WIDTH;
    localparam int PACKET_META_WIDTH =
        QUEUE_ID_WIDTH + 16 + PACKET_BEAT_COUNT_WIDTH;
    localparam int META_BYTES_LSB = QUEUE_ID_WIDTH;
    localparam int META_BEATS_LSB = META_BYTES_LSB + 16;
    localparam int COMPLETION_COUNT_WIDTH = $clog2(NUM_URO_QUEUES + 1);
    localparam int INFLIGHT_COUNT_WIDTH = 16;

    initial begin
        if (DATA_WIDTH < 64 || (DATA_WIDTH % 8) != 0 ||
            ((DATA_WIDTH & (DATA_WIDTH-1)) != 0)) begin
            $error("uro: DATA_WIDTH must be a byte-aligned power of two >= 64");
            $finish;
        end
        if (NUM_URO_QUEUES < 8 || (NUM_URO_QUEUES % 4) != 0 ||
            ((NUM_URO_QUEUES & (NUM_URO_QUEUES-1)) != 0)) begin
            $error("uro: NUM_URO_QUEUES must be a power-of-two multiple of four and >= 8");
            $finish;
        end
        if (INPUT_SELECTOR_DEPTH < 1 ||
            INPUT_SELECTOR_DEPTH > QUEUE_ID_WIDTH) begin
            $error("uro: INPUT_SELECTOR_DEPTH must be in [1, %0d]",
                   QUEUE_ID_WIDTH);
            $finish;
        end
        if ($bits(ctrl_in.w.data) != 32) begin
            $error("uro: ctrl_in must be 32-bit AXI-Lite");
            $finish;
        end
    end

    // Control plane.
    ifc_axil #(.ADDR_WIDTH(32), .DATA_WIDTH(32)) ctrl_split [2] (clk);
    localparam logic [1:0][31:0] CTRL_BASE = {
        32'h0001_0000, 32'h0000_0000
    };
    localparam logic [1:0][31:0] CTRL_SIZE = {
        32'h0001_0000, 32'h0001_0000
    };

    logic global_enable;
    logic queue_enable [NUM_URO_QUEUES];
    logic [8*28-1:0] queue_header [NUM_URO_QUEUES];
    logic [BEAT_COUNT_WIDTH-1:0] queue_target_beats [NUM_URO_QUEUES];
    logic [TIMEOUT_COUNTER_WIDTH-1:0]
        queue_timeout_threshold [NUM_URO_QUEUES];
    logic [TIMEOUT_PRESCALER_WIDTH-1:0]
        queue_timeout_prescale [NUM_URO_QUEUES];
    logic [5:0] queue_bank_status [NUM_URO_QUEUES];
    logic [BYTE_COUNT_WIDTH-1:0] queue_bank0_bytes [NUM_URO_QUEUES];
    logic [BYTE_COUNT_WIDTH-1:0] queue_bank1_bytes [NUM_URO_QUEUES];
    logic count_miss, count_drop, count_aggregate;

    axil_crossbar #(
        .ADDR_WIDTH(32), .DATA_WIDTH(32), .TUSER_WIDTH(1),
        .NUM_SLAVES(2), .SLAVE_BASE_ADDR(CTRL_BASE),
        .SLAVE_ADDR_SIZE(CTRL_SIZE)
    ) u_ctrl_xbar (
        .clk(clk), .resetn(resetn),
        .s_axil(ctrl_in), .m_axil(ctrl_split)
    );

    uro_csr #(
        .NUM_QUEUES(NUM_URO_QUEUES),
        .TIMEOUT_COUNTER_WIDTH(TIMEOUT_COUNTER_WIDTH),
        .TIMEOUT_PRESCALER_WIDTH(TIMEOUT_PRESCALER_WIDTH),
        .TARGET_BEAT_COUNT_WIDTH(BEAT_COUNT_WIDTH),
        .BYTE_COUNT_WIDTH(BYTE_COUNT_WIDTH)
    ) u_csr (
        .clk(clk), .resetn(resetn), .ctrl(ctrl_split[0]),
        .global_enable(global_enable),
        .queue_enable(queue_enable), .queue_header(queue_header),
        .queue_target_beats(queue_target_beats),
        .queue_timeout_threshold(queue_timeout_threshold),
        .queue_timeout_prescale(queue_timeout_prescale),
        .queue_bank_status(queue_bank_status),
        .queue_bank0_bytes(queue_bank0_bytes),
        .queue_bank1_bytes(queue_bank1_bytes),
        .count_miss(count_miss), .count_drop(count_drop),
        .count_aggregate(count_aggregate)
    );

    // Packet-boundary ingress gate for the management drain barrier.
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) capture_packet_in (clk);
    logic ingress_packet_active_r;
    logic mgmt_write_pending, mgmt_write_safe, mgmt_force_close;
    logic mgmt_flush_active_r;
    logic input_packet_started;
    wire packet_in_fire = packet_in.tvalid && packet_in.tready;

    always_comb begin
        capture_packet_in.t = packet_in.t;
        capture_packet_in.tvalid = packet_in.tvalid &&
            (!mgmt_write_pending || ingress_packet_active_r);
        packet_in.tready = capture_packet_in.tready &&
            (!mgmt_write_pending || ingress_packet_active_r);
        input_packet_started = packet_in_fire && !ingress_packet_active_r;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            ingress_packet_active_r <= 1'b0;
        end else if (packet_in_fire) begin
            if (packet_in.t.last)
                ingress_packet_active_r <= 1'b0;
            else if (!ingress_packet_active_r)
                ingress_packet_active_r <= 1'b1;
        end
    end

    // Parsed packet and flow lookup streams.
    logic desc_valid, desc_ready, desc_eligible;
    uro_pkg::uro_key_t desc_key;
    logic [TABLE_ADDR_WIDTH-1:0] desc_hash;
    logic [15:0] desc_payload_bytes;
    logic [PACKET_BEAT_COUNT_WIDTH-1:0] desc_payload_beats;
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) staged_payload (clk);
    ifc_uro_lookup_result #(
        .VALUE_WIDTH(32), .BEAT_WIDTH(PACKET_BEAT_COUNT_WIDTH)
    ) lookup_result ();
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(PACKET_META_WIDTH)
    ) routed_payload (clk);
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(AGGREGATE_META_WIDTH)
    ) aggregate_payload (clk);

    uro_packet_capture #(
        .DATA_WIDTH(DATA_WIDTH),
        .TABLE_ADDR_WIDTH(TABLE_ADDR_WIDTH),
        .DESC_DEPTH(64),
        .BEAT_DESC_DEPTH(256),
        .FRAGMENT_PACKER_PAGE_COUNT(PARSER_FRAGMENT_PACKER_PAGE_COUNT),
        .PACKET_BEAT_COUNT_WIDTH(PACKET_BEAT_COUNT_WIDTH)
    ) u_capture (
        .clk(clk), .resetn(resetn), .packet_in(capture_packet_in),
        .desc_valid(desc_valid), .desc_ready(desc_ready),
        .desc_key(desc_key), .desc_hash(desc_hash),
        .desc_eligible(desc_eligible),
        .desc_payload_bytes(desc_payload_bytes),
        .desc_payload_beats(desc_payload_beats),
        .parsed_payload(staged_payload)
    );

    uro_flow_table #(
        .TABLE_DEPTH(TABLE_DEPTH),
        .TABLE_ADDR_WIDTH(TABLE_ADDR_WIDTH),
        .WAY_WIDTH(2),
        .PACKET_BEAT_COUNT_WIDTH(PACKET_BEAT_COUNT_WIDTH)
    ) u_flow_table (
        .clk(clk), .resetn(resetn), .ctrl(ctrl_split[1]),
        .desc_valid(desc_valid), .desc_ready(desc_ready),
        .desc_key(desc_key), .desc_hash(desc_hash),
        .desc_eligible(desc_eligible),
        .desc_payload_bytes(desc_payload_bytes),
        .desc_payload_beats(desc_payload_beats),
        .lookup_result(lookup_result),
        .mgmt_write_pending(mgmt_write_pending),
        .mgmt_write_safe(mgmt_write_safe)
    );

    logic dropped_packet_done;
    uro_dispatch #(
        .DATA_WIDTH(DATA_WIDTH),
        .NUM_QUEUES(NUM_URO_QUEUES),
        .MAX_URO_QUEUE_BYTES(MAX_URO_QUEUE_BYTES),
        .PACKET_BEAT_COUNT_WIDTH(PACKET_BEAT_COUNT_WIDTH),
        .PACKET_META_WIDTH(PACKET_META_WIDTH)
    ) u_dispatch (
        .clk(clk), .resetn(resetn),
        .global_enable(global_enable), .queue_enable(queue_enable),
        .lookup_result(lookup_result),
        .staged_payload(staged_payload), .routed_payload(routed_payload),
        .count_miss(count_miss), .count_drop(count_drop),
        .dropped_packet_done(dropped_packet_done)
    );

    logic [COMPLETION_COUNT_WIDTH-1:0] queue_completed_packets;
    logic queues_empty, output_empty;
    uro_queue_bank #(
        .DATA_WIDTH(DATA_WIDTH),
        .NUM_QUEUES(NUM_URO_QUEUES),
        .INPUT_SELECTOR_DEPTH(INPUT_SELECTOR_DEPTH),
        .OUTPUT_SELECTOR_DEPTH(OUTPUT_SELECTOR_DEPTH),
        .PACKET_META_WIDTH(PACKET_META_WIDTH),
        .META_BYTES_LSB(META_BYTES_LSB),
        .META_BEATS_LSB(META_BEATS_LSB),
        .TIMEOUT_COUNTER_WIDTH(TIMEOUT_COUNTER_WIDTH),
        .TIMEOUT_PRESCALER_WIDTH(TIMEOUT_PRESCALER_WIDTH),
        .MAX_URO_QUEUE_BYTES(MAX_URO_QUEUE_BYTES),
        .PACKET_BEAT_COUNT_WIDTH(PACKET_BEAT_COUNT_WIDTH),
        .BYTE_COUNT_WIDTH(BYTE_COUNT_WIDTH),
        .BEAT_COUNT_WIDTH(BEAT_COUNT_WIDTH),
        .AGGREGATE_META_WIDTH(AGGREGATE_META_WIDTH),
        .COMPLETION_COUNT_WIDTH(COMPLETION_COUNT_WIDTH)
    ) u_queue_bank (
        .clk(clk), .resetn(resetn),
        .routed_payload(routed_payload),
        .aggregate_payload(aggregate_payload),
        .queue_header(queue_header),
        .queue_target_beats(queue_target_beats),
        .queue_timeout_threshold(queue_timeout_threshold),
        .queue_timeout_prescale(queue_timeout_prescale),
        .force_close(mgmt_force_close),
        .completed_packets(queue_completed_packets),
        .queues_empty(queues_empty),
        .queue_bank_status(queue_bank_status),
        .queue_bank0_bytes(queue_bank0_bytes),
        .queue_bank1_bytes(queue_bank1_bytes),
        .count_aggregate(count_aggregate)
    );

    // A single packet count covers capture, lookup, dispatch, and routing.
    // The barrier closes queues only after every accepted packet has either
    // completed at a queue or been fully drained as a drop.
    logic [INFLIGHT_COUNT_WIDTH-1:0] inflight_packets_r;
    logic [INFLIGHT_COUNT_WIDTH-1:0] inflight_packets_n;
    logic input_packet_started_r;
    logic [COMPLETION_COUNT_WIDTH-1:0] queue_completed_packets_r;
    logic dropped_packet_done_r;
    logic [COMPLETION_COUNT_WIDTH:0] completed_packets_c;

    always_comb begin
        completed_packets_c =
            (COMPLETION_COUNT_WIDTH+1)'(queue_completed_packets_r) +
            (COMPLETION_COUNT_WIDTH+1)'(dropped_packet_done_r);
        inflight_packets_n = inflight_packets_r +
            INFLIGHT_COUNT_WIDTH'(input_packet_started_r) -
            INFLIGHT_COUNT_WIDTH'(completed_packets_c);

        mgmt_force_close = mgmt_flush_active_r;
        mgmt_write_safe = mgmt_write_pending &&
                          mgmt_flush_active_r && queues_empty && output_empty;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            inflight_packets_r <= '0;
            input_packet_started_r <= 1'b0;
            queue_completed_packets_r <= '0;
            dropped_packet_done_r <= 1'b0;
            mgmt_flush_active_r <= 1'b0;
        end else begin
            inflight_packets_r <= inflight_packets_n;
            input_packet_started_r <= input_packet_started;
            queue_completed_packets_r <= queue_completed_packets;
            dropped_packet_done_r <= dropped_packet_done;
            if (!mgmt_write_pending)
                mgmt_flush_active_r <= 1'b0;
            else if (inflight_packets_r == 0)
                mgmt_flush_active_r <= 1'b1;
        end
    end

    assert property (@(posedge clk) disable iff (!resetn)
        INFLIGHT_COUNT_WIDTH'(completed_packets_c) <=
            inflight_packets_r + INFLIGHT_COUNT_WIDTH'(input_packet_started_r))
        else $error("uro: in-flight packet count underflow");

    uro_output_formatter #(
        .DATA_WIDTH(DATA_WIDTH),
        .BYTE_COUNT_WIDTH(BYTE_COUNT_WIDTH),
        .AGGREGATE_META_WIDTH(AGGREGATE_META_WIDTH)
    ) u_output_formatter (
        .clk(clk), .resetn(resetn),
        .aggregate_payload(aggregate_payload),
        .packet_out(packet_out), .empty(output_empty)
    );
endmodule
