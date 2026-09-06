`include "ifc_axis.sv"
`include "_uro_pkg.sv"

// Queue-local aggregation and raw payload storage. The queue is the sole
// owner of aggregation state; flow lookup only selects which queue receives a
// packet. Closed descriptors include the active drain and therefore combine
// with fill_active to describe the two physical aggregate slots exactly.
module uro_queue #(
    parameter int DATA_WIDTH                 = 512,
    parameter int PACKET_META_WIDTH          = 32,
    parameter int META_BYTES_LSB             = 3,
    parameter int META_BEATS_LSB             = 19,
    parameter int PACKET_BEAT_COUNT_WIDTH    = 8,
    parameter int TIMEOUT_COUNTER_WIDTH       = 16,
    parameter int TIMEOUT_PRESCALER_WIDTH     = 16,
    parameter int MAX_URO_QUEUE_BYTES         = 9000,
    parameter int BYTE_COUNT_WIDTH            = $clog2(MAX_URO_QUEUE_BYTES + 1),
    parameter int BEAT_COUNT_WIDTH            =
        $clog2((MAX_URO_QUEUE_BYTES + DATA_WIDTH/8 - 1) /
               (DATA_WIDTH/8) + 3)
) (
    input logic clk,
    input logic resetn,

    input logic [8*28-1:0] config_header,
    input logic [BEAT_COUNT_WIDTH-1:0] config_target_beats,
    input logic [TIMEOUT_COUNTER_WIDTH-1:0] config_timeout_threshold,
    input logic [TIMEOUT_PRESCALER_WIDTH-1:0] config_timeout_prescale,
    input logic force_close,

    ifc_axis.slave payload_in,
    ifc_axis.master payload_out,

    output logic input_done,
    output logic aggregate_done,
    output logic queue_empty,
    output logic [5:0] bank_status,
    output logic [BYTE_COUNT_WIDTH-1:0] bank0_bytes,
    output logic [BYTE_COUNT_WIDTH-1:0] bank1_bytes
);
    localparam int DATA_BYTES = DATA_WIDTH / 8;
    localparam int MAX_AGGREGATE_BEATS =
        (MAX_URO_QUEUE_BYTES + DATA_BYTES - 1) / DATA_BYTES + 2;
    localparam int FIFO_DEPTH = 2 * MAX_AGGREGATE_BEATS;

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
               .TUSER_WIDTH(1))
        fifo_in (clk), fifo_write (clk), fifo_out (clk);
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
               .TUSER_WIDTH(PACKET_META_WIDTH))
        payload_exec (clk);
    logic [BEAT_COUNT_WIDTH-1:0] desc_beats_r [2], desc_beats_n [2];
    logic [BYTE_COUNT_WIDTH-1:0] desc_bytes_r [2], desc_bytes_n [2];
    logic [8*28-1:0] desc_header_r [2], desc_header_n [2];
    logic desc_head_r, desc_head_n, desc_tail_r, desc_tail_n;
    logic [1:0] desc_count_r, desc_count_n;

    logic drain_active_r, drain_active_n;
    logic [BEAT_COUNT_WIDTH-1:0]
        drain_beats_remaining_r, drain_beats_remaining_n;
    logic [BYTE_COUNT_WIDTH-1:0] drain_bytes_r, drain_bytes_n;
    logic [8*28-1:0] drain_header_r, drain_header_n;

    logic fill_active_r, fill_active_n;
    logic [BYTE_COUNT_WIDTH-1:0] fill_bytes_r, fill_bytes_n;
    logic [BEAT_COUNT_WIDTH-1:0] fill_beats_r, fill_beats_n;
    logic [BEAT_COUNT_WIDTH-1:0]
        fill_remaining_beats_r, fill_remaining_beats_n;
    logic [15:0] fill_expected_size_r, fill_expected_size_n;
    logic [8*28-1:0] fill_header_r, fill_header_n;
    logic [TIMEOUT_COUNTER_WIDTH-1:0]
        fill_timeout_threshold_r, fill_timeout_threshold_n;
    logic [TIMEOUT_PRESCALER_WIDTH-1:0]
        fill_timeout_prescale_r, fill_timeout_prescale_n;

    // Queue configuration is first localized at the queue boundary. A new
    // aggregate snapshots these registers, so AXI-Lite routing and fanout do
    // not enter the first-packet aggregation decision.
    logic [8*28-1:0] config_header_r;
    logic [BEAT_COUNT_WIDTH-1:0] config_target_beats_r;
    logic [TIMEOUT_COUNTER_WIDTH-1:0] config_timeout_threshold_r;
    logic [TIMEOUT_PRESCALER_WIDTH-1:0] config_timeout_prescale_r;

    logic packet_active_r, packet_active_n;
    logic [BYTE_COUNT_WIDTH-1:0]
        packet_total_bytes_r, packet_total_bytes_n;
    logic [BEAT_COUNT_WIDTH-1:0]
        packet_total_beats_r, packet_total_beats_n;
    logic [BEAT_COUNT_WIDTH-1:0]
        packet_remaining_beats_r, packet_remaining_beats_n;
    logic [15:0] packet_expected_size_r, packet_expected_size_n;
    logic packet_close_r, packet_close_n;
    logic preclose_pending_r, preclose_pending_n;
    logic [8*28-1:0] packet_header_r, packet_header_n;
    logic [TIMEOUT_COUNTER_WIDTH-1:0]
        packet_timeout_threshold_r, packet_timeout_threshold_n;
    logic [TIMEOUT_PRESCALER_WIDTH-1:0]
        packet_timeout_prescale_r, packet_timeout_prescale_n;

    logic [TIMEOUT_PRESCALER_WIDTH-1:0]
        timeout_prescale_r, timeout_prescale_n;
    logic [TIMEOUT_COUNTER_WIDTH-1:0] timeout_count_r, timeout_count_n;

    logic [BEAT_COUNT_WIDTH-1:0] command_beats_c, target_beats_c;
    logic [15:0] command_bytes_c;
    logic first_preclose_c, first_start_c, first_close_c;
    logic first_larger_c, first_smaller_c, first_fits_c;
    logic first_close_append_c, first_close_new_c;
    logic first_has_slot_c;
    logic first_needs_preclose_c, preclose_request_c;
    logic [2:0] occupied_slots_c;
    logic [BYTE_COUNT_WIDTH-1:0] first_total_bytes_c;
    logic [BEAT_COUNT_WIDTH-1:0] first_total_beats_c;
    logic [BEAT_COUNT_WIDTH-1:0] first_remaining_beats_c;
    logic [BEAT_COUNT_WIDTH-1:0] packet_total_beats_with_current_c;
    logic [15:0] first_expected_size_c;
    logic [8*28-1:0] first_header_c;
    logic [TIMEOUT_COUNTER_WIDTH-1:0] first_timeout_threshold_c;
    logic [TIMEOUT_PRESCALER_WIDTH-1:0] first_timeout_prescale_c;

    logic [1:0] desc_push_count_c;
    logic [BEAT_COUNT_WIDTH-1:0] push0_beats_c, push1_beats_c;
    logic [BYTE_COUNT_WIDTH-1:0] push0_bytes_c, push1_bytes_c;
    logic [8*28-1:0] push0_header_c, push1_header_c;
    logic descriptor_pop_c, timeout_expired_c, external_close_c;
    logic timeout_close_pending_r, timeout_close_pending_n;

    wire payload_fire = payload_exec.tvalid && payload_exec.tready;
    wire packet_first = !packet_active_r;
    wire packet_last_fire = payload_fire && payload_exec.t.last;
    wire output_fire = payload_out.tvalid && payload_out.tready;
    wire output_done_fire = output_fire &&
        drain_beats_remaining_r == BEAT_COUNT_WIDTH'(1);

    assign command_bytes_c =
        payload_exec.t.user[META_BYTES_LSB +: 16];
    assign command_beats_c = BEAT_COUNT_WIDTH'(
        payload_exec.t.user[META_BEATS_LSB +: PACKET_BEAT_COUNT_WIDTH]);

    // Keep four beats of per-queue elasticity while making the router-facing
    // ready signal and the admission-facing payload fully registered. Unlike
    // an FF FIFO with EXTRA_OUTPUT_REG, all four registers are usable storage;
    // there is no fifth mirrored copy of the wide AXIS payload.
    axis_register_slice #(
        .MODE("ISOLATE"), .NUM_STAGES(4)
    ) u_payload_exec_buffer (
        .clk(clk), .resetn(resetn),
        .s_axis(payload_in), .m_axis(payload_exec)
    );

    always_comb begin
        target_beats_c = config_target_beats_r;
        first_larger_c = command_bytes_c > fill_expected_size_r;
        first_smaller_c = command_bytes_c < fill_expected_size_r;
        first_fits_c = command_beats_c <= fill_remaining_beats_r;
        first_needs_preclose_c = fill_active_r &&
            (first_larger_c || !first_fits_c);
        // Size/capacity pre-close is registered before it mutates the
        // descriptor ring. The packet remains at the execution FIFO head for
        // that cycle, so no packet reservation or partial acceptance exists.
        first_preclose_c = preclose_pending_r;
        first_start_c = !fill_active_r || first_preclose_c;
        first_close_append_c = first_smaller_c ||
            command_beats_c >= fill_remaining_beats_r;
        first_close_new_c = command_beats_c >= target_beats_c;
        first_close_c = first_start_c ? first_close_new_c :
                                        first_close_append_c;

        occupied_slots_c = 3'(desc_count_r) + 3'(fill_active_r);
        first_has_slot_c = !first_start_c || occupied_slots_c < 2;
        preclose_request_c = packet_first && payload_exec.tvalid &&
            first_needs_preclose_c && !preclose_pending_r &&
            occupied_slots_c < 2;
        first_total_bytes_c = first_start_c ?
            BYTE_COUNT_WIDTH'(command_bytes_c) :
            fill_bytes_r + BYTE_COUNT_WIDTH'(command_bytes_c);
        // Count stored beats as they actually enter this queue. The measured
        // packet descriptor is used only for the atomic budget decision.
        first_total_beats_c = first_start_c ? BEAT_COUNT_WIDTH'(1) :
            fill_beats_r + 1'b1;
        first_remaining_beats_c = first_close_c ? '0 :
            first_start_c ? target_beats_c - command_beats_c :
                            fill_remaining_beats_r - command_beats_c;
        first_expected_size_c = first_start_c ? command_bytes_c :
                                                fill_expected_size_r;
        first_header_c = first_start_c ? config_header_r : fill_header_r;
        first_timeout_threshold_c = first_start_c ?
            config_timeout_threshold_r : fill_timeout_threshold_r;
        first_timeout_prescale_c = first_start_c ?
            config_timeout_prescale_r : fill_timeout_prescale_r;
        packet_total_beats_with_current_c = packet_total_beats_r + 1'b1;
    end

    always_comb begin
        fifo_in.t = '0;
        fifo_in.t.data = payload_exec.t.data;
        fifo_in.t.keep = payload_exec.t.keep;
        fifo_in.t.last = 1'b0;
        fifo_in.tvalid = payload_exec.tvalid &&
            !timeout_close_pending_r &&
            (!packet_first || !first_needs_preclose_c ||
             preclose_pending_r) &&
            (!packet_first || first_has_slot_c);
        payload_exec.tready = fifo_in.tready &&
            !timeout_close_pending_r &&
            (!packet_first || !first_needs_preclose_c ||
             preclose_pending_r) &&
            (!packet_first || first_has_slot_c);

        payload_out.t = '0;
        payload_out.t.data = fifo_out.t.data;
        payload_out.t.keep = fifo_out.t.keep;
        payload_out.t.last =
            drain_beats_remaining_r == BEAT_COUNT_WIDTH'(1);
        payload_out.t.user = {drain_header_r, drain_bytes_r};
        payload_out.tvalid = drain_active_r && fifo_out.tvalid;
        fifo_out.tready = drain_active_r && payload_out.tready;
    end

    // Register the result of the first-beat aggregation decision before the
    // raw FIFO. The size/slot comparisons therefore terminate in nearby FFs;
    // only this registered valid drives the BRAM write enable. The elastic
    // stage can replace a consumed beat in the same cycle, so it adds latency
    // without introducing an ingress bubble.
    axis_register_slice #(
        .MODE("STANDARD"), .NUM_STAGES(1)
    ) u_payload_write_boundary (
        .clk(clk), .resetn(resetn),
        .s_axis(fifo_in), .m_axis(fifo_write)
    );

    axis_fifo #(
        .DEPTH(FIFO_DEPTH), .USE_BRAM(1'b1),
        .EXTRA_OUTPUT_REG(1'b1), .MODE("CONSERVATIVE")
    ) u_payload_fifo (
        .clk(clk), .resetn(resetn), .s_axis(fifo_write), .m_axis(fifo_out)
    );

    assign input_done = packet_last_fire;
    assign aggregate_done = output_done_fire;
    assign queue_empty = !fill_active_r && !packet_active_r &&
                         desc_count_r == 0 && !drain_active_r;

    always_comb begin
        bank_status[2:0] = fill_active_r ? uro_pkg::URO_BANK_FILLING :
                                            uro_pkg::URO_BANK_FREE;
        bank_status[5:3] = drain_active_r ? uro_pkg::URO_BANK_DRAIN :
                             (desc_count_r != 0) ? uro_pkg::URO_BANK_READY :
                                                   uro_pkg::URO_BANK_FREE;
        bank0_bytes = fill_active_r ? fill_bytes_r : '0;
        bank1_bytes = drain_active_r ? drain_bytes_r :
                      ((desc_count_r != 0) ? desc_bytes_r[desc_head_r] : '0);
    end

    always_comb begin
        desc_head_n = desc_head_r;
        desc_tail_n = desc_tail_r;
        desc_count_n = desc_count_r;
        drain_active_n = drain_active_r;
        drain_beats_remaining_n = drain_beats_remaining_r;
        drain_bytes_n = drain_bytes_r;
        drain_header_n = drain_header_r;
        fill_active_n = fill_active_r;
        fill_bytes_n = fill_bytes_r;
        fill_beats_n = fill_beats_r;
        fill_remaining_beats_n = fill_remaining_beats_r;
        fill_expected_size_n = fill_expected_size_r;
        fill_header_n = fill_header_r;
        fill_timeout_threshold_n = fill_timeout_threshold_r;
        fill_timeout_prescale_n = fill_timeout_prescale_r;
        packet_active_n = packet_active_r;
        packet_total_bytes_n = packet_total_bytes_r;
        packet_total_beats_n = packet_total_beats_r;
        packet_remaining_beats_n = packet_remaining_beats_r;
        packet_expected_size_n = packet_expected_size_r;
        packet_close_n = packet_close_r;
        preclose_pending_n = preclose_pending_r;
        packet_header_n = packet_header_r;
        packet_timeout_threshold_n = packet_timeout_threshold_r;
        packet_timeout_prescale_n = packet_timeout_prescale_r;
        timeout_prescale_n = timeout_prescale_r;
        timeout_count_n = timeout_count_r;
        timeout_close_pending_n = timeout_close_pending_r;

        for (int d = 0; d < 2; d++) begin
            desc_beats_n[d] = desc_beats_r[d];
            desc_bytes_n[d] = desc_bytes_r[d];
            desc_header_n[d] = desc_header_r[d];
        end

        desc_push_count_c = '0;
        push0_beats_c = '0;
        push0_bytes_c = '0;
        push0_header_c = '0;
        push1_beats_c = '0;
        push1_bytes_c = '0;
        push1_header_c = '0;
        descriptor_pop_c = output_done_fire;

        if (preclose_request_c)
            preclose_pending_n = 1'b1;

        timeout_expired_c = fill_active_r && !packet_active_r &&
            !payload_exec.tvalid && fill_timeout_threshold_r != 0 &&
            timeout_count_r >= fill_timeout_threshold_r;
        external_close_c = fill_active_r && !packet_active_r &&
                           (force_close || timeout_close_pending_r);

        // Register timeout expiration before it reaches the descriptor ring.
        // The execution input is held while the pending close is consumed, so
        // a packet arriving in that cycle starts a new aggregate afterward.
        if (timeout_expired_c)
            timeout_close_pending_n = 1'b1;
        if (external_close_c)
            timeout_close_pending_n = 1'b0;

        if (!fill_active_r || packet_last_fire || external_close_c) begin
            timeout_prescale_n = '0;
            timeout_count_n = '0;
        end else if (!packet_active_r) begin
            if (fill_timeout_prescale_r == 0 ||
                timeout_prescale_r >= fill_timeout_prescale_r) begin
                timeout_prescale_n = '0;
                if (~&timeout_count_r)
                    timeout_count_n = timeout_count_r + 1'b1;
            end else begin
                timeout_prescale_n = timeout_prescale_r + 1'b1;
            end
        end

        if (!drain_active_r && desc_count_r != 0) begin
            drain_active_n = 1'b1;
            drain_beats_remaining_n = desc_beats_r[desc_head_r];
            drain_bytes_n = desc_bytes_r[desc_head_r];
            drain_header_n = desc_header_r[desc_head_r];
        end else if (output_fire) begin
            if (output_done_fire) begin
                drain_active_n = 1'b0;
                drain_beats_remaining_n = '0;
                desc_head_n = ~desc_head_r;
            end else begin
                drain_beats_remaining_n = drain_beats_remaining_r - 1'b1;
            end
        end

        if (external_close_c) begin
            desc_push_count_c = 1;
            push0_beats_c = fill_beats_r;
            push0_bytes_c = fill_bytes_r;
            push0_header_c = fill_header_r;
            fill_active_n = 1'b0;
        end

        if (payload_fire) begin
            if (packet_first) begin
                if (first_preclose_c) begin
                    desc_push_count_c = 1;
                    push0_beats_c = fill_beats_r;
                    push0_bytes_c = fill_bytes_r;
                    push0_header_c = fill_header_r;
                    fill_active_n = 1'b0;
                    preclose_pending_n = 1'b0;
                end

                if (payload_exec.t.last) begin
                    // The data fields are don't-care while fill_active is
                    // clear. Updating them unconditionally avoids feeding the
                    // target/close decision through every state-field mux.
                    fill_bytes_n = first_total_bytes_c;
                    fill_beats_n = first_total_beats_c;
                    fill_remaining_beats_n = first_remaining_beats_c;
                    fill_expected_size_n = first_expected_size_c;
                    fill_header_n = first_header_c;
                    fill_timeout_threshold_n = first_timeout_threshold_c;
                    fill_timeout_prescale_n = first_timeout_prescale_c;
                    if (first_close_c) begin
                        if (desc_push_count_c == 0) begin
                            push0_beats_c = first_total_beats_c;
                            push0_bytes_c = first_total_bytes_c;
                            push0_header_c = first_header_c;
                        end else begin
                            push1_beats_c = first_total_beats_c;
                            push1_bytes_c = first_total_bytes_c;
                            push1_header_c = first_header_c;
                        end
                        desc_push_count_c = desc_push_count_c + 1'b1;
                        fill_active_n = 1'b0;
                    end else begin
                        fill_active_n = 1'b1;
                    end
                end else begin
                    packet_active_n = 1'b1;
                    packet_total_bytes_n = first_total_bytes_c;
                    packet_total_beats_n = first_total_beats_c;
                    packet_remaining_beats_n = first_remaining_beats_c;
                    packet_expected_size_n = first_expected_size_c;
                    packet_close_n = first_close_c;
                    packet_header_n = first_header_c;
                    packet_timeout_threshold_n = first_timeout_threshold_c;
                    packet_timeout_prescale_n = first_timeout_prescale_c;
                end
            end else begin
                packet_total_beats_n = packet_total_beats_with_current_c;
                if (payload_exec.t.last) begin
                    packet_active_n = 1'b0;
                    fill_bytes_n = packet_total_bytes_r;
                    fill_beats_n = packet_total_beats_with_current_c;
                    fill_remaining_beats_n = packet_remaining_beats_r;
                    fill_expected_size_n = packet_expected_size_r;
                    fill_header_n = packet_header_r;
                    fill_timeout_threshold_n = packet_timeout_threshold_r;
                    fill_timeout_prescale_n = packet_timeout_prescale_r;
                    if (packet_close_r) begin
                        desc_push_count_c = 1;
                        push0_beats_c = packet_total_beats_with_current_c;
                        push0_bytes_c = packet_total_bytes_r;
                        push0_header_c = packet_header_r;
                        fill_active_n = 1'b0;
                    end else begin
                        fill_active_n = 1'b1;
                    end
                end
            end
        end

        if (desc_push_count_c >= 1) begin
            desc_beats_n[desc_tail_r] = push0_beats_c;
            desc_bytes_n[desc_tail_r] = push0_bytes_c;
            desc_header_n[desc_tail_r] = push0_header_c;
        end
        if (desc_push_count_c == 2) begin
            desc_beats_n[~desc_tail_r] = push1_beats_c;
            desc_bytes_n[~desc_tail_r] = push1_bytes_c;
            desc_header_n[~desc_tail_r] = push1_header_c;
        end
        if (desc_push_count_c[0])
            desc_tail_n = ~desc_tail_r;
        desc_count_n = desc_count_r + desc_push_count_c - descriptor_pop_c;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            config_header_r <= '0;
            config_target_beats_r <= '0;
            config_timeout_threshold_r <= '0;
            config_timeout_prescale_r <= '0;
            desc_head_r <= 1'b0;
            desc_tail_r <= 1'b0;
            desc_count_r <= '0;
            drain_active_r <= 1'b0;
            drain_beats_remaining_r <= '0;
            drain_bytes_r <= '0;
            drain_header_r <= '0;
            fill_active_r <= 1'b0;
            fill_bytes_r <= '0;
            fill_beats_r <= '0;
            fill_remaining_beats_r <= '0;
            fill_expected_size_r <= '0;
            fill_header_r <= '0;
            fill_timeout_threshold_r <= '0;
            fill_timeout_prescale_r <= '0;
            packet_active_r <= 1'b0;
            packet_total_bytes_r <= '0;
            packet_total_beats_r <= '0;
            packet_remaining_beats_r <= '0;
            packet_expected_size_r <= '0;
            packet_close_r <= 1'b0;
            preclose_pending_r <= 1'b0;
            packet_header_r <= '0;
            packet_timeout_threshold_r <= '0;
            packet_timeout_prescale_r <= '0;
            timeout_prescale_r <= '0;
            timeout_count_r <= '0;
            timeout_close_pending_r <= 1'b0;
            for (int d = 0; d < 2; d++) begin
                desc_beats_r[d] <= '0;
                desc_bytes_r[d] <= '0;
                desc_header_r[d] <= '0;
            end
        end else begin
            config_header_r <= config_header;
            if (config_target_beats == 0 ||
                config_target_beats > BEAT_COUNT_WIDTH'(MAX_AGGREGATE_BEATS))
                config_target_beats_r <=
                    BEAT_COUNT_WIDTH'(MAX_AGGREGATE_BEATS);
            else
                config_target_beats_r <= config_target_beats;
            config_timeout_threshold_r <= config_timeout_threshold;
            config_timeout_prescale_r <= config_timeout_prescale;
            desc_head_r <= desc_head_n;
            desc_tail_r <= desc_tail_n;
            desc_count_r <= desc_count_n;
            drain_active_r <= drain_active_n;
            drain_beats_remaining_r <= drain_beats_remaining_n;
            drain_bytes_r <= drain_bytes_n;
            drain_header_r <= drain_header_n;
            fill_active_r <= fill_active_n;
            fill_bytes_r <= fill_bytes_n;
            fill_beats_r <= fill_beats_n;
            fill_remaining_beats_r <= fill_remaining_beats_n;
            fill_expected_size_r <= fill_expected_size_n;
            fill_header_r <= fill_header_n;
            fill_timeout_threshold_r <= fill_timeout_threshold_n;
            fill_timeout_prescale_r <= fill_timeout_prescale_n;
            packet_active_r <= packet_active_n;
            packet_total_bytes_r <= packet_total_bytes_n;
            packet_total_beats_r <= packet_total_beats_n;
            packet_remaining_beats_r <= packet_remaining_beats_n;
            packet_expected_size_r <= packet_expected_size_n;
            packet_close_r <= packet_close_n;
            preclose_pending_r <= preclose_pending_n;
            packet_header_r <= packet_header_n;
            packet_timeout_threshold_r <= packet_timeout_threshold_n;
            packet_timeout_prescale_r <= packet_timeout_prescale_n;
            timeout_prescale_r <= timeout_prescale_n;
            timeout_count_r <= timeout_count_n;
            timeout_close_pending_r <= timeout_close_pending_n;
            for (int d = 0; d < 2; d++) begin
                desc_beats_r[d] <= desc_beats_n[d];
                desc_bytes_r[d] <= desc_bytes_n[d];
                desc_header_r[d] <= desc_header_n[d];
            end
        end
    end

    assert property (@(posedge clk) disable iff (!resetn)
        (desc_count_r + 2'(fill_active_r)) <= 2)
        else $error("uro_queue: aggregate occupancy exceeded two slots");
    assert property (@(posedge clk) disable iff (!resetn)
        (desc_count_r + desc_push_count_c - descriptor_pop_c) <= 2)
        else $error("uro_queue: descriptor ring overflow");

    initial begin
        if (MAX_URO_QUEUE_BYTES < 9000) begin
            $error("uro_queue: MAX_URO_QUEUE_BYTES must be at least 9000");
            $finish;
        end
        if (PACKET_META_WIDTH <
            META_BEATS_LSB + PACKET_BEAT_COUNT_WIDTH) begin
            $error("uro_queue: packet metadata width is too small");
            $finish;
        end
    end
endmodule
