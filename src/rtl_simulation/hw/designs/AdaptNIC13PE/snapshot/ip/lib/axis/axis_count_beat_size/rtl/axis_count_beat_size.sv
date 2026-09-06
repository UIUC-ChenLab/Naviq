// Counts valid bytes in one AXI-Stream beat.
//
// The count is based only on tkeep population count. No byte ordering or
// contiguity is assumed. The datapath has three registered stages: four local
// sub-counts, two pair sums, then the final total.

`include "ifc_axis.sv"

module axis_count_beat_size #(
    parameter int DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int SUBPROBLEM_COUNT = 4;
    localparam int KEEP_WIDTH       = DATA_WIDTH / 8;
    localparam int SUB_KEEP_WIDTH   = KEEP_WIDTH / SUBPROBLEM_COUNT;
    localparam int COUNT_WIDTH      = $clog2(DATA_WIDTH);
    localparam int SUB_COUNT_WIDTH  = $clog2(SUB_KEEP_WIDTH + 1);
    localparam int PAIR_COUNT_WIDTH = $clog2((2 * SUB_KEEP_WIDTH) + 1);
    localparam int BYTE_COUNT_WIDTH = $clog2(KEEP_WIDTH + 1);

    typedef logic [SUB_KEEP_WIDTH-1:0]   sub_keep_t;
    typedef logic [SUB_COUNT_WIDTH-1:0]  sub_count_t;
    typedef logic [PAIR_COUNT_WIDTH-1:0] pair_count_t;
    typedef logic [BYTE_COUNT_WIDTH-1:0] byte_count_t;

    initial begin
        if ((DATA_WIDTH % 8) != 0)
            $error("axis_count_beat_size: DATA_WIDTH (%0d) must be a multiple of 8", DATA_WIDTH);
        if ((KEEP_WIDTH % SUBPROBLEM_COUNT) != 0)
            $error("axis_count_beat_size: DATA_WIDTH (%0d) must divide into four byte-aligned groups", DATA_WIDTH);
        if ($bits(s_axis.t.data) != DATA_WIDTH)
            $error("axis_count_beat_size: s_axis data width must match DATA_WIDTH");
        if ($bits(m_axis.t.data) != COUNT_WIDTH)
            $error("axis_count_beat_size: m_axis data width must be clog2(DATA_WIDTH)");
    end

    function automatic sub_count_t count_sub_keep(input sub_keep_t keep);
        sub_count_t count;
        begin
            count = '0;
            for (int i = 0; i < SUB_KEEP_WIDTH; i++)
                count = sub_count_t'(count + sub_count_t'(keep[i]));
            return count;
        end
    endfunction

    logic       stage1_valid_r;
    sub_count_t stage1_count_r [SUBPROBLEM_COUNT];
    logic       stage1_last_r;

    logic        stage2_valid_r;
    pair_count_t stage2_sum_01_r;
    pair_count_t stage2_sum_23_r;
    logic        stage2_last_r;

    logic                   stage3_valid_r;
    logic [COUNT_WIDTH-1:0] stage3_count_r;
    logic                   stage3_last_r;

    logic stage3_ready;
    logic stage2_ready;
    logic stage1_ready;

    pair_count_t sum_01;
    pair_count_t sum_23;
    byte_count_t total_count;

    assign stage3_ready = !stage3_valid_r || m_axis.tready;
    assign stage2_ready = !stage2_valid_r || stage3_ready;
    assign stage1_ready = !stage1_valid_r || stage2_ready;
    assign s_axis.tready = resetn && stage1_ready;

    assign sum_01 = pair_count_t'(stage1_count_r[0]) + pair_count_t'(stage1_count_r[1]);
    assign sum_23 = pair_count_t'(stage1_count_r[2]) + pair_count_t'(stage1_count_r[3]);
    assign total_count = byte_count_t'(stage2_sum_01_r) + byte_count_t'(stage2_sum_23_r);

    assign m_axis.tvalid = stage3_valid_r;
    assign m_axis.t.data = stage3_count_r;
    assign m_axis.t.keep = '1;
    assign m_axis.t.id   = '0;
    assign m_axis.t.dest = '0;
    assign m_axis.t.user = '0;
    assign m_axis.t.last = stage3_last_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            stage1_valid_r <= 1'b0;
            stage2_valid_r <= 1'b0;
            stage3_valid_r <= 1'b0;
        end else begin
            if (stage3_ready) begin
                stage3_valid_r <= stage2_valid_r;
                if (stage2_valid_r) begin
                    stage3_count_r <= COUNT_WIDTH'(total_count);
                    stage3_last_r <= stage2_last_r;
                end
            end

            if (stage2_ready) begin
                stage2_valid_r <= stage1_valid_r;
                if (stage1_valid_r) begin
                    stage2_sum_01_r <= sum_01;
                    stage2_sum_23_r <= sum_23;
                    stage2_last_r <= stage1_last_r;
                end
            end

            if (stage1_ready) begin
                stage1_valid_r <= s_axis.tvalid;
                if (s_axis.tvalid) begin
                    for (int g = 0; g < SUBPROBLEM_COUNT; g++) begin
                        stage1_count_r[g] <= count_sub_keep(
                            s_axis.t.keep[g * SUB_KEEP_WIDTH +: SUB_KEEP_WIDTH]
                        );
                    end
                    stage1_last_r <= s_axis.t.last;
                end
            end
        end
    end

endmodule
