// =============================================================================
// packet_rate_limiter - atomic packet-level beat-token limiter
// =============================================================================

module packet_rate_limiter #(
    parameter int unsigned DATA_WIDTH          = 512,
    parameter int unsigned MAX_FLOWS           = 4096,
    parameter int unsigned PACKET_FIFO_DEPTH   = 64,
    parameter int unsigned PARSER_FIFO_DEPTH   = 4,
    parameter int unsigned META_FIFO_DEPTH     = 64,
    parameter int unsigned TABLE_ASSOCIATIVITY = 4,
    parameter int unsigned MAX_PACKET_BEATS    = 24,
    parameter logic [15:0] COUNTER_START_VALUE = '0
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  packet_in,
    ifc_axis.master packet_out,
    ifc_axil.slave ctrl
);

    localparam int TABLE_DEPTH = MAX_FLOWS / TABLE_ASSOCIATIVITY;
    localparam int FLOW_STATE_W = (MAX_FLOWS <= 2) ? 1 : $clog2(MAX_FLOWS);
    localparam int BEAT_COUNT_W = 5;

    typedef struct packed {
        logic hit;
        logic [FLOW_STATE_W-1:0] state_idx;
        logic [6:0] max_burst;
        logic [6:0] scalar_mask;
        logic [BEAT_COUNT_W-1:0] packet_beats;
    } packet_meta_t;

    typedef struct packed {
        logic hit;
        logic [FLOW_STATE_W-1:0] flow_id;
        logic [6:0] max_burst;
        logic [6:0] scalar_mask;
        logic [2:0] scalar_shift;
        logic epoch;
        logic [15:0] counter;
        logic [BEAT_COUNT_W-1:0] packet_beats;
        logic counter_forward_valid;
        logic [17:0] counter_forward_data;
    } token_s0_t;

    typedef struct packed {
        logic hit;
        logic [FLOW_STATE_W-1:0] flow_id;
        logic [6:0] max_burst;
        logic [6:0] scalar_mask;
        logic [2:0] scalar_shift;
        logic epoch;
        logic [15:0] counter;
        logic [BEAT_COUNT_W-1:0] packet_beats;
        logic state_fresh;
        logic [15:0] elapsed;
    } token_s1_t;

    typedef struct packed {
        logic hit;
        logic [FLOW_STATE_W-1:0] flow_id;
        logic [6:0] max_burst;
        logic [6:0] scalar_mask;
        logic epoch;
        logic [15:0] counter;
        logic [BEAT_COUNT_W-1:0] packet_beats;
        logic state_fresh;
        logic [7:0] refill;
        logic token_read_forward_valid;
        logic [7:0] token_read_forward_data;
    } token_s2_t;

    typedef token_s2_t token_s3_t;

    typedef struct packed {
        logic hit;
        logic [FLOW_STATE_W-1:0] flow_id;
        logic [6:0] max_burst;
        logic [6:0] scalar_mask;
        logic epoch;
        logic [15:0] counter;
        logic [7:0] refill;
        logic max_nonzero;
        logic [7:0] refill_minus_beats;
        logic [7:0] biased_max_minus_beats;
        // Runtime token balances use offset binary: stored = signed + 128.
        logic [7:0] base_token;
    } token_s4_t;

    function automatic logic [2:0] f_scalar_shift(input logic [6:0] mask);
        f_scalar_shift = 3'd0;
        for (int bit_idx = 0; bit_idx < 7; bit_idx++) begin
            if (mask[bit_idx])
                f_scalar_shift = 3'(bit_idx + 1);
        end
    endfunction

    function automatic logic [7:0] f_saturating_refill(
        input logic [15:0] elapsed,
        input logic [2:0] shift
    );
        case (shift)
            3'd0: f_saturating_refill = |elapsed[15:8]
                ? 8'hff : elapsed[7:0];
            3'd1: f_saturating_refill = |elapsed[15:7]
                ? 8'hff : {elapsed[6:0], 1'b0};
            3'd2: f_saturating_refill = |elapsed[15:6]
                ? 8'hff : {elapsed[5:0], 2'b0};
            3'd3: f_saturating_refill = |elapsed[15:5]
                ? 8'hff : {elapsed[4:0], 3'b0};
            3'd4: f_saturating_refill = |elapsed[15:4]
                ? 8'hff : {elapsed[3:0], 4'b0};
            3'd5: f_saturating_refill = |elapsed[15:3]
                ? 8'hff : {elapsed[2:0], 5'b0};
            3'd6: f_saturating_refill = |elapsed[15:2]
                ? 8'hff : {elapsed[1:0], 6'b0};
            default: f_saturating_refill = |elapsed[15:1]
                ? 8'hff : {elapsed[0], 7'b0};
        endcase
    endfunction

    initial begin
        if (DATA_WIDTH < 8 || DATA_WIDTH % 8 != 0 ||
            ((DATA_WIDTH & (DATA_WIDTH - 1)) != 0)) begin
            $error("packet_rate_limiter: DATA_WIDTH must be a byte-aligned power of two >= 8");
            $finish;
        end
        if (MAX_FLOWS < 2 || ((MAX_FLOWS & (MAX_FLOWS - 1)) != 0)) begin
            $error("packet_rate_limiter: MAX_FLOWS must be a power of two and >= 2");
            $finish;
        end
        if (MAX_PACKET_BEATS < 1 || MAX_PACKET_BEATS > 24) begin
            $error("packet_rate_limiter: MAX_PACKET_BEATS must be in [1, 24]");
            $finish;
        end
        if (PACKET_FIFO_DEPTH < MAX_PACKET_BEATS + 2) begin
            $error("packet_rate_limiter: packet FIFO must hold a complete supported packet");
            $finish;
        end
    end

    // Fixed 128-clock refill tick.
    logic [15:0] global_counter;
    logic [6:0] global_prescale_count;
    logic global_prescale_terminal;
    wire global_counter_wrap = global_prescale_terminal && (&global_counter);

    generic_prescaled_counter #(
        .COUNTER_WIDTH(16),
        .PRESCALER_WIDTH(7),
        .COUNTER_START_VALUE(COUNTER_START_VALUE)
    ) u_timebase (
        .clk(clk), .resetn(resetn), .enable(1'b1), .increment(1'b1),
        .step_value(16'd1), .prescale_value(7'd127),
        .count(global_counter), .prescale_count(global_prescale_count),
        .prescale_terminal(global_prescale_terminal)
    );

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(12), .TID_WIDTH(16), .TUSER_WIDTH(16)
    ) u_packet_fifo_out (.axis_aclk(clk));

    packet_meta_t meta_pop_data;
    logic [$bits(packet_meta_t)-1:0] ingress_meta_data;
    logic meta_pop_valid;
    logic meta_pop_ready;
    logic config_write_commit;
    logic [FLOW_STATE_W-1:0] config_write_idx;

    assign meta_pop_data = packet_meta_t'(ingress_meta_data);

    packet_rate_limiter_ingress #(
        .DATA_WIDTH(DATA_WIDTH),
        .PACKET_FIFO_DEPTH(PACKET_FIFO_DEPTH),
        .PARSER_FIFO_DEPTH(PARSER_FIFO_DEPTH),
        .META_FIFO_DEPTH(META_FIFO_DEPTH),
        .MAX_FLOWS(MAX_FLOWS),
        .TABLE_ASSOCIATIVITY(TABLE_ASSOCIATIVITY),
        .MAX_PACKET_BEATS(MAX_PACKET_BEATS)
    ) u_ingress (
        .clk(clk), .resetn(resetn),
        .packet_in(packet_in), .packet_buffer_out(u_packet_fifo_out),
        .table_ctrl(ctrl),
        .lookup_meta_valid(meta_pop_valid),
        .lookup_meta_ready(meta_pop_ready),
        .lookup_meta_data(ingress_meta_data),
        .config_write_commit(config_write_commit),
        .config_write_idx(config_write_idx)
    );

    /* verilator lint_off PROCASSINIT */
    logic token_state_epoch_r = 1'b0;
    logic token_reset_seen_r = 1'b0;
    /* verilator lint_on PROCASSINIT */

    // Runtime state is kept in two physical-flow-indexed BRAMs.
    logic [17:0] counter_bram_dout;
    logic counter_bram_we;
    logic [FLOW_STATE_W-1:0] counter_bram_write_addr;
    logic [17:0] counter_bram_write_data;
    logic [7:0] token_bram_dout_bits;
    logic [17:0] counter_bram_dout_b_unused;
    logic [7:0] token_bram_dout_b_unused;
    logic token_bram_we;
    logic [FLOW_STATE_W-1:0] token_bram_write_addr;
    logic [7:0] token_bram_write_data;

    token_s0_t token_s0_r;
    token_s1_t token_s1_r;
    token_s2_t token_s2_r;
    token_s3_t token_s3_r;
    token_s4_t token_s4_r;
    logic token_s0_valid_r;
    logic token_s1_valid_r;
    logic token_s2_valid_r;
    logic token_s3_valid_r;
    logic token_s4_valid_r;

    true_dual_port_bram #(
        .BRAM_WIDTH(18), .BRAM_DEPTH(MAX_FLOWS),
        .INIT_VALID_ZERO(1'b1), .VALID_BIT_INDEX(17)
    ) u_last_counter_bram (
        .clk(clk),
        .we_a(1'b0), .addr_a(meta_pop_data.state_idx), .din_a('0),
        .dout_a(counter_bram_dout),
        .we_b(counter_bram_we), .addr_b(counter_bram_write_addr),
        .din_b(counter_bram_write_data), .dout_b(counter_bram_dout_b_unused)
    );

    true_dual_port_bram #(
        .BRAM_WIDTH(8), .BRAM_DEPTH(MAX_FLOWS),
        .INIT_VALID_ZERO(1'b1), .VALID_BIT_INDEX(7)
    ) u_token_bram (
        .clk(clk),
        // Launch one stage early so the BRAM result can be resolved and
        // registered as base_token before the final arithmetic/write stage.
        .we_a(1'b0), .addr_a(token_s2_r.flow_id), .din_a('0),
        .dout_a(token_bram_dout_bits),
        .we_b(token_bram_we), .addr_b(token_bram_write_addr),
        .din_b(token_bram_write_data), .dout_b(token_bram_dout_b_unused)
    );

    logic decision_push_ready;
    wire decision_push_valid = token_s4_valid_r && !config_write_commit;
    wire pipeline_advance = !config_write_commit &&
                            (!token_s4_valid_r || decision_push_ready);
    assign meta_pop_ready = pipeline_advance;

    wire counter_write_fire = pipeline_advance && token_s0_valid_r &&
                              token_s0_r.hit;
    wire token_write_fire = pipeline_advance && token_s4_valid_r &&
                            token_s4_r.hit;

    logic [17:0] token_s0_counter_state;
    logic [15:0] token_s0_elapsed;
    logic token_s0_state_fresh;
    logic [7:0] token_s1_refill;

    always_comb begin
        token_s0_counter_state = token_s0_r.counter_forward_valid
            ? token_s0_r.counter_forward_data : counter_bram_dout;
        token_s0_state_fresh = token_s0_counter_state[17] &&
            token_s0_counter_state[16] == token_s0_r.epoch;
        token_s0_elapsed = token_s0_state_fresh
            ? token_s0_r.counter - token_s0_counter_state[15:0] : 16'd0;
    end

    assign token_s1_refill = f_saturating_refill(
        token_s1_r.elapsed, token_s1_r.scalar_shift);

    logic [8:0] token_s4_refilled_biased;
    logic [7:0] token_s4_uncapped_post;
    logic token_s4_capped;
    logic token_s4_positive;
    logic token_s4_admit;
    logic [7:0] token_s4_stored_balance;

    always_comb begin
        token_s4_refilled_biased = {1'b0, token_s4_r.base_token} +
            {1'b0, token_s4_r.refill};
        token_s4_uncapped_post = token_s4_r.base_token +
            token_s4_r.refill_minus_beats;

        // A carry is unconditionally above the 8-bit biased maximum. Without
        // a carry, only an 8-bit comparison against 128 + max_burst is needed.
        token_s4_capped = token_s4_refilled_biased[8] ||
            (token_s4_refilled_biased[7:0] >
             {1'b1, token_s4_r.max_burst});
        // In offset binary, values greater than 128 represent positive
        // signed balances. This avoids a signed zero comparison.
        token_s4_positive = token_s4_refilled_biased[8] ||
            (token_s4_refilled_biased[7] &&
             (|token_s4_refilled_biased[6:0]));

        token_s4_admit = 1'b0;
        if (token_s4_capped) begin
            // Refill clamps at max_burst. A zero-sized burst remains a drop
            // and must not be debited.
            token_s4_admit = token_s4_r.hit && token_s4_r.max_nonzero;
            token_s4_stored_balance = token_s4_r.max_nonzero
                ? token_s4_r.biased_max_minus_beats : 8'h80;
        end else if (token_s4_positive) begin
            // The uncapped balance is positive, so reserve this packet.
            token_s4_admit = token_s4_r.hit;
            token_s4_stored_balance = token_s4_uncapped_post;
        end else begin
            // Zero/negative balances are retained without another debit.
            // For a miss this value is don't-care because token_bram_we=0.
            token_s4_stored_balance = token_s4_refilled_biased[7:0];
        end
    end

    always_comb begin
        counter_bram_we = 1'b0;
        counter_bram_write_addr = '0;
        counter_bram_write_data = '0;
        if (config_write_commit) begin
            counter_bram_we = 1'b1;
            counter_bram_write_addr = config_write_idx;
            counter_bram_write_data = '0;
        end else if (counter_write_fire) begin
            counter_bram_we = 1'b1;
            counter_bram_write_addr = token_s0_r.flow_id;
            counter_bram_write_data = {
                1'b1, token_s0_r.epoch, token_s0_r.counter
            };
        end

        token_bram_we = token_write_fire;
        token_bram_write_addr = token_s4_r.flow_id;
        token_bram_write_data = token_s4_stored_balance;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            if (!token_reset_seen_r)
                token_state_epoch_r <= ~token_state_epoch_r;
            token_reset_seen_r <= 1'b1;
            token_s0_valid_r <= 1'b0;
            token_s1_valid_r <= 1'b0;
            token_s2_valid_r <= 1'b0;
            token_s3_valid_r <= 1'b0;
            token_s4_valid_r <= 1'b0;
            token_s0_r <= '0;
            token_s1_r <= '0;
            token_s2_r <= '0;
            token_s3_r <= '0;
            token_s4_r <= '0;
        end else begin
            token_reset_seen_r <= 1'b0;

            if (pipeline_advance) begin
                token_s4_valid_r <= token_s3_valid_r;
                if (token_s3_valid_r) begin
                    token_s4_r.hit <= token_s3_r.hit;
                    token_s4_r.flow_id <= token_s3_r.flow_id;
                    token_s4_r.max_burst <= token_s3_r.max_burst;
                    token_s4_r.scalar_mask <= token_s3_r.scalar_mask;
                    token_s4_r.epoch <= token_s3_r.epoch;
                    token_s4_r.counter <= token_s3_r.counter;
                    token_s4_r.refill <= token_s3_r.refill;
                    token_s4_r.max_nonzero <= |token_s3_r.max_burst;
                    token_s4_r.refill_minus_beats <=
                        token_s3_r.refill -
                        {3'd0, token_s3_r.packet_beats};
                    token_s4_r.biased_max_minus_beats <=
                        {1'b1, token_s3_r.max_burst} -
                        {3'd0, token_s3_r.packet_beats};
                    if (!token_s3_r.state_fresh)
                        token_s4_r.base_token <=
                            {1'b1, token_s3_r.max_burst};
                    else if (token_write_fire &&
                             token_s4_r.flow_id == token_s3_r.flow_id)
                        token_s4_r.base_token <= token_s4_stored_balance;
                    else if (token_s3_r.token_read_forward_valid)
                        token_s4_r.base_token <=
                            token_s3_r.token_read_forward_data;
                    else
                        token_s4_r.base_token <= token_bram_dout_bits;
                end

                token_s3_valid_r <= token_s2_valid_r;
                if (token_s2_valid_r) begin
                    token_s3_r <= token_s2_r;
                    token_s3_r.token_read_forward_valid <= token_write_fire &&
                        token_s4_r.flow_id == token_s2_r.flow_id;
                    token_s3_r.token_read_forward_data <=
                        token_s4_stored_balance;
                end

                token_s2_valid_r <= token_s1_valid_r;
                if (token_s1_valid_r) begin
                    token_s2_r.hit <= token_s1_r.hit;
                    token_s2_r.flow_id <= token_s1_r.flow_id;
                    token_s2_r.max_burst <= token_s1_r.max_burst;
                    token_s2_r.scalar_mask <= token_s1_r.scalar_mask;
                    token_s2_r.epoch <= token_s1_r.epoch;
                    token_s2_r.counter <= token_s1_r.counter;
                    token_s2_r.packet_beats <= token_s1_r.packet_beats;
                    token_s2_r.state_fresh <= token_s1_r.state_fresh;
                    token_s2_r.refill <= token_s1_refill;
                    token_s2_r.token_read_forward_valid <= 1'b0;
                    token_s2_r.token_read_forward_data <= '0;
                end

                token_s1_valid_r <= token_s0_valid_r;
                if (token_s0_valid_r) begin
                    token_s1_r.hit <= token_s0_r.hit;
                    token_s1_r.flow_id <= token_s0_r.flow_id;
                    token_s1_r.max_burst <= token_s0_r.max_burst;
                    token_s1_r.scalar_mask <= token_s0_r.scalar_mask;
                    token_s1_r.scalar_shift <= token_s0_r.scalar_shift;
                    token_s1_r.epoch <= token_s0_r.epoch;
                    token_s1_r.counter <= token_s0_r.counter;
                    token_s1_r.packet_beats <= token_s0_r.packet_beats;
                    token_s1_r.state_fresh <= token_s0_state_fresh;
                    token_s1_r.elapsed <= token_s0_elapsed;
                end

                token_s0_valid_r <= meta_pop_valid;
                if (meta_pop_valid) begin
                    token_s0_r.hit <= meta_pop_data.hit;
                    token_s0_r.flow_id <= meta_pop_data.state_idx;
                    token_s0_r.max_burst <= meta_pop_data.max_burst;
                    token_s0_r.scalar_mask <= meta_pop_data.scalar_mask;
                    token_s0_r.scalar_shift <=
                        f_scalar_shift(meta_pop_data.scalar_mask);
                    token_s0_r.epoch <= token_state_epoch_r;
                    token_s0_r.counter <= global_counter;
                    token_s0_r.packet_beats <= meta_pop_data.packet_beats;
                    token_s0_r.counter_forward_valid <= counter_write_fire &&
                        token_s0_r.flow_id == meta_pop_data.state_idx;
                    token_s0_r.counter_forward_data <= counter_bram_write_data;
                end
            end

            if (global_counter_wrap)
                token_state_epoch_r <= ~token_state_epoch_r;
        end
    end

    logic context_pop_valid;
    logic context_pop_ready;
    logic context_pop_data;
    sync_ff_fifo #(
        .DEPTH(8), .T(logic), .MODE("CONSERVATIVE")
    ) u_decision_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(decision_push_valid),
        .push_data(token_s4_admit),
        .push_ready(decision_push_ready),
        .pop_valid(context_pop_valid),
        .pop_data(context_pop_data),
        .pop_ready(context_pop_ready)
    );

    logic packet_pop;
    packet_rate_limiter_egress u_egress (
        .clk(clk), .resetn(resetn),
        .packet_buffer_in(u_packet_fifo_out), .packet_out(packet_out),
        .decision_valid(context_pop_valid),
        .decision_ready(context_pop_ready),
        .decision_admit(context_pop_data),
        .packet_pop(packet_pop)
    );

endmodule
