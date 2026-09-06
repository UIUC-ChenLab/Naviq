`ifndef ADDER_TREE_OC_TREE_SEGMENT_SV
`define ADDER_TREE_OC_TREE_SEGMENT_SV

// One pipeline segment of the AXIS adder tree (partial tree depth per segment).
module oc_adder_tree_segment #(
    parameter int PADDED_LEAVES = 32,
    parameter int TREE_DEPTH_USED = 5,
    parameter int SEG_INDEX = 0,
    parameter int SUM_WIDTH = 16,
    parameter bit ADDER_SPLIT_SUM_STAGES = 1'b0,
    parameter int ADD_STAGES_PER_ADDITION = 1
) (
    input  logic clk,
    input  logic resetn,
    input  logic in_valid,
    input  logic [SUM_WIDTH-1:0] in_word[PADDED_LEAVES],
    output logic out_valid,
    output logic [SUM_WIDTH-1:0] out_word[PADDED_LEAVES]
);

    typedef logic [SUM_WIDTH-1:0] sum_t;

    localparam int start_level = SEG_INDEX;
    localparam int rem_levels  = TREE_DEPTH_USED - start_level;
    localparam int LVLS = (rem_levels <= 0) ? 0 :
        ((rem_levels < 1) ? rem_levels : 1);
    localparam int NUM_IN  = PADDED_LEAVES >> start_level;
    localparam int NUM_OUT = (LVLS == 0) ? NUM_IN : (NUM_IN >> LVLS);

    sum_t reduced[0:PADDED_LEAVES - 1];

    genvar gj;
    generate
        if (LVLS > 0) begin : g_tree
            sum_t lv0[0:NUM_IN - 1];

            for (gj = 0; gj < NUM_IN; gj++) begin : g_lv_init
                assign lv0[gj] = in_word[gj];
            end

            oc_adder_tree_reduce #(
                .W_IN                   (NUM_IN),
                .LVLS                   (LVLS),
                .SUM_WIDTH              (SUM_WIDTH),
                .ADDER_SPLIT_SUM_STAGES (ADDER_SPLIT_SUM_STAGES),
                .ADD_STAGES_PER_ADDITION(ADD_STAGES_PER_ADDITION)
            ) u_red (
                .clk      (clk),
                .resetn   (resetn),
                .in_valid (in_valid),
                .in_word  (lv0),
                .out_valid(out_valid),
                .out_word (reduced[0:NUM_OUT - 1])
            );
        end else begin : g_pass_valid
            assign out_valid = in_valid;
        end
    endgenerate

    integer jx;
    always_comb begin
        for (jx = 0; jx < PADDED_LEAVES; jx++) begin
            out_word[jx] = sum_t'('0);
        end
        if (LVLS > 0) begin
            for (jx = 0; jx < NUM_OUT; jx++) begin
                out_word[jx] = reduced[jx];
            end
        end else begin
            for (jx = 0; jx < NUM_IN; jx++) begin
                out_word[jx] = in_word[jx];
            end
        end
    end

endmodule

`endif
