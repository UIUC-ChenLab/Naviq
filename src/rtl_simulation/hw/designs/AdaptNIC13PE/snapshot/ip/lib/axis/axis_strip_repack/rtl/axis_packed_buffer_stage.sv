`include "ifc_axis.sv"
`include "axi_struct_macros.svh"

module axis_packed_buffer_stage #(
    parameter int DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int BUF_BYTES  = 2 * KEEP_WIDTH;
    localparam int BUF_BITS   = 8 * BUF_BYTES;
    localparam int COUNT_W    = $clog2(BUF_BYTES + 1);

    `AXIS_T_CHAN_STRUCT(DATA_WIDTH, KEEP_WIDTH, 1, 1, 1, beat_t);

    typedef logic [DATA_WIDTH-1:0] data_t;
    typedef logic [KEEP_WIDTH-1:0] keep_t;
    typedef logic [BUF_BITS-1:0]   buf_t;
    typedef logic [COUNT_W-1:0]    count_t;

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /* verilator lint_off VARHIDDEN */
    function automatic int unsigned count_keep_ones(input keep_t keep);
        int unsigned c;
        begin
            c = 0;
            for (int i = 0; i < KEEP_WIDTH; i++) begin
                c += keep[i];
            end
            return c;
        end
    endfunction
    /* verilator lint_on VARHIDDEN */

    function automatic keep_t keep_from_count(input count_t count);
        return (count >= count_t'(KEEP_WIDTH))
            ? {KEEP_WIDTH{1'b1}}
            : keep_t'((keep_t'(1) << count) - 1);
    endfunction

    function automatic data_t low_data_from_buf(input buf_t b);
        data_t out;
        begin
            out = b[DATA_WIDTH-1:0];
            return out;
        end
    endfunction

    function automatic buf_t shift_buf_right_bytes(
        input buf_t        b,
        input int unsigned shift_bytes
    );
        buf_t out;
        begin
            out = '0;
            for (int i = 0; i < BUF_BYTES; i++) begin
                if ((i + shift_bytes) < BUF_BYTES)
                    out[i*8 +: 8] = b[(i + shift_bytes)*8 +: 8];
            end
            return out;
        end
    endfunction

    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------

    buf_t                 buf_data_r,         buf_data_n;
    count_t               buf_count_r,        buf_count_n;
    logic                 buf_last_pending_r, buf_last_pending_n;
    logic                 pkt_open_r,         pkt_open_n;

    logic                 out_valid_r, out_valid_n;
    beat_t                out_beat_r,  out_beat_n;

    assign m_axis.tvalid = out_valid_r;
    assign m_axis.t      = out_beat_r;

    logic out_fire;
    assign out_fire = out_valid_r && m_axis.tready;

    // -------------------------------------------------------------------------
    // Input-side derived values
    // -------------------------------------------------------------------------

    int unsigned in_valid_bytes;
    logic        in_nonempty;

    always_comb begin
        in_valid_bytes = count_keep_ones(s_axis.t.keep);
        in_nonempty    = (in_valid_bytes != 0);
    end

    // Accept when buffer has room, or when a drain this cycle will free space.
    // Forward-path only (downstream tready → upstream tready); no comb loop
    // because the output register stage decouples tready from tvalid.
    logic can_drain_this_cycle;
    logic out_slot_available;
    logic can_accept_after_last_pending;
    logic stalled_last_outstanding;

    assign out_slot_available = !out_valid_r || m_axis.tready;
    assign can_drain_this_cycle = (buf_count_r >= count_t'(KEEP_WIDTH))
                                && out_slot_available;
    assign stalled_last_outstanding = out_valid_r && out_beat_r.last && !m_axis.tready;
    // Once input tlast has been accepted for the buffered packet, do not append the next
    // packet until the remaining bytes of the finished packet can be staged out completely.
    assign can_accept_after_last_pending =
        !buf_last_pending_r || (out_slot_available && (buf_count_r <= count_t'(KEEP_WIDTH)));
    assign s_axis.tready = !stalled_last_outstanding
                         && can_accept_after_last_pending
                         && ((buf_count_r <= count_t'(KEEP_WIDTH)) || can_drain_this_cycle);

    logic in_fire;
    assign in_fire = s_axis.tvalid && s_axis.tready;

    // -------------------------------------------------------------------------
    // Pre-shifted input for barrel-shift + OR append (ideas 1+2)
    // -------------------------------------------------------------------------
    // Mask input data so invalid byte lanes are zero (safe for OR-merge).
    data_t masked_in_data;
    always_comb begin
        for (int i = 0; i < KEEP_WIDTH; i++) begin
            masked_in_data[i*8 +: 8] = s_axis.t.data[i*8 +: 8] & {8{s_axis.t.keep[i]}};
        end
    end

    // Barrel-shift by registered buf_count_r: starts at clock edge, no
    // combinational dependency on the drain decision.
    buf_t input_at_count_r;
    assign input_at_count_r = buf_t'(masked_in_data) << (buf_count_r * 8);

    // Post-drain append offset: after a case-A drain the residual is
    // buf_count_r - KEEP_WIDTH; after a case-B partial-last drain the
    // buffer is zeroed so the offset is 0.  Both use only registered
    // values, so this barrel shift also starts at the clock edge.
    count_t post_drain_count;
    assign post_drain_count = (buf_count_r >= count_t'(KEEP_WIDTH))
                            ? count_t'(buf_count_r - count_t'(KEEP_WIDTH))
                            : '0;
    buf_t input_post_drain;
    assign input_post_drain = buf_t'(masked_in_data) << (post_drain_count * 8);

    logic did_drain;
    logic emit_full_last;

    // -------------------------------------------------------------------------
    // Next-state logic
    // -------------------------------------------------------------------------

    always_comb begin
        // defaults
        buf_data_n         = buf_data_r;
        buf_count_n        = buf_count_r;
        buf_last_pending_n = buf_last_pending_r;
        pkt_open_n         = pkt_open_r;

        out_valid_n        = out_valid_r;
        out_beat_n         = out_beat_r;
        did_drain          = 1'b0;
        emit_full_last     = 1'b0;

        // ------------------------------------------------------------
        // 1) Consume output register if downstream fired
        // ------------------------------------------------------------
        if (out_fire) begin
            out_valid_n = 1'b0;
            out_beat_n  = '0;
        end

        // ------------------------------------------------------------
        // 2) If output register will be empty, form next output from buffer
        // ------------------------------------------------------------
        if (!out_valid_n) begin
            if (buf_count_n >= KEEP_WIDTH) begin
                did_drain          = 1'b1;
                emit_full_last     = buf_last_pending_n && (buf_count_n == count_t'(KEEP_WIDTH));
                out_valid_n        = 1'b1;
                out_beat_n         = '0;
                out_beat_n.data    = low_data_from_buf(buf_data_n);
                out_beat_n.keep    = {KEEP_WIDTH{1'b1}};
                out_beat_n.last    = emit_full_last;

                buf_data_n         = shift_buf_right_bytes(buf_data_n, KEEP_WIDTH);
                buf_count_n        = count_t'(unsigned'(buf_count_n) - unsigned'(KEEP_WIDTH));

                if (emit_full_last) begin
                    buf_last_pending_n = 1'b0;
                    pkt_open_n         = 1'b0;
                end
            end
            else if (buf_last_pending_n && (buf_count_n > 0)) begin
                did_drain          = 1'b1;
                out_valid_n        = 1'b1;
                out_beat_n         = '0;
                out_beat_n.data    = low_data_from_buf(buf_data_n);
                out_beat_n.keep    = keep_from_count(buf_count_n);
                out_beat_n.last    = 1'b1;

                buf_data_n         = '0;
                buf_count_n        = '0;
                buf_last_pending_n = 1'b0;
                pkt_open_n         = 1'b0;
            end
            else if (buf_last_pending_n && (buf_count_n == 0)) begin
                // whole packet stripped away / empty after buffering
                buf_last_pending_n = 1'b0;
                pkt_open_n         = 1'b0;
            end
        end

        // ------------------------------------------------------------
        // 3) Accept new input beat into packed buffer
        // ------------------------------------------------------------
        if (in_fire) begin
            // Metadata belongs to the currently open input packet, not to whether the
            // packed-byte buffer happens to be momentarily empty after a full-beat drain.
            if (!pkt_open_n)
                pkt_open_n = 1'b1;

            if (in_valid_bytes > 0) begin
                // Both barrel shifts use only registered values; the late
                // 1-bit did_drain mux is the only logic waiting on the
                // drain decision.
                buf_data_n  = buf_data_n | (did_drain ? input_post_drain
                                                      : input_at_count_r);
                buf_count_n = count_t'(unsigned'(buf_count_n) + unsigned'(in_valid_bytes));
            end

            if (s_axis.t.last)
                buf_last_pending_n = 1'b1;
        end

        // ------------------------------------------------------------
        // 4) If append filled the buffer enough to emit, stage output
        //    immediately instead of waiting an extra cycle.
        // ------------------------------------------------------------
        if (!out_valid_n) begin
            if (buf_count_n >= KEEP_WIDTH) begin
                emit_full_last     = buf_last_pending_n && (buf_count_n == count_t'(KEEP_WIDTH));
                out_valid_n        = 1'b1;
                out_beat_n         = '0;
                out_beat_n.data    = low_data_from_buf(buf_data_n);
                out_beat_n.keep    = {KEEP_WIDTH{1'b1}};
                out_beat_n.last    = emit_full_last;

                buf_data_n         = shift_buf_right_bytes(buf_data_n, KEEP_WIDTH);
                buf_count_n        = count_t'(unsigned'(buf_count_n) - unsigned'(KEEP_WIDTH));

                if (emit_full_last) begin
                    buf_last_pending_n = 1'b0;
                    pkt_open_n         = 1'b0;
                end
            end
            else if (buf_last_pending_n && (buf_count_n > 0)) begin
                out_valid_n        = 1'b1;
                out_beat_n         = '0;
                out_beat_n.data    = low_data_from_buf(buf_data_n);
                out_beat_n.keep    = keep_from_count(buf_count_n);
                out_beat_n.last    = 1'b1;

                buf_data_n         = '0;
                buf_count_n        = '0;
                buf_last_pending_n = 1'b0;
                pkt_open_n         = 1'b0;
            end
            else if (buf_last_pending_n && (buf_count_n == 0)) begin
                buf_last_pending_n = 1'b0;
                pkt_open_n         = 1'b0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Registers
    // -------------------------------------------------------------------------

    always_ff @(posedge clk) begin
        if (!resetn) begin
            buf_data_r         <= '0;
            buf_count_r        <= '0;
            buf_last_pending_r <= 1'b0;
            pkt_open_r         <= 1'b0;

            out_valid_r        <= 1'b0;
            out_beat_r         <= '0;
        end else begin
            buf_data_r         <= buf_data_n;
            buf_count_r        <= buf_count_n;
            buf_last_pending_r <= buf_last_pending_n;
            pkt_open_r         <= pkt_open_n;

            out_valid_r        <= out_valid_n;
            out_beat_r         <= out_beat_n;
        end
    end

endmodule
