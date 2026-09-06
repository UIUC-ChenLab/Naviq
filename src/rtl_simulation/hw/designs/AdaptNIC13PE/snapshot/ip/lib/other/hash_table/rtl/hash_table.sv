`include "ifc_axis.sv"

module hash_table #(
    parameter int TABLE_DEPTH   = 1024,
    parameter int KEY_WIDTH     = 32,
    parameter int VALUE_WIDTH   = 32,
    parameter int ASSOCIATIVITY = 1,
    localparam int TABLE_ADDR_WIDTH = $clog2(TABLE_DEPTH),
    localparam int WAY_WIDTH = (ASSOCIATIVITY <= 1) ? 1 : $clog2(ASSOCIATIVITY),
    localparam int KEY_ENTRY_BITS = 1 + KEY_WIDTH
) (
    input logic clk,
    input logic resetn,

    input  logic                        key_update_valid,
    output logic                        key_update_ready,
    input  logic [TABLE_ADDR_WIDTH-1:0] key_update_set,
    input  logic [WAY_WIDTH-1:0]        key_update_way,
    input  logic                        key_update_valid_bit,
    input  logic [KEY_WIDTH-1:0]        key_update_key,

    input  logic                        value_update_valid,
    output logic                        value_update_ready,
    input  logic [TABLE_ADDR_WIDTH-1:0] value_update_set,
    input  logic [WAY_WIDTH-1:0]        value_update_way,
    input  logic [VALUE_WIDTH-1:0]      value_update_data,

    input  logic                        entry_read_valid,
    output logic                        entry_read_ready,
    input  logic [TABLE_ADDR_WIDTH-1:0] entry_read_set,
    input  logic [WAY_WIDTH-1:0]        entry_read_way,
    output logic                        entry_resp_valid,
    input  logic                        entry_resp_ready,
    output logic                        entry_resp_valid_bit,
    output logic [KEY_WIDTH-1:0]        entry_resp_key,
    output logic [VALUE_WIDTH-1:0]      entry_resp_value,

    ifc_axis.slave  s_axis_lookup_index,
    ifc_axis.slave  s_axis_key,
    ifc_axis.master m_axis_value,
    ifc_axis.master m_axis_error,

    // Physical way associated with m_axis_value; valid with tvalid.
    output logic [WAY_WIDTH-1:0] m_axis_value_way
);

    localparam int ERROR_WIDTH = KEY_WIDTH + TABLE_ADDR_WIDTH;
    localparam int RESP_DEPTH = 8;
    localparam int RESP_INDEX_WIDTH = $clog2(RESP_DEPTH);
    localparam int RESP_COUNT_WIDTH = $clog2(RESP_DEPTH + 1);

    initial begin
        if (TABLE_DEPTH < 2 || ((TABLE_DEPTH & (TABLE_DEPTH - 1)) != 0)) begin
            $error("hash_table: TABLE_DEPTH (%0d) must be a power of two and >= 2", TABLE_DEPTH);
            $finish;
        end
        if (!(ASSOCIATIVITY == 1 || ASSOCIATIVITY == 2 || ASSOCIATIVITY == 4 || ASSOCIATIVITY == 8)) begin
            $error("hash_table: ASSOCIATIVITY (%0d) must be one of 1, 2, 4, 8", ASSOCIATIVITY);
            $finish;
        end
        if (KEY_WIDTH < 1 || VALUE_WIDTH < 1) begin
            $error("hash_table: KEY_WIDTH and VALUE_WIDTH must be >= 1");
            $finish;
        end
        if ($bits(s_axis_lookup_index.t.data) < TABLE_ADDR_WIDTH) begin
            $error("hash_table: lookup index width (%0d) must be at least %0d",
                   $bits(s_axis_lookup_index.t.data), TABLE_ADDR_WIDTH);
            $finish;
        end
        if ($bits(s_axis_key.t.data) < KEY_WIDTH) begin
            $error("hash_table: key stream width (%0d) must be at least KEY_WIDTH (%0d)",
                   $bits(s_axis_key.t.data), KEY_WIDTH);
            $finish;
        end
        if ($bits(m_axis_value.t.data) < VALUE_WIDTH) begin
            $error("hash_table: value stream width (%0d) must be at least VALUE_WIDTH (%0d)",
                   $bits(m_axis_value.t.data), VALUE_WIDTH);
            $finish;
        end
        if ($bits(m_axis_error.t.data) < ERROR_WIDTH) begin
            $error("hash_table: error stream width (%0d) must be at least KEY_WIDTH + index width (%0d)",
                   $bits(m_axis_error.t.data), ERROR_WIDTH);
            $finish;
        end
    end

    logic lookup_index_pop_valid;
    logic [TABLE_ADDR_WIDTH-1:0] lookup_index_pop_data;
    logic lookup_key_pop_valid;
    logic [KEY_WIDTH-1:0] lookup_key_pop_data;
    logic lookup_pair_pop_ready;

    // The index and key may arrive independently. Registered-ready FIFOs keep
    // them ordered while cutting the paired-lookup backpressure path. A lookup
    // consumes one entry from both FIFOs atomically.
    sync_ff_fifo #(
        .DEPTH(4),
        .T(logic [TABLE_ADDR_WIDTH-1:0]),
        .MODE("CONSERVATIVE")
    ) u_lookup_index_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(s_axis_lookup_index.tvalid),
        .push_data(s_axis_lookup_index.t.data[TABLE_ADDR_WIDTH-1:0]),
        .push_ready(s_axis_lookup_index.tready),
        .pop_valid(lookup_index_pop_valid),
        .pop_data(lookup_index_pop_data),
        .pop_ready(lookup_pair_pop_ready)
    );

    sync_ff_fifo #(
        .DEPTH(4),
        .T(logic [KEY_WIDTH-1:0]),
        .MODE("CONSERVATIVE")
    ) u_lookup_key_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(s_axis_key.tvalid),
        .push_data(s_axis_key.t.data[KEY_WIDTH-1:0]),
        .push_ready(s_axis_key.tready),
        .pop_valid(lookup_key_pop_valid),
        .pop_data(lookup_key_pop_data),
        .pop_ready(lookup_pair_pop_ready)
    );

    logic [TABLE_ADDR_WIDTH-1:0] lookup_rd_addr;
    logic [KEY_ENTRY_BITS-1:0]   lookup_key_data [ASSOCIATIVITY];
    logic [VALUE_WIDTH-1:0]      lookup_value_data [ASSOCIATIVITY];
    logic [KEY_ENTRY_BITS-1:0]   port_b_key_data [ASSOCIATIVITY];
    logic [VALUE_WIDTH-1:0]      port_b_value_data [ASSOCIATIVITY];
    logic                        entry_read_pending_r;
    logic [WAY_WIDTH-1:0]        entry_read_way_r;

    assign entry_read_ready = !entry_read_pending_r &&
                              !(entry_resp_valid && !entry_resp_ready);
    assign key_update_ready = !entry_read_valid && !entry_read_pending_r;
    assign value_update_ready = !entry_read_valid && !entry_read_pending_r;

    for (genvar way = 0; way < ASSOCIATIVITY; way++) begin : g_way_mem
        true_dual_port_bram #(
            .BRAM_WIDTH      (KEY_ENTRY_BITS),
            .BRAM_DEPTH      (TABLE_DEPTH),
            .INIT_VALID_ZERO (1'b1),
            .VALID_BIT_INDEX (KEY_ENTRY_BITS - 1)
        ) u_key_bram (
            .clk    (clk),
            .we_a   (1'b0),
            .addr_a (lookup_rd_addr),
            .din_a  ('0),
            .dout_a (lookup_key_data[way]),
            .we_b   (key_update_valid && key_update_ready && key_update_way == WAY_WIDTH'(way)),
            .addr_b (entry_read_valid && entry_read_ready ? entry_read_set : key_update_set),
            .din_b  ({key_update_valid_bit, key_update_key}),
            .dout_b (port_b_key_data[way])
        );

        true_dual_port_bram #(
            .BRAM_WIDTH      (VALUE_WIDTH),
            .BRAM_DEPTH      (TABLE_DEPTH),
            .INIT_VALID_ZERO (1'b1),
            .VALID_BIT_INDEX (VALUE_WIDTH - 1)
        ) u_value_bram (
            .clk    (clk),
            .we_a   (1'b0),
            .addr_a (lookup_rd_addr),
            .din_a  ('0),
            .dout_a (lookup_value_data[way]),
            .we_b   (value_update_valid && value_update_ready && value_update_way == WAY_WIDTH'(way)),
            .addr_b (entry_read_valid && entry_read_ready ? entry_read_set : value_update_set),
            .din_b  (value_update_data),
            .dout_b (port_b_value_data[way])
        );
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            entry_read_pending_r <= 1'b0;
            entry_read_way_r <= '0;
            entry_resp_valid <= 1'b0;
            entry_resp_valid_bit <= 1'b0;
            entry_resp_key <= '0;
            entry_resp_value <= '0;
        end else begin
            if (entry_resp_valid && entry_resp_ready)
                entry_resp_valid <= 1'b0;

            if (entry_read_pending_r) begin
                entry_resp_valid <= 1'b1;
                entry_resp_valid_bit <= port_b_key_data[entry_read_way_r][KEY_ENTRY_BITS-1];
                entry_resp_key <= port_b_key_data[entry_read_way_r][KEY_WIDTH-1:0];
                entry_resp_value <= port_b_value_data[entry_read_way_r];
                entry_read_pending_r <= 1'b0;
            end

            if (entry_read_valid && entry_read_ready) begin
                entry_read_pending_r <= 1'b1;
                entry_read_way_r <= entry_read_way;
            end
        end
    end

    logic [TABLE_ADDR_WIDTH-1:0] rd_set_r;
    logic [KEY_WIDTH-1:0]        rd_key_r;
    logic [TABLE_ADDR_WIDTH-1:0] cmp_set_r;
    logic [KEY_WIDTH-1:0]        cmp_key_r;
    logic [KEY_ENTRY_BITS-1:0]   cmp_key_entry_r [ASSOCIATIVITY];
    logic [VALUE_WIDTH-1:0]      cmp_value_entry_r [ASSOCIATIVITY];
    logic                        rd_valid_r;
    logic                        cmp_valid_r;
    logic                        cmp_hit_comb;
    logic [VALUE_WIDTH-1:0]      cmp_value_comb;
    logic [WAY_WIDTH-1:0]        cmp_way_comb;
    logic [ERROR_WIDTH-1:0]      cmp_error_comb;
    logic                        cmp_result_valid_r;
    logic                        cmp_result_hit_r;
    logic [VALUE_WIDTH-1:0]      cmp_result_value_r;
    logic [WAY_WIDTH-1:0]        cmp_result_way_r;
    logic [ERROR_WIDTH-1:0]      cmp_result_error_r;

    logic [RESP_COUNT_WIDTH-1:0] resp_count_r;
    logic                        resp_hit_q [RESP_DEPTH];
    logic [VALUE_WIDTH-1:0]      resp_value_q [RESP_DEPTH];
    logic [WAY_WIDTH-1:0]        resp_way_q [RESP_DEPTH];
    logic [ERROR_WIDTH-1:0]      resp_error_q [RESP_DEPTH];

    wire value_pop = (resp_count_r != '0) && resp_hit_q[0] && m_axis_value.tready;
    wire error_pop = (resp_count_r != '0) && !resp_hit_q[0] && m_axis_error.tready;
    wire resp_pop = value_pop || error_pop;
    wire [RESP_COUNT_WIDTH-1:0] pending_count =
        resp_count_r + RESP_COUNT_WIDTH'(rd_valid_r) + RESP_COUNT_WIDTH'(cmp_valid_r) +
        RESP_COUNT_WIDTH'(cmp_result_valid_r);
    wire resp_has_space = pending_count < RESP_COUNT_WIDTH'(RESP_DEPTH);
    wire lookup_fire = lookup_index_pop_valid && lookup_key_pop_valid &&
                       resp_has_space;

    assign lookup_pair_pop_ready = lookup_fire;
    assign lookup_rd_addr = lookup_fire ? lookup_index_pop_data : '0;

    assign m_axis_value.tvalid = (resp_count_r != '0) && resp_hit_q[0];
    assign m_axis_value.t.keep = '1;
    assign m_axis_value.t.id = '0;
    assign m_axis_value.t.dest = '0;
    assign m_axis_value.t.user = '0;
    assign m_axis_value.t.last = 1'b1;

    assign m_axis_error.tvalid = (resp_count_r != '0) && !resp_hit_q[0];
    assign m_axis_error.t.keep = '1;
    assign m_axis_error.t.id = '0;
    assign m_axis_error.t.dest = '0;
    assign m_axis_error.t.user = '0;
    assign m_axis_error.t.last = 1'b1;

    always_comb begin
        m_axis_value.t.data = '0;
        m_axis_value.t.data[VALUE_WIDTH-1:0] = resp_value_q[0];
        m_axis_value_way = resp_way_q[0];
        m_axis_error.t.data = '0;
        m_axis_error.t.data[ERROR_WIDTH-1:0] = resp_error_q[0];
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            rd_valid_r <= 1'b0;
            rd_set_r <= '0;
            rd_key_r <= '0;
        end else begin
            rd_valid_r <= lookup_fire;
            if (lookup_fire) begin
                rd_set_r <= lookup_index_pop_data;
                rd_key_r <= lookup_key_pop_data;
            end
        end
    end

    // Register the exact-match result before response-queue steering. This
    // separates the wide, associative key comparison from the variable-index
    // queue write/shift mux while retaining one lookup result per cycle.
    always_ff @(posedge clk) begin
        if (!resetn) begin
            cmp_result_valid_r <= 1'b0;
            cmp_result_hit_r <= 1'b0;
            cmp_result_value_r <= '0;
            cmp_result_way_r <= '0;
            cmp_result_error_r <= '0;
        end else begin
            cmp_result_valid_r <= cmp_valid_r;
            if (cmp_valid_r) begin
                cmp_result_hit_r <= cmp_hit_comb;
                cmp_result_value_r <= cmp_value_comb;
                cmp_result_way_r <= cmp_way_comb;
                cmp_result_error_r <= cmp_error_comb;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            cmp_valid_r <= 1'b0;
            cmp_set_r <= '0;
            cmp_key_r <= '0;
            for (int way = 0; way < ASSOCIATIVITY; way++) begin
                cmp_key_entry_r[way] <= '0;
                cmp_value_entry_r[way] <= '0;
            end
        end else begin
            cmp_valid_r <= rd_valid_r;
            if (rd_valid_r) begin
                cmp_set_r <= rd_set_r;
                cmp_key_r <= rd_key_r;
                for (int way = 0; way < ASSOCIATIVITY; way++) begin
                    cmp_key_entry_r[way] <= lookup_key_data[way];
                    cmp_value_entry_r[way] <= lookup_value_data[way];
                end
            end
        end
    end

    always_comb begin
        cmp_hit_comb = 1'b0;
        cmp_value_comb = '0;
        cmp_way_comb = '0;
        cmp_error_comb = {cmp_key_r, cmp_set_r};
        for (int way = ASSOCIATIVITY - 1; way >= 0; way--) begin
            if (cmp_key_entry_r[way][KEY_ENTRY_BITS-1] &&
                (cmp_key_entry_r[way][KEY_WIDTH-1:0] == cmp_key_r)) begin
                cmp_hit_comb = 1'b1;
                cmp_value_comb = cmp_value_entry_r[way];
                cmp_way_comb = WAY_WIDTH'(way);
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            resp_count_r <= '0;
            for (int i = 0; i < RESP_DEPTH; i++) begin
                resp_hit_q[i] <= 1'b0;
                resp_value_q[i] <= '0;
                resp_way_q[i] <= '0;
                resp_error_q[i] <= '0;
            end
        end else begin
            logic [RESP_COUNT_WIDTH-1:0] base_count;
            logic [RESP_INDEX_WIDTH-1:0] base_index;
            base_count = resp_count_r;
            if (resp_pop) begin
                for (int i = 0; i < RESP_DEPTH - 1; i++) begin
                    resp_hit_q[i] <= resp_hit_q[i + 1];
                    resp_value_q[i] <= resp_value_q[i + 1];
                    resp_way_q[i] <= resp_way_q[i + 1];
                    resp_error_q[i] <= resp_error_q[i + 1];
                end
                base_count = resp_count_r - RESP_COUNT_WIDTH'(1);
            end

            if (cmp_result_valid_r) begin
                base_index = base_count[RESP_INDEX_WIDTH-1:0];
                resp_hit_q[base_index] <= cmp_result_hit_r;
                resp_value_q[base_index] <= cmp_result_value_r;
                resp_way_q[base_index] <= cmp_result_way_r;
                resp_error_q[base_index] <= cmp_result_error_r;
                resp_count_r <= base_count + RESP_COUNT_WIDTH'(1);
            end else begin
                resp_count_r <= base_count;
            end
        end
    end

endmodule
