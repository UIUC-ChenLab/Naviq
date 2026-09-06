`include "ifc_axis.sv"
`include "ifc_axil.sv"
`include "_uro_pkg.sv"
`include "_uro_interfaces.sv"

// Owns the programmable flow table and its AXI-Lite transaction interlock.
// Lookup results are joined with their issue-time packet metadata and exposed
// as one ordered result stream. Management writes wait for the top-level URO
// drain barrier; reads remain independent.
module uro_flow_table #(
    parameter int TABLE_DEPTH       = 2,
    parameter int TABLE_ADDR_WIDTH  = $clog2(TABLE_DEPTH),
    parameter int WAY_WIDTH         = 2,
    parameter int PACKET_BEAT_COUNT_WIDTH = 8
) (
    input logic clk,
    input logic resetn,
    ifc_axil.slave ctrl,

    input logic desc_valid,
    output logic desc_ready,
    input uro_pkg::uro_key_t desc_key,
    input logic [TABLE_ADDR_WIDTH-1:0] desc_hash,
    input logic desc_eligible,
    input logic [15:0] desc_payload_bytes,
    input logic [PACKET_BEAT_COUNT_WIDTH-1:0] desc_payload_beats,

    ifc_uro_lookup_result.producer lookup_result,
    output logic mgmt_write_pending,
    input  logic mgmt_write_safe
);
    localparam int VALUE_WIDTH = 32;

    typedef struct packed {
        logic eligible;
        logic [15:0] payload_bytes;
        logic [PACKET_BEAT_COUNT_WIDTH-1:0] payload_beats;
    } route_meta_t;

    typedef struct packed {
        route_meta_t meta;
        logic hit;
        logic [VALUE_WIDTH-1:0] value;
    } request_t;

    ifc_axis #(
        .DATA_WIDTH(TABLE_ADDR_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) lookup_index (clk);
    ifc_axis #(
        .DATA_WIDTH(uro_pkg::URO_KEY_BITS), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) lookup_key (clk);
    ifc_axis #(
        .DATA_WIDTH(VALUE_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) lookup_value (clk);
    ifc_axis #(
        .DATA_WIDTH(uro_pkg::URO_KEY_BITS + TABLE_ADDR_WIDTH),
        .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) lookup_error (clk);
    ifc_axil #(.ADDR_WIDTH(32), .DATA_WIDTH(32)) table_ctrl (clk);

    route_meta_t meta_push, meta_pop;
    request_t request_push, request_pop;
    logic meta_push_valid, meta_push_ready, meta_pop_valid, meta_pop_ready;
    logic request_push_valid, request_push_ready;
    logic request_pop_valid, request_pop_ready;
    logic [WAY_WIDTH-1:0] table_value_way_unused;
    logic table_mgmt_write_commit_unused;
    logic [TABLE_ADDR_WIDTH-1:0] table_mgmt_write_set_unused;
    logic [WAY_WIDTH-1:0] table_mgmt_write_way_unused;
    logic runtime_update_ready_unused;

    logic aw_buf_valid_r, w_buf_valid_r;
    logic [31:0] aw_addr_r, w_data_r;
    logic [2:0] aw_prot_r;
    logic [3:0] w_strb_r;
    logic aw_sent_r, w_sent_r, write_inflight_r, read_inflight_r;
    logic aw_buf_valid_n, w_buf_valid_n;
    logic [31:0] aw_addr_n, w_data_n;
    logic [2:0] aw_prot_n;
    logic [3:0] w_strb_n;
    logic aw_sent_n, w_sent_n, write_inflight_n, read_inflight_n;
    logic write_pending_c;

    wire table_aw_fire = table_ctrl.aw_valid && table_ctrl.aw_ready;
    wire table_w_fire = table_ctrl.w_valid && table_ctrl.w_ready;

    always_comb begin
        lookup_index.t = '0;
        lookup_key.t = '0;
        lookup_index.t.data = desc_hash;
        lookup_key.t.data = desc_key;
        lookup_index.t.keep = '1;
        lookup_key.t.keep = '1;
        lookup_index.t.last = 1'b1;
        lookup_key.t.last = 1'b1;
        lookup_index.tvalid = desc_valid && lookup_key.tready && meta_push_ready;
        lookup_key.tvalid = desc_valid && lookup_index.tready && meta_push_ready;
        desc_ready = lookup_index.tready && lookup_key.tready && meta_push_ready;
        meta_push_valid = desc_valid && lookup_index.tready && lookup_key.tready;
        meta_push = '{
            eligible: desc_eligible,
            payload_bytes: desc_payload_bytes,
            payload_beats: desc_payload_beats
        };
    end

    sync_ff_fifo #(
        .DEPTH(32), .T(route_meta_t), .MODE("CONSERVATIVE")
    ) u_meta_q (
        .clk(clk), .resetn(resetn),
        .push_valid(meta_push_valid), .push_data(meta_push),
        .push_ready(meta_push_ready),
        .pop_valid(meta_pop_valid), .pop_data(meta_pop),
        .pop_ready(meta_pop_ready)
    );

    axil_hash_table #(
        .TABLE_DEPTH(TABLE_DEPTH),
        .KEY_WIDTH(uro_pkg::URO_KEY_BITS),
        .VALUE_WIDTH(32),
        .RUNTIME_VALUE_WIDTH(0),
        .ASSOCIATIVITY(4)
    ) u_table (
        .clk(clk), .resetn(resetn), .ctrl_in(table_ctrl),
        .s_axis_lookup_index(lookup_index), .s_axis_key(lookup_key),
        .m_axis_value(lookup_value), .m_axis_error(lookup_error),
        .m_axis_value_way(table_value_way_unused),
        .runtime_update_valid(1'b0),
        .runtime_update_ready(runtime_update_ready_unused),
        .runtime_update_set('0),
        .runtime_update_way('0),
        .runtime_update_data('0),
        .mgmt_write_commit(table_mgmt_write_commit_unused),
        .mgmt_write_set(table_mgmt_write_set_unused),
        .mgmt_write_way(table_mgmt_write_way_unused)
    );

    always_comb begin
        request_push = '0;
        request_push.meta = meta_pop;
        request_push.hit = lookup_value.tvalid;
        request_push.value = lookup_value.t.data;
        request_push_valid = meta_pop_valid &&
            (lookup_value.tvalid || lookup_error.tvalid);
        meta_pop_ready = request_push_ready &&
            (lookup_value.tvalid || lookup_error.tvalid);
        lookup_value.tready = request_push_ready && meta_pop_valid;
        lookup_error.tready = request_push_ready && meta_pop_valid;
    end

    sync_ff_fifo #(
        .DEPTH(8), .T(request_t), .EXTRA_OUTPUT_REG(1'b1),
        .MODE("CONSERVATIVE")
    ) u_request_q (
        .clk(clk), .resetn(resetn),
        .push_valid(request_push_valid), .push_data(request_push),
        .push_ready(request_push_ready),
        .pop_valid(request_pop_valid), .pop_data(request_pop),
        .pop_ready(request_pop_ready)
    );

    always_comb begin
        lookup_result.valid = request_pop_valid;
        lookup_result.eligible = request_pop.meta.eligible;
        lookup_result.payload_bytes = request_pop.meta.payload_bytes;
        lookup_result.payload_beats = request_pop.meta.payload_beats;
        lookup_result.hit = request_pop.hit;
        lookup_result.value = request_pop.value;
        request_pop_ready = lookup_result.ready;
    end

    // AXI-Lite AW and W channels are buffered independently. A write reaches
    // the generic table only after the top-level barrier has quiesced ingress,
    // flushed every partial aggregate, and drained all queue output.
    always_comb begin
        write_pending_c = aw_buf_valid_r && w_buf_valid_r &&
                          !write_inflight_r;
        // Keep ingress quiesced through the generic table's write response,
        // not merely until its AW/W handshakes complete.
        mgmt_write_pending = aw_buf_valid_r && w_buf_valid_r;

        table_ctrl.aw = '0;
        table_ctrl.aw.addr = aw_addr_r;
        table_ctrl.aw.prot = aw_prot_r;
        table_ctrl.aw_valid = write_pending_c && mgmt_write_safe && !aw_sent_r;
        table_ctrl.w = '0;
        table_ctrl.w.data = w_data_r;
        table_ctrl.w.strb = w_strb_r;
        table_ctrl.w_valid = write_pending_c && mgmt_write_safe && !w_sent_r;
        table_ctrl.b_ready = ctrl.b_ready;

        ctrl.aw_ready = !aw_buf_valid_r && !write_inflight_r &&
                        !read_inflight_r;
        ctrl.w_ready = !w_buf_valid_r && !write_inflight_r &&
                       !read_inflight_r;
        ctrl.b = table_ctrl.b;
        ctrl.b_valid = table_ctrl.b_valid && write_inflight_r;

        table_ctrl.ar = ctrl.ar;
        table_ctrl.ar_valid = ctrl.ar_valid &&
            !aw_buf_valid_r && !w_buf_valid_r &&
            !write_inflight_r && !read_inflight_r &&
            !ctrl.aw_valid && !ctrl.w_valid;
        ctrl.ar_ready = table_ctrl.ar_ready &&
            !aw_buf_valid_r && !w_buf_valid_r &&
            !write_inflight_r && !read_inflight_r &&
            !ctrl.aw_valid && !ctrl.w_valid;
        ctrl.r = table_ctrl.r;
        ctrl.r_valid = table_ctrl.r_valid && read_inflight_r;
        table_ctrl.r_ready = ctrl.r_ready;
    end

    always_comb begin
        aw_buf_valid_n = aw_buf_valid_r;
        w_buf_valid_n = w_buf_valid_r;
        aw_addr_n = aw_addr_r;
        aw_prot_n = aw_prot_r;
        w_data_n = w_data_r;
        w_strb_n = w_strb_r;
        aw_sent_n = aw_sent_r;
        w_sent_n = w_sent_r;
        write_inflight_n = write_inflight_r;
        read_inflight_n = read_inflight_r;

        if (ctrl.aw_valid && ctrl.aw_ready) begin
            aw_buf_valid_n = 1'b1;
            aw_addr_n = ctrl.aw.addr;
            aw_prot_n = ctrl.aw.prot;
        end
        if (ctrl.w_valid && ctrl.w_ready) begin
            w_buf_valid_n = 1'b1;
            w_data_n = ctrl.w.data;
            w_strb_n = ctrl.w.strb;
        end

        if (table_aw_fire)
            aw_sent_n = 1'b1;
        if (table_w_fire)
            w_sent_n = 1'b1;
        if ((aw_sent_r || table_aw_fire) &&
            (w_sent_r || table_w_fire) && write_pending_c) begin
            write_inflight_n = 1'b1;
        end

        if (table_ctrl.b_valid && table_ctrl.b_ready && write_inflight_r) begin
            aw_buf_valid_n = 1'b0;
            w_buf_valid_n = 1'b0;
            aw_sent_n = 1'b0;
            w_sent_n = 1'b0;
            write_inflight_n = 1'b0;
        end

        if (table_ctrl.ar_valid && table_ctrl.ar_ready)
            read_inflight_n = 1'b1;
        if (table_ctrl.r_valid && table_ctrl.r_ready && read_inflight_r)
            read_inflight_n = 1'b0;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            aw_buf_valid_r <= 1'b0;
            w_buf_valid_r <= 1'b0;
            aw_addr_r <= '0;
            aw_prot_r <= '0;
            w_data_r <= '0;
            w_strb_r <= '0;
            aw_sent_r <= 1'b0;
            w_sent_r <= 1'b0;
            write_inflight_r <= 1'b0;
            read_inflight_r <= 1'b0;
        end else begin
            aw_buf_valid_r <= aw_buf_valid_n;
            w_buf_valid_r <= w_buf_valid_n;
            aw_addr_r <= aw_addr_n;
            aw_prot_r <= aw_prot_n;
            w_data_r <= w_data_n;
            w_strb_r <= w_strb_n;
            aw_sent_r <= aw_sent_n;
            w_sent_r <= w_sent_n;
            write_inflight_r <= write_inflight_n;
            read_inflight_r <= read_inflight_n;
        end
    end
endmodule
