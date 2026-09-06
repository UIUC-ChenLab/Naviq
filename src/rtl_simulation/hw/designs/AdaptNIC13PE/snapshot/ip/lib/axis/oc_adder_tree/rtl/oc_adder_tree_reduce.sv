`ifndef ADDER_TREE_OC_REDUCE_SV
`define ADDER_TREE_OC_REDUCE_SV

// Recursive reduction: LVLS binary levels (feed-forward; 1-D wires per hierarchy).
module oc_adder_tree_reduce #(
    parameter int W_IN = 32,
    parameter int LVLS = 0,
    parameter int SUM_WIDTH = 16,
    parameter bit ADDER_SPLIT_SUM_STAGES = 1'b0,
    parameter int ADD_STAGES_PER_ADDITION = 1
) (
    input  logic clk,
    input  logic resetn,
    input  logic in_valid,
    input  logic [SUM_WIDTH-1:0] in_word[W_IN],
    output logic out_valid,
    output logic [SUM_WIDTH-1:0] out_word[W_IN >> LVLS]
);
    typedef logic [SUM_WIDTH-1:0] sum_t;

    generate
        if (LVLS == 0) begin : g_pass
            genvar ji;
            for (ji = 0; ji < W_IN; ji++) begin : g_cp
                assign out_word[ji] = in_word[ji];
            end
            assign out_valid = in_valid;
        end else begin : g_red
            localparam int W_mid = W_IN / 2;
            sum_t mid[0:W_mid - 1];
            logic mid_valid;

            oc_adder_tree_binary_level #(
                .W_IN                   (W_IN),
                .SUM_WIDTH              (SUM_WIDTH),
                .ADDER_SPLIT_SUM_STAGES (ADDER_SPLIT_SUM_STAGES),
                .ADD_STAGES_PER_ADDITION(ADD_STAGES_PER_ADDITION)
            ) u_level (
                .clk      (clk),
                .resetn   (resetn),
                .in_valid (in_valid),
                .in_word  (in_word),
                .out_valid(mid_valid),
                .out_word (mid)
            );

            oc_adder_tree_reduce #(
                .W_IN                   (W_mid),
                .LVLS                   (LVLS - 1),
                .SUM_WIDTH              (SUM_WIDTH),
                .ADDER_SPLIT_SUM_STAGES (ADDER_SPLIT_SUM_STAGES),
                .ADD_STAGES_PER_ADDITION(ADD_STAGES_PER_ADDITION)
            ) u_rec (
                .clk      (clk),
                .resetn   (resetn),
                .in_valid (mid_valid),
                .in_word  (mid),
                .out_valid(out_valid),
                .out_word (out_word)
            );
        end
    endgenerate
endmodule

`endif
