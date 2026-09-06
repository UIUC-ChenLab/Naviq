`include "ifc_axis.sv"

// PAT adapter around lib/other/hash_table.
//
// hash_table owns BRAM storage and exact-match lookup.  This wrapper only
// sequences management-port reads/writes to provide insert/delete commands for
// the dynamic PAT policy.
module pat_managed_hash_table #(
    parameter int TABLE_DEPTH   = 1024,
    parameter int KEY_WIDTH     = 104,
    parameter int VALUE_WIDTH   = 10,
    parameter int ASSOCIATIVITY = 4,
    localparam int TABLE_ADDR_WIDTH = $clog2(TABLE_DEPTH),
    localparam int WAY_WIDTH = (ASSOCIATIVITY <= 1) ? 1 : $clog2(ASSOCIATIVITY),
    localparam int LOOKUP_AXIS_WIDTH = ((TABLE_ADDR_WIDTH + 7) / 8) * 8,
    localparam int KEY_AXIS_WIDTH    = ((KEY_WIDTH + 7) / 8) * 8,
    localparam int VALUE_AXIS_WIDTH  = ((VALUE_WIDTH + 7) / 8) * 8,
    localparam int ERROR_AXIS_WIDTH  = ((KEY_WIDTH + TABLE_ADDR_WIDTH + 7) / 8) * 8
) (
    input  logic clk,
    input  logic resetn,

    input  logic                         lookup_valid,
    output logic                         lookup_ready,
    input  logic [KEY_WIDTH-1:0]         lookup_key,
    input  logic [TABLE_ADDR_WIDTH-1:0]  lookup_hash,
    output logic                         result_valid,
    input  logic                         result_ready,
    output logic                         result_hit,
    output logic [VALUE_WIDTH-1:0]       result_value,

    input  logic                         insert_valid,
    output logic                         insert_ready,
    input  logic [KEY_WIDTH-1:0]         insert_key,
    input  logic [TABLE_ADDR_WIDTH-1:0]  insert_hash,
    input  logic [VALUE_WIDTH-1:0]       insert_value,
    output logic                         insert_done,
    output logic                         insert_fail,

    input  logic                         delete_valid,
    output logic                         delete_ready,
    input  logic [KEY_WIDTH-1:0]         delete_key,
    input  logic [TABLE_ADDR_WIDTH-1:0]  delete_hash,
    output logic                         delete_done
);

    ifc_axis #(.DATA_WIDTH(LOOKUP_AXIS_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_lookup_index (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(KEY_AXIS_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_lookup_key (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(VALUE_AXIS_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_value (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(ERROR_AXIS_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_error (.axis_aclk(clk));

    logic                         mgmt_valid;
    logic                         mgmt_ready;
    logic                         mgmt_write;
    logic [TABLE_ADDR_WIDTH-1:0]  mgmt_set;
    logic [WAY_WIDTH-1:0]         mgmt_way;
    logic                         mgmt_valid_bit;
    logic [KEY_WIDTH-1:0]         mgmt_key;
    logic [VALUE_WIDTH-1:0]       mgmt_value;
    logic                         mgmt_resp_valid;
    logic                         mgmt_resp_ready;
    logic                         mgmt_resp_valid_bit;
    logic [KEY_WIDTH-1:0]         mgmt_resp_key;
    logic [VALUE_WIDTH-1:0]       mgmt_resp_value;
    logic key_update_ready, value_update_ready, entry_read_ready;

    assign mgmt_ready = mgmt_write
                      ? (key_update_ready && value_update_ready)
                      : entry_read_ready;

    hash_table #(
        .TABLE_DEPTH   (TABLE_DEPTH),
        .KEY_WIDTH     (KEY_WIDTH),
        .VALUE_WIDTH   (VALUE_WIDTH),
        .ASSOCIATIVITY (ASSOCIATIVITY)
    ) u_hash_table (
        .clk                  (clk),
        .resetn               (resetn),
        .key_update_valid     (mgmt_valid && mgmt_write),
        .key_update_ready     (key_update_ready),
        .key_update_set       (mgmt_set), .key_update_way(mgmt_way),
        .key_update_valid_bit (mgmt_valid_bit), .key_update_key(mgmt_key),
        .value_update_valid   (mgmt_valid && mgmt_write),
        .value_update_ready   (value_update_ready),
        .value_update_set     (mgmt_set), .value_update_way(mgmt_way),
        .value_update_data    (mgmt_value),
        .entry_read_valid     (mgmt_valid && !mgmt_write),
        .entry_read_ready     (entry_read_ready),
        .entry_read_set       (mgmt_set), .entry_read_way(mgmt_way),
        .entry_resp_valid     (mgmt_resp_valid),
        .entry_resp_ready     (mgmt_resp_ready),
        .entry_resp_valid_bit (mgmt_resp_valid_bit),
        .entry_resp_key       (mgmt_resp_key),
        .entry_resp_value     (mgmt_resp_value),
        .s_axis_lookup_index  (u_lookup_index.slave),
        .s_axis_key           (u_lookup_key.slave),
        .m_axis_value         (u_value.master),
        .m_axis_error         (u_error.master)
    );

    always_comb begin
        u_lookup_index.t = '0;
        u_lookup_index.t.data[TABLE_ADDR_WIDTH-1:0] = lookup_hash;
        u_lookup_index.t.keep = '1;
        u_lookup_index.t.last = 1'b1;
        u_lookup_index.tvalid = lookup_valid;

        u_lookup_key.t = '0;
        u_lookup_key.t.data[KEY_WIDTH-1:0] = lookup_key;
        u_lookup_key.t.keep = '1;
        u_lookup_key.t.last = 1'b1;
        u_lookup_key.tvalid = lookup_valid;
    end

    assign lookup_ready = u_lookup_index.tready && u_lookup_key.tready;
    assign u_value.tready = result_ready;
    assign u_error.tready = result_ready;

    assign result_valid = u_value.tvalid || u_error.tvalid;
    assign result_hit   = u_value.tvalid;
    assign result_value = u_value.t.data[VALUE_WIDTH-1:0];

    typedef enum logic [2:0] {
        M_IDLE,
        M_READ_REQ,
        M_READ_WAIT,
        M_WRITE_REQ,
        M_DONE
    } mgmt_state_t;

    mgmt_state_t state_r;
    logic        op_insert_r;
    logic [KEY_WIDTH-1:0] op_key_r;
    logic [TABLE_ADDR_WIDTH-1:0] op_hash_r;
    logic [VALUE_WIDTH-1:0] op_value_r;
    logic [WAY_WIDTH-1:0] way_r;
    logic fail_r;

    assign insert_ready = (state_r == M_IDLE);
    assign delete_ready = (state_r == M_IDLE);

    always_comb begin
        mgmt_valid = 1'b0;
        mgmt_write = 1'b0;
        mgmt_set = op_hash_r;
        mgmt_way = way_r;
        mgmt_valid_bit = 1'b0;
        mgmt_key = op_key_r;
        mgmt_value = op_value_r;
        mgmt_resp_ready = 1'b0;

        if (state_r == M_READ_REQ) begin
            mgmt_valid = 1'b1;
        end else if (state_r == M_READ_WAIT) begin
            mgmt_resp_ready = 1'b1;
        end else if (state_r == M_WRITE_REQ) begin
            mgmt_valid = 1'b1;
            mgmt_write = 1'b1;
            mgmt_valid_bit = op_insert_r;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            state_r <= M_IDLE;
            op_insert_r <= 1'b0;
            op_key_r <= '0;
            op_hash_r <= '0;
            op_value_r <= '0;
            way_r <= '0;
            fail_r <= 1'b0;
            insert_done <= 1'b0;
            insert_fail <= 1'b0;
            delete_done <= 1'b0;
        end else begin
            insert_done <= 1'b0;
            insert_fail <= 1'b0;
            delete_done <= 1'b0;

            unique case (state_r)
                M_IDLE: begin
                    if (insert_valid) begin
                        op_insert_r <= 1'b1;
                        op_key_r <= insert_key;
                        op_hash_r <= insert_hash;
                        op_value_r <= insert_value;
                        way_r <= '0;
                        fail_r <= 1'b0;
                        state_r <= M_READ_REQ;
                    end else if (delete_valid) begin
                        op_insert_r <= 1'b0;
                        op_key_r <= delete_key;
                        op_hash_r <= delete_hash;
                        op_value_r <= '0;
                        way_r <= '0;
                        fail_r <= 1'b0;
                        state_r <= M_READ_REQ;
                    end
                end

                M_READ_REQ: begin
                    if (mgmt_ready)
                        state_r <= M_READ_WAIT;
                end

                M_READ_WAIT: begin
                    if (mgmt_resp_valid) begin
                        if (op_insert_r) begin
                            if (!mgmt_resp_valid_bit ||
                                (mgmt_resp_key == op_key_r)) begin
                                state_r <= M_WRITE_REQ;
                            end else if (way_r == WAY_WIDTH'(ASSOCIATIVITY - 1)) begin
                                fail_r <= 1'b1;
                                state_r <= M_DONE;
                            end else begin
                                way_r <= way_r + 1'b1;
                                state_r <= M_READ_REQ;
                            end
                        end else begin
                            if (mgmt_resp_valid_bit && (mgmt_resp_key == op_key_r)) begin
                                state_r <= M_WRITE_REQ;
                            end else if (way_r == WAY_WIDTH'(ASSOCIATIVITY - 1)) begin
                                state_r <= M_DONE;
                            end else begin
                                way_r <= way_r + 1'b1;
                                state_r <= M_READ_REQ;
                            end
                        end
                    end
                end

                M_WRITE_REQ: begin
                    if (mgmt_ready)
                        state_r <= M_DONE;
                end

                M_DONE: begin
                    if (op_insert_r) begin
                        insert_done <= !fail_r;
                        insert_fail <= fail_r;
                    end else begin
                        delete_done <= 1'b1;
                    end
                    state_r <= M_IDLE;
                end

                default: state_r <= M_IDLE;
            endcase
        end
    end

endmodule
