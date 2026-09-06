`include "ifc_axil.sv"
`include "ifc_axis.sv"

module axil_hash_table #(
    parameter int TABLE_DEPTH   = 1024,
    parameter int KEY_WIDTH     = 32,
    parameter int VALUE_WIDTH   = 32,
    parameter int RUNTIME_VALUE_WIDTH = 0,
    parameter int ASSOCIATIVITY = 1,
    localparam int TABLE_ADDR_WIDTH = $clog2(TABLE_DEPTH),
    localparam int WAY_WIDTH = (ASSOCIATIVITY <= 1) ? 1 : $clog2(ASSOCIATIVITY),
    localparam int KEY_WORDS = (KEY_WIDTH + 31) / 32,
    localparam int VALUE_WORDS = (VALUE_WIDTH + 31) / 32,
    localparam int LOGICAL_ENTRY_WORDS = 1 + KEY_WORDS + VALUE_WORDS,
    localparam int ENTRY_WORD_SHIFT = $clog2(LOGICAL_ENTRY_WORDS),
    localparam int ENTRY_WORDS = 1 << ENTRY_WORD_SHIFT
) (
    input logic clk,
    input logic resetn,

    ifc_axil.slave  ctrl_in,
    ifc_axis.slave  s_axis_lookup_index,
    ifc_axis.slave  s_axis_key,
    ifc_axis.master m_axis_value,
    ifc_axis.master m_axis_error,

    output logic [WAY_WIDTH-1:0]        m_axis_value_way,
    input  logic                        runtime_update_valid,
    output logic                        runtime_update_ready,
    input  logic [TABLE_ADDR_WIDTH-1:0] runtime_update_set,
    input  logic [WAY_WIDTH-1:0]        runtime_update_way,
    input  logic [VALUE_WIDTH+RUNTIME_VALUE_WIDTH-1:0] runtime_update_data,
    output logic                        mgmt_write_commit,
    output logic [TABLE_ADDR_WIDTH-1:0] mgmt_write_set,
    output logic [WAY_WIDTH-1:0]        mgmt_write_way
);

    localparam int TOTAL_ENTRIES = TABLE_DEPTH * ASSOCIATIVITY;
    localparam int TOTAL_WORDS = TOTAL_ENTRIES * ENTRY_WORDS;
    localparam int AXIL_WORD_ADDR_WIDTH = (TOTAL_WORDS <= 1) ? 1 : $clog2(TOTAL_WORDS + 1);

    initial begin
        if ($bits(ctrl_in.w.data) != 32) begin
            $error("axil_hash_table: ctrl_in data width (%0d) must be 32", $bits(ctrl_in.w.data));
            $finish;
        end
    end

    localparam int STORED_VALUE_WIDTH = VALUE_WIDTH + RUNTIME_VALUE_WIDTH;
    logic                        entry_read_valid;
    logic                        entry_read_ready;
    logic [TABLE_ADDR_WIDTH-1:0] mgmt_set;
    logic [WAY_WIDTH-1:0]        mgmt_way;
    logic                        key_update_valid;
    logic                        key_update_ready;
    logic                        value_update_valid;
    logic                        value_update_ready;
    logic                        entry_resp_valid;
    logic                        entry_resp_ready;
    logic                        entry_resp_valid_bit;
    logic [KEY_WIDTH-1:0]        entry_resp_key;
    logic [STORED_VALUE_WIDTH-1:0] entry_resp_value;
    typedef enum logic [2:0] {
        S_IDLE,
        S_WR_READ_REQ,
        S_WR_READ_WAIT,
        S_WR_WRITE_REQ,
        S_RD_REQ,
        S_RD_WAIT
    } state_t;
    state_t state_r;
    logic                            entry_valid_bit_r;
    logic [KEY_WIDTH-1:0]            entry_key_r;
    logic [VALUE_WIDTH-1:0]          entry_value_r;

    hash_table #(
        .TABLE_DEPTH   (TABLE_DEPTH),
        .KEY_WIDTH     (KEY_WIDTH),
        .VALUE_WIDTH   (STORED_VALUE_WIDTH),
        .ASSOCIATIVITY (ASSOCIATIVITY)
    ) u_hash_table (
        .clk                  (clk),
        .resetn               (resetn),
        .key_update_valid     (key_update_valid),
        .key_update_ready     (key_update_ready),
        .key_update_set       (mgmt_set),
        .key_update_way       (mgmt_way),
        .key_update_valid_bit (entry_valid_bit_r),
        .key_update_key       (entry_key_r),
        .value_update_valid   (value_update_valid ||
                               (runtime_update_valid && state_r == S_IDLE)),
        .value_update_ready   (value_update_ready),
        .value_update_set     (value_update_valid ? mgmt_set : runtime_update_set),
        .value_update_way     (value_update_valid ? mgmt_way : runtime_update_way),
        .value_update_data    (value_update_valid ? STORED_VALUE_WIDTH'(entry_value_r) : runtime_update_data),
        .entry_read_valid     (entry_read_valid),
        .entry_read_ready     (entry_read_ready),
        .entry_read_set       (mgmt_set),
        .entry_read_way       (mgmt_way),
        .entry_resp_valid     (entry_resp_valid),
        .entry_resp_ready     (entry_resp_ready),
        .entry_resp_valid_bit (entry_resp_valid_bit),
        .entry_resp_key       (entry_resp_key),
        .entry_resp_value     (entry_resp_value),
        .s_axis_lookup_index  (s_axis_lookup_index),
        .s_axis_key           (s_axis_key),
        .m_axis_value         (m_axis_value),
        .m_axis_error         (m_axis_error),
        .m_axis_value_way     (m_axis_value_way)
    );

    assign runtime_update_ready = value_update_ready && !value_update_valid &&
                                  state_r == S_IDLE;

    logic                            aw_buf_valid_r;
    logic [AXIL_WORD_ADDR_WIDTH-1:0] aw_word_addr_r;
    logic                            w_buf_valid_r;
    logic [31:0]                     w_data_r;
    logic [3:0]                      w_strb_r;
    logic                            b_valid_r;
    logic [1:0]                      b_resp_r;
    logic                            r_valid_r;
    logic [31:0]                     r_data_r;
    logic [1:0]                      r_resp_r;

    logic [AXIL_WORD_ADDR_WIDTH-1:0] op_word_addr_r;
    logic [31:0]                     op_wdata_r;
    logic [TABLE_ADDR_WIDTH-1:0]     op_set_r;
    logic [WAY_WIDTH-1:0]            op_way_r;
    logic [$clog2(ENTRY_WORDS)-1:0]  op_word_sel_r;
    logic                            op_in_range_r;

    function automatic logic [31:0] f_read_word(
        input logic valid_bit,
        input logic [KEY_WIDTH-1:0] key,
        input logic [VALUE_WIDTH-1:0] value,
        input int unsigned word_sel
    );
        logic [31:0] word;
        word = '0;
        if (word_sel == 0) begin
            word[0] = valid_bit;
        end else if (word_sel <= KEY_WORDS) begin
            for (int bit_idx = 0; bit_idx < 32; bit_idx++) begin
                int key_bit;
                key_bit = ((word_sel - 1) * 32) + bit_idx;
                if (key_bit < KEY_WIDTH)
                    word[bit_idx] = key[key_bit];
            end
        end else if (word_sel < LOGICAL_ENTRY_WORDS) begin
            for (int bit_idx = 0; bit_idx < 32; bit_idx++) begin
                int value_bit;
                value_bit = ((word_sel - 1 - KEY_WORDS) * 32) + bit_idx;
                if (value_bit < VALUE_WIDTH)
                    word[bit_idx] = value[value_bit];
            end
        end
        return word;
    endfunction

    task automatic t_write_word(
        inout logic valid_bit,
        inout logic [KEY_WIDTH-1:0] key,
        inout logic [VALUE_WIDTH-1:0] value,
        input int unsigned word_sel,
        input logic [31:0] word
    );
        if (word_sel == 0) begin
            valid_bit = word[0];
        end else if (word_sel <= KEY_WORDS) begin
            for (int bit_idx = 0; bit_idx < 32; bit_idx++) begin
                int key_bit;
                key_bit = ((word_sel - 1) * 32) + bit_idx;
                if (key_bit < KEY_WIDTH)
                    key[key_bit] = word[bit_idx];
            end
        end else if (word_sel < LOGICAL_ENTRY_WORDS) begin
            for (int bit_idx = 0; bit_idx < 32; bit_idx++) begin
                int value_bit;
                value_bit = ((word_sel - 1 - KEY_WORDS) * 32) + bit_idx;
                if (value_bit < VALUE_WIDTH)
                    value[value_bit] = word[bit_idx];
            end
        end
    endtask

    task automatic t_decode_addr(
        input logic [AXIL_WORD_ADDR_WIDTH-1:0] word_addr,
        output logic [TABLE_ADDR_WIDTH-1:0] set_idx,
        output logic [WAY_WIDTH-1:0] way_idx,
        output logic [$clog2(ENTRY_WORDS)-1:0] word_sel,
        output logic in_range
    );
        int unsigned flat_entry;
        // ENTRY_WORDS and TABLE_DEPTH are powers of two, so physical address
        // decoding is wiring rather than division/modulo logic.
        flat_entry = word_addr >> ENTRY_WORD_SHIFT;
        word_sel = word_addr[ENTRY_WORD_SHIFT-1:0];
        way_idx = WAY_WIDTH'(flat_entry >> TABLE_ADDR_WIDTH);
        set_idx = flat_entry[TABLE_ADDR_WIDTH-1:0];
        in_range = word_addr < AXIL_WORD_ADDR_WIDTH'(TOTAL_WORDS);
    endtask

    wire write_buf_ready = aw_buf_valid_r && w_buf_valid_r && (state_r == S_IDLE) && !b_valid_r;

    assign ctrl_in.aw_ready = (state_r == S_IDLE) && !aw_buf_valid_r && !b_valid_r;
    assign ctrl_in.w_ready  = (state_r == S_IDLE) && !w_buf_valid_r && !b_valid_r;
    assign ctrl_in.b.resp   = b_resp_r;
    assign ctrl_in.b.user   = '0;
    assign ctrl_in.b_valid  = b_valid_r;

    assign ctrl_in.ar_ready = (state_r == S_IDLE) && !r_valid_r && !aw_buf_valid_r && !w_buf_valid_r;
    assign ctrl_in.r.data   = r_data_r;
    assign ctrl_in.r.resp   = r_resp_r;
    assign ctrl_in.r.user   = '0;
    assign ctrl_in.r_valid  = r_valid_r;

    always_comb begin
        entry_read_valid = 1'b0;
        key_update_valid = 1'b0;
        value_update_valid = 1'b0;
        mgmt_set = op_set_r;
        mgmt_way = op_way_r;
        entry_resp_ready = 1'b0;

        if (state_r == S_WR_READ_REQ || state_r == S_RD_REQ) begin
            entry_read_valid = 1'b1;
        end else if (state_r == S_WR_WRITE_REQ) begin
            if (op_word_sel_r <= KEY_WORDS)
                key_update_valid = 1'b1;
            else
                value_update_valid = 1'b1;
        end

        if (state_r == S_WR_READ_WAIT || state_r == S_RD_WAIT)
            entry_resp_ready = 1'b1;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            state_r <= S_IDLE;
            aw_buf_valid_r <= 1'b0;
            aw_word_addr_r <= '0;
            w_buf_valid_r <= 1'b0;
            w_data_r <= '0;
            w_strb_r <= '0;
            b_valid_r <= 1'b0;
            b_resp_r <= 2'b00;
            r_valid_r <= 1'b0;
            r_data_r <= '0;
            r_resp_r <= 2'b00;
            op_word_addr_r <= '0;
            op_wdata_r <= '0;
            op_set_r <= '0;
            op_way_r <= '0;
            op_word_sel_r <= '0;
            op_in_range_r <= 1'b0;
            entry_valid_bit_r <= 1'b0;
            entry_key_r <= '0;
            entry_value_r <= '0;
            mgmt_write_commit <= 1'b0;
            mgmt_write_set <= '0;
            mgmt_write_way <= '0;
        end else begin
            mgmt_write_commit <= 1'b0;

            if (b_valid_r && ctrl_in.b_ready)
                b_valid_r <= 1'b0;
            if (r_valid_r && ctrl_in.r_ready)
                r_valid_r <= 1'b0;

            if (ctrl_in.aw_valid && ctrl_in.aw_ready) begin
                aw_buf_valid_r <= 1'b1;
                aw_word_addr_r <= ctrl_in.aw.addr[AXIL_WORD_ADDR_WIDTH+1:2];
            end
            if (ctrl_in.w_valid && ctrl_in.w_ready) begin
                w_buf_valid_r <= 1'b1;
                w_data_r <= ctrl_in.w.data;
                w_strb_r <= ctrl_in.w.strb;
            end

            unique case (state_r)
                S_IDLE: begin
                    if (write_buf_ready) begin
                        op_word_addr_r <= aw_word_addr_r;
                        op_wdata_r <= w_data_r;
                        t_decode_addr(aw_word_addr_r, op_set_r, op_way_r, op_word_sel_r, op_in_range_r);
                        aw_buf_valid_r <= 1'b0;
                        w_buf_valid_r <= 1'b0;
                        if ((w_strb_r == 4'hF) && (aw_word_addr_r < AXIL_WORD_ADDR_WIDTH'(TOTAL_WORDS))) begin
                            state_r <= S_WR_READ_REQ;
                        end else begin
                            b_valid_r <= 1'b1;
                            b_resp_r <= 2'b10;
                        end
                    end else if (ctrl_in.ar_valid && ctrl_in.ar_ready) begin
                        op_word_addr_r <= ctrl_in.ar.addr[AXIL_WORD_ADDR_WIDTH+1:2];
                        t_decode_addr(ctrl_in.ar.addr[AXIL_WORD_ADDR_WIDTH+1:2],
                                      op_set_r, op_way_r, op_word_sel_r, op_in_range_r);
                        if (ctrl_in.ar.addr[AXIL_WORD_ADDR_WIDTH+1:2] < AXIL_WORD_ADDR_WIDTH'(TOTAL_WORDS)) begin
                            state_r <= S_RD_REQ;
                        end else begin
                            r_valid_r <= 1'b1;
                            r_data_r <= 32'h0;
                            r_resp_r <= 2'b10;
                        end
                    end
                end

                S_WR_READ_REQ: begin
                    if (entry_read_ready)
                        state_r <= S_WR_READ_WAIT;
                end

                S_WR_READ_WAIT: begin
                    if (entry_resp_valid) begin
                        logic temp_valid_bit;
                        logic [KEY_WIDTH-1:0] temp_key;
                        logic [VALUE_WIDTH-1:0] temp_value;
                        temp_valid_bit = entry_resp_valid_bit;
                        temp_key = entry_resp_key;
                        temp_value = entry_resp_value[VALUE_WIDTH-1:0];
                        t_write_word(temp_valid_bit, temp_key, temp_value, op_word_sel_r, op_wdata_r);
                        entry_valid_bit_r <= temp_valid_bit;
                        entry_key_r <= temp_key;
                        entry_value_r <= temp_value;
                        state_r <= S_WR_WRITE_REQ;
                    end
                end

                S_WR_WRITE_REQ: begin
                    if ((key_update_valid && key_update_ready) ||
                        (value_update_valid && value_update_ready)) begin
                        mgmt_write_commit <= 1'b1;
                        mgmt_write_set <= op_set_r;
                        mgmt_write_way <= op_way_r;
                        b_valid_r <= 1'b1;
                        b_resp_r <= 2'b00;
                        state_r <= S_IDLE;
                    end
                end

                S_RD_REQ: begin
                    if (entry_read_ready)
                        state_r <= S_RD_WAIT;
                end

                S_RD_WAIT: begin
                    if (entry_resp_valid) begin
                        r_valid_r <= 1'b1;
                        r_data_r <= f_read_word(entry_resp_valid_bit, entry_resp_key,
                                                entry_resp_value[VALUE_WIDTH-1:0], op_word_sel_r);
                        r_resp_r <= 2'b00;
                        state_r <= S_IDLE;
                    end
                end

                default: state_r <= S_IDLE;
            endcase
        end
    end

endmodule
