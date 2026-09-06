// Combine two AXI-Stream packets into one logical packet by serializing the
// configured primary stream followed by the secondary stream, then delegating
// byte packing to axis_fragment_packer.
//
// Input beats are expected to have lower-contiguous tkeep. Output metadata is
// zeroed; input id, dest, and user are intentionally ignored.

`include "ifc_axis.sv"

module axis_combine_repack #(
    parameter int FIRST_STREAM_IS_A = 1,
    parameter int DATA_WIDTH        = 512,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_a,
    ifc_axis.slave  s_axis_b,
    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int BYTE_CNT_W = $clog2(KEEP_WIDTH + 1);
    localparam int COMBINED_CNT_W = $clog2((2 * KEEP_WIDTH) + 1);
    localparam int MERGE_GROUP_BYTES = (KEEP_WIDTH < 16) ? KEEP_WIDTH : 16;
    localparam int MERGE_FINE_W = (MERGE_GROUP_BYTES <= 1) ? 1 : $clog2(MERGE_GROUP_BYTES);

    typedef enum logic {
        INPUT_PRIMARY,
        INPUT_SECONDARY
    } input_state_t;
    typedef logic [BYTE_CNT_W-1:0] byte_count_t;
    typedef logic [MERGE_FINE_W-1:0] merge_fine_t;

    function automatic logic [KEEP_WIDTH-1:0] keep_from_count(input byte_count_t count);
        keep_from_count = '0;
        for (int i = 0; i < KEEP_WIDTH; i++)
            keep_from_count[i] = (byte_count_t'(i) < count);
    endfunction

    function automatic logic [DATA_WIDTH-1:0] coarse_shift_secondary_data(
        input logic [DATA_WIDTH-1:0] secondary_data,
        input byte_count_t primary_count
    );
        int coarse_count;
        int src_idx;

        coarse_shift_secondary_data = '0;
        coarse_count = (int'(primary_count) / MERGE_GROUP_BYTES) * MERGE_GROUP_BYTES;

        for (int i = 0; i < KEEP_WIDTH; i++) begin
            src_idx = i - coarse_count;
            if ((src_idx >= 0) && (src_idx < KEEP_WIDTH))
                coarse_shift_secondary_data[i * 8 +: 8] = secondary_data[src_idx * 8 +: 8];
        end
    endfunction

    function automatic logic [DATA_WIDTH-1:0] merge_beat_data(
        input logic [DATA_WIDTH-1:0] primary_data,
        input logic [KEEP_WIDTH-1:0] primary_keep,
        input logic [DATA_WIDTH-1:0] secondary_coarse_data,
        input merge_fine_t fine_offset
    );
        int src_idx;

        merge_beat_data = '0;
        for (int i = 0; i < KEEP_WIDTH; i++) begin
            src_idx = i - int'(fine_offset);
            if (primary_keep[i]) begin
                merge_beat_data[i * 8 +: 8] = primary_data[i * 8 +: 8];
            end else if ((src_idx >= 0) && (src_idx < KEEP_WIDTH)) begin
                merge_beat_data[i * 8 +: 8] = secondary_coarse_data[src_idx * 8 +: 8];
            end
        end
    endfunction

    initial begin
        if ((KEEP_WIDTH % MERGE_GROUP_BYTES) != 0)
            $error("axis_combine_repack: DATA_WIDTH (%0d) must have a byte width divisible by %0d", DATA_WIDTH, MERGE_GROUP_BYTES);
    end

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_axis_a_in (clk);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_axis_b_in (clk);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_axis_a_reg (clk);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_axis_b_reg (clk);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_packer_in (clk);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_packer_out (clk);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_axis_out (clk);

    input_state_t input_state_r;

    logic axis_a_valid;
    logic axis_a_ready;
    logic [DATA_WIDTH-1:0] axis_a_data;
    logic [KEEP_WIDTH-1:0] axis_a_keep;
    logic axis_a_last;
    byte_count_t axis_a_count;

    logic axis_b_valid;
    logic axis_b_ready;
    logic [DATA_WIDTH-1:0] axis_b_data;
    logic [KEEP_WIDTH-1:0] axis_b_keep;
    logic axis_b_last;
    byte_count_t axis_b_count;

    logic primary_valid;
    logic primary_ready;
    logic [DATA_WIDTH-1:0] primary_data;
    logic [KEEP_WIDTH-1:0] primary_keep;
    logic primary_last;
    byte_count_t primary_count;

    logic secondary_valid;
    logic secondary_ready;
    logic [DATA_WIDTH-1:0] secondary_data;
    logic [KEEP_WIDTH-1:0] secondary_keep;
    logic secondary_last;
    byte_count_t secondary_count;

    logic [COMBINED_CNT_W-1:0] combined_count;

    logic op_valid_r;
    logic op_ready;
    logic op_issue_fire;
    logic op_is_secondary_r;
    logic op_has_secondary_r;
    logic op_merge_r;
    logic [DATA_WIDTH-1:0] op_primary_data_r;
    logic [KEEP_WIDTH-1:0] op_primary_keep_r;
    logic [DATA_WIDTH-1:0] op_secondary_data_r;
    logic [KEEP_WIDTH-1:0] op_secondary_keep_r;
    logic op_secondary_last_r;
    logic [COMBINED_CNT_W-1:0] op_combined_count_r;
    logic [DATA_WIDTH-1:0] op_secondary_coarse_data_r;
    merge_fine_t op_merge_fine_offset_r;

    logic pending_secondary_valid_r;
    logic [DATA_WIDTH-1:0] pending_secondary_data_r;
    logic [KEEP_WIDTH-1:0] pending_secondary_keep_r;
    logic pending_secondary_last_r;
    logic pending_issue_fire;

    logic primary_fire;
    logic secondary_fire;
    logic capture_primary_only;
    logic capture_boundary;
    logic capture_secondary_only;
    logic merge_boundary;
    logic issue_valid_r;
    logic [DATA_WIDTH-1:0] issue_data_r;
    logic [KEEP_WIDTH-1:0] issue_keep_r;
    logic issue_last_r;
    logic issue_ready;
    logic issue_accept;

    assign u_axis_a_in.t.data = s_axis_a.t.data;
    assign u_axis_a_in.t.keep = s_axis_a.t.keep;
    assign u_axis_a_in.t.id = '0;
    assign u_axis_a_in.t.dest = '0;
    assign u_axis_a_in.t.user = '0;
    assign u_axis_a_in.t.last = s_axis_a.t.last;
    assign u_axis_a_in.tvalid = s_axis_a.tvalid;
    assign s_axis_a.tready = u_axis_a_in.tready;

    assign u_axis_b_in.t.data = s_axis_b.t.data;
    assign u_axis_b_in.t.keep = s_axis_b.t.keep;
    assign u_axis_b_in.t.id = '0;
    assign u_axis_b_in.t.dest = '0;
    assign u_axis_b_in.t.user = '0;
    assign u_axis_b_in.t.last = s_axis_b.t.last;
    assign u_axis_b_in.tvalid = s_axis_b.tvalid;
    assign s_axis_b.tready = u_axis_b_in.tready;

    assign m_axis.t.data = u_axis_out.t.data;
    assign m_axis.t.keep = u_axis_out.t.keep;
    assign m_axis.t.id = '0;
    assign m_axis.t.dest = '0;
    assign m_axis.t.user = '0;
    assign m_axis.t.last = u_axis_out.t.last;
    assign m_axis.tvalid = u_axis_out.tvalid;
    assign u_axis_out.tready = m_axis.tready;

    axis_fifo #(
        .DEPTH            (4),
        .USE_BRAM         (1'b0),
        .EXTRA_OUTPUT_REG (1'b1),
        .MODE             ("CONSERVATIVE")
    ) u_input_a_reg (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_axis_a_in.slave),
        .m_axis (u_axis_a_reg.master)
    );

    axis_fifo #(
        .DEPTH            (4),
        .USE_BRAM         (1'b0),
        .EXTRA_OUTPUT_REG (1'b1),
        .MODE             ("CONSERVATIVE")
    ) u_input_b_reg (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_axis_b_in.slave),
        .m_axis (u_axis_b_reg.master)
    );

    axis_combine_repack_counted_beat_stage #(
        .DATA_WIDTH (DATA_WIDTH)
    ) u_axis_a_counted_stage (
        .clk       (clk),
        .resetn    (resetn),
        .s_axis    (u_axis_a_reg.slave),
        .out_valid (axis_a_valid),
        .out_data  (axis_a_data),
        .out_keep  (axis_a_keep),
        .out_last  (axis_a_last),
        .out_count (axis_a_count),
        .out_ready (axis_a_ready)
    );

    axis_combine_repack_counted_beat_stage #(
        .DATA_WIDTH (DATA_WIDTH)
    ) u_axis_b_counted_stage (
        .clk       (clk),
        .resetn    (resetn),
        .s_axis    (u_axis_b_reg.slave),
        .out_valid (axis_b_valid),
        .out_data  (axis_b_data),
        .out_keep  (axis_b_keep),
        .out_last  (axis_b_last),
        .out_count (axis_b_count),
        .out_ready (axis_b_ready)
    );

    generate
        if (FIRST_STREAM_IS_A != 0) begin : gen_a_primary
            assign primary_valid = axis_a_valid;
            assign primary_data = axis_a_data;
            assign primary_keep = axis_a_keep;
            assign primary_last = axis_a_last;
            assign primary_count = axis_a_count;
            assign axis_a_ready = primary_ready;

            assign secondary_valid = axis_b_valid;
            assign secondary_data = axis_b_data;
            assign secondary_keep = axis_b_keep;
            assign secondary_last = axis_b_last;
            assign secondary_count = axis_b_count;
            assign axis_b_ready = secondary_ready;
        end else begin : gen_b_primary
            assign primary_valid = axis_b_valid;
            assign primary_data = axis_b_data;
            assign primary_keep = axis_b_keep;
            assign primary_last = axis_b_last;
            assign primary_count = axis_b_count;
            assign axis_b_ready = primary_ready;

            assign secondary_valid = axis_a_valid;
            assign secondary_data = axis_a_data;
            assign secondary_keep = axis_a_keep;
            assign secondary_last = axis_a_last;
            assign secondary_count = axis_a_count;
            assign axis_a_ready = secondary_ready;
        end
    endgenerate

    assign combined_count = COMBINED_CNT_W'(primary_count) + COMBINED_CNT_W'(secondary_count);

    assign issue_ready = !issue_valid_r || u_packer_in.tready;
    assign pending_issue_fire = pending_secondary_valid_r && issue_ready;
    assign op_issue_fire = op_valid_r && !pending_secondary_valid_r && issue_ready;
    assign op_ready = !op_valid_r || op_issue_fire;
    assign issue_accept = (pending_secondary_valid_r || op_valid_r) && issue_ready;

    assign primary_ready = (input_state_r == INPUT_PRIMARY)
                         && op_ready
                         && (!primary_valid || !primary_last || secondary_valid);
    assign secondary_ready = op_ready
                           && (((input_state_r == INPUT_PRIMARY) && primary_valid && primary_last)
                            || (input_state_r == INPUT_SECONDARY));

    assign primary_fire = primary_valid && primary_ready;
    assign secondary_fire = secondary_valid && secondary_ready;
    assign capture_primary_only = (input_state_r == INPUT_PRIMARY) && primary_fire && !primary_last;
    assign capture_boundary = (input_state_r == INPUT_PRIMARY) && primary_fire && primary_last && secondary_fire;
    assign capture_secondary_only = (input_state_r == INPUT_SECONDARY) && secondary_fire;
    assign merge_boundary = op_issue_fire && op_merge_r;
    assign u_packer_in.tvalid = issue_valid_r;
    assign u_packer_in.t.data = issue_data_r;
    assign u_packer_in.t.keep = issue_keep_r;
    assign u_packer_in.t.id = '0;
    assign u_packer_in.t.dest = '0;
    assign u_packer_in.t.user = '0;
    assign u_packer_in.t.last = issue_last_r;

    axis_fragment_packer #(
        .DATA_WIDTH  (DATA_WIDTH),
        .PAGE_COUNT  (FRAGMENT_PACKER_PAGE_COUNT),
        .FIFO_MODE   ("CONSERVATIVE")
    ) u_fragment_packer (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_packer_in.slave),
        .m_axis (u_packer_out.master)
    );

    axis_fifo #(
        .DEPTH            (4),
        .USE_BRAM         (1'b0),
        .EXTRA_OUTPUT_REG (1'b0),
        .MODE             ("CONSERVATIVE")
    ) u_output_reg (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_packer_out.slave),
        .m_axis (u_axis_out.master)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            input_state_r <= INPUT_PRIMARY;
            op_valid_r <= 1'b0;
            pending_secondary_valid_r <= 1'b0;
            issue_valid_r <= 1'b0;
        end else begin
            if (issue_ready) begin
                issue_valid_r <= issue_accept;
                if (pending_secondary_valid_r) begin
                    issue_data_r <= pending_secondary_data_r;
                    issue_keep_r <= pending_secondary_keep_r;
                    issue_last_r <= pending_secondary_last_r;
                end else if (op_valid_r) begin
                    if (op_is_secondary_r) begin
                        issue_data_r <= op_secondary_data_r;
                        issue_keep_r <= op_secondary_keep_r;
                        issue_last_r <= op_secondary_last_r;
                    end else if (op_merge_r) begin
                        issue_data_r <= merge_beat_data(
                            op_primary_data_r,
                            op_primary_keep_r,
                            op_secondary_coarse_data_r,
                            op_merge_fine_offset_r
                        );
                        issue_keep_r <= keep_from_count(byte_count_t'(op_combined_count_r));
                        issue_last_r <= op_secondary_last_r;
                    end else begin
                        issue_data_r <= op_primary_data_r;
                        issue_keep_r <= op_primary_keep_r;
                        issue_last_r <= 1'b0;
                    end
                end
            end

            if (pending_issue_fire)
                pending_secondary_valid_r <= 1'b0;

            if (op_issue_fire) begin
                op_valid_r <= 1'b0;
                if (op_has_secondary_r && !op_merge_r) begin
                    pending_secondary_valid_r <= 1'b1;
                    pending_secondary_data_r <= op_secondary_data_r;
                    pending_secondary_keep_r <= op_secondary_keep_r;
                    pending_secondary_last_r <= op_secondary_last_r;
                end
            end

            if (capture_primary_only) begin
                op_valid_r <= 1'b1;
                op_is_secondary_r <= 1'b0;
                op_has_secondary_r <= 1'b0;
                op_merge_r <= 1'b0;
                op_primary_data_r <= primary_data;
                op_primary_keep_r <= primary_keep;
            end

            if (capture_boundary) begin
                op_valid_r <= 1'b1;
                op_is_secondary_r <= 1'b0;
                op_has_secondary_r <= 1'b1;
                op_merge_r <= (combined_count <= COMBINED_CNT_W'(KEEP_WIDTH));
                op_primary_data_r <= primary_data;
                op_primary_keep_r <= primary_keep;
                op_secondary_data_r <= secondary_data;
                op_secondary_keep_r <= secondary_keep;
                op_secondary_last_r <= secondary_last;
                op_combined_count_r <= combined_count;
                op_secondary_coarse_data_r <= coarse_shift_secondary_data(
                    secondary_data,
                    primary_count
                );
                op_merge_fine_offset_r <= merge_fine_t'(primary_count[MERGE_FINE_W-1:0]);
                input_state_r <= secondary_last ? INPUT_PRIMARY : INPUT_SECONDARY;
            end else if (capture_secondary_only) begin
                op_valid_r <= 1'b1;
                op_is_secondary_r <= 1'b1;
                op_has_secondary_r <= 1'b0;
                op_merge_r <= 1'b0;
                op_secondary_data_r <= secondary_data;
                op_secondary_keep_r <= secondary_keep;
                op_secondary_last_r <= secondary_last;
                if (secondary_last)
                    input_state_r <= INPUT_PRIMARY;
            end
        end
    end

endmodule


module axis_combine_repack_counted_beat_stage #(
    parameter int DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave s_axis,

    output logic                  out_valid,
    output logic [DATA_WIDTH-1:0] out_data,
    output logic [KEEP_WIDTH-1:0] out_keep,
    output logic                  out_last,
    output logic [BYTE_CNT_W-1:0] out_count,
    input  logic                  out_ready
);

    localparam int SUBPROBLEM_COUNT = 4;
    localparam int KEEP_WIDTH       = DATA_WIDTH / 8;
    localparam int SUB_KEEP_WIDTH   = KEEP_WIDTH / SUBPROBLEM_COUNT;
    localparam int BYTE_CNT_W       = $clog2(KEEP_WIDTH + 1);
    localparam int SUB_COUNT_W      = $clog2(SUB_KEEP_WIDTH + 1);
    localparam int PAIR_COUNT_W     = $clog2((2 * SUB_KEEP_WIDTH) + 1);

    typedef logic [SUB_KEEP_WIDTH-1:0] sub_keep_t;
    typedef logic [SUB_COUNT_W-1:0]    sub_count_t;
    typedef logic [PAIR_COUNT_W-1:0]   pair_count_t;
    typedef logic [BYTE_CNT_W-1:0]     byte_count_t;

    function automatic sub_count_t count_sub_keep(input sub_keep_t keep);
        sub_count_t count;
        begin
            count = '0;
            for (int i = 0; i < SUB_KEEP_WIDTH; i++)
                count = sub_count_t'(count + sub_count_t'(keep[i]));
            return count;
        end
    endfunction

    logic stage1_valid_r;
    logic [DATA_WIDTH-1:0] stage1_data_r;
    logic [KEEP_WIDTH-1:0] stage1_keep_r;
    logic stage1_last_r;
    sub_count_t stage1_count_r [SUBPROBLEM_COUNT];

    logic stage2_valid_r;
    logic [DATA_WIDTH-1:0] stage2_data_r;
    logic [KEEP_WIDTH-1:0] stage2_keep_r;
    logic stage2_last_r;
    pair_count_t stage2_sum_01_r;
    pair_count_t stage2_sum_23_r;

    logic stage3_valid_r;
    logic [DATA_WIDTH-1:0] stage3_data_r;
    logic [KEEP_WIDTH-1:0] stage3_keep_r;
    logic stage3_last_r;
    byte_count_t stage3_count_r;

    logic stage3_ready;
    logic stage2_ready;
    logic stage1_ready;

    pair_count_t sum_01;
    pair_count_t sum_23;
    byte_count_t total_count;

    initial begin
        if ((DATA_WIDTH % 8) != 0)
            $error("axis_combine_repack_counted_beat_stage: DATA_WIDTH (%0d) must be a multiple of 8", DATA_WIDTH);
        if ((KEEP_WIDTH % SUBPROBLEM_COUNT) != 0)
            $error("axis_combine_repack_counted_beat_stage: DATA_WIDTH (%0d) must divide into four byte groups", DATA_WIDTH);
    end

    assign stage3_ready = !stage3_valid_r || out_ready;
    assign stage2_ready = !stage2_valid_r || stage3_ready;
    assign stage1_ready = !stage1_valid_r || stage2_ready;
    assign s_axis.tready = resetn && stage1_ready;

    assign sum_01 = pair_count_t'(stage1_count_r[0]) + pair_count_t'(stage1_count_r[1]);
    assign sum_23 = pair_count_t'(stage1_count_r[2]) + pair_count_t'(stage1_count_r[3]);
    assign total_count = byte_count_t'(stage2_sum_01_r) + byte_count_t'(stage2_sum_23_r);

    assign out_valid = stage3_valid_r;
    assign out_data = stage3_data_r;
    assign out_keep = stage3_keep_r;
    assign out_last = stage3_last_r;
    assign out_count = stage3_count_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            stage1_valid_r <= 1'b0;
            stage2_valid_r <= 1'b0;
            stage3_valid_r <= 1'b0;
        end else begin
            if (stage3_ready) begin
                stage3_valid_r <= stage2_valid_r;
                if (stage2_valid_r) begin
                    stage3_data_r <= stage2_data_r;
                    stage3_keep_r <= stage2_keep_r;
                    stage3_last_r <= stage2_last_r;
                    stage3_count_r <= total_count;
                end
            end

            if (stage2_ready) begin
                stage2_valid_r <= stage1_valid_r;
                if (stage1_valid_r) begin
                    stage2_data_r <= stage1_data_r;
                    stage2_keep_r <= stage1_keep_r;
                    stage2_last_r <= stage1_last_r;
                    stage2_sum_01_r <= sum_01;
                    stage2_sum_23_r <= sum_23;
                end
            end

            if (stage1_ready) begin
                stage1_valid_r <= s_axis.tvalid;
                if (s_axis.tvalid) begin
                    stage1_data_r <= s_axis.t.data;
                    stage1_keep_r <= s_axis.t.keep;
                    stage1_last_r <= s_axis.t.last;
                    for (int g = 0; g < SUBPROBLEM_COUNT; g++) begin
                        stage1_count_r[g] <= count_sub_keep(
                            s_axis.t.keep[g * SUB_KEEP_WIDTH +: SUB_KEEP_WIDTH]
                        );
                    end
                end
            end
        end
    end

endmodule
