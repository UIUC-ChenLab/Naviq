`include "ifc_axis.sv"
`include "ifc_axil.sv"

// Fully pipelined, packet-oriented AES-CTR transform.
//
// Interface contract:
//   * Program an SA's salt, initial packet counter, and key through ctrl_in,
//     then commit it before referencing that SA on the streaming interfaces.
//   * Send exactly one s_axis_meta beat per packet, in packet order.  Metadata
//     may lead packet data and is queued internally (four contexts).  The first
//     s_axis_packet beat waits until its corresponding context is available.
//   * s_axis_meta data layout:
//       [SA_ID_WIDTH-1:0]              SA id
//       [SA_ID_WIDTH]                  explicit packet counter valid
//       [SA_ID_WIDTH+1 +: 64]          explicit packet counter
//     When the explicit-counter bit is clear, the selected SA's next counter
//     is allocated and incremented.  When set, the supplied counter is used
//     without advancing the stored counter (the RX/decrypt use case).
//   * s_axis_packet carries one 128-bit AES block per beat.  tlast terminates
//     the packet and resets the per-packet block counter.  Partial final beats
//     are allowed through tkeep, which is preserved unchanged.
//   * m_axis_meta produces one result per accepted metadata request:
//       [63:0]                          packet counter actually used
//       [64 +: SA_ID_WIDTH]             SA id
//       [64+SA_ID_WIDTH]                drop (SA was not valid)
//     A dropped packet is still consumed from s_axis_packet but produces no
//     m_axis_packet beats.
//   * m_axis_packet is the input data XORed bit-for-bit with AES applied to
//       {salt[31:0], packet_counter[63:0], block_counter[31:0]}.
//     The AES state byte at tdata[127:120] is the first byte of that counter
//     block.  Callers using AXIS byte 0 in tdata[7:0] must account for this
//     byte-lane convention when comparing against a software CTR reference.
//
// Once primed and not backpressured, the core accepts and emits one 128-bit
// packet beat per cycle.  Packet and metadata outputs are independently
// backpressured; callers must keep both output channels draining.
module aes_ctr #(
    parameter int SBOX_COUNT = 16,
    parameter int KEY_BITS = 256,
    parameter int PACKET_DATA_WIDTH = 128,
    parameter int SA_TABLE_DEPTH = 1024,
    parameter int SA_ID_WIDTH = (SA_TABLE_DEPTH <= 1) ? 1 : $clog2(SA_TABLE_DEPTH),
    parameter int AXIL_ADDR_WIDTH = 32,
    parameter int AXIL_DATA_WIDTH = 32,
    parameter int SA_STRIDE = 256
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_packet,
    ifc_axis.slave  s_axis_meta,
    ifc_axil.slave  ctrl_in,
    ifc_axis.master m_axis_packet,
    ifc_axis.master m_axis_meta
);

    localparam int PACKET_KEEP_WIDTH = PACKET_DATA_WIDTH / 8;
    localparam int NUM_ROUNDS = (KEY_BITS == 128) ? 10 : 14;
    localparam int PIPE_STAGES = NUM_ROUNDS + 1;
    localparam int KEY_WORDS = KEY_BITS / 32;
    localparam int TOTAL_KEY_WORDS = 4 * (NUM_ROUNDS + 1);
    localparam int MAX_KEY_WORDS = 8;
    localparam int INITIAL_KEY_ROUNDS = KEY_WORDS / 4;
    localparam int META_WIDTH = 1 + 32 + 64;
    localparam int IN_META_WIDTH = SA_ID_WIDTH + 1 + 64;
    localparam int OUT_META_WIDTH = 1 + SA_ID_WIDTH + 64;
    localparam int CTX_FIFO_DEPTH = 4;
    localparam int CTX_FIFO_ADDR_W = $clog2(CTX_FIFO_DEPTH);
    localparam int SA_STRIDE_BITS = $clog2(SA_STRIDE);
    typedef struct packed {
        logic                  drop;
        logic [SA_ID_WIDTH-1:0] sa_id;
        logic [31:0]           salt;
        logic [63:0]           packet_counter;
        logic [127:0]          round_key0;
    } ctx_t;

    typedef enum logic [2:0] {
        K_IDLE,
        K_EXPAND,
        K_WRITE_INIT,
        K_WRITE_ROUND,
        K_WRITE_META
    } key_state_t;

    logic [SA_ID_WIDTH-1:0] s_meta_id;
    logic                  s_meta_counter_valid;
    logic [63:0]           s_meta_packet_counter;
    logic                  s_meta_hs;

    logic [SA_ID_WIDTH-1:0] meta_rd_addr;
    logic [META_WIDTH-1:0]  meta_rd_data;
    logic                  meta_wr_en;
    logic [SA_ID_WIDTH-1:0] meta_wr_addr;
    logic [META_WIDTH-1:0]  meta_wr_data;

    logic [SA_ID_WIDTH-1:0] meta_req_sa_r;
    logic                  meta_req_counter_valid_r;
    logic [63:0]           meta_req_packet_counter_r;
    logic                  meta_req_pending_r;
    logic                  meta_resp_valid;
    ctx_t                  meta_resp_ctx;

    ctx_t ctx_fifo_r [CTX_FIFO_DEPTH];
    logic [CTX_FIFO_ADDR_W-1:0] ctx_head_r;
    logic [CTX_FIFO_ADDR_W-1:0] ctx_tail_r;
    logic [$clog2(CTX_FIFO_DEPTH+1)-1:0] ctx_count_r;
    logic ctx_full;
    logic ctx_empty;
    logic ctx_push;
    logic ctx_pop;
    ctx_t ctx_head;

    logic [OUT_META_WIDTH-1:0] meta_out_fifo_r [CTX_FIFO_DEPTH];
    logic [CTX_FIFO_ADDR_W-1:0] meta_out_head_r;
    logic [CTX_FIFO_ADDR_W-1:0] meta_out_tail_r;
    logic [$clog2(CTX_FIFO_DEPTH+1)-1:0] meta_out_count_r;
    logic meta_out_full;
    logic meta_out_empty;
    logic meta_out_push;
    logic meta_out_pop;
    logic [OUT_META_WIDTH-1:0] meta_out_push_data;

    logic [SA_ID_WIDTH-1:0] current_sa_r;
    logic [31:0] current_salt_r;
    logic [63:0] current_packet_counter_r;
    logic [127:0] current_round_key0_r;
    logic current_drop_r;
    logic [31:0] block_counter_r;
    logic expect_first_r;

    logic [PIPE_STAGES-1:0]                         pipe_valid_r;
    logic [PIPE_STAGES-1:0][127:0]                  pipe_state_r;
    logic [PIPE_STAGES-1:0][PACKET_DATA_WIDTH-1:0]  pipe_packet_data_r;
    logic [PIPE_STAGES-1:0][PACKET_KEEP_WIDTH-1:0]  pipe_packet_keep_r;
    logic [PIPE_STAGES-1:0]                         pipe_packet_last_r;
    logic [PIPE_STAGES-1:0][SA_ID_WIDTH-1:0]        pipe_sa_id_r;

    logic [PIPE_STAGES-1:1][127:0] round_state;
    logic [NUM_ROUNDS:0][SA_ID_WIDTH-1:0] round_key_rd_addr;
    logic [NUM_ROUNDS:0][127:0] round_key_rd_data;
    logic round_key_wr_en;
    logic [$clog2(NUM_ROUNDS+1)-1:0] round_key_wr_idx;
    logic [SA_ID_WIDTH-1:0] round_key_wr_sa;
    logic [127:0] round_key_wr_data;

    logic [127:0] input_counter_block;
    logic [127:0] input_initial_state;
    logic [SA_ID_WIDTH-1:0] input_sa_id;
    logic [31:0] input_salt;
    logic [63:0] input_packet_counter;
    logic input_drop;
    logic input_ready;
    logic first_hs;
    logic next_hs;
    logic packet_hs;
    logic pipe_insert;
    logic advance_pipeline;

    logic [31:0] stage_key_words_r [MAX_KEY_WORDS];
    logic [31:0] key_window_r [MAX_KEY_WORDS];
    logic [31:0] round_build_r [4];
    logic [31:0] stage_salt_r;
    logic [63:0] stage_counter_r;

    key_state_t key_state_r;
    logic [5:0] expand_word_idx_r;
    logic [$clog2(NUM_ROUNDS+1)-1:0] write_round_idx_r;
    logic [SA_ID_WIDTH-1:0] commit_sa_r;
    logic [31:0] commit_salt_r;
    logic [63:0] commit_counter_r;

    logic [31:0] key_sbox_in;
    logic [31:0] key_sbox_out;
    logic [31:0] key_temp_word;
    logic [31:0] key_transformed_word;
    logic [31:0] key_next_word;
    logic key_word_boundary;
    logic key_aes256_midword;
    logic [3:0] key_rcon_idx;
    logic [1:0] expand_word_lane;
    logic [2:0] init_round_base;
    logic [127:0] pending_round_key_r;
    logic [$clog2(NUM_ROUNDS+1)-1:0] pending_round_idx_r;

    logic axil_b_valid_r;
    logic axil_r_valid_r;
    logic axil_write_fire;
    logic axil_read_fire;
    logic [AXIL_ADDR_WIDTH-1:0] axil_wr_addr;
    logic [31:0] axil_wr_sa_word;
    logic [SA_ID_WIDTH-1:0] axil_wr_sa;
    logic [SA_STRIDE_BITS-1:0] axil_wr_offset;
    logic axil_wr_sa_valid;
    logic commit_request;
    logic key_busy;
    logic datapath_meta_update;
    logic meta_update_pending_r;
    logic [SA_ID_WIDTH-1:0] meta_update_addr_r;
    logic [META_WIDTH-1:0] meta_update_data_r;
    logic commit_meta_wr_en;

    function automatic [7:0] rcon(input int unsigned idx);
        begin
            unique case (idx)
                1: rcon = 8'h01;
                2: rcon = 8'h02;
                3: rcon = 8'h04;
                4: rcon = 8'h08;
                5: rcon = 8'h10;
                6: rcon = 8'h20;
                7: rcon = 8'h40;
                8: rcon = 8'h80;
                9: rcon = 8'h1b;
                default: rcon = 8'h36;
            endcase
        end
    endfunction

    initial begin
        if (PACKET_DATA_WIDTH != 128) begin
            $error("aes_ctr: only PACKET_DATA_WIDTH=128 is supported");
            $finish;
        end
        if (SBOX_COUNT != 16) begin
            $error("aes_ctr: pipelined II=1 CTR mode requires SBOX_COUNT=16");
            $finish;
        end
        if (!((KEY_BITS == 128) || (KEY_BITS == 256))) begin
            $error("aes_ctr: KEY_BITS must be 128 or 256");
            $finish;
        end
        if (AXIL_DATA_WIDTH != 32) begin
            $error("aes_ctr: AXIL_DATA_WIDTH must be 32");
            $finish;
        end
        if ($bits(s_axis_meta.t.data) < IN_META_WIDTH) begin
            $error("aes_ctr: s_axis_meta.t.data must be at least SA_ID_WIDTH+65 bits");
            $finish;
        end
        if ($bits(m_axis_meta.t.data) < OUT_META_WIDTH) begin
            $error("aes_ctr: m_axis_meta.t.data must be at least SA_ID_WIDTH+65 bits");
            $finish;
        end
        if (SA_STRIDE != (1 << SA_STRIDE_BITS)) begin
            $error("aes_ctr: SA_STRIDE must be a power of two");
            $finish;
        end
    end

    assign s_meta_id = s_axis_meta.t.data[SA_ID_WIDTH-1:0];
    assign s_meta_counter_valid = s_axis_meta.t.data[SA_ID_WIDTH];
    assign s_meta_packet_counter = s_axis_meta.t.data[SA_ID_WIDTH + 1 +: 64];
    assign ctx_full = (ctx_count_r == CTX_FIFO_DEPTH[$bits(ctx_count_r)-1:0]);
    assign ctx_empty = (ctx_count_r == '0);
    assign ctx_head = ctx_fifo_r[ctx_head_r];
    assign meta_out_full = (meta_out_count_r == CTX_FIFO_DEPTH[$bits(meta_out_count_r)-1:0]);
    assign meta_out_empty = (meta_out_count_r == '0);
    assign s_meta_hs = s_axis_meta.tvalid && s_axis_meta.tready;
    assign s_axis_meta.tready = !ctx_full && !meta_out_full &&
                                !meta_req_pending_r && !meta_update_pending_r;

    assign s_axis_packet.tready = input_ready;
    assign m_axis_packet.t.data = pipe_packet_data_r[PIPE_STAGES-1] ^ pipe_state_r[PIPE_STAGES-1];
    assign m_axis_packet.t.keep = pipe_packet_keep_r[PIPE_STAGES-1];
    assign m_axis_packet.t.id = '0;
    assign m_axis_packet.t.dest = '0;
    assign m_axis_packet.t.user = '0;
    assign m_axis_packet.t.last = pipe_packet_last_r[PIPE_STAGES-1];
    assign m_axis_packet.tvalid = pipe_valid_r[PIPE_STAGES-1];

    assign m_axis_meta.t.data =
        {{($bits(m_axis_meta.t.data)-OUT_META_WIDTH){1'b0}}, meta_out_fifo_r[meta_out_head_r]};
    assign m_axis_meta.t.keep = '1;
    assign m_axis_meta.t.id = '0;
    assign m_axis_meta.t.dest = '0;
    assign m_axis_meta.t.user = '0;
    assign m_axis_meta.t.last = 1'b1;
    assign m_axis_meta.tvalid = !meta_out_empty;
    assign meta_out_pop = m_axis_meta.tvalid && m_axis_meta.tready;

    assign advance_pipeline = !pipe_valid_r[PIPE_STAGES-1] || m_axis_packet.tready;
    assign input_drop = expect_first_r ? ctx_head.drop : current_drop_r;
    assign input_ready = expect_first_r ? (!ctx_empty && (ctx_head.drop || advance_pipeline)) :
                                          (current_drop_r || advance_pipeline);
    assign first_hs = expect_first_r && !ctx_empty && s_axis_packet.tvalid && input_ready;
    assign next_hs = !expect_first_r && s_axis_packet.tvalid && input_ready;
    assign packet_hs = first_hs || next_hs;
    assign pipe_insert = packet_hs && !input_drop;
    assign ctx_pop = first_hs;

    assign input_sa_id = expect_first_r ? ctx_head.sa_id : current_sa_r;
    assign input_salt = expect_first_r ? ctx_head.salt : current_salt_r;
    assign input_packet_counter = expect_first_r ? ctx_head.packet_counter : current_packet_counter_r;
    assign input_counter_block = {input_salt, input_packet_counter, block_counter_r};
    assign input_initial_state = input_counter_block ^ (expect_first_r ? ctx_head.round_key0 : current_round_key0_r);

    assign meta_rd_addr = s_meta_hs ? s_meta_id : meta_req_sa_r;
    assign datapath_meta_update = meta_req_pending_r && meta_rd_data[META_WIDTH-1] &&
                                  !meta_req_counter_valid_r;
    assign commit_meta_wr_en = (key_state_r == K_WRITE_META) && !meta_update_pending_r;
    assign meta_wr_en = meta_update_pending_r || commit_meta_wr_en;
    assign meta_wr_addr = meta_update_pending_r ? meta_update_addr_r : commit_sa_r;
    assign meta_wr_data = meta_update_pending_r ? meta_update_data_r :
        {1'b1, commit_salt_r, commit_counter_r};

    simple_dual_port_bram #(
        .BRAM_WIDTH (META_WIDTH),
        .BRAM_DEPTH (SA_TABLE_DEPTH)
    ) u_sa_meta_bram (
        .clk    (clk),
        .we_w   (meta_wr_en),
        .addr_w (meta_wr_addr),
        .din_w  (meta_wr_data),
        .addr_r (meta_rd_addr),
        .dout_r (meta_rd_data)
    );

    for (genvar bank = 0; bank <= NUM_ROUNDS; bank++) begin : g_round_key_bram
        simple_dual_port_bram #(
            .BRAM_WIDTH (128),
            .BRAM_DEPTH (SA_TABLE_DEPTH)
        ) u_round_key_bram (
            .clk    (clk),
            .we_w   (round_key_wr_en && (round_key_wr_idx == bank[$bits(round_key_wr_idx)-1:0])),
            .addr_w (round_key_wr_sa),
            .din_w  (round_key_wr_data),
            .addr_r (round_key_rd_addr[bank]),
            .dout_r (round_key_rd_data[bank])
        );
    end

    assign round_key_rd_addr[0] = meta_rd_addr;
    assign round_key_rd_addr[1] = advance_pipeline ?
        (expect_first_r ? (!ctx_empty ? ctx_head.sa_id : meta_rd_addr) : current_sa_r) :
        pipe_sa_id_r[0];
    for (genvar bank = 2; bank <= NUM_ROUNDS; bank++) begin : g_round_key_read_addr
        assign round_key_rd_addr[bank] = advance_pipeline ?
            pipe_sa_id_r[bank-2] : pipe_sa_id_r[bank-1];
    end

    for (genvar stage = 1; stage < PIPE_STAGES; stage++) begin : g_round_stages
        localparam int ROUND_IDX = stage;

        aes_encipher_round_stage #(
            .FINAL_ROUND (ROUND_IDX == NUM_ROUNDS)
        ) u_round_stage (
            .state_in  (pipe_state_r[stage-1]),
            .round_key (round_key_rd_data[stage]),
            .state_out (round_state[stage])
        );
    end

    aes_sbox u_key_expand_sbox (
        .sboxw     (key_sbox_in),
        .new_sboxw (key_sbox_out)
    );

    always_comb begin
        expand_word_lane = expand_word_idx_r[1:0];
        key_temp_word = key_window_r[KEY_WORDS-1];
        key_sbox_in = key_temp_word;

        if (KEY_BITS == 128) begin
            key_word_boundary = (expand_word_idx_r[1:0] == 2'd0);
            key_aes256_midword = 1'b0;
            key_rcon_idx = expand_word_idx_r[5:2];
        end else begin
            key_word_boundary = (expand_word_idx_r[2:0] == 3'd0);
            key_aes256_midword = (expand_word_idx_r[2:0] == 3'd4);
            key_rcon_idx = {1'b0, expand_word_idx_r[5:3]};
        end

        if (key_word_boundary) begin
            key_sbox_in = {key_temp_word[23:0], key_temp_word[31:24]};
        end else if (key_aes256_midword) begin
            key_sbox_in = key_temp_word;
        end
    end

    always_comb begin
        key_transformed_word = key_temp_word;
        if (key_word_boundary) begin
            key_transformed_word = key_sbox_out ^
                {rcon(key_rcon_idx), 24'h0};
        end else if (key_aes256_midword) begin
            key_transformed_word = key_sbox_out;
        end
        key_next_word = key_window_r[0] ^ key_transformed_word;
    end

    always_comb begin
        init_round_base = {write_round_idx_r[0], 2'b00};
        round_key_wr_en = 1'b0;
        round_key_wr_idx = '0;
        round_key_wr_sa = commit_sa_r;
        round_key_wr_data = 128'h0;

        if (key_state_r == K_WRITE_INIT) begin
            round_key_wr_en = 1'b1;
            round_key_wr_idx = write_round_idx_r;
            round_key_wr_data = {
                key_window_r[init_round_base + 3'd0],
                key_window_r[init_round_base + 3'd1],
                key_window_r[init_round_base + 3'd2],
                key_window_r[init_round_base + 3'd3]
            };
        end else if (key_state_r == K_WRITE_ROUND) begin
            round_key_wr_en = 1'b1;
            round_key_wr_idx = pending_round_idx_r;
            round_key_wr_data = pending_round_key_r;
        end
    end

    assign key_busy = (key_state_r != K_IDLE);
    assign axil_wr_addr = ctrl_in.aw.addr;
    assign axil_wr_sa_word = axil_wr_addr >> SA_STRIDE_BITS;
    assign axil_wr_sa = axil_wr_addr[SA_STRIDE_BITS + SA_ID_WIDTH - 1:SA_STRIDE_BITS];
    assign axil_wr_offset = axil_wr_addr[SA_STRIDE_BITS-1:0];
    assign axil_wr_sa_valid = (axil_wr_sa_word < SA_TABLE_DEPTH);

    assign ctrl_in.aw_ready = ctrl_in.w_valid && !axil_b_valid_r && !key_busy;
    assign ctrl_in.w_ready = ctrl_in.aw_valid && !axil_b_valid_r && !key_busy;
    assign ctrl_in.b_valid = axil_b_valid_r;
    assign ctrl_in.b.resp = 2'b00;
    assign ctrl_in.b.user = '0;
    assign ctrl_in.ar_ready = !axil_r_valid_r;
    assign ctrl_in.r_valid = axil_r_valid_r;
    assign ctrl_in.r.data = 32'h0;
    assign ctrl_in.r.resp = 2'b00;
    assign ctrl_in.r.user = '0;

    assign axil_write_fire = ctrl_in.aw_valid && ctrl_in.aw_ready &&
                             ctrl_in.w_valid && ctrl_in.w_ready;
    assign axil_read_fire = ctrl_in.ar_valid && ctrl_in.ar_ready;
    assign commit_request = axil_write_fire && axil_wr_sa_valid &&
                            (axil_wr_offset == '0) && ctrl_in.w.data[0];

    always_ff @(posedge clk) begin
        if (!resetn) begin
            axil_b_valid_r <= 1'b0;
            axil_r_valid_r <= 1'b0;
            stage_salt_r <= 32'h0;
            stage_counter_r <= 64'h0;
            for (int i = 0; i < MAX_KEY_WORDS; i++) begin
                stage_key_words_r[i] <= 32'h0;
            end
        end else begin
            if (axil_b_valid_r && ctrl_in.b_ready) begin
                axil_b_valid_r <= 1'b0;
            end
            if (axil_r_valid_r && ctrl_in.r_ready) begin
                axil_r_valid_r <= 1'b0;
            end

            if (axil_write_fire) begin
                axil_b_valid_r <= 1'b1;
                if (axil_wr_sa_valid) begin
                    unique case (axil_wr_offset)
                        8'h04: stage_salt_r <= ctrl_in.w.data;
                        8'h08: stage_counter_r[31:0] <= ctrl_in.w.data;
                        8'h0c: stage_counter_r[63:32] <= ctrl_in.w.data;
                        8'h20: stage_key_words_r[0] <= ctrl_in.w.data;
                        8'h24: stage_key_words_r[1] <= ctrl_in.w.data;
                        8'h28: stage_key_words_r[2] <= ctrl_in.w.data;
                        8'h2c: stage_key_words_r[3] <= ctrl_in.w.data;
                        8'h30: stage_key_words_r[4] <= ctrl_in.w.data;
                        8'h34: stage_key_words_r[5] <= ctrl_in.w.data;
                        8'h38: stage_key_words_r[6] <= ctrl_in.w.data;
                        8'h3c: stage_key_words_r[7] <= ctrl_in.w.data;
                        default: begin
                        end
                    endcase
                end
            end

            if (axil_read_fire) begin
                axil_r_valid_r <= 1'b1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            key_state_r <= K_IDLE;
            expand_word_idx_r <= '0;
            write_round_idx_r <= '0;
            pending_round_key_r <= '0;
            pending_round_idx_r <= '0;
            commit_sa_r <= '0;
            commit_salt_r <= 32'h0;
            commit_counter_r <= 64'h0;
            for (int i = 0; i < MAX_KEY_WORDS; i++) begin
                key_window_r[i] <= 32'h0;
            end
            for (int i = 0; i < 4; i++) begin
                round_build_r[i] <= 32'h0;
            end
        end else begin
            unique case (key_state_r)
                K_IDLE: begin
                    if (commit_request) begin
                        commit_sa_r <= axil_wr_sa;
                        commit_salt_r <= stage_salt_r;
                        commit_counter_r <= stage_counter_r;
                        for (int i = 0; i < MAX_KEY_WORDS; i++) begin
                            key_window_r[i] <= (i < KEY_WORDS) ? stage_key_words_r[i] : 32'h0;
                        end
                        for (int i = 0; i < 4; i++) begin
                            round_build_r[i] <= 32'h0;
                        end
                        expand_word_idx_r <= KEY_WORDS[5:0];
                        write_round_idx_r <= '0;
                        key_state_r <= K_WRITE_INIT;
                    end
                end

                K_WRITE_INIT: begin
                    if (write_round_idx_r == (INITIAL_KEY_ROUNDS - 1)) begin
                        key_state_r <= K_EXPAND;
                    end else begin
                        write_round_idx_r <= write_round_idx_r + 1'b1;
                    end
                end

                K_EXPAND: begin
                    for (int i = 0; i < KEY_WORDS-1; i++) begin
                        key_window_r[i] <= key_window_r[i+1];
                    end
                    key_window_r[KEY_WORDS-1] <= key_next_word;
                    round_build_r[expand_word_lane] <= key_next_word;
                    if (expand_word_lane == 2'd3) begin
                        pending_round_key_r <= {
                            round_build_r[0],
                            round_build_r[1],
                            round_build_r[2],
                            key_next_word
                        };
                        pending_round_idx_r <= expand_word_idx_r[5:2];
                        key_state_r <= K_WRITE_ROUND;
                    end else begin
                        expand_word_idx_r <= expand_word_idx_r + 6'd1;
                    end
                end

                K_WRITE_ROUND: begin
                    if (expand_word_idx_r == (TOTAL_KEY_WORDS - 1)) begin
                        key_state_r <= K_WRITE_META;
                    end else begin
                        expand_word_idx_r <= expand_word_idx_r + 6'd1;
                        key_state_r <= K_EXPAND;
                    end
                end

                K_WRITE_META: begin
                    if (!meta_update_pending_r) begin
                        key_state_r <= K_IDLE;
                    end
                end

                default: key_state_r <= K_IDLE;
            endcase
        end
    end

    always_comb begin
        meta_resp_valid = meta_req_pending_r;
        meta_resp_ctx = '0;
        meta_resp_ctx.drop = !meta_rd_data[META_WIDTH-1];
        meta_resp_ctx.sa_id = meta_req_sa_r;
        meta_resp_ctx.salt = meta_rd_data[95:64];
        meta_resp_ctx.packet_counter = meta_req_counter_valid_r ?
            meta_req_packet_counter_r : meta_rd_data[63:0];
        meta_resp_ctx.round_key0 = round_key_rd_data[0];
        ctx_push = meta_resp_valid;
        meta_out_push = meta_resp_valid;
        meta_out_push_data = {
            meta_resp_ctx.drop,
            meta_resp_ctx.sa_id,
            meta_resp_ctx.packet_counter
        };
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            meta_req_pending_r <= 1'b0;
            meta_req_sa_r <= '0;
            meta_req_counter_valid_r <= 1'b0;
            meta_req_packet_counter_r <= 64'h0;
            meta_update_pending_r <= 1'b0;
            meta_update_addr_r <= '0;
            meta_update_data_r <= '0;
            ctx_head_r <= '0;
            ctx_tail_r <= '0;
            ctx_count_r <= '0;
            meta_out_head_r <= '0;
            meta_out_tail_r <= '0;
            meta_out_count_r <= '0;
        end else begin
            if (meta_update_pending_r) begin
                meta_update_pending_r <= 1'b0;
            end
            if (datapath_meta_update) begin
                meta_update_pending_r <= 1'b1;
                meta_update_addr_r <= meta_req_sa_r;
                meta_update_data_r <= {
                    1'b1,
                    meta_rd_data[95:64],
                    meta_rd_data[63:32] + {31'd0, &meta_rd_data[31:0]},
                    meta_rd_data[31:0] + 32'd1
                };
            end

            if (s_meta_hs) begin
                meta_req_pending_r <= 1'b1;
                meta_req_sa_r <= s_meta_id;
                meta_req_counter_valid_r <= s_meta_counter_valid;
                meta_req_packet_counter_r <= s_meta_packet_counter;
            end else if (meta_req_pending_r) begin
                meta_req_pending_r <= 1'b0;
            end

            if (ctx_push) begin
                ctx_fifo_r[ctx_tail_r] <= meta_resp_ctx;
                ctx_tail_r <= ctx_tail_r + 1'b1;
            end
            if (ctx_pop) begin
                ctx_head_r <= ctx_head_r + 1'b1;
            end
            unique case ({ctx_push, ctx_pop})
                2'b10: ctx_count_r <= ctx_count_r + 1'b1;
                2'b01: ctx_count_r <= ctx_count_r - 1'b1;
                default: begin
                end
            endcase

            if (meta_out_push) begin
                meta_out_fifo_r[meta_out_tail_r] <= meta_out_push_data;
                meta_out_tail_r <= meta_out_tail_r + 1'b1;
            end
            if (meta_out_pop) begin
                meta_out_head_r <= meta_out_head_r + 1'b1;
            end
            unique case ({meta_out_push, meta_out_pop})
                2'b10: meta_out_count_r <= meta_out_count_r + 1'b1;
                2'b01: meta_out_count_r <= meta_out_count_r - 1'b1;
                default: begin
                end
            endcase
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            current_sa_r <= '0;
            current_salt_r <= 32'h0;
            current_packet_counter_r <= 64'h0;
            current_round_key0_r <= 128'h0;
            current_drop_r <= 1'b0;
            block_counter_r <= 32'h0;
            expect_first_r <= 1'b1;
            pipe_valid_r <= '0;
            pipe_state_r <= '0;
            pipe_packet_data_r <= '0;
            pipe_packet_keep_r <= '0;
            pipe_packet_last_r <= '0;
            pipe_sa_id_r <= '0;
        end else begin
            if (advance_pipeline) begin
                pipe_valid_r[0] <= pipe_insert;
                if (pipe_insert) begin
                    pipe_state_r[0] <= input_initial_state;
                    pipe_packet_data_r[0] <= s_axis_packet.t.data;
                    pipe_packet_keep_r[0] <= s_axis_packet.t.keep;
                    pipe_packet_last_r[0] <= s_axis_packet.t.last;
                    pipe_sa_id_r[0] <= input_sa_id;
                end

                for (int stage = 1; stage < PIPE_STAGES; stage++) begin
                    pipe_valid_r[stage] <= pipe_valid_r[stage-1];
                    if (pipe_valid_r[stage-1]) begin
                        pipe_state_r[stage] <= round_state[stage];
                        pipe_packet_data_r[stage] <= pipe_packet_data_r[stage-1];
                        pipe_packet_keep_r[stage] <= pipe_packet_keep_r[stage-1];
                        pipe_packet_last_r[stage] <= pipe_packet_last_r[stage-1];
                        pipe_sa_id_r[stage] <= pipe_sa_id_r[stage-1];
                    end
                end
            end

            if (packet_hs) begin
                if (first_hs) begin
                    current_sa_r <= ctx_head.sa_id;
                    current_salt_r <= ctx_head.salt;
                    current_packet_counter_r <= ctx_head.packet_counter;
                    current_round_key0_r <= ctx_head.round_key0;
                    current_drop_r <= ctx_head.drop;
                    block_counter_r <= 32'h0;
                end

                if (s_axis_packet.t.last) begin
                    expect_first_r <= 1'b1;
                    current_drop_r <= 1'b0;
                    block_counter_r <= 32'h0;
                end else begin
                    expect_first_r <= 1'b0;
                    if (!input_drop) begin
                        block_counter_r <= block_counter_r + 32'd1;
                    end
                end
            end
        end
    end

endmodule
