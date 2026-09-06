`ifndef ADDER_TREE_OC_BINARY_LEVEL_SV
`define ADDER_TREE_OC_BINARY_LEVEL_SV

// One binary tree level: pairwise one's-complement add (W_IN must be even, >= 2).
module oc_adder_tree_binary_level #(
    parameter int W_IN = 32,
    parameter int SUM_WIDTH = 16,
    parameter bit ADDER_SPLIT_SUM_STAGES = 1'b0,
    parameter int ADD_STAGES_PER_ADDITION = 1
) (
    input  logic clk,
    input  logic resetn,
    input  logic in_valid,
    input  logic [SUM_WIDTH-1:0] in_word[W_IN],
    output logic out_valid,
    output logic [SUM_WIDTH-1:0] out_word[W_IN / 2]
);
    typedef logic [SUM_WIDTH-1:0] sum_t;
    logic add_out_valid[W_IN / 2];

    genvar gj;
    generate
        for (gj = 0; gj < W_IN / 2; gj++) begin : g_pair
            pipelined_oc_adder #(
                .T(sum_t),
                .SPLIT_SUM_STAGES(ADDER_SPLIT_SUM_STAGES),
                .ADD_STAGES_PER_ADDITION(ADD_STAGES_PER_ADDITION)
            ) u_oc_add (
                .clk          (clk),
                .resetn       (resetn),
                .add_a        (in_word[2 * gj]),
                .add_b        (in_word[2 * gj + 1]),
                .inputs_valid (in_valid),
                .output_valid (add_out_valid[gj]),
                .sum          (out_word[gj])
            );
        end
    endgenerate

    assign out_valid = add_out_valid[0];
endmodule

`endif
