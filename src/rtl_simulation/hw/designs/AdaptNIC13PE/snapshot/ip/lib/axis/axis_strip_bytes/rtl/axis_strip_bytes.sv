// Strip the first N bytes from densely packed AXI Stream packets.
//
// One remove-count beat is consumed for each packet.  Output beat boundaries
// follow input beat boundaries, except beats made empty by stripping are
// suppressed.

`include "ifc_axis.sv"

module axis_strip_bytes #(
    parameter int DATA_WIDTH  = 512,
    parameter int STRIP_WIDTH = 10
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.slave  s_axis_remove,
    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int SHIFT_WIDTH = $clog2(KEEP_WIDTH + 1);
    localparam int DATA_SHIFT_WIDTH = $clog2(DATA_WIDTH + 1);

    typedef struct packed {
        logic [DATA_SHIFT_WIDTH-1:0] data;
        logic [SHIFT_WIDTH-1:0]      keep;
    } shift_meta_t;

    initial begin
        if ((DATA_WIDTH % 8) != 0)
            $error("axis_strip_bytes: DATA_WIDTH (%0d) must be a multiple of 8", DATA_WIDTH);
        // if ((STRIP_WIDTH % 8) != 0)
        //     $error("axis_strip_bytes: STRIP_WIDTH (%0d) must be a multiple of 8", STRIP_WIDTH);
        if ($bits(s_axis_remove.t.data) != STRIP_WIDTH)
            $error("axis_strip_bytes: s_axis_remove DATA_WIDTH must equal STRIP_WIDTH (%0d)", STRIP_WIDTH);
        if (STRIP_WIDTH > DATA_WIDTH)
            $error("axis_strip_bytes: STRIP_WIDTH (%0d) must be <= DATA_WIDTH (%0d)",
                   STRIP_WIDTH, DATA_WIDTH);
    end

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(s_axis.TDEST_WIDTH),
        .TID_WIDTH(s_axis.TID_WIDTH),
        .TUSER_WIDTH(s_axis.TUSER_WIDTH)
    ) u_packet_in (clk), u_packet_q (clk);

    shift_meta_t            shift_push_data;
    shift_meta_t            shift_pop_data;
    logic                   shift_push_valid;
    logic                   shift_push_ready;
    logic                   shift_pop_valid;
    logic                   shift_pop_ready;

    logic                   in_packet_r;
    logic [STRIP_WIDTH-1:0] remove_remaining_r;
    logic [STRIP_WIDTH-1:0] current_remove;
    logic [SHIFT_WIDTH-1:0] beat_shift;
    logic                   input_fire;
    logic                   input_context_valid;

    always_comb begin
        current_remove = in_packet_r ? remove_remaining_r : s_axis_remove.t.data;
        if (current_remove >= STRIP_WIDTH'(KEEP_WIDTH))
            beat_shift = SHIFT_WIDTH'(KEEP_WIDTH);
        else
            beat_shift = SHIFT_WIDTH'(current_remove);

        input_context_valid = in_packet_r || s_axis_remove.tvalid;

        u_packet_in.t = s_axis.t;
        u_packet_in.tvalid = s_axis.tvalid && input_context_valid && shift_push_ready;
        s_axis.tready = u_packet_in.tready && input_context_valid && shift_push_ready;

        shift_push_data.data = DATA_SHIFT_WIDTH'(beat_shift) << 3;
        shift_push_data.keep = beat_shift;
        shift_push_valid = s_axis.tvalid && input_context_valid && u_packet_in.tready;

        s_axis_remove.tready = !in_packet_r && s_axis.tvalid &&
                               u_packet_in.tready && shift_push_ready;
        input_fire = s_axis.tvalid && s_axis.tready;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            in_packet_r        <= 1'b0;
            remove_remaining_r <= '0;
        end else if (input_fire) begin
            if (s_axis.t.last) begin
                in_packet_r        <= 1'b0;
                remove_remaining_r <= '0;
            end else begin
                in_packet_r <= 1'b1;
                if (current_remove > STRIP_WIDTH'(KEEP_WIDTH))
                    remove_remaining_r <= current_remove - STRIP_WIDTH'(KEEP_WIDTH);
                else
                    remove_remaining_r <= '0;
            end
        end
    end

    // synthesis translate_off
    always_ff @(posedge clk) begin
        if (resetn && input_fire) begin
            if (!s_axis.t.last)
                assert (s_axis.t.keep == '1)
                    else $error("axis_strip_bytes: non-final input beat must be full");
            else
                assert ((s_axis.t.keep & (s_axis.t.keep + 1'b1)) == '0)
                    else $error("axis_strip_bytes: final tkeep must be lower-contiguous");
        end
    end
    // synthesis translate_on

    axis_fifo #(
        .DEPTH(8), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")
    ) u_packet_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_packet_in), .m_axis(u_packet_q)
    );

    sync_ff_fifo #(
        .DEPTH(8), .T(shift_meta_t), .MODE("CONSERVATIVE")
    ) u_shift_fifo (
        .clk       (clk),
        .resetn    (resetn),
        .push_valid(shift_push_valid),
        .push_data (shift_push_data),
        .push_ready(shift_push_ready),
        .pop_valid (shift_pop_valid),
        .pop_data  (shift_pop_data),
        .pop_ready (shift_pop_ready)
    );

    logic [DATA_WIDTH-1:0] shifted_data;
    logic [KEEP_WIDTH-1:0] shifted_keep;

    localparam int BEAT_COUNT_WIDTH = $clog2(DATA_WIDTH);

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_count_input (clk);

    ifc_axis #(
        .DATA_WIDTH(BEAT_COUNT_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_beat_count (clk);

    logic                  payload_stage1_valid_r;
    logic [DATA_WIDTH-1:0] payload_stage1_data_r;
    logic [KEEP_WIDTH-1:0] payload_stage1_keep_r;
    logic                  payload_stage1_last_r;
    logic                  payload_stage2_valid_r;
    logic [DATA_WIDTH-1:0] payload_stage2_data_r;
    logic [KEEP_WIDTH-1:0] payload_stage2_keep_r;
    logic                  payload_stage2_last_r;
    logic                  payload_stage3_valid_r;
    logic [DATA_WIDTH-1:0] payload_stage3_data_r;
    logic [KEEP_WIDTH-1:0] payload_stage3_keep_r;
    logic                  payload_stage3_last_r;
    logic                  payload_stage1_ready;
    logic                  payload_stage2_ready;
    logic                  payload_stage3_ready;
    logic                  counted_nonempty;
    logic                  counted_ready;

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_emit (clk), u_emitted (clk);

    always_comb begin
        shifted_data = u_packet_q.t.data >> shift_pop_data.data;
        shifted_keep = u_packet_q.t.keep >> shift_pop_data.keep;

        u_count_input.t = '0;
        u_count_input.t.data = shifted_data;
        u_count_input.t.keep = shifted_keep;
        u_count_input.t.last = u_packet_q.t.last;
        u_count_input.tvalid = u_packet_q.tvalid && shift_pop_valid;

        // Packet and shift entries advance together when the count pipeline
        // accepts their shifted beat.
        u_packet_q.tready = shift_pop_valid && u_count_input.tready;
        shift_pop_ready = u_packet_q.tvalid && u_count_input.tready;

        u_emit.t = '0;
        u_emit.t.data = payload_stage3_data_r;
        u_emit.t.keep = payload_stage3_keep_r;
        u_emit.t.last = payload_stage3_last_r;
        u_emit.tvalid = u_beat_count.tvalid && payload_stage3_valid_r && counted_nonempty;
    end

    axis_count_beat_size #(
        .DATA_WIDTH(DATA_WIDTH)
    ) u_count_beat_size (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_count_input.slave),
        .m_axis (u_beat_count.master)
    );

    // Delay the shifted payload through the same three elastic stages as the
    // beat-size counter so the count and payload remain aligned.
    assign counted_nonempty = u_beat_count.t.data != '0;
    assign counted_ready = !counted_nonempty || u_emit.tready;
    assign u_beat_count.tready = counted_ready;

    assign payload_stage3_ready = !payload_stage3_valid_r || counted_ready;
    assign payload_stage2_ready = !payload_stage2_valid_r || payload_stage3_ready;
    assign payload_stage1_ready = !payload_stage1_valid_r || payload_stage2_ready;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            payload_stage1_valid_r <= 1'b0;
            payload_stage2_valid_r <= 1'b0;
            payload_stage3_valid_r <= 1'b0;
        end else begin
            if (payload_stage3_ready) begin
                payload_stage3_valid_r <= payload_stage2_valid_r;
                if (payload_stage2_valid_r) begin
                    payload_stage3_data_r <= payload_stage2_data_r;
                    payload_stage3_keep_r <= payload_stage2_keep_r;
                    payload_stage3_last_r <= payload_stage2_last_r;
                end
            end

            if (payload_stage2_ready) begin
                payload_stage2_valid_r <= payload_stage1_valid_r;
                if (payload_stage1_valid_r) begin
                    payload_stage2_data_r <= payload_stage1_data_r;
                    payload_stage2_keep_r <= payload_stage1_keep_r;
                    payload_stage2_last_r <= payload_stage1_last_r;
                end
            end

            if (payload_stage1_ready) begin
                payload_stage1_valid_r <= u_count_input.tvalid;
                if (u_count_input.tvalid) begin
                    payload_stage1_data_r <= u_count_input.t.data;
                    payload_stage1_keep_r <= u_count_input.t.keep;
                    payload_stage1_last_r <= u_count_input.t.last;
                end
            end
        end
    end

    axis_fifo #(
        .DEPTH(4), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")
    ) u_output_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_emit), .m_axis(u_emitted)
    );

    always_comb begin
        m_axis.t = '0;
        m_axis.t.data = u_emitted.t.data;
        m_axis.t.keep = u_emitted.t.keep;
        m_axis.t.last = u_emitted.t.last;
        m_axis.tvalid = u_emitted.tvalid;
        u_emitted.tready = m_axis.tready;
    end

endmodule
