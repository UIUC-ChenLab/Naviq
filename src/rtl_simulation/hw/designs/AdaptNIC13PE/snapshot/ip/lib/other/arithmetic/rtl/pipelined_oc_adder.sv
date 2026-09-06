module pipelined_oc_adder #(
    parameter type T = logic [15:0],
    parameter bit SPLIT_SUM_STAGES = 1'b0,
    parameter int ADD_STAGES_PER_ADDITION = 1
) (
    input logic clk,
    input logic resetn,
    input T add_a,
    input T add_b,
    input logic inputs_valid,
    output logic output_valid,
    output T sum
);

    localparam int W = $bits(T);
    logic [W:0] sum_with_carry;
    logic [W-1:0] sum_stage;
    logic add_ab_valid;
    logic [W-1:0] carry_ext;
    logic [W:0] folded_sum_raw;
    logic fold_valid;

    assign carry_ext = {{(W - 1) {1'b0}}, sum_with_carry[W]};

    generate
        if (SPLIT_SUM_STAGES) begin: l_split_sum
            pipelined_adder #(
                .WIDTH (W),
                .STAGES(ADD_STAGES_PER_ADDITION)
            ) u_add_ab (
                .clk         (clk),
                .resetn      (resetn),
                .add_a       (add_a),
                .add_b       (add_b),
                .inputs_valid(inputs_valid),
                .sum         (sum_with_carry),
                .output_valid(add_ab_valid)
            );

            pipelined_adder #(
                .WIDTH (W),
                .STAGES(ADD_STAGES_PER_ADDITION)
            ) u_fold_carry (
                .clk         (clk),
                .resetn      (resetn),
                .add_a       (sum_with_carry[W-1:0]),
                .add_b       (carry_ext),
                .inputs_valid(add_ab_valid),
                .sum         (folded_sum_raw),
                .output_valid(fold_valid)
            );

            assign sum_stage = folded_sum_raw[W-1:0];
            assign output_valid = fold_valid;
        end else begin: l_direct_sum
            pipelined_adder #(
                .WIDTH (W),
                .STAGES(ADD_STAGES_PER_ADDITION)
            ) u_add_ab_direct (
                .clk         (clk),
                .resetn      (resetn),
                .add_a       (add_a),
                .add_b       (add_b),
                .inputs_valid(inputs_valid),
                .sum         (sum_with_carry),
                .output_valid(add_ab_valid)
            );

            assign sum_stage = sum_with_carry[W-1:0] + sum_with_carry[W];
            assign output_valid = add_ab_valid;
        end
    endgenerate

    assign sum = T'(sum_stage);

endmodule

module pipelined_oc_adder_axis #(
    parameter type T = logic [15:0],
    parameter bit SPLIT_SUM_STAGES = 1'b0,
    parameter int ADD_STAGES_PER_ADDITION = 1
) (
    input  logic clk,
    input  logic resetn,
    input  T     add_a,
    input  T     add_b,
    input  logic s_valid,
    output logic s_ready,
    output logic m_valid,
    input  logic m_ready,
    output T     sum
);

    localparam int W = $bits(T);

    logic [W:0] sum_with_carry;
    logic [W-1:0] carry_ext;
    logic [W:0] folded_sum_raw;
    logic add_ab_valid;
    logic add_ab_ready;
    logic fold_valid;

    assign carry_ext = {{(W - 1) {1'b0}}, sum_with_carry[W]};

    generate
        if (SPLIT_SUM_STAGES) begin : g_split_sum
            pipelined_adder_axis #(
                .WIDTH (W),
                .STAGES(ADD_STAGES_PER_ADDITION)
            ) u_add_ab (
                .clk    (clk),
                .resetn (resetn),
                .add_a  (add_a),
                .add_b  (add_b),
                .s_valid(s_valid),
                .s_ready(s_ready),
                .sum    (sum_with_carry),
                .m_valid(add_ab_valid),
                .m_ready(add_ab_ready)
            );

            pipelined_adder_axis #(
                .WIDTH (W),
                .STAGES(ADD_STAGES_PER_ADDITION)
            ) u_fold_carry (
                .clk    (clk),
                .resetn (resetn),
                .add_a  (sum_with_carry[W-1:0]),
                .add_b  (carry_ext),
                .s_valid(add_ab_valid),
                .s_ready(add_ab_ready),
                .sum    (folded_sum_raw),
                .m_valid(fold_valid),
                .m_ready(m_ready)
            );

            assign sum     = T'(folded_sum_raw[W-1:0]);
            assign m_valid = fold_valid;
        end else begin : g_direct_sum
            pipelined_adder_axis #(
                .WIDTH (W),
                .STAGES(ADD_STAGES_PER_ADDITION)
            ) u_add_ab_direct (
                .clk    (clk),
                .resetn (resetn),
                .add_a  (add_a),
                .add_b  (add_b),
                .s_valid(s_valid),
                .s_ready(s_ready),
                .sum    (sum_with_carry),
                .m_valid(m_valid),
                .m_ready(m_ready)
            );

            assign sum = T'(sum_with_carry[W-1:0] + sum_with_carry[W]);
        end
    endgenerate

endmodule
