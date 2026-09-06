`ifndef ADDER_TREE_ONE_COMPLEMENT_AXIS_SV
`define ADDER_TREE_ONE_COMPLEMENT_AXIS_SV

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"

module oc_adder_tree_axis_level #(
    parameter int MAX_WORDS = 32,
    parameter int WORDS_IN = 32,
    parameter int SUM_WIDTH = 16,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16,
    parameter int TUSER_WIDTH = 16
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int DATA_WIDTH = MAX_WORDS * SUM_WIDTH;
    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int WORDS_OUT = (WORDS_IN > 1) ? (WORDS_IN / 2) : 1;
    localparam int PIPE_STAGES = 1;
    typedef logic [SUM_WIDTH-1:0] sum_t;

    `AXIS_T_CHAN_STRUCT(DATA_WIDTH, KEEP_WIDTH, TID_WIDTH, TDEST_WIDTH, TUSER_WIDTH, level_chan_t);

    typedef struct packed {
        logic [TID_WIDTH-1:0]   id;
        logic [TDEST_WIDTH-1:0] dest;
        logic [TUSER_WIDTH-1:0] user;
        logic                   last;
    } meta_t;

    generate
        if (WORDS_IN <= 1) begin : g_word_passthrough
            assign s_axis.tready = m_axis.tready;
            assign m_axis.tvalid = s_axis.tvalid;
            assign m_axis.t      = s_axis.t;
        end else begin : g_word_reduce
            meta_t meta_in;
            meta_t meta_out;
            logic [WORDS_OUT-1:0] pair_in_ready;
            logic [WORDS_OUT-1:0] pair_out_valid;
            logic [SUM_WIDTH-1:0] pair_sum[0:WORDS_OUT-1];

            logic meta_in_ready;
            logic meta_out_valid;
            logic pair_accept_ready;
            logic pair_emit_valid;

            assign meta_in.id   = s_axis.t.id;
            assign meta_in.dest = s_axis.t.dest;
            assign meta_in.user = s_axis.t.user;
            assign meta_in.last = s_axis.t.last;

            for (genvar gp = 0; gp < WORDS_OUT; gp++) begin : g_pairs
                pipelined_oc_adder_axis #(
                    .T(sum_t)
                ) u_pair_add (
                    .clk    (clk),
                    .resetn (resetn),
                    .add_a  (s_axis.t.data[(2 * gp) * SUM_WIDTH+:SUM_WIDTH]),
                    .add_b  (s_axis.t.data[(2 * gp + 1) * SUM_WIDTH+:SUM_WIDTH]),
                    .s_valid(s_axis.tvalid && meta_in_ready),
                    .s_ready(pair_in_ready[gp]),
                    .m_valid(pair_out_valid[gp]),
                    .m_ready(meta_out_valid && m_axis.tready),
                    .sum    (pair_sum[gp])
                );
            end

            assign pair_accept_ready = &pair_in_ready;
            assign pair_emit_valid   = &pair_out_valid;

            assign s_axis.tready = pair_accept_ready && meta_in_ready;
            assign m_axis.tvalid = pair_emit_valid && meta_out_valid;
            assign m_axis.t.id   = meta_out.id;
            assign m_axis.t.dest = meta_out.dest;
            assign m_axis.t.user = meta_out.user;
            assign m_axis.t.last = meta_out.last;
            assign m_axis.t.keep = '1;

            for (genvar gp = 0; gp < WORDS_OUT; gp++) begin : g_out_words
                assign m_axis.t.data[gp*SUM_WIDTH+:SUM_WIDTH] = pair_sum[gp];
            end

            if (PIPE_STAGES <= 0) begin : g_meta_bypass
                assign meta_in_ready  = m_axis.tready && pair_emit_valid;
                assign meta_out       = meta_in;
                assign meta_out_valid = s_axis.tvalid && pair_accept_ready;
            end else begin : g_meta_pipe
                meta_t meta_push_data [PIPE_STAGES];
                logic  meta_push_valid[PIPE_STAGES];
                logic  meta_push_ready[PIPE_STAGES];
                meta_t meta_pop_data  [PIPE_STAGES];
                logic  meta_pop_valid [PIPE_STAGES];
                logic  meta_pop_ready [PIPE_STAGES];

                assign meta_push_data[0]  = meta_in;
                assign meta_push_valid[0] = s_axis.tvalid && pair_accept_ready;
                assign meta_in_ready      = meta_push_ready[0];
                assign meta_out           = meta_pop_data[PIPE_STAGES-1];
                assign meta_out_valid     = meta_pop_valid[PIPE_STAGES-1];
                assign meta_pop_ready[PIPE_STAGES-1] = pair_emit_valid && m_axis.tready;

                for (genvar gm = 0; gm < PIPE_STAGES; gm++) begin : g_meta_stage
                    register_slice #(
                        .T(meta_t)
                    ) u_meta_reg (
                        .clk       (clk),
                        .resetn    (resetn),
                        .push_valid(meta_push_valid[gm]),
                        .push_data (meta_push_data[gm]),
                        .push_ready(meta_push_ready[gm]),
                        .pop_valid (meta_pop_valid[gm]),
                        .pop_data  (meta_pop_data[gm]),
                        .pop_ready (meta_pop_ready[gm])
                    );
                    if (gm < PIPE_STAGES - 1) begin : g_meta_link
                        assign meta_push_data[gm+1]  = meta_pop_data[gm];
                        assign meta_push_valid[gm+1] = meta_pop_valid[gm];
                        assign meta_pop_ready[gm]    = meta_push_ready[gm+1];
                    end
                end
            end
        end
    endgenerate

endmodule

module oc_adder_tree_axis_accumulator #(
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16,
    parameter int TUSER_WIDTH = 16,
    parameter int SUM_WIDTH = 16,
    parameter int M_AXIS_DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int M_KEEP_WIDTH = M_AXIS_DATA_WIDTH / 8;

    `AXIS_T_CHAN_STRUCT(M_AXIS_DATA_WIDTH, M_KEEP_WIDTH, TID_WIDTH, TDEST_WIDTH, TUSER_WIDTH, m_chan_t);
    typedef logic [SUM_WIDTH-1:0] sum_t;

    sum_t acc_state;
    logic acc_state_valid;
    logic add_inflight;
    logic inflight_last;
    logic [TID_WIDTH-1:0] inflight_id;
    logic [TDEST_WIDTH-1:0] inflight_dest;
    logic [TUSER_WIDTH-1:0] inflight_user;

    logic emit_ready;
    logic emit_valid;
    m_chan_t emit_beat;
    logic direct_emit_valid;
    m_chan_t direct_emit_beat;
    logic add_emit_valid;
    m_chan_t add_emit_beat;
    logic add_in_ready;
    logic add_out_valid;
    logic [SUM_WIDTH-1:0] add_out_sum;
    logic s_accept;
    logic s_ready_int;
    logic s_continue_packet;
    logic add_complete;
    logic add_complete_last;
    logic add_complete_nonlast;
    logic add_pipe_available;
    logic carry_state_valid;
    logic [SUM_WIDTH-1:0] carry_state_sum;
    logic launch_add;

    pipelined_oc_adder_axis #(
        .T(sum_t)
    ) u_acc_add (
        .clk    (clk),
        .resetn (resetn),
        .add_a  (carry_state_sum),
        .add_b  (s_axis.t.data[0+:SUM_WIDTH]),
        .s_valid(launch_add),
        .s_ready(add_in_ready),
        .m_valid(add_out_valid),
        .m_ready((!inflight_last) || emit_ready),
        .sum    (add_out_sum)
    );

    always_comb begin
        direct_emit_beat = '0;
        direct_emit_beat.data[0+:SUM_WIDTH] = ~s_axis.t.data[0+:SUM_WIDTH];
        direct_emit_beat.keep = '1;
        direct_emit_beat.id   = s_axis.t.id;
        direct_emit_beat.dest = s_axis.t.dest;
        direct_emit_beat.user = s_axis.t.user;
        direct_emit_beat.last = 1'b1;

        add_emit_beat = '0;
        add_emit_beat.data[0+:SUM_WIDTH] = ~add_out_sum;
        add_emit_beat.keep = '1;
        add_emit_beat.id   = inflight_id;
        add_emit_beat.dest = inflight_dest;
        add_emit_beat.user = inflight_user;
        add_emit_beat.last = 1'b1;

        emit_beat  = add_emit_valid ? add_emit_beat : direct_emit_beat;
    end

    assign add_complete         = add_out_valid && ((!inflight_last) || emit_ready);
    assign add_complete_last    = add_complete && inflight_last;
    assign add_complete_nonlast = add_complete && !inflight_last;
    assign add_pipe_available   = !add_inflight || add_complete;
    assign carry_state_valid =
        add_complete_nonlast ? 1'b1 :
        add_complete_last    ? 1'b0 :
        acc_state_valid;
    assign carry_state_sum = add_complete_nonlast ? add_out_sum : acc_state;
    assign launch_add      = s_axis.tvalid && carry_state_valid && add_in_ready &&
        add_pipe_available;
    assign add_emit_valid  = add_out_valid && inflight_last;
    assign direct_emit_valid = s_axis.tvalid && !carry_state_valid && s_axis.t.last;
    assign emit_valid      = add_emit_valid || direct_emit_valid;

    assign s_ready_int =
        carry_state_valid ? (add_in_ready && add_pipe_available) :
        (!s_axis.t.last || ((!add_emit_valid) && emit_ready));
    assign s_axis.tready     = s_ready_int;
    assign s_accept          = s_axis.tvalid && s_ready_int;
    assign s_continue_packet = s_accept && carry_state_valid;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            acc_state       <= '0;
            acc_state_valid <= 1'b0;
            add_inflight    <= 1'b0;
        end else begin
            if (launch_add) begin
                add_inflight  <= 1'b1;
                inflight_last <= s_axis.t.last;
                inflight_id   <= s_axis.t.id;
                inflight_dest <= s_axis.t.dest;
                inflight_user <= s_axis.t.user;
            end else if (add_complete) begin
                add_inflight <= 1'b0;
            end

            if (s_accept) begin
                if (s_continue_packet) begin
                    if (add_complete_last) begin
                        acc_state       <= '0;
                        acc_state_valid <= 1'b0;
                    end else begin
                        acc_state       <= carry_state_sum;
                        acc_state_valid <= 1'b1;
                    end
                end else if (!s_axis.t.last) begin
                    acc_state       <= s_axis.t.data[0+:SUM_WIDTH];
                    acc_state_valid <= 1'b1;
                end else begin
                    acc_state       <= '0;
                    acc_state_valid <= 1'b0;
                end
            end else if (add_complete) begin
                if (inflight_last) begin
                    acc_state       <= '0;
                    acc_state_valid <= 1'b0;
                end else begin
                    acc_state       <= add_out_sum;
                    acc_state_valid <= 1'b1;
                end
            end
        end
    end

    assign emit_ready    = m_axis.tready;
    assign m_axis.tvalid = emit_valid;
    assign m_axis.t      = emit_beat;

endmodule

// One's-complement checksum generator over AXIS packet beats.
// - Input beat bytes are packed into 16-bit words with tkeep masking.
// - Every binary tree level is now an elastic valid/ready stage carrying data and metadata together.
// - Packet accumulation is kept separate and only backpressures packet-final beats when checksum output stalls.
module oc_adder_tree_axis #(
    parameter int IN_DATA_WIDTH = 512,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16,
    parameter int TUSER_WIDTH = 16,
    parameter int SUM_WIDTH = 16,
    parameter int M_AXIS_DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    typedef logic [SUM_WIDTH-1:0] sum_t;

    localparam int NUM_LEAF_WORDS = IN_DATA_WIDTH / 16;
    localparam int PADDED_LEAVES = (NUM_LEAF_WORDS <= 1) ? 1 : (1 << $clog2(NUM_LEAF_WORDS));
    localparam int TREE_DEPTH_USED = (PADDED_LEAVES <= 1) ? 0 : $clog2(PADDED_LEAVES);
    localparam int INTERNAL_DATA_WIDTH = PADDED_LEAVES * SUM_WIDTH;

    `AXIS_T_CHAN_STRUCT(INTERNAL_DATA_WIDTH, INTERNAL_DATA_WIDTH / 8, TID_WIDTH, TDEST_WIDTH, TUSER_WIDTH, tree_chan_t);

    tree_chan_t leaf_beat;

    always_comb begin
        leaf_beat = '0;
        leaf_beat.keep = '1;
        leaf_beat.id   = s_axis.t.id;
        leaf_beat.dest = s_axis.t.dest;
        leaf_beat.user = s_axis.t.user;
        leaf_beat.last = s_axis.t.last;

        for (int wi = 0; wi < NUM_LEAF_WORDS; wi++) begin
            int bi0;
            int bi1;
            logic [7:0] b0;
            logic [7:0] b1;
            logic       k0;
            logic       k1;

            bi0 = wi * 2;
            bi1 = wi * 2 + 1;
            b0  = s_axis.t.data[8*bi0+:8];
            b1  = s_axis.t.data[8*bi1+:8];
            k0  = s_axis.t.keep[bi0];
            k1  = s_axis.t.keep[bi1];

            leaf_beat.data[wi*SUM_WIDTH+:SUM_WIDTH] = sum_t'({k1 ? b1 : 8'h00, k0 ? b0 : 8'h00});
        end
    end

    ifc_axis #(
        .DATA_WIDTH  (INTERNAL_DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) tree_axis [0:TREE_DEPTH_USED] (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (INTERNAL_DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) tree_level_raw [0:TREE_DEPTH_USED] (.axis_aclk(clk));

    assign tree_axis[0].t      = leaf_beat;
    assign tree_axis[0].tvalid = s_axis.tvalid;
    assign s_axis.tready       = tree_axis[0].tready;

    generate
        for (genvar gl = 0; gl < TREE_DEPTH_USED; gl++) begin : g_levels
            localparam int WORDS_AT_LEVEL = PADDED_LEAVES >> gl;
            oc_adder_tree_axis_level #(
                .MAX_WORDS  (PADDED_LEAVES),
                .WORDS_IN   (WORDS_AT_LEVEL),
                .SUM_WIDTH  (SUM_WIDTH),
                .TDEST_WIDTH(TDEST_WIDTH),
                .TID_WIDTH  (TID_WIDTH),
                .TUSER_WIDTH(TUSER_WIDTH)
            ) u_level (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (tree_axis[gl]),
                .m_axis (tree_level_raw[gl+1])
            );

            axis_register_slice #(
                .MODE ("ISOLATE"),
                .NUM_STAGES (2)
            ) u_level_timing_cut (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (tree_level_raw[gl+1]),
                .m_axis (tree_axis[gl+1])
            );
        end
    endgenerate

    ifc_axis #(
        .DATA_WIDTH  (M_AXIS_DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) acc_axis_raw (.axis_aclk(clk));

    oc_adder_tree_axis_accumulator #(
        .TDEST_WIDTH      (TDEST_WIDTH),
        .TID_WIDTH        (TID_WIDTH),
        .TUSER_WIDTH      (TUSER_WIDTH),
        .SUM_WIDTH        (SUM_WIDTH),
        .M_AXIS_DATA_WIDTH(M_AXIS_DATA_WIDTH)
    ) u_accumulator (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (tree_axis[TREE_DEPTH_USED]),
        .m_axis (acc_axis_raw)
    );

    axis_register_slice #(
        .MODE ("ISOLATE"),
        .NUM_STAGES (2)
    ) u_acc_output_stage (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (acc_axis_raw),
        .m_axis (m_axis)
    );

endmodule

`endif
