// pat_free_list — Free entry_id allocator for the PAT.
//
// Wraps fifo. On reset, automatically pushes entry_ids 0..NUM_ENTRIES-1
// so that every ID is initially available.
//
// Interfaces:
//   alloc_valid / alloc_ready / alloc_id   — pop (allocate an entry_id)
//   free_valid  / free_ready  / free_id    — push (return an entry_id)
//   empty                                  — 1 when no IDs available

import pat_pkg::*;

module pat_free_list #(
    /* verilator lint_off VARHIDDEN */
    parameter int NUM_ENTRIES  = pat_pkg::NUM_ENTRIES,
    parameter int ENTRY_ID_W   = $clog2(NUM_ENTRIES),
    parameter bit EXTRA_OUTPUT_REG = 1'b0
    /* verilator lint_on VARHIDDEN */
) (
    input  logic clk,
    input  logic resetn,

    // Allocate port (pop)
    output logic                   alloc_valid,
    input  logic                   alloc_ready,
    output logic [ENTRY_ID_W-1:0]  alloc_id,

    // Free / return port (push)
    input  logic                   free_valid,
    output logic                   free_ready,
    input  logic [ENTRY_ID_W-1:0]  free_id,

    // Status
    output logic                   empty
);

    // -------------------------------------------------------------------------
    // Initialization FSM — push 0..NUM_ENTRIES-1 on reset
    // -------------------------------------------------------------------------
    logic                    init_done_r;
    logic [ENTRY_ID_W-1:0]  init_cnt_r;

    logic                    fifo_push_valid;
    logic [ENTRY_ID_W-1:0]  fifo_push_data;
    logic                    fifo_push_ready;

    logic                    fifo_pop_valid;
    logic [ENTRY_ID_W-1:0]  fifo_pop_data;
    logic                    fifo_pop_ready;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            init_done_r <= 1'b0;
            init_cnt_r  <= '0;
        end else if (!init_done_r) begin
            if (fifo_push_ready) begin
                if (init_cnt_r == ENTRY_ID_W'(NUM_ENTRIES - 1))
                    init_done_r <= 1'b1;
                else
                    init_cnt_r <= init_cnt_r + 1;
            end
        end
    end

    // Mux: during init, the FSM drives push; after init, the free port drives push.
    assign fifo_push_valid = init_done_r ? free_valid   : 1'b1;
    assign fifo_push_data  = init_done_r ? free_id      : init_cnt_r;
    assign free_ready      = init_done_r ? fifo_push_ready : 1'b0;

    // Pop port: only exposed after init is done.
    assign alloc_valid   = init_done_r ? fifo_pop_valid : 1'b0;
    assign alloc_id      = fifo_pop_data;
    assign fifo_pop_ready = init_done_r ? alloc_ready    : 1'b0;

    assign empty = init_done_r ? ~fifo_pop_valid : 1'b1;

    // -------------------------------------------------------------------------
    // Underlying FIFO
    // -------------------------------------------------------------------------
    sync_bram_fifo #(
        // CONSERVATIVE mode reserves one slot for registered-ready safety;
        // retain capacity for all NUM_ENTRIES allocatable IDs.
        .DEPTH            (NUM_ENTRIES + 1),
        .T                (logic [ENTRY_ID_W-1:0]),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_fifo (
        .clk        (clk),
        .resetn      (resetn),
        .push_valid (fifo_push_valid),
        .push_data  (fifo_push_data),
        .push_ready (fifo_push_ready),
        .pop_valid  (fifo_pop_valid),
        .pop_data   (fifo_pop_data),
        .pop_ready  (fifo_pop_ready)
    );

endmodule
