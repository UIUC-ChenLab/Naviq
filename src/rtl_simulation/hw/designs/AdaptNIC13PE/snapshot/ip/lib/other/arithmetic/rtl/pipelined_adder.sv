`ifndef PIPELINED_ADDER_SV
`define PIPELINED_ADDER_SV

// Generic pipelined adder.
// - WIDTH: input operand width.
// - STAGES: latency in cycles (minimum 1).
// The sum is computed across STAGES pipeline stages and output_valid is asserted
// when sum is valid.
module pipelined_adder #(
    parameter int WIDTH = 16,
    parameter int STAGES = 1
) (
    input  logic             clk,
    input  logic             resetn,
    input  logic [WIDTH-1:0] add_a,
    input  logic [WIDTH-1:0] add_b,
    input  logic             inputs_valid,
    output logic [WIDTH:0]   sum,
    output logic             output_valid
);

    localparam int USED_STAGES = (STAGES < 1) ? 1 : ((STAGES > WIDTH) ? WIDTH : STAGES);

    function automatic int f_stage_chunk_width(input int stage_idx);
        int base_w;
        int rem_w;
        base_w = WIDTH / USED_STAGES;
        rem_w  = WIDTH % USED_STAGES;
        return base_w + ((stage_idx < rem_w) ? 1 : 0);
    endfunction

    function automatic int f_stage_chunk_lsb(input int stage_idx);
        int base_w;
        int rem_w;
        int extra;
        base_w = WIDTH / USED_STAGES;
        rem_w  = WIDTH % USED_STAGES;
        extra  = (stage_idx < rem_w) ? stage_idx : rem_w;
        return stage_idx * base_w + extra;
    endfunction

    generate
        if (STAGES <= 0) begin: l_comb
            assign sum = {1'b0, add_a} + {1'b0, add_b};
            assign output_valid = inputs_valid;
        end else begin: l_pipe
            logic [WIDTH-1:0] a_pipe     [0:USED_STAGES-1];
            logic [WIDTH-1:0] b_pipe     [0:USED_STAGES-1];
            logic [WIDTH-1:0] partial_sum[0:USED_STAGES-1];
            logic             carry_pipe [0:USED_STAGES-1];
            logic             valid_pipe [0:USED_STAGES-1];

            for (genvar gs = 0; gs < USED_STAGES; gs++) begin: l_stage
                localparam int CHUNK_W = f_stage_chunk_width(gs);
                localparam int CHUNK_L = f_stage_chunk_lsb(gs);
                localparam int CHUNK_H = CHUNK_L + CHUNK_W - 1;

                logic [CHUNK_W:0] chunk_add;
                logic [WIDTH-1:0] sum_next;

                always_comb begin
                    if (gs == 0) begin
                        chunk_add = {1'b0, add_a[CHUNK_H:CHUNK_L]} + {1'b0, add_b[CHUNK_H:CHUNK_L]};
                        sum_next  = '0;
                        sum_next[CHUNK_H:CHUNK_L] = chunk_add[CHUNK_W-1:0];
                    end else begin
                        chunk_add = {1'b0, a_pipe[gs-1][CHUNK_H:CHUNK_L]} +
                                    {1'b0, b_pipe[gs-1][CHUNK_H:CHUNK_L]} +
                                    carry_pipe[gs-1];
                        sum_next = partial_sum[gs-1];
                        sum_next[CHUNK_H:CHUNK_L] = chunk_add[CHUNK_W-1:0];
                    end
                end

                always_ff @(posedge clk) begin
                    if (!resetn) begin
                        valid_pipe[gs] <= 1'b0;
                        a_pipe[gs] <= '0;
                        b_pipe[gs] <= '0;
                        partial_sum[gs] <= '0;
                        carry_pipe[gs] <= 1'b0;
                    end else begin
                        if (gs == 0) begin
                            valid_pipe[gs] <= inputs_valid;
                            a_pipe[gs] <= add_a;
                            b_pipe[gs] <= add_b;
                            partial_sum[gs] <= sum_next;
                            carry_pipe[gs] <= chunk_add[CHUNK_W];
                        end else begin
                            valid_pipe[gs] <= valid_pipe[gs-1];
                            a_pipe[gs] <= a_pipe[gs-1];
                            b_pipe[gs] <= b_pipe[gs-1];
                            partial_sum[gs] <= sum_next;
                            carry_pipe[gs] <= chunk_add[CHUNK_W];
                        end
                    end
                end
            end

            assign sum = {carry_pipe[USED_STAGES-1], partial_sum[USED_STAGES-1]};
            assign output_valid = valid_pipe[USED_STAGES-1];
        end
    endgenerate

endmodule

// AXIS-style ready/valid wrapper for the pipelined adder core.
module pipelined_adder_axis #(
    parameter int WIDTH = 16,
    parameter int STAGES = 1
) (
    input  logic             clk,
    input  logic             resetn,
    input  logic [WIDTH-1:0] add_a,
    input  logic [WIDTH-1:0] add_b,
    input  logic             s_valid,
    output logic             s_ready,
    output logic [WIDTH:0]   sum,
    output logic             m_valid,
    input  logic             m_ready
);

    localparam int USED_STAGES = (STAGES < 1) ? 1 : ((STAGES > WIDTH) ? WIDTH : STAGES);

    typedef struct packed {
        logic [WIDTH-1:0] a;
        logic [WIDTH-1:0] b;
        logic [WIDTH-1:0] partial_sum;
        logic             carry;
    } stage_payload_t;

    function automatic int f_stage_chunk_width(input int stage_idx);
        int base_w;
        int rem_w;
        base_w = WIDTH / USED_STAGES;
        rem_w  = WIDTH % USED_STAGES;
        return base_w + ((stage_idx < rem_w) ? 1 : 0);
    endfunction

    function automatic int f_stage_chunk_lsb(input int stage_idx);
        int base_w;
        int rem_w;
        int extra;
        base_w = WIDTH / USED_STAGES;
        rem_w  = WIDTH % USED_STAGES;
        extra  = (stage_idx < rem_w) ? stage_idx : rem_w;
        return stage_idx * base_w + extra;
    endfunction

    generate
        if (STAGES <= 0) begin : g_comb
            assign s_ready = m_ready;
            assign sum     = {1'b0, add_a} + {1'b0, add_b};
            assign m_valid = s_valid;
        end else begin : g_pipe
            stage_payload_t stage_data [0:USED_STAGES-1];
            stage_payload_t stage_next [0:USED_STAGES-1];
            logic           stage_valid[0:USED_STAGES-1];
            logic           stage_ready[0:USED_STAGES-1];

            for (genvar gs = 0; gs < USED_STAGES; gs++) begin : g_stage
                localparam int CHUNK_W = f_stage_chunk_width(gs);
                localparam int CHUNK_L = f_stage_chunk_lsb(gs);
                localparam int CHUNK_H = CHUNK_L + CHUNK_W - 1;

                logic [CHUNK_W:0] chunk_add;
                stage_payload_t   payload_in;

                always_comb begin
                    payload_in = '0;
                    if (gs == 0) begin
                        payload_in.a = add_a;
                        payload_in.b = add_b;
                    end else begin
                        payload_in = stage_data[gs-1];
                    end

                    if (gs == 0) begin
                        chunk_add = {1'b0, add_a[CHUNK_H:CHUNK_L]} + {1'b0, add_b[CHUNK_H:CHUNK_L]};
                    end else begin
                        chunk_add = {1'b0, payload_in.a[CHUNK_H:CHUNK_L]} +
                                    {1'b0, payload_in.b[CHUNK_H:CHUNK_L]} +
                                    payload_in.carry;
                    end

                    stage_next[gs] = payload_in;
                    if (gs == 0) begin
                        stage_next[gs].partial_sum = '0;
                    end
                    stage_next[gs].partial_sum[CHUNK_H:CHUNK_L] = chunk_add[CHUNK_W-1:0];
                    stage_next[gs].carry = chunk_add[CHUNK_W];
                end

                register_slice #(
                    .T(stage_payload_t)
                ) u_reg (
                    .clk       (clk),
                    .resetn    (resetn),
                    .push_valid(gs == 0 ? s_valid : stage_valid[gs-1]),
                    .push_data (stage_next[gs]),
                    .push_ready(stage_ready[gs]),
                    .pop_valid (stage_valid[gs]),
                    .pop_data  (stage_data[gs]),
                    .pop_ready (gs == USED_STAGES - 1 ? m_ready : stage_ready[gs+1])
                );
            end

            assign s_ready = stage_ready[0];
            assign sum     = {stage_data[USED_STAGES-1].carry, stage_data[USED_STAGES-1].partial_sum};
            assign m_valid = stage_valid[USED_STAGES-1];
        end
    endgenerate

endmodule

`endif
