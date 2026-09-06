// Packs dense AXI-Stream byte fragments into full-width packet beats.
//
// Input tkeep is assumed to be lower-contiguous. Output tkeep is lower-contiguous
// and only the final packet beat may be partial. tid/tdest/tuser are 1-bit on internal
// interfaces and are intentionally left undriven (don't care); id/dest are not carried
// through the internal packing pipeline.

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"

module axis_fragment_packer #(
    parameter int DATA_WIDTH  = 512,
    parameter int PAGE_COUNT  = 8,
    parameter int TIMING_FIFO_DEPTH = 4,
    parameter string FIFO_MODE = "CONSERVATIVE"
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    /* verilator inline_module */

    localparam int KEEP_WIDTH  = DATA_WIDTH / 8;
    localparam int PAGE_IDX_W  = (PAGE_COUNT <= 2) ? 1 : $clog2(PAGE_COUNT);
    localparam int BYTE_CNT_W  = $clog2(KEEP_WIDTH + 1);

    localparam int TOKEN_W = DATA_WIDTH + BYTE_CNT_W + 1;
    localparam int DISPATCH_CMD_W = 1 + PAGE_IDX_W + (4 * BYTE_CNT_W) + 2;
    localparam int POOL_REQ_W = DATA_WIDTH + 1 + (4 * BYTE_CNT_W) + 2;
    localparam int POOL_DISPATCH_W = DATA_WIDTH + DISPATCH_CMD_W;
    localparam int TOKEN_AXIS_DATA_W = ((TOKEN_W + 7) / 8) * 8;
    localparam int PAGE_INSERT_W = DATA_WIDTH + KEEP_WIDTH + BYTE_CNT_W + 2;
    localparam int PAGE_INSERT_AXIS_DATA_W = ((PAGE_INSERT_W + 7) / 8) * 8;
    localparam int DISPATCH_INSERT_PIPE_PAGE_L = 0;
    localparam int DISPATCH_INSERT_PIPE_PAYLOAD_L = DISPATCH_INSERT_PIPE_PAGE_L + PAGE_IDX_W;
    localparam int DISPATCH_INSERT_PIPE_W = DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_AXIS_DATA_W;

    localparam int PAGE_INSERT_DATA_L  = 0;
    localparam int PAGE_INSERT_WEN_L   = PAGE_INSERT_DATA_L + DATA_WIDTH;
    localparam int PAGE_INSERT_COUNT_L = PAGE_INSERT_WEN_L + KEEP_WIDTH;
    localparam int PAGE_INSERT_DONE_L  = PAGE_INSERT_COUNT_L + BYTE_CNT_W;
    localparam int PAGE_INSERT_LAST_L  = PAGE_INSERT_DONE_L + 1;

    initial begin
        if ((DATA_WIDTH % 8) != 0)
            $error("axis_fragment_packer: DATA_WIDTH (%0d) must be a multiple of 8", DATA_WIDTH);
        if (PAGE_COUNT < 2)
            $error("axis_fragment_packer: PAGE_COUNT (%0d) must be at least 2", PAGE_COUNT);
        if ((PAGE_COUNT % 2) != 0)
            $error("axis_fragment_packer: PAGE_COUNT (%0d) must be even for two page pools", PAGE_COUNT);
        if (TIMING_FIFO_DEPTH < 2)
            $error("axis_fragment_packer: TIMING_FIFO_DEPTH (%0d) must be at least 2", TIMING_FIFO_DEPTH);
    end

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_in_wide (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_in_axis (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_out_axis (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_out_wide (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (TOKEN_AXIS_DATA_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_token_pre_axis (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (TOKEN_AXIS_DATA_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_token_axis (.axis_aclk(clk));


    logic [TOKEN_W-1:0] token_stage_data;
    logic               token_stage_valid;
    logic               token_stage_ready;

    logic [TOKEN_W-1:0] token_data;
    logic               token_valid;
    logic               token_ready;

    logic [1:0] pool_req_valid;
    logic [1:0] pool_req_ready;
    logic [POOL_REQ_W-1:0] pool_req_data [2];
    logic [1:0] pool_alloc_available;

    logic [1:0] pool_dispatch_valid;
    logic [1:0] pool_dispatch_ready;
    logic [POOL_DISPATCH_W-1:0] pool_dispatch_data [2];

    logic                  dispatch_insert0_valid;
    logic                  dispatch_insert0_ready;
    logic [PAGE_IDX_W-1:0] dispatch_insert0_page;
    logic [DATA_WIDTH-1:0] dispatch_insert0_data;
    logic [KEEP_WIDTH-1:0] dispatch_insert0_wen;
    logic [BYTE_CNT_W-1:0] dispatch_insert0_count;
    logic                  dispatch_insert0_done;
    logic                  dispatch_insert0_last;

    logic                  dispatch_insert0_raw_valid;
    logic                  dispatch_insert0_raw_ready;
    logic [PAGE_IDX_W-1:0] dispatch_insert0_raw_page;
    logic [DATA_WIDTH-1:0] dispatch_insert0_raw_data;
    logic [KEEP_WIDTH-1:0] dispatch_insert0_raw_wen;
    logic [BYTE_CNT_W-1:0] dispatch_insert0_raw_count;
    logic                  dispatch_insert0_raw_done;
    logic                  dispatch_insert0_raw_last;

    logic                  dispatch_insert1_valid;
    logic                  dispatch_insert1_ready;
    logic [PAGE_IDX_W-1:0] dispatch_insert1_page;
    logic [DATA_WIDTH-1:0] dispatch_insert1_data;
    logic [KEEP_WIDTH-1:0] dispatch_insert1_wen;
    logic [BYTE_CNT_W-1:0] dispatch_insert1_count;
    logic                  dispatch_insert1_done;
    logic                  dispatch_insert1_last;

    logic                  dispatch_insert1_raw_valid;
    logic                  dispatch_insert1_raw_ready;
    logic [PAGE_IDX_W-1:0] dispatch_insert1_raw_page;
    logic [DATA_WIDTH-1:0] dispatch_insert1_raw_data;
    logic [KEEP_WIDTH-1:0] dispatch_insert1_raw_wen;
    logic [BYTE_CNT_W-1:0] dispatch_insert1_raw_count;
    logic                  dispatch_insert1_raw_done;
    logic                  dispatch_insert1_raw_last;

    logic [DISPATCH_INSERT_PIPE_W-1:0] dispatch_insert0_raw_pipe_data;
    logic [DISPATCH_INSERT_PIPE_W-1:0] dispatch_insert0_pipe_data;
    logic [DISPATCH_INSERT_PIPE_W-1:0] dispatch_insert1_raw_pipe_data;
    logic [DISPATCH_INSERT_PIPE_W-1:0] dispatch_insert1_pipe_data;

    logic [PAGE_COUNT-1:0]  page_insert_valid;
    logic [PAGE_COUNT-1:0]  page_insert_ready;
    logic [DATA_WIDTH-1:0]  page_insert_data [PAGE_COUNT];
    logic [KEEP_WIDTH-1:0]  page_insert_wen [PAGE_COUNT];
    logic [BYTE_CNT_W-1:0]  page_insert_count [PAGE_COUNT];
    logic                   page_insert_done [PAGE_COUNT];
    logic                   page_insert_last [PAGE_COUNT];

    logic [PAGE_COUNT-1:0]  page_output_valid;
    logic [PAGE_COUNT-1:0]  page_output_ready;
    logic [DATA_WIDTH-1:0]  page_output_data [PAGE_COUNT];
    logic [KEEP_WIDTH-1:0]  page_output_keep [PAGE_COUNT];
    logic                   page_output_last [PAGE_COUNT];

    logic                  output_pop;
    logic [PAGE_IDX_W-1:0] output_page;

    axis_fifo #(
        .DEPTH            (4),
        .USE_BRAM         (1'b0),
        .EXTRA_OUTPUT_REG (1'b0),
        .MODE             ("CONSERVATIVE")
    ) u_input_iso (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis),
        .m_axis (u_in_wide.master)
    );

    assign u_in_axis.tvalid = u_in_wide.tvalid;
    assign u_in_axis.t.data = u_in_wide.t.data;
    assign u_in_axis.t.keep = u_in_wide.t.keep;
    assign u_in_axis.t.last = u_in_wide.t.last;
    assign u_in_wide.tready = u_in_axis.tready;


    axis_fragment_packer_token_stage #(
        .DATA_WIDTH (DATA_WIDTH)
    ) u_token_stage (
        .clk          (clk),
        .resetn       (resetn),
        .s_axis       (u_in_axis.slave),
        .token_valid  (token_stage_valid),
        .token_data   (token_stage_data),
        .token_ready  (token_stage_ready)
    );

    assign u_token_pre_axis.tvalid = token_stage_valid;
    assign u_token_pre_axis.t.data = {{(TOKEN_AXIS_DATA_W - TOKEN_W){1'b0}}, token_stage_data};
    assign u_token_pre_axis.t.keep = '1;
    assign u_token_pre_axis.t.last = 1'b0;
    assign token_stage_ready = u_token_pre_axis.tready;

    axis_fifo #(
        .DEPTH            (TIMING_FIFO_DEPTH),
        .USE_BRAM         (1'b0),
        .EXTRA_OUTPUT_REG (1'b0),
        .MODE             (FIFO_MODE)
    ) u_token_fifo (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_token_pre_axis.slave),
        .m_axis (u_token_axis.master)
    );

    assign token_valid = u_token_axis.tvalid;
    assign token_data = u_token_axis.t.data[TOKEN_W-1:0];
    assign u_token_axis.tready = token_ready;

    axis_fragment_packer_prealloc_stage #(
        .DATA_WIDTH (DATA_WIDTH),
        .PAGE_COUNT (PAGE_COUNT)
    ) u_prealloc_stage (
        .clk                  (clk),
        .resetn               (resetn),
        .token_valid          (token_valid),
        .token_data           (token_data),
        .token_ready          (token_ready),
        .pool_req_valid       (pool_req_valid),
        .pool_req_data        (pool_req_data),
        .pool_req_ready       (pool_req_ready),
        .pool_alloc_available (pool_alloc_available)
    );

    for (genvar pool = 0; pool < 2; pool++) begin : gen_page_managers
        axis_fragment_packer_page_manager #(
            .DATA_WIDTH (DATA_WIDTH),
            .PAGE_COUNT (PAGE_COUNT),
            .POOL_ODD   (pool)
        ) u_page_manager (
            .clk             (clk),
            .resetn          (resetn),
            .req_valid       (pool_req_valid[pool]),
            .req_data        (pool_req_data[pool]),
            .req_ready       (pool_req_ready[pool]),
            .alloc_available (pool_alloc_available[pool]),
            .dispatch_valid  (pool_dispatch_valid[pool]),
            .dispatch_data   (pool_dispatch_data[pool]),
            .dispatch_ready  (pool_dispatch_ready[pool]),
            .output_pop      (output_pop),
            .output_page     (output_page)
        );
    end

    axis_fragment_packer_dispatch_stage #(
        .DATA_WIDTH (DATA_WIDTH),
        .PAGE_COUNT (PAGE_COUNT)
    ) u_even_dispatch_stage (
        .dispatch_valid (pool_dispatch_valid[0]),
        .dispatch_data  (pool_dispatch_data[0]),
        .dispatch_ready (pool_dispatch_ready[0]),
        .insert_valid   (dispatch_insert0_raw_valid),
        .insert_ready   (dispatch_insert0_raw_ready),
        .insert_page    (dispatch_insert0_raw_page),
        .insert_data    (dispatch_insert0_raw_data),
        .insert_wen     (dispatch_insert0_raw_wen),
        .insert_count   (dispatch_insert0_raw_count),
        .insert_done    (dispatch_insert0_raw_done),
        .insert_last    (dispatch_insert0_raw_last)
    );

    axis_fragment_packer_dispatch_stage #(
        .DATA_WIDTH (DATA_WIDTH),
        .PAGE_COUNT (PAGE_COUNT)
    ) u_odd_dispatch_stage (
        .dispatch_valid (pool_dispatch_valid[1]),
        .dispatch_data  (pool_dispatch_data[1]),
        .dispatch_ready (pool_dispatch_ready[1]),
        .insert_valid   (dispatch_insert1_raw_valid),
        .insert_ready   (dispatch_insert1_raw_ready),
        .insert_page    (dispatch_insert1_raw_page),
        .insert_data    (dispatch_insert1_raw_data),
        .insert_wen     (dispatch_insert1_raw_wen),
        .insert_count   (dispatch_insert1_raw_count),
        .insert_done    (dispatch_insert1_raw_done),
        .insert_last    (dispatch_insert1_raw_last)
    );

    always_comb begin
        dispatch_insert0_raw_pipe_data = '0;
        dispatch_insert0_raw_pipe_data[DISPATCH_INSERT_PIPE_PAGE_L +: PAGE_IDX_W] = dispatch_insert0_raw_page;
        dispatch_insert0_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DATA_L +: DATA_WIDTH] = dispatch_insert0_raw_data;
        dispatch_insert0_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_WEN_L +: KEEP_WIDTH] = dispatch_insert0_raw_wen;
        dispatch_insert0_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_COUNT_L +: BYTE_CNT_W] = dispatch_insert0_raw_count;
        dispatch_insert0_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DONE_L] = dispatch_insert0_raw_done;
        dispatch_insert0_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_LAST_L] = dispatch_insert0_raw_last;

        dispatch_insert1_raw_pipe_data = '0;
        dispatch_insert1_raw_pipe_data[DISPATCH_INSERT_PIPE_PAGE_L +: PAGE_IDX_W] = dispatch_insert1_raw_page;
        dispatch_insert1_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DATA_L +: DATA_WIDTH] = dispatch_insert1_raw_data;
        dispatch_insert1_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_WEN_L +: KEEP_WIDTH] = dispatch_insert1_raw_wen;
        dispatch_insert1_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_COUNT_L +: BYTE_CNT_W] = dispatch_insert1_raw_count;
        dispatch_insert1_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DONE_L] = dispatch_insert1_raw_done;
        dispatch_insert1_raw_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_LAST_L] = dispatch_insert1_raw_last;
    end

    axis_fragment_packer_pipeline_reg #(
        .DATA_WIDTH (DISPATCH_INSERT_PIPE_W)
    ) u_dispatch_insert0_pipe (
        .clk       (clk),
        .resetn    (resetn),
        .in_valid  (dispatch_insert0_raw_valid),
        .in_data   (dispatch_insert0_raw_pipe_data),
        .in_ready  (dispatch_insert0_raw_ready),
        .out_valid (dispatch_insert0_valid),
        .out_data  (dispatch_insert0_pipe_data),
        .out_ready (dispatch_insert0_ready)
    );

    axis_fragment_packer_pipeline_reg #(
        .DATA_WIDTH (DISPATCH_INSERT_PIPE_W)
    ) u_dispatch_insert1_pipe (
        .clk       (clk),
        .resetn    (resetn),
        .in_valid  (dispatch_insert1_raw_valid),
        .in_data   (dispatch_insert1_raw_pipe_data),
        .in_ready  (dispatch_insert1_raw_ready),
        .out_valid (dispatch_insert1_valid),
        .out_data  (dispatch_insert1_pipe_data),
        .out_ready (dispatch_insert1_ready)
    );

    assign dispatch_insert0_page = dispatch_insert0_pipe_data[DISPATCH_INSERT_PIPE_PAGE_L +: PAGE_IDX_W];
    assign dispatch_insert0_data = dispatch_insert0_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DATA_L +: DATA_WIDTH];
    assign dispatch_insert0_wen = dispatch_insert0_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_WEN_L +: KEEP_WIDTH];
    assign dispatch_insert0_count = dispatch_insert0_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_COUNT_L +: BYTE_CNT_W];
    assign dispatch_insert0_done = dispatch_insert0_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DONE_L];
    assign dispatch_insert0_last = dispatch_insert0_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_LAST_L];

    assign dispatch_insert1_page = dispatch_insert1_pipe_data[DISPATCH_INSERT_PIPE_PAGE_L +: PAGE_IDX_W];
    assign dispatch_insert1_data = dispatch_insert1_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DATA_L +: DATA_WIDTH];
    assign dispatch_insert1_wen = dispatch_insert1_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_WEN_L +: KEEP_WIDTH];
    assign dispatch_insert1_count = dispatch_insert1_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_COUNT_L +: BYTE_CNT_W];
    assign dispatch_insert1_done = dispatch_insert1_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_DONE_L];
    assign dispatch_insert1_last = dispatch_insert1_pipe_data[DISPATCH_INSERT_PIPE_PAYLOAD_L + PAGE_INSERT_LAST_L];

    always_comb begin
        page_insert_valid = '0;
        for (int p = 0; p < PAGE_COUNT; p++) begin
            page_insert_data[p] = '0;
            page_insert_wen[p] = '0;
            page_insert_count[p] = '0;
            page_insert_done[p] = 1'b0;
            page_insert_last[p] = 1'b0;
        end

        if (dispatch_insert0_valid) begin
            page_insert_valid[dispatch_insert0_page] = 1'b1;
            page_insert_data[dispatch_insert0_page] = dispatch_insert0_data;
            page_insert_wen[dispatch_insert0_page] = dispatch_insert0_wen;
            page_insert_count[dispatch_insert0_page] = dispatch_insert0_count;
            page_insert_done[dispatch_insert0_page] = dispatch_insert0_done;
            page_insert_last[dispatch_insert0_page] = dispatch_insert0_last;
        end

        if (dispatch_insert1_valid) begin
            page_insert_valid[dispatch_insert1_page] = 1'b1;
            page_insert_data[dispatch_insert1_page] = dispatch_insert1_data;
            page_insert_wen[dispatch_insert1_page] = dispatch_insert1_wen;
            page_insert_count[dispatch_insert1_page] = dispatch_insert1_count;
            page_insert_done[dispatch_insert1_page] = dispatch_insert1_done;
            page_insert_last[dispatch_insert1_page] = dispatch_insert1_last;
        end
    end

    assign dispatch_insert0_ready = !dispatch_insert0_valid || page_insert_ready[dispatch_insert0_page];
    assign dispatch_insert1_ready = !dispatch_insert1_valid || page_insert_ready[dispatch_insert1_page];

    // synthesis translate_off
    always_ff @(posedge clk) begin
        if (resetn) begin
            if (dispatch_insert0_valid && dispatch_insert1_valid)
                assert(dispatch_insert0_page != dispatch_insert1_page);
        end
    end
    // synthesis translate_on

    for (genvar p = 0; p < PAGE_COUNT; p++) begin : gen_pages
        axis_fragment_packer_page #(
            .DATA_WIDTH (DATA_WIDTH)
        ) u_page (
            .clk          (clk),
            .resetn       (resetn),
            .insert_valid (page_insert_valid[p]),
            .insert_data  (page_insert_data[p]),
            .insert_wen   (page_insert_wen[p]),
            .insert_count (page_insert_count[p]),
            .insert_done  (page_insert_done[p]),
            .insert_last  (page_insert_last[p]),
            .insert_ready (page_insert_ready[p]),
            .output_valid (page_output_valid[p]),
            .output_data  (page_output_data[p]),
            .output_keep  (page_output_keep[p]),
            .output_last  (page_output_last[p]),
            .output_ready (page_output_ready[p])
        );

        // synthesis translate_off
        always_ff @(posedge clk) begin
            if (resetn) begin
                if (page_insert_valid[p])
                    assert(page_insert_ready[p]);
                assert(!(page_insert_valid[p] && page_output_ready[p]));
            end
        end
        // synthesis translate_on
    end

    axis_fragment_packer_output_select_stage #(
        .DATA_WIDTH (DATA_WIDTH),
        .PAGE_COUNT (PAGE_COUNT)
    ) u_output_select_stage (
        .clk               (clk),
        .resetn            (resetn),
        .page_output_valid (page_output_valid),
        .page_output_data  (page_output_data),
        .page_output_keep  (page_output_keep),
        .page_output_last  (page_output_last),
        .page_output_ready (page_output_ready),
        .output_pop         (output_pop),
        .output_page        (output_page),
        .m_axis             (u_out_axis.master)
    );

    assign u_out_wide.tvalid = u_out_axis.tvalid;
    assign u_out_wide.t.data = u_out_axis.t.data;
    assign u_out_wide.t.keep = u_out_axis.t.keep;
    assign u_out_wide.t.last = u_out_axis.t.last;
    assign u_out_axis.tready = u_out_wide.tready;

    axis_fifo #(
        .DEPTH            (4),
        .USE_BRAM         (1'b0),
        .EXTRA_OUTPUT_REG (1'b0),
        .MODE             ("CONSERVATIVE")
    ) u_output_iso (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_out_wide.slave),
        .m_axis (m_axis)
    );

endmodule

module axis_fragment_packer_pipeline_reg #(
    parameter int DATA_WIDTH = 1
) (
    input logic clk,
    input logic resetn,

    input  logic                  in_valid,
    input  logic [DATA_WIDTH-1:0] in_data,
    output logic                  in_ready,

    output logic                  out_valid,
    output logic [DATA_WIDTH-1:0] out_data,
    input  logic                  out_ready
);

    logic valid_r;
    logic [DATA_WIDTH-1:0] data_r;

    assign in_ready = !valid_r || out_ready;
    assign out_valid = valid_r;
    assign out_data = data_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            valid_r <= 1'b0;
        end else if (in_ready) begin
            valid_r <= in_valid;
            if (in_valid)
                data_r <= in_data;
        end
    end

endmodule

module axis_fragment_packer_token_stage #(
    parameter int DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave s_axis,

    output logic [TOKEN_W-1:0] token_data,
    output logic               token_valid,
    input  logic               token_ready
);

    localparam int KEEP_WIDTH        = DATA_WIDTH / 8;
    localparam int BYTE_CNT_W        = $clog2(KEEP_WIDTH + 1);
    localparam int COUNT_AXIS_DATA_W = $clog2(DATA_WIDTH);
    localparam int TOKEN_W           = DATA_WIDTH + BYTE_CNT_W + 1;

    localparam int TOKEN_DATA_L  = 0;
    localparam int TOKEN_COUNT_L = TOKEN_DATA_L + DATA_WIDTH;
    localparam int TOKEN_LAST_L  = TOKEN_COUNT_L + BYTE_CNT_W;

    typedef logic [BYTE_CNT_W-1:0] byte_count_t;

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_count_s_axis (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (COUNT_AXIS_DATA_W),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_count_m_axis (.axis_aclk(clk));

    logic stage1_valid_r;
    logic [DATA_WIDTH-1:0] stage1_data_r;
    logic stage1_last_r;

    logic stage2_valid_r;
    logic [DATA_WIDTH-1:0] stage2_data_r;
    logic stage2_last_r;

    logic stage3_valid_r;
    logic [DATA_WIDTH-1:0] stage3_data_r;
    logic stage3_last_r;

    logic stage3_ready;
    logic stage2_ready;
    logic stage1_ready;

    assign stage3_ready = !stage3_valid_r || token_ready;
    assign stage2_ready = !stage2_valid_r || stage3_ready;
    assign stage1_ready = !stage1_valid_r || stage2_ready;

    assign u_count_s_axis.t.data = s_axis.t.data;
    assign u_count_s_axis.t.keep = s_axis.t.keep;
    assign u_count_s_axis.t.last = s_axis.t.last;
    assign u_count_s_axis.tvalid = s_axis.tvalid;
    assign s_axis.tready = stage1_ready;
    assign u_count_m_axis.tready = token_ready;

    axis_count_beat_size #(
        .DATA_WIDTH (DATA_WIDTH)
    ) u_count_beat_size (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_count_s_axis.slave),
        .m_axis (u_count_m_axis.master)
    );

    assign token_valid = stage3_valid_r;
    assign token_data[TOKEN_DATA_L +: DATA_WIDTH] = stage3_data_r;
    assign token_data[TOKEN_COUNT_L +: BYTE_CNT_W] = byte_count_t'(u_count_m_axis.t.data);
    assign token_data[TOKEN_LAST_L] = stage3_last_r;

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
                    stage3_last_r <= stage2_last_r;
                end
            end

            if (stage2_ready) begin
                stage2_valid_r <= stage1_valid_r;
                if (stage1_valid_r) begin
                    stage2_data_r <= stage1_data_r;
                    stage2_last_r <= stage1_last_r;
                end
            end

            if (stage1_ready) begin
                stage1_valid_r <= s_axis.tvalid;
                if (s_axis.tvalid) begin
                    stage1_data_r <= s_axis.t.data;
                    stage1_last_r <= s_axis.t.last;
                end
            end
        end
    end

    // synthesis translate_off
    always_ff @(posedge clk) begin
        if (resetn) begin
            assert(u_count_s_axis.tready == stage1_ready);
            assert(u_count_m_axis.tvalid == stage3_valid_r);
        end
    end
    // synthesis translate_on

endmodule

module axis_fragment_packer_prealloc_stage #(
    parameter int DATA_WIDTH = 512,
    parameter int PAGE_COUNT = 8
) (
    input logic clk,
    input logic resetn,

    input  logic [TOKEN_W-1:0] token_data,
    input  logic               token_valid,
    output logic               token_ready,

    output logic [1:0]              pool_req_valid,
    output logic [POOL_REQ_W-1:0]   pool_req_data [2],
    input  logic [1:0]              pool_req_ready,
    input  logic [1:0]              pool_alloc_available
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int BYTE_CNT_W = $clog2(KEEP_WIDTH + 1);

    localparam int TOKEN_W       = DATA_WIDTH + BYTE_CNT_W + 1;
    localparam int TOKEN_DATA_L  = 0;
    localparam int TOKEN_COUNT_L = TOKEN_DATA_L + DATA_WIDTH;
    localparam int TOKEN_LAST_L  = TOKEN_COUNT_L + BYTE_CNT_W;

    localparam int REQ_DATA_L   = 0;
    localparam int REQ_ALLOC_L  = REQ_DATA_L + DATA_WIDTH;
    localparam int REQ_SRC_L    = REQ_ALLOC_L + 1;
    localparam int REQ_DST_L    = REQ_SRC_L + BYTE_CNT_W;
    localparam int REQ_INSERT_L = REQ_DST_L + BYTE_CNT_W;
    localparam int REQ_COUNT_L  = REQ_INSERT_L + BYTE_CNT_W;
    localparam int REQ_DONE_L   = REQ_COUNT_L + BYTE_CNT_W;
    localparam int REQ_LAST_L   = REQ_DONE_L + 1;
    localparam int POOL_REQ_W   = REQ_LAST_L + 1;
    localparam int REQ_META_W   = POOL_REQ_W - DATA_WIDTH;

    typedef logic [BYTE_CNT_W-1:0] byte_count_t;

    typedef struct packed {
        logic        pool;
        logic        allocate;
        byte_count_t src_offset;
        byte_count_t dst_offset;
        byte_count_t insert_count;
        byte_count_t page_count;
        logic        done;
        logic        last;
    } request_lane_t;

    typedef struct packed {
        logic [DATA_WIDTH-1:0] payload;
        logic                  lane0_valid;
        request_lane_t         lane0;
        logic                  lane1_valid;
        request_lane_t         lane1;
    } request_bundle_t;

    function automatic logic [REQ_META_W-1:0] pack_req_meta(
        input request_lane_t lane
    );
        pack_req_meta = '0;
        pack_req_meta[REQ_ALLOC_L - DATA_WIDTH] = lane.allocate;
        pack_req_meta[REQ_SRC_L - DATA_WIDTH +: BYTE_CNT_W] = lane.src_offset;
        pack_req_meta[REQ_DST_L - DATA_WIDTH +: BYTE_CNT_W] = lane.dst_offset;
        pack_req_meta[REQ_INSERT_L - DATA_WIDTH +: BYTE_CNT_W] = lane.insert_count;
        pack_req_meta[REQ_COUNT_L - DATA_WIDTH +: BYTE_CNT_W] = lane.page_count;
        pack_req_meta[REQ_DONE_L - DATA_WIDTH] = lane.done;
        pack_req_meta[REQ_LAST_L - DATA_WIDTH] = lane.last;
    endfunction

    logic alloc_pool_r;
    logic alloc_pool_n;
    logic active_valid_r;
    logic active_pool_r;
    byte_count_t active_space_r;
    logic pkt_open_r;

    logic active_valid_n;
    logic active_pool_n;
    byte_count_t active_space_n;
    logic pkt_open_n;

    request_bundle_t req_bundle_comb;
    request_bundle_t req_bundle_out;
    logic req_bundle_push_valid;
    logic req_bundle_push_ready;
    logic req_bundle_pop_valid;
    logic req_bundle_pop_ready;
    logic req_bundle_targets_ready;
    logic [REQ_META_W-1:0] lane0_meta;
    logic [REQ_META_W-1:0] lane1_meta;

    byte_count_t token_count;
    logic token_last;
    logic token_has_bytes;
    logic flush_empty_last;
    logic [DATA_WIDTH-1:0] token_payload;

    byte_count_t wr0_count;
    byte_count_t wr0_dst_offset;
    byte_count_t wr0_page_count;
    byte_count_t wr0_space_after;
    byte_count_t wr1_count;
    byte_count_t wr1_page_count;
    byte_count_t wr1_space_after;
    logic wr0_valid;
    logic wr1_valid;
    logic wr0_done;
    logic wr1_done;
    logic wr0_last;
    logic wr1_last;
    logic wr0_allocate;
    logic wr1_allocate;
    logic wr0_pool;
    logic wr1_pool;
    logic free_page_needed;
    logic free_page_available;
    logic do_prealloc;

    assign token_payload = token_data[TOKEN_DATA_L +: DATA_WIDTH];
    assign token_count = token_data[TOKEN_COUNT_L +: BYTE_CNT_W];
    assign token_last = token_data[TOKEN_LAST_L];
    assign token_has_bytes = (token_count != '0);
    assign flush_empty_last = token_valid && !token_has_bytes && token_last && active_valid_r;

    always_comb begin
        wr0_valid = 1'b0;
        wr0_allocate = 1'b0;
        wr0_pool = active_pool_r;
        wr0_count = '0;
        wr0_dst_offset = '0;
        wr0_page_count = '0;
        wr0_space_after = active_space_r;
        wr0_done = 1'b0;
        wr0_last = 1'b0;

        wr1_valid = 1'b0;
        wr1_allocate = 1'b1;
        wr1_pool = alloc_pool_r;
        wr1_count = '0;
        wr1_page_count = '0;
        wr1_space_after = '0;
        wr1_done = 1'b0;
        wr1_last = 1'b0;

        if (active_valid_r) begin
            wr0_pool = active_pool_r;
            wr0_dst_offset = byte_count_t'(byte_count_t'(KEEP_WIDTH) - active_space_r);
            wr0_page_count = wr0_dst_offset;

            if (flush_empty_last) begin
                wr0_valid = 1'b1;
                wr0_done = 1'b1;
                wr0_last = 1'b1;
            end else if (token_valid && token_has_bytes) begin
                wr0_valid = 1'b1;

                if (token_count > active_space_r) begin
                    wr0_count = active_space_r;
                    wr0_page_count = byte_count_t'(KEEP_WIDTH);
                    wr0_done = 1'b1;

                    wr1_valid = 1'b1;
                    wr1_count = byte_count_t'(token_count - active_space_r);
                    wr1_page_count = wr1_count;
                    wr1_space_after = byte_count_t'(byte_count_t'(KEEP_WIDTH) - wr1_count);
                    wr1_done = token_last || (wr1_count == byte_count_t'(KEEP_WIDTH));
                    wr1_last = token_last;
                end else begin
                    wr0_count = token_count;
                    wr0_page_count = byte_count_t'(wr0_dst_offset + token_count);
                    wr0_space_after = byte_count_t'(active_space_r - token_count);
                    wr0_done = token_last || (token_count == active_space_r);
                    wr0_last = token_last;
                end
            end
        end else if (token_valid && token_has_bytes) begin
            wr0_valid = 1'b1;
            wr0_allocate = 1'b1;
            wr0_pool = alloc_pool_r;
            wr0_count = token_count;
            wr0_page_count = token_count;
            wr0_space_after = byte_count_t'(byte_count_t'(KEEP_WIDTH) - token_count);
            wr0_done = token_last || (token_count == byte_count_t'(KEEP_WIDTH));
            wr0_last = token_last;
        end

        free_page_needed = 1'b0;
        if (wr0_valid && wr0_allocate)
            free_page_needed = 1'b1;
        else if (wr1_valid && wr1_allocate)
            free_page_needed = 1'b1;

        // Register the payload once.  The two narrow lanes describe the first
        // write and the optional page-overflow write without steering the wide
        // payload into pool-indexed registers in this stage.
        req_bundle_comb = '0;
        req_bundle_comb.payload = token_payload;
        req_bundle_comb.lane0_valid = wr0_valid;
        req_bundle_comb.lane0.pool = wr0_pool;
        req_bundle_comb.lane0.allocate = wr0_allocate;
        req_bundle_comb.lane0.src_offset = '0;
        req_bundle_comb.lane0.dst_offset = wr0_dst_offset;
        req_bundle_comb.lane0.insert_count = wr0_count;
        req_bundle_comb.lane0.page_count = wr0_page_count;
        req_bundle_comb.lane0.done = wr0_done;
        req_bundle_comb.lane0.last = wr0_last;
        req_bundle_comb.lane1_valid = wr1_valid;
        req_bundle_comb.lane1.pool = wr1_pool;
        req_bundle_comb.lane1.allocate = wr1_allocate;
        req_bundle_comb.lane1.src_offset = wr0_count;
        req_bundle_comb.lane1.dst_offset = '0;
        req_bundle_comb.lane1.insert_count = wr1_count;
        req_bundle_comb.lane1.page_count = wr1_page_count;
        req_bundle_comb.lane1.done = wr1_done;
        req_bundle_comb.lane1.last = wr1_last;
    end

    assign free_page_available = !free_page_needed || pool_alloc_available[alloc_pool_r];
    assign req_bundle_push_valid = token_valid && free_page_available;
    assign token_ready = req_bundle_push_ready && free_page_available;
    assign do_prealloc = req_bundle_push_valid && req_bundle_push_ready;

    // A two-entry isolate stage makes token_ready depend only on registered
    // occupancy.  Page-manager backpressure cannot propagate through the
    // preallocation arithmetic into the token FIFO's pop control.
    register_slice #(
        .T          (request_bundle_t),
        .MODE       ("ISOLATE"),
        .NUM_STAGES (2)
    ) u_request_bundle (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (req_bundle_push_valid),
        .push_data  (req_bundle_comb),
        .push_ready (req_bundle_push_ready),
        .pop_valid  (req_bundle_pop_valid),
        .pop_data   (req_bundle_out),
        .pop_ready  (req_bundle_pop_ready)
    );

    assign lane0_meta = pack_req_meta(req_bundle_out.lane0);
    assign lane1_meta = pack_req_meta(req_bundle_out.lane1);

    // The payload is broadcast directly from its register. Only the narrow
    // request metadata is selected by destination pool.
    always_comb begin
        pool_req_valid = '0;
        for (int pool = 0; pool < 2; pool++) begin
            pool_req_data[pool] = '0;
            pool_req_data[pool][REQ_DATA_L +: DATA_WIDTH] = req_bundle_out.payload;
            if (req_bundle_out.lane0_valid
                    && (req_bundle_out.lane0.pool == logic'(pool)))
                pool_req_data[pool][REQ_ALLOC_L +: REQ_META_W] = lane0_meta;
            else
                pool_req_data[pool][REQ_ALLOC_L +: REQ_META_W] = lane1_meta;
        end

        req_bundle_targets_ready = 1'b1;
        if (req_bundle_pop_valid) begin
            if (req_bundle_out.lane0_valid)
                req_bundle_targets_ready &= pool_req_ready[req_bundle_out.lane0.pool];
            if (req_bundle_out.lane1_valid)
                req_bundle_targets_ready &= pool_req_ready[req_bundle_out.lane1.pool];
        end

        // Commit both halves of a split token atomically. Gating valid here
        // controls the page-manager action; it never gates the payload data.
        if (req_bundle_pop_valid && req_bundle_targets_ready) begin
            if (req_bundle_out.lane0_valid)
                pool_req_valid[req_bundle_out.lane0.pool] = 1'b1;
            if (req_bundle_out.lane1_valid)
                pool_req_valid[req_bundle_out.lane1.pool] = 1'b1;
        end

        req_bundle_pop_ready = !req_bundle_pop_valid || req_bundle_targets_ready;
    end

    always_comb begin
        active_valid_n = active_valid_r;
        active_pool_n = active_pool_r;
        active_space_n = active_space_r;
        pkt_open_n = pkt_open_r;
        alloc_pool_n = alloc_pool_r;

        if (do_prealloc) begin
            if (token_has_bytes && !pkt_open_r)
                pkt_open_n = 1'b1;

            if (wr1_valid) begin
                active_valid_n = !wr1_done;
                active_pool_n = wr1_pool;
                active_space_n = wr1_space_after;
            end else if (wr0_valid) begin
                active_valid_n = !wr0_done;
                active_pool_n = wr0_pool;
                active_space_n = wr0_space_after;
            end

            if (free_page_needed)
                alloc_pool_n = !alloc_pool_r;

            if (token_last)
                pkt_open_n = 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            active_valid_r <= 1'b0;
            pkt_open_r <= 1'b0;
            alloc_pool_r <= 1'b0;
        end else begin
            active_valid_r <= active_valid_n;
            active_pool_r <= active_pool_n;
            active_space_r <= active_space_n;
            pkt_open_r <= pkt_open_n;
            alloc_pool_r <= alloc_pool_n;
        end
    end

    // synthesis translate_off
    always_ff @(posedge clk) begin
        if (resetn) begin
            if (do_prealloc && wr1_valid) begin
                assert(wr0_valid);
                assert(wr0_pool != wr1_pool);
            end
            if (req_bundle_pop_valid && req_bundle_out.lane1_valid) begin
                assert(req_bundle_out.lane0_valid);
                assert(req_bundle_out.lane0.pool != req_bundle_out.lane1.pool);
            end
        end
    end
    // synthesis translate_on

endmodule

module axis_fragment_packer_page_manager #(
    parameter int DATA_WIDTH = 512,
    parameter int PAGE_COUNT = 8,
    parameter int POOL_ODD   = 0
) (
    input logic clk,
    input logic resetn,

    input  logic [POOL_REQ_W-1:0] req_data,
    input  logic                  req_valid,
    output logic                  req_ready,
    output logic                  alloc_available,

    output logic [POOL_DISPATCH_W-1:0] dispatch_data,
    output logic                       dispatch_valid,
    input  logic                       dispatch_ready,

    input  logic                  output_pop,
    input  logic [PAGE_IDX_W-1:0] output_page
);

    localparam int KEEP_WIDTH      = DATA_WIDTH / 8;
    localparam int PAGE_IDX_W      = (PAGE_COUNT <= 2) ? 1 : $clog2(PAGE_COUNT);
    localparam int BYTE_CNT_W      = $clog2(KEEP_WIDTH + 1);
    localparam int POOL_PAGE_COUNT = PAGE_COUNT / 2;
    localparam int POOL_PAGE_IDX_W = (POOL_PAGE_COUNT <= 2) ? 1 : $clog2(POOL_PAGE_COUNT);

    localparam int REQ_DATA_L   = 0;
    localparam int REQ_ALLOC_L  = REQ_DATA_L + DATA_WIDTH;
    localparam int REQ_SRC_L    = REQ_ALLOC_L + 1;
    localparam int REQ_DST_L    = REQ_SRC_L + BYTE_CNT_W;
    localparam int REQ_INSERT_L = REQ_DST_L + BYTE_CNT_W;
    localparam int REQ_COUNT_L  = REQ_INSERT_L + BYTE_CNT_W;
    localparam int REQ_DONE_L   = REQ_COUNT_L + BYTE_CNT_W;
    localparam int REQ_LAST_L   = REQ_DONE_L + 1;
    localparam int POOL_REQ_W   = REQ_LAST_L + 1;

    localparam int CMD_VALID_L    = 0;
    localparam int CMD_PAGE_L     = CMD_VALID_L + 1;
    localparam int CMD_SRC_L      = CMD_PAGE_L + PAGE_IDX_W;
    localparam int CMD_DST_L      = CMD_SRC_L + BYTE_CNT_W;
    localparam int CMD_INSERT_L   = CMD_DST_L + BYTE_CNT_W;
    localparam int CMD_COUNT_L    = CMD_INSERT_L + BYTE_CNT_W;
    localparam int CMD_DONE_L     = CMD_COUNT_L + BYTE_CNT_W;
    localparam int CMD_LAST_L     = CMD_DONE_L + 1;
    localparam int CMD_W          = CMD_LAST_L + 1;

    localparam int POOL_DISPATCH_DATA_L = 0;
    localparam int POOL_DISPATCH_CMD_L  = POOL_DISPATCH_DATA_L + DATA_WIDTH;
    localparam int POOL_DISPATCH_W      = POOL_DISPATCH_CMD_L + CMD_W;

    typedef logic [PAGE_IDX_W-1:0] page_idx_t;
    typedef logic [POOL_PAGE_IDX_W-1:0] pool_page_idx_t;

    function automatic pool_page_idx_t next_pool_page(input pool_page_idx_t page);
        if (page == pool_page_idx_t'(POOL_PAGE_COUNT - 1))
            next_pool_page = '0;
        else
            next_pool_page = pool_page_idx_t'(page + pool_page_idx_t'(1));
    endfunction

    function automatic page_idx_t global_page(input pool_page_idx_t page);
        global_page = page_idx_t'({page, logic'(POOL_ODD != 0)});
    endfunction

    function automatic pool_page_idx_t local_page(input page_idx_t page);
        local_page = pool_page_idx_t'(page >> 1);
    endfunction

    function automatic logic [CMD_W-1:0] pack_cmd(
        input page_idx_t page,
        input logic [POOL_REQ_W-1:0] req
    );
        pack_cmd = '0;
        pack_cmd[CMD_VALID_L] = 1'b1;
        pack_cmd[CMD_PAGE_L +: PAGE_IDX_W] = page;
        pack_cmd[CMD_SRC_L +: BYTE_CNT_W] = req[REQ_SRC_L +: BYTE_CNT_W];
        pack_cmd[CMD_DST_L +: BYTE_CNT_W] = req[REQ_DST_L +: BYTE_CNT_W];
        pack_cmd[CMD_INSERT_L +: BYTE_CNT_W] = req[REQ_INSERT_L +: BYTE_CNT_W];
        pack_cmd[CMD_COUNT_L +: BYTE_CNT_W] = req[REQ_COUNT_L +: BYTE_CNT_W];
        pack_cmd[CMD_DONE_L] = req[REQ_DONE_L];
        pack_cmd[CMD_LAST_L] = req[REQ_LAST_L];
    endfunction

    pool_page_idx_t alloc_page_r;
    pool_page_idx_t active_page_r;
    logic active_valid_r;
    logic [POOL_PAGE_COUNT-1:0] page_available_r;
    logic [POOL_PAGE_COUNT-1:0] page_available_n;

    logic req_allocate;
    logic req_done;
    logic req_fire;
    page_idx_t req_page;

    assign req_allocate = req_data[REQ_ALLOC_L];
    assign req_done = req_data[REQ_DONE_L];
    assign req_page = req_allocate ? global_page(alloc_page_r) : global_page(active_page_r);
    assign alloc_available = page_available_r[alloc_page_r];
    assign req_ready = !dispatch_valid || dispatch_ready;
    assign req_fire = req_valid && req_ready;

    always_comb begin
        page_available_n = page_available_r;

        if (req_fire && req_allocate)
            page_available_n[alloc_page_r] = 1'b0;

        if (output_pop && (output_page[0] == logic'(POOL_ODD != 0)))
            page_available_n[local_page(output_page)] = 1'b1;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            dispatch_valid <= 1'b0;
            alloc_page_r <= '0;
            active_valid_r <= 1'b0;
            page_available_r <= '1;
        end else begin
            if (req_ready) begin
                dispatch_valid <= req_valid;
                if (req_valid) begin
                    dispatch_data[POOL_DISPATCH_DATA_L +: DATA_WIDTH] <= req_data[REQ_DATA_L +: DATA_WIDTH];
                    dispatch_data[POOL_DISPATCH_CMD_L +: CMD_W] <= pack_cmd(req_page, req_data);
                end
            end

            if (req_fire) begin
                if (req_allocate) begin
                    alloc_page_r <= next_pool_page(alloc_page_r);
                    active_page_r <= alloc_page_r;
                    active_valid_r <= !req_done;
                end else if (req_done) begin
                    active_valid_r <= 1'b0;
                end
            end

            page_available_r <= page_available_n;
        end
    end

    // synthesis translate_off
    always_ff @(posedge clk) begin
        if (resetn) begin
            if (req_valid && !req_allocate)
                assert(active_valid_r);
            if (req_valid && req_allocate)
                assert(alloc_available);
        end
    end
    // synthesis translate_on

endmodule

module axis_fragment_packer_dispatch_stage #(
    parameter int DATA_WIDTH = 512,
    parameter int PAGE_COUNT = 8
) (
    input  logic [POOL_DISPATCH_W-1:0] dispatch_data,
    input  logic                       dispatch_valid,
    output logic                       dispatch_ready,

    output logic                   insert_valid,
    input  logic                   insert_ready,
    output logic [PAGE_IDX_W-1:0]  insert_page,
    output logic [DATA_WIDTH-1:0]  insert_data,
    output logic [KEEP_WIDTH-1:0]  insert_wen,
    output logic [BYTE_CNT_W-1:0]  insert_count,
    output logic                   insert_done,
    output logic                   insert_last
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int PAGE_IDX_W = (PAGE_COUNT <= 2) ? 1 : $clog2(PAGE_COUNT);
    localparam int BYTE_CNT_W = $clog2(KEEP_WIDTH + 1);

    localparam int CMD_VALID_L    = 0;
    localparam int CMD_PAGE_L     = CMD_VALID_L + 1;
    localparam int CMD_SRC_L      = CMD_PAGE_L + PAGE_IDX_W;
    localparam int CMD_DST_L      = CMD_SRC_L + BYTE_CNT_W;
    localparam int CMD_INSERT_L   = CMD_DST_L + BYTE_CNT_W;
    localparam int CMD_COUNT_L    = CMD_INSERT_L + BYTE_CNT_W;
    localparam int CMD_DONE_L     = CMD_COUNT_L + BYTE_CNT_W;
    localparam int CMD_LAST_L     = CMD_DONE_L + 1;
    localparam int CMD_W          = CMD_LAST_L + 1;

    localparam int POOL_DISPATCH_DATA_L = 0;
    localparam int POOL_DISPATCH_CMD_L  = POOL_DISPATCH_DATA_L + DATA_WIDTH;
    localparam int POOL_DISPATCH_W      = POOL_DISPATCH_CMD_L + CMD_W;

    typedef logic [BYTE_CNT_W-1:0] byte_count_t;
    typedef logic [$clog2(KEEP_WIDTH)-1:0] byte_idx_t;

    function automatic logic [DATA_WIDTH-1:0] place_data(
        input logic [DATA_WIDTH-1:0] data,
        input byte_count_t src_offset,
        input byte_count_t dst_offset
    );
        byte_idx_t src_byte;
        place_data = '0;
        for (int i = 0; i < KEEP_WIDTH; i++) begin
            src_byte = byte_idx_t'(src_offset + byte_count_t'(i) - dst_offset);
            if (byte_count_t'(i) >= dst_offset)
                place_data[i * 8 +: 8] = data[src_byte * 8 +: 8];
        end
    endfunction

    function automatic logic [KEEP_WIDTH-1:0] write_mask(
        input byte_count_t dst_offset,
        input byte_count_t count
    );
        write_mask = '0;
        for (int i = 0; i < KEEP_WIDTH; i++) begin
            if ((byte_count_t'(i) >= dst_offset) && (byte_count_t'(i) < byte_count_t'(dst_offset + count)))
                write_mask[i] = 1'b1;
        end
    endfunction

    logic [CMD_W-1:0] cmd;
    logic [DATA_WIDTH-1:0] raw_data;

    assign raw_data = dispatch_data[POOL_DISPATCH_DATA_L +: DATA_WIDTH];
    assign cmd = dispatch_data[POOL_DISPATCH_CMD_L +: CMD_W];

    assign insert_valid = dispatch_valid && cmd[CMD_VALID_L];
    assign insert_page = dispatch_valid ? cmd[CMD_PAGE_L +: PAGE_IDX_W] : '0;
    assign insert_data = place_data(
        raw_data,
        cmd[CMD_SRC_L +: BYTE_CNT_W],
        cmd[CMD_DST_L +: BYTE_CNT_W]
    );
    assign insert_wen = dispatch_valid
                      ? write_mask(cmd[CMD_DST_L +: BYTE_CNT_W], cmd[CMD_INSERT_L +: BYTE_CNT_W])
                      : '0;
    assign insert_count = dispatch_valid ? cmd[CMD_COUNT_L +: BYTE_CNT_W] : '0;
    assign insert_done = dispatch_valid && cmd[CMD_DONE_L];
    assign insert_last = dispatch_valid && cmd[CMD_LAST_L];
    assign dispatch_ready = !insert_valid || insert_ready;

endmodule

module axis_fragment_packer_page #(
    parameter int DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    input  logic                   insert_valid,
    input  logic [DATA_WIDTH-1:0]  insert_data,
    input  logic [KEEP_WIDTH-1:0]  insert_wen,
    input  logic [BYTE_CNT_W-1:0]  insert_count,
    input  logic                   insert_done,
    input  logic                   insert_last,
    output logic                   insert_ready,

    output logic                   output_valid,
    output logic [DATA_WIDTH-1:0]  output_data,
    output logic [KEEP_WIDTH-1:0]  output_keep,
    output logic                   output_last,
    input  logic                   output_ready
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int BYTE_CNT_W = $clog2(KEEP_WIDTH + 1);

    typedef logic [BYTE_CNT_W-1:0] byte_count_t;
    typedef logic [KEEP_WIDTH-1:0] keep_t;

    function automatic keep_t keep_from_count(input byte_count_t count);
        for (int i = 0; i < KEEP_WIDTH; i++)
            keep_from_count[i] = (byte_count_t'(i) < count);
    endfunction

    logic [DATA_WIDTH-1:0] data_r;
    byte_count_t count_r;
    logic closed_r;
    logic last_r;

    logic prep_valid_r;
    logic [KEEP_WIDTH-1:0] prep_wen_r;
    logic [DATA_WIDTH-1:0] prep_data_r;
    byte_count_t prep_count_r;
    logic prep_done_r;
    logic prep_last_r;

    logic insert_fire;

    assign insert_ready = 1'b1;
    assign insert_fire = insert_valid;

    assign output_valid = closed_r && !prep_valid_r;
    assign output_data = data_r;
    assign output_keep = keep_from_count(count_r);
    assign output_last = last_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            closed_r <= 1'b0;
            prep_valid_r <= 1'b0;
        end else begin
            if (output_ready) begin
                closed_r <= 1'b0;
                prep_valid_r <= 1'b0;
            end else begin
                if (prep_valid_r) begin
                    for (int b = 0; b < KEEP_WIDTH; b++) begin
                        if (prep_wen_r[b])
                            data_r[b * 8 +: 8] <= prep_data_r[b * 8 +: 8];
                    end

                    count_r <= prep_count_r;
                    last_r <= prep_last_r;
                    if (prep_done_r)
                        closed_r <= 1'b1;
                end

                prep_valid_r <= insert_fire;
                if (insert_fire) begin
                    prep_wen_r <= insert_wen;
                    prep_data_r <= insert_data;
                    prep_count_r <= insert_count;
                    prep_done_r <= insert_done;
                    prep_last_r <= insert_last;
                end
            end
        end
    end

    // synthesis translate_off
    always_ff @(posedge clk) begin
        if (resetn) begin
            assert(!(output_ready && insert_fire));
            if (insert_valid)
                assert(!closed_r);
        end
    end
    // synthesis translate_on

endmodule

module axis_fragment_packer_output_select_stage #(
    parameter int DATA_WIDTH = 512,
    parameter int PAGE_COUNT = 8
) (
    input logic clk,
    input logic resetn,

    input logic [PAGE_COUNT-1:0]  page_output_valid,
    input logic [DATA_WIDTH-1:0]  page_output_data [PAGE_COUNT],
    input logic [KEEP_WIDTH-1:0]  page_output_keep [PAGE_COUNT],
    input logic                   page_output_last [PAGE_COUNT],
    output logic [PAGE_COUNT-1:0] page_output_ready,

    output logic output_pop,
    output logic [PAGE_IDX_W-1:0] output_page,

    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int PAGE_IDX_W = (PAGE_COUNT <= 2) ? 1 : $clog2(PAGE_COUNT);

    `AXIS_T_CHAN_STRUCT(DATA_WIDTH, KEEP_WIDTH, 1, 1, 1, beat_t);

    typedef logic [PAGE_IDX_W-1:0] page_idx_t;

    function automatic page_idx_t next_page(input page_idx_t page);
        if (page == page_idx_t'(PAGE_COUNT - 1))
            next_page = '0;
        else
            next_page = page_idx_t'(page + page_idx_t'(1));
    endfunction

    page_idx_t expected_page_r;
    beat_t out_beat;
    logic selected_valid;

    assign selected_valid = page_output_valid[expected_page_r];
    assign output_pop = selected_valid && m_axis.tready;
    assign output_page = expected_page_r;

    always_comb begin
        page_output_ready = '0;
        if (output_pop)
            page_output_ready[expected_page_r] = 1'b1;
    end

    always_comb begin
        out_beat.data = '0;
        out_beat.keep = '0;
        out_beat.last = 1'b0;
        if (selected_valid) begin
            out_beat.data = page_output_data[expected_page_r];
            out_beat.keep = page_output_keep[expected_page_r];
            out_beat.last = page_output_last[expected_page_r];
        end
    end

    assign m_axis.tvalid = selected_valid;
    assign m_axis.t = out_beat;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            expected_page_r <= '0;
        end else if (output_pop) begin
            expected_page_r <= next_page(expected_page_r);
        end
    end

endmodule
