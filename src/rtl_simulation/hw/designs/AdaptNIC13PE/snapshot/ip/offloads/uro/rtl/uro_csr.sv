`include "ifc_axil.sv"

module uro_csr #(
    parameter int NUM_QUEUES             = 64,
    parameter int TIMEOUT_COUNTER_WIDTH  = 16,
    parameter int TIMEOUT_PRESCALER_WIDTH = 16,
    parameter int TARGET_BEAT_COUNT_WIDTH = 8,
    parameter int BYTE_COUNT_WIDTH       = 14
) (
    input logic clk,
    input logic resetn,
    ifc_axil.slave ctrl,

    output logic global_enable,
    output logic queue_enable [NUM_QUEUES],
    output logic [8*28-1:0] queue_header [NUM_QUEUES],
    output logic [TARGET_BEAT_COUNT_WIDTH-1:0]
        queue_target_beats [NUM_QUEUES],
    output logic [TIMEOUT_COUNTER_WIDTH-1:0] queue_timeout_threshold [NUM_QUEUES],
    output logic [TIMEOUT_PRESCALER_WIDTH-1:0] queue_timeout_prescale [NUM_QUEUES],

    input logic [5:0] queue_bank_status [NUM_QUEUES],
    input logic [BYTE_COUNT_WIDTH-1:0] queue_bank0_bytes [NUM_QUEUES],
    input logic [BYTE_COUNT_WIDTH-1:0] queue_bank1_bytes [NUM_QUEUES],
    input logic count_miss,
    input logic count_drop,
    input logic count_aggregate
);
    localparam int QUEUE_ID_WIDTH =
        (NUM_QUEUES <= 1) ? 1 : $clog2(NUM_QUEUES);

    logic [31:0] miss_count_r, drop_count_r, aggregate_count_r;
    logic aw_valid_r, w_valid_r, b_valid_r, r_valid_r;
    logic aw_global_enable_r;
    logic [NUM_QUEUES-1:0] aw_queue_onehot_r;
    logic [9:0] aw_queue_word_onehot_r;
    logic [31:0] w_data_r, r_data_r;
    logic [3:0] w_strb_r;
    logic rd_pending_r;
    logic rd_global_valid_r;
    logic [2:0] rd_global_word_r;
    logic rd_queue_valid_r;
    logic [QUEUE_ID_WIDTH-1:0] rd_queue_r;
    logic [3:0] rd_queue_word_r;
    logic global_enable_n;
    logic [NUM_QUEUES-1:0] queue_enable_n;
    logic [8*28-1:0] queue_header_n [NUM_QUEUES];
    logic [TARGET_BEAT_COUNT_WIDTH-1:0]
        queue_target_beats_n [NUM_QUEUES];
    logic [TIMEOUT_COUNTER_WIDTH-1:0]
        queue_timeout_threshold_n [NUM_QUEUES];
    logic [TIMEOUT_PRESCALER_WIDTH-1:0]
        queue_timeout_prescale_n [NUM_QUEUES];
    logic [31:0] miss_count_n, drop_count_n, aggregate_count_n;
    logic aw_valid_n, w_valid_n, b_valid_n, r_valid_n;
    logic aw_global_enable_n;
    logic [NUM_QUEUES-1:0] aw_queue_onehot_n;
    logic [9:0] aw_queue_word_onehot_n;
    logic [31:0] w_data_n, r_data_n;
    logic [3:0] w_strb_n;
    logic rd_pending_n;
    logic rd_global_valid_n;
    logic [2:0] rd_global_word_n;
    logic rd_queue_valid_n;
    logic [QUEUE_ID_WIDTH-1:0] rd_queue_n;
    logic [3:0] rd_queue_word_n;
    logic [31:0] aw_queue_index_c, ar_queue_index_c;
    logic [3:0] aw_queue_word_c, ar_queue_word_c;
    logic [31:0] read_data_c;
    logic [31:0] global_write_merged_c;
    logic [31:0] queue_config_write_merged_c [NUM_QUEUES];
    logic [31:0] queue_timeout_write_merged_c [NUM_QUEUES];
    logic [31:0] queue_prescale_write_merged_c [NUM_QUEUES];

    wire aw_fire = ctrl.aw_valid && ctrl.aw_ready;
    wire w_fire  = ctrl.w_valid && ctrl.w_ready;
    wire do_write = aw_valid_r && w_valid_r && !b_valid_r;
    wire ar_fire = ctrl.ar_valid && ctrl.ar_ready;

    assign ctrl.aw_ready = !aw_valid_r && !b_valid_r;
    assign ctrl.w_ready  = !w_valid_r && !b_valid_r;
    assign ctrl.b_valid  = b_valid_r;
    assign ctrl.b.resp   = 2'b00;
    assign ctrl.b.user   = '0;
    assign ctrl.ar_ready = !rd_pending_r && !r_valid_r &&
                           !aw_valid_r && !w_valid_r;
    assign ctrl.r_valid  = r_valid_r;
    assign ctrl.r.data   = r_data_r;
    assign ctrl.r.resp   = 2'b00;
    assign ctrl.r.user   = '0;

    function automatic logic [31:0] merge_wstrb(
        input logic [31:0] old_value,
        input logic [31:0] new_value,
        input logic [3:0] strb
    );
        logic [31:0] value;
        value = old_value;
        for (int i = 0; i < 4; i++)
            if (strb[i])
                value[i*8 +: 8] = new_value[i*8 +: 8];
        return value;
    endfunction

    always_comb begin
        aw_queue_index_c = (ctrl.aw.addr - 32'h0000_1000) >> 6;
        aw_queue_word_c = 4'((ctrl.aw.addr - 32'h0000_1000) >> 2);
        ar_queue_index_c = (ctrl.ar.addr - 32'h0000_1000) >> 6;
        ar_queue_word_c = 4'((ctrl.ar.addr - 32'h0000_1000) >> 2);
        global_write_merged_c = merge_wstrb(
            {31'd0, global_enable}, w_data_r, w_strb_r);
        for (int q = 0; q < NUM_QUEUES; q++) begin
            queue_config_write_merged_c[q] = merge_wstrb(
                {queue_enable[q],
                 {(31-TARGET_BEAT_COUNT_WIDTH){1'b0}},
                 queue_target_beats[q]}, w_data_r, w_strb_r);
            queue_timeout_write_merged_c[q] = merge_wstrb(
                32'(queue_timeout_threshold[q]), w_data_r, w_strb_r);
            queue_prescale_write_merged_c[q] = merge_wstrb(
                32'(queue_timeout_prescale[q]), w_data_r, w_strb_r);
        end

        read_data_c = '0;
        if (rd_global_valid_r) begin
            unique case (rd_global_word_r)
                3'd0: read_data_c = {31'd0, global_enable};
                3'd1: read_data_c = 32'h5552_4f32;
                3'd2: read_data_c = 32'(NUM_QUEUES);
                3'd3: read_data_c = miss_count_r;
                3'd4: read_data_c = drop_count_r;
                3'd5: read_data_c = aggregate_count_r;
                default: read_data_c = '0;
            endcase
        end else if (rd_queue_valid_r) begin
            if (rd_queue_word_r < 7) begin
                read_data_c = queue_header[rd_queue_r][
                    rd_queue_word_r*32 +: 32
                ];
            end else begin
                unique case (rd_queue_word_r)
                    7: read_data_c = {
                        queue_enable[rd_queue_r],
                        {(31-TARGET_BEAT_COUNT_WIDTH){1'b0}},
                        queue_target_beats[rd_queue_r]};
                    8: read_data_c = 32'(queue_timeout_threshold[rd_queue_r]);
                    9: read_data_c = 32'(queue_timeout_prescale[rd_queue_r]);
                    10: read_data_c = {26'd0, queue_bank_status[rd_queue_r]};
                    11: read_data_c = 32'(queue_bank0_bytes[rd_queue_r]);
                    12: read_data_c = 32'(queue_bank1_bytes[rd_queue_r]);
                    default: read_data_c = '0;
                endcase
            end
        end
    end

    always_comb begin
        global_enable_n = global_enable;
        aw_valid_n = aw_valid_r;
        w_valid_n = w_valid_r;
        b_valid_n = b_valid_r;
        r_valid_n = r_valid_r;
        aw_global_enable_n = aw_global_enable_r;
        aw_queue_onehot_n = aw_queue_onehot_r;
        aw_queue_word_onehot_n = aw_queue_word_onehot_r;
        w_data_n = w_data_r;
        w_strb_n = w_strb_r;
        r_data_n = r_data_r;
        rd_pending_n = rd_pending_r;
        rd_global_valid_n = rd_global_valid_r;
        rd_global_word_n = rd_global_word_r;
        rd_queue_valid_n = rd_queue_valid_r;
        rd_queue_n = rd_queue_r;
        rd_queue_word_n = rd_queue_word_r;
        miss_count_n = miss_count_r;
        drop_count_n = drop_count_r;
        aggregate_count_n = aggregate_count_r;
        for (int q = 0; q < NUM_QUEUES; q++) begin
            queue_enable_n[q] = queue_enable[q];
            queue_header_n[q] = queue_header[q];
            queue_target_beats_n[q] = queue_target_beats[q];
            queue_timeout_threshold_n[q] = queue_timeout_threshold[q];
            queue_timeout_prescale_n[q] = queue_timeout_prescale[q];
        end

        if (count_miss)
            miss_count_n = miss_count_r + 1'b1;
        if (count_drop)
            drop_count_n = drop_count_r + 1'b1;
        if (count_aggregate)
            aggregate_count_n = aggregate_count_r + 1'b1;

        if (aw_fire) begin
            aw_valid_n = 1'b1;
            aw_global_enable_n = (ctrl.aw.addr == 32'h0000_0000);
            aw_queue_onehot_n = '0;
            aw_queue_word_onehot_n = '0;
            if ((ctrl.aw.addr >= 32'h0000_1000) &&
                (aw_queue_index_c < NUM_QUEUES) &&
                (aw_queue_word_c < 10)) begin
                aw_queue_onehot_n[aw_queue_index_c] = 1'b1;
                aw_queue_word_onehot_n[aw_queue_word_c] = 1'b1;
            end
        end

        if (w_fire) begin
            w_valid_n = 1'b1;
            w_data_n = ctrl.w.data;
            w_strb_n = ctrl.w.strb;
        end

        if (do_write) begin
            if (aw_global_enable_r) begin
                global_enable_n = global_write_merged_c[0];
            end

            for (int q = 0; q < NUM_QUEUES; q++) begin
                if (aw_queue_onehot_r[q]) begin
                    for (int word_idx = 0; word_idx < 7; word_idx++) begin
                        if (aw_queue_word_onehot_r[word_idx]) begin
                            for (int byte_idx = 0; byte_idx < 4; byte_idx++) begin
                                if (w_strb_r[byte_idx]) begin
                                    queue_header_n[q][
                                        word_idx*32 + byte_idx*8 +: 8
                                    ] = w_data_r[byte_idx*8 +: 8];
                                end
                            end
                        end
                    end

                    if (aw_queue_word_onehot_r[7]) begin
                        queue_enable_n[q] = queue_config_write_merged_c[q][31];
                        queue_target_beats_n[q] =
                            queue_config_write_merged_c[q][
                                TARGET_BEAT_COUNT_WIDTH-1:0];
                    end
                    if (aw_queue_word_onehot_r[8]) begin
                        queue_timeout_threshold_n[q] =
                            queue_timeout_write_merged_c[q][
                                TIMEOUT_COUNTER_WIDTH-1:0];
                    end
                    if (aw_queue_word_onehot_r[9]) begin
                        queue_timeout_prescale_n[q] =
                            queue_prescale_write_merged_c[q][
                                TIMEOUT_PRESCALER_WIDTH-1:0];
                    end
                end
            end
            aw_valid_n = 1'b0;
            w_valid_n = 1'b0;
            b_valid_n = 1'b1;
        end

        if (ctrl.b_valid && ctrl.b_ready)
            b_valid_n = 1'b0;

        if (ar_fire) begin
            rd_pending_n = 1'b1;
            rd_global_valid_n =
                (ctrl.ar.addr == 32'h0000_0000) ||
                (ctrl.ar.addr == 32'h0000_0004) ||
                (ctrl.ar.addr == 32'h0000_0008) ||
                (ctrl.ar.addr == 32'h0000_000c) ||
                (ctrl.ar.addr == 32'h0000_0010) ||
                (ctrl.ar.addr == 32'h0000_0014);
            rd_global_word_n = ctrl.ar.addr[4:2];
            rd_queue_valid_n = (ctrl.ar.addr >= 32'h0000_1000) &&
                               (ar_queue_index_c < NUM_QUEUES);
            rd_queue_n = QUEUE_ID_WIDTH'(ar_queue_index_c);
            rd_queue_word_n = ar_queue_word_c;
        end

        if (rd_pending_r) begin
            r_data_n = read_data_c;
            rd_pending_n = 1'b0;
            r_valid_n = 1'b1;
        end
        if (ctrl.r_valid && ctrl.r_ready)
            r_valid_n = 1'b0;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            global_enable <= 1'b1;
            aw_valid_r <= 1'b0;
            w_valid_r <= 1'b0;
            b_valid_r <= 1'b0;
            r_valid_r <= 1'b0;
            aw_global_enable_r <= 1'b0;
            aw_queue_onehot_r <= '0;
            aw_queue_word_onehot_r <= '0;
            w_data_r <= '0;
            w_strb_r <= '0;
            r_data_r <= '0;
            rd_pending_r <= 1'b0;
            rd_global_valid_r <= 1'b0;
            rd_global_word_r <= '0;
            rd_queue_valid_r <= 1'b0;
            rd_queue_r <= '0;
            rd_queue_word_r <= '0;
            miss_count_r <= '0;
            drop_count_r <= '0;
            aggregate_count_r <= '0;
            for (int q = 0; q < NUM_QUEUES; q++) begin
                queue_enable[q] <= 1'b0;
                queue_header[q] <= '0;
                queue_target_beats[q] <= '0;
                queue_timeout_threshold[q] <= '0;
                queue_timeout_prescale[q] <= '0;
            end
        end else begin
            global_enable <= global_enable_n;
            aw_valid_r <= aw_valid_n;
            w_valid_r <= w_valid_n;
            b_valid_r <= b_valid_n;
            r_valid_r <= r_valid_n;
            aw_global_enable_r <= aw_global_enable_n;
            aw_queue_onehot_r <= aw_queue_onehot_n;
            aw_queue_word_onehot_r <= aw_queue_word_onehot_n;
            w_data_r <= w_data_n;
            w_strb_r <= w_strb_n;
            r_data_r <= r_data_n;
            rd_pending_r <= rd_pending_n;
            rd_global_valid_r <= rd_global_valid_n;
            rd_global_word_r <= rd_global_word_n;
            rd_queue_valid_r <= rd_queue_valid_n;
            rd_queue_r <= rd_queue_n;
            rd_queue_word_r <= rd_queue_word_n;
            miss_count_r <= miss_count_n;
            drop_count_r <= drop_count_n;
            aggregate_count_r <= aggregate_count_n;
            for (int q = 0; q < NUM_QUEUES; q++) begin
                queue_enable[q] <= queue_enable_n[q];
                queue_header[q] <= queue_header_n[q];
                queue_target_beats[q] <= queue_target_beats_n[q];
                queue_timeout_threshold[q] <= queue_timeout_threshold_n[q];
                queue_timeout_prescale[q] <= queue_timeout_prescale_n[q];
            end
        end
    end
endmodule
