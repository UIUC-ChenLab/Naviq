`include "ifc_axil.sv"
`include "ifc_axis.sv"
`include "axi_struct_macros.svh"

module multicast #(
    parameter int DATA_WIDTH        = 512,
    parameter int HASH_WIDTH        = 12,
    parameter int FLOW_ID_WIDTH     = 6,
    parameter int FLOW_SELECTOR_TREE_DEPTH = 3,
    parameter int PARSER_FRAGMENT_PACKER_PAGE_COUNT = 4,
    parameter int MAX_PACKET_BYTES  = 1500,
    parameter bit EXTRA_OUTPUT_REG = 1'b0,
    parameter logic [31:0] HASH_TABLE_BASE   = 32'h0000_0000,
    parameter logic [31:0] FLOW_MASK_BASE    = 32'h0010_0000,
    parameter logic [31:0] FLOW_TABLE_STRIDE = 32'h0001_0000,
    parameter logic [31:0] FLOW_IP_BASE      = 32'h4000_0000,
    localparam int HASH_TABLE_DEPTH = 1 << HASH_WIDTH,
    localparam int NUM_FLOWS        = 1 << FLOW_ID_WIDTH,
    localparam int MASK_CHUNKS      = (NUM_FLOWS + 31) / 32,
    localparam int NUM_CTRL_SLAVES  = MASK_CHUNKS + 3
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  packet_in,
    ifc_axil.slave  ctrl_in,
    ifc_axis.master packet_out
);

    localparam int KEEP_WIDTH         = DATA_WIDTH / 8;
    localparam int MAX_PACKET_BEATS   = (MAX_PACKET_BYTES + KEEP_WIDTH - 1) / KEEP_WIDTH;
    localparam int PACKET_BEAT_W      = (MAX_PACKET_BEATS <= 1) ? 1 : $clog2(MAX_PACKET_BEATS + 1);
    localparam int MASK_CHUNK_SEL_W   = (MASK_CHUNKS <= 1) ? 1 : $clog2(MASK_CHUNKS);
    localparam int FLOW_COUNT_W       = FLOW_ID_WIDTH + 1;
    localparam int CAPTURE_FIFO_DEPTH = 64;
    localparam int META_FIFO_DEPTH    = 4;
    localparam int PACKET_META_FIFO_DEPTH = 64;
    localparam int PACKET_HEADER_FIFO_DEPTH = 8;
    localparam int MASK_META_FIFO_DEPTH = META_FIFO_DEPTH;
    localparam int HASH_ADDR_BYTES    = HASH_TABLE_DEPTH * 4;
    localparam int FLOW_ADDR_BYTES    = NUM_FLOWS * 4;
    localparam int FLOW_COPIES_CTRL_IDX = MASK_CHUNKS + 1;
    localparam logic [31:0] FLOW_COPIES_BASE =
        FLOW_MASK_BASE + 32'(MASK_CHUNKS) * FLOW_TABLE_STRIDE;
    localparam int IPV4_DST_BYTE_OFF  = 16;
    localparam int IPV4_DST_BYTES     = 4;
    localparam int IPV4_DST_BEAT_IDX  = IPV4_DST_BYTE_OFF / KEEP_WIDTH;
    localparam int SELECTOR_LEAVES    = 1 << ((FLOW_SELECTOR_TREE_DEPTH > 0)
        ? (FLOW_SELECTOR_TREE_DEPTH - 1) : 0);
    localparam int SELECTOR_LEAF_WIDTH = (NUM_FLOWS + SELECTOR_LEAVES - 1) / SELECTOR_LEAVES;

    `AXIS_T_CHAN_T(packet_in, packet_chan_t);

    function automatic logic is_power_of_two_32(input logic [31:0] value);
        is_power_of_two_32 = (value != 32'h0) && ((value & (value - 32'h1)) == 32'h0);
    endfunction

    function automatic logic [NUM_CTRL_SLAVES-1:0][31:0] ctrl_base_addr();
        logic [NUM_CTRL_SLAVES-1:0][31:0] tmp;
        tmp = '0;
        tmp[0] = HASH_TABLE_BASE;
        for (int i = 0; i < MASK_CHUNKS; i++) begin
            tmp[i + 1] = FLOW_MASK_BASE + 32'(i) * FLOW_TABLE_STRIDE;
        end
        tmp[FLOW_COPIES_CTRL_IDX] = FLOW_COPIES_BASE;
        tmp[NUM_CTRL_SLAVES - 1] = FLOW_IP_BASE;
        return tmp;
    endfunction

    function automatic logic [NUM_CTRL_SLAVES-1:0][31:0] ctrl_addr_size();
        logic [NUM_CTRL_SLAVES-1:0][31:0] tmp;
        tmp = '0;
        tmp[0] = 32'(HASH_ADDR_BYTES);
        for (int i = 0; i < MASK_CHUNKS; i++) begin
            tmp[i + 1] = FLOW_TABLE_STRIDE;
        end
        tmp[FLOW_COPIES_CTRL_IDX] = 32'(FLOW_ADDR_BYTES);
        tmp[NUM_CTRL_SLAVES - 1] = 32'(FLOW_ADDR_BYTES);
        return tmp;
    endfunction

    localparam logic [NUM_CTRL_SLAVES-1:0][31:0] CTRL_BASE_ADDR = ctrl_base_addr();
    localparam logic [NUM_CTRL_SLAVES-1:0][31:0] CTRL_ADDR_SIZE = ctrl_addr_size();

    initial begin
        if (DATA_WIDTH < 8 || DATA_WIDTH % 8 != 0 || !is_power_of_two_32(32'(DATA_WIDTH))) begin
            $error("multicast: DATA_WIDTH must be a byte-aligned power of two >= 8, got %0d",
                   DATA_WIDTH);
            $finish;
        end
        if ($bits(packet_in.t.data) != DATA_WIDTH || $bits(packet_out.t.data) != DATA_WIDTH) begin
            $error("multicast: packet AXIS widths must match DATA_WIDTH");
            $finish;
        end
        if (HASH_WIDTH < 1 || HASH_WIDTH > 31) begin
            $error("multicast: HASH_WIDTH must be in [1, 31], got %0d", HASH_WIDTH);
            $finish;
        end
        if (FLOW_ID_WIDTH < 1 || FLOW_ID_WIDTH > 32) begin
            $error("multicast: FLOW_ID_WIDTH must be in [1, 32], got %0d", FLOW_ID_WIDTH);
            $finish;
        end
        if (FLOW_SELECTOR_TREE_DEPTH < 1 || SELECTOR_LEAVES > NUM_FLOWS) begin
            $error("multicast: FLOW_SELECTOR_TREE_DEPTH must produce between 1 and NUM_FLOWS leaves");
            $finish;
        end
        if (!is_power_of_two_32(32'(HASH_ADDR_BYTES))) begin
            $error("multicast: hash table aperture must be a power of two");
            $finish;
        end
        if (!is_power_of_two_32(FLOW_TABLE_STRIDE) || FLOW_TABLE_STRIDE < 32'(FLOW_ADDR_BYTES)) begin
            $error("multicast: FLOW_TABLE_STRIDE must be a power of two and cover NUM_FLOWS words");
            $finish;
        end
        if (!is_power_of_two_32(32'(FLOW_ADDR_BYTES))) begin
            $error("multicast: flow table aperture must be a power of two");
            $finish;
        end
    end

    // -------------------------------------------------------------------------
    // Control plane: one AXI-Lite slave, many lookup-table control ports.
    // -------------------------------------------------------------------------

    ifc_axil #(
        .ADDR_WIDTH  (32),
        .DATA_WIDTH  (32),
        .TUSER_WIDTH (1)
    ) u_ctrl_table [NUM_CTRL_SLAVES] (.axil_aclk(clk));

    axil_crossbar #(
        .ADDR_WIDTH      (32),
        .DATA_WIDTH      (32),
        .TUSER_WIDTH     (1),
        .NUM_SLAVES      (NUM_CTRL_SLAVES),
        .SLAVE_BASE_ADDR (CTRL_BASE_ADDR),
        .SLAVE_ADDR_SIZE (CTRL_ADDR_SIZE)
    ) u_ctrl_xbar (
        .clk    (clk),
        .resetn (resetn),
        .s_axil (ctrl_in),
        .m_axil (u_ctrl_table)
    );

    // -------------------------------------------------------------------------
    // Hash path.
    // -------------------------------------------------------------------------

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_hash_packet (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (32),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_hash_out (.axis_aclk(clk));

    parse_and_hash_packet #(
        .DATA_WIDTH  (DATA_WIDTH),
        .OUTPUT_DATA_WIDTH (32),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1),
        .HASH_WIDTH  (HASH_WIDTH),
        .FRAGMENT_PACKER_PAGE_COUNT(PARSER_FRAGMENT_PACKER_PAGE_COUNT)
    ) u_parse_and_hash_packet (
        .clk        (clk),
        .resetn     (resetn),
        .packet_in  (u_hash_packet.slave),
        .packet_out (u_hash_out.master)
    );

    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_hash_flow_req (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_hash_flow_value (.axis_aclk(clk));

    lookup_table #(
        .TABLE_DEPTH       (HASH_TABLE_DEPTH),
        .TABLE_VALUE_WIDTH (FLOW_ID_WIDTH),
        .ENABLE_AXIL_READ  (1)
    ) u_hash_to_flow_table (
        .clk           (clk),
        .resetn        (resetn),
        .ctrl_in       (u_ctrl_table[0].slave),
        .s_axis_lookup (u_hash_flow_req.slave),
        .m_axis_value  (u_hash_flow_value.master)
    );

    // -------------------------------------------------------------------------
    // Flow-mask lookup shards.
    // -------------------------------------------------------------------------

    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_mask_req [MASK_CHUNKS] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_mask_value_raw [MASK_CHUNKS] (.axis_aclk(clk));

    for (genvar i = 0; i < MASK_CHUNKS; i++) begin : g_mask_tables
        lookup_table #(
            .TABLE_DEPTH       (NUM_FLOWS),
            .TABLE_VALUE_WIDTH (32),
            .ENABLE_AXIL_READ  (1)
        ) u_flow_mask_table (
            .clk           (clk),
            .resetn        (resetn),
            .ctrl_in       (u_ctrl_table[i + 1].slave),
            .s_axis_lookup (u_mask_req[i].slave),
            .m_axis_value  (u_mask_value_raw[i].master)
        );
    end

    // The control plane supplies the population count for each mask. Keeping
    // this value in a separate table removes the wide mask reduction and
    // popcount from the descriptor-consumption path.
    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_mask_copies_req (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_mask_copies_value (.axis_aclk(clk));

    lookup_table #(
        .TABLE_DEPTH       (NUM_FLOWS),
        .TABLE_VALUE_WIDTH (FLOW_COUNT_W),
        .ENABLE_AXIL_READ  (1)
    ) u_flow_mask_copies_table (
        .clk           (clk),
        .resetn        (resetn),
        .ctrl_in       (u_ctrl_table[FLOW_COPIES_CTRL_IDX].slave),
        .s_axis_lookup (u_mask_copies_req.slave),
        .m_axis_value  (u_mask_copies_value.master)
    );

    // -------------------------------------------------------------------------
    // Flow-ID to IPv4 destination table.
    // -------------------------------------------------------------------------

    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_flow_ip_req (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_flow_ip_value (.axis_aclk(clk));

    lookup_table #(
        .TABLE_DEPTH       (NUM_FLOWS),
        .TABLE_VALUE_WIDTH (32),
        .ENABLE_AXIL_READ  (1)
    ) u_flow_ip_table (
        .clk           (clk),
        .resetn        (resetn),
        .ctrl_in       (u_ctrl_table[NUM_CTRL_SLAVES - 1].slave),
        .s_axis_lookup (u_flow_ip_req.slave),
        .m_axis_value  (u_flow_ip_value.master)
    );

    // -------------------------------------------------------------------------
    // FIFO-backed packet capture, lookup, and generation datapath.
    // -------------------------------------------------------------------------

    typedef struct packed {
        logic marker;
    } packet_meta_t;

    typedef struct packed {
        logic [FLOW_ID_WIDTH-1:0] base_flow;
    } flow_meta_t;

    typedef struct packed {
        logic [NUM_FLOWS-1:0] mask;
        logic [FLOW_COUNT_W-1:0] copies;
    } mask_meta_t;

    typedef struct packed {
        logic [FLOW_COUNT_W-1:0] copies;
    } ip_resp_meta_t;

    typedef struct packed {
        packet_chan_t header_beat;
    } packet_header_t;

    typedef struct packed {
        logic                          drop;
        logic [FLOW_COUNT_W-1:0]       copies;
    } packet_disposition_t;

    typedef struct packed {
        logic valid;
        logic [FLOW_ID_WIDTH-1:0] flow;
    } selector_candidate_t;

    typedef struct packed {
        selector_candidate_t candidate;
        logic [SELECTOR_LEAF_WIDTH-1:0] remaining_mask;
    } selector_leaf_result_t;

    function automatic selector_leaf_result_t select_flow_leaf(
        input logic [SELECTOR_LEAF_WIDTH-1:0] mask,
        input int unsigned base_flow
    );
        selector_leaf_result_t selected;
        logic found;
        selected = '0;
        selected.remaining_mask = mask;
        found = 1'b0;
        for (int i = 0; i < SELECTOR_LEAF_WIDTH; i++) begin
            if (!found && mask[i]) begin
                selected.candidate.valid = 1'b1;
                selected.candidate.flow = FLOW_ID_WIDTH'(base_flow + i);
                selected.remaining_mask[i] = 1'b0;
                found = 1'b1;
            end
        end
        return selected;
    endfunction

    function automatic logic [FLOW_COUNT_W-1:0] popcount_flows(input logic [NUM_FLOWS-1:0] mask);
        logic [FLOW_COUNT_W-1:0] count;
        count = '0;
        for (int i = 0; i < NUM_FLOWS; i++) begin
            count = count + FLOW_COUNT_W'(mask[i]);
        end
        return count;
    endfunction

    function automatic packet_chan_t rewrite_ipv4_dst(
        input packet_chan_t in_t,
        input logic [31:0] dst_ip,
        input logic [PACKET_BEAT_W-1:0] beat_idx
    );
        packet_chan_t out_t;
        int unsigned packet_byte;
        int unsigned dst_byte;

        out_t = in_t;
        for (int byte_idx = 0; byte_idx < KEEP_WIDTH; byte_idx++) begin
            packet_byte = int'(beat_idx) * KEEP_WIDTH + byte_idx;
            if (packet_byte >= IPV4_DST_BYTE_OFF && packet_byte < IPV4_DST_BYTE_OFF + IPV4_DST_BYTES) begin
                dst_byte = packet_byte - IPV4_DST_BYTE_OFF;
                out_t.data[8 * byte_idx +: 8] = dst_ip[8 * (IPV4_DST_BYTES - 1 - dst_byte) +: 8];
            end
        end
        return out_t;
    endfunction

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_main_fifo_in (.axis_aclk(clk));

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_main_fifo_out (.axis_aclk(clk));

    axis_fifo #(
        .DEPTH    (CAPTURE_FIFO_DEPTH),
        .USE_BRAM (1),
        .MODE     ("CONSERVATIVE")
    ) u_main_packet_fifo (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_main_fifo_in.slave),
        .m_axis (u_main_fifo_out.master)
    );

    packet_meta_t packet_meta_push_data;
    packet_meta_t packet_meta_pop_data;
    logic packet_meta_push_valid;
    logic packet_meta_push_ready;
    logic packet_meta_pop_valid;
    logic packet_meta_pop_ready;

    sync_bram_fifo #(
        .DEPTH            (PACKET_META_FIFO_DEPTH),
        .T                (packet_meta_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_packet_meta_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (packet_meta_push_valid),
        .push_data  (packet_meta_push_data),
        .push_ready (packet_meta_push_ready),
        .pop_valid  (packet_meta_pop_valid),
        .pop_data   (packet_meta_pop_data),
        .pop_ready  (packet_meta_pop_ready)
    );

    packet_chan_t packet_template_push_data;
    packet_chan_t packet_template_pop_data;
    logic packet_template_push_valid;
    logic packet_template_push_ready;
    logic packet_template_pop_valid;
    logic packet_template_pop_ready;

    sync_bram_fifo #(
        .DEPTH            (PACKET_META_FIFO_DEPTH),
        .T                (packet_chan_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_packet_template_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (packet_template_push_valid),
        .push_data  (packet_template_push_data),
        .push_ready (packet_template_push_ready),
        .pop_valid  (packet_template_pop_valid),
        .pop_data   (packet_template_pop_data),
        .pop_ready  (packet_template_pop_ready)
    );

    logic [HASH_WIDTH-1:0] hash_push_data;
    logic [HASH_WIDTH-1:0] hash_pop_data;
    logic hash_push_valid;
    logic hash_push_ready;
    logic hash_pop_valid;
    logic hash_pop_ready;

    sync_ff_fifo #(
        .DEPTH            (META_FIFO_DEPTH),
        .T                (logic [HASH_WIDTH-1:0]),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_hash_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (hash_push_valid),
        .push_data  (hash_push_data),
        .push_ready (hash_push_ready),
        .pop_valid  (hash_pop_valid),
        .pop_data   (hash_pop_data),
        .pop_ready  (hash_pop_ready)
    );

    packet_meta_t hash_flow_meta_push_data;
    packet_meta_t hash_flow_meta_pop_data;
    logic hash_flow_meta_push_valid;
    logic hash_flow_meta_push_ready;
    logic hash_flow_meta_pop_valid;
    logic hash_flow_meta_pop_ready;

    sync_ff_fifo #(
        .DEPTH            (META_FIFO_DEPTH),
        .T                (packet_meta_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_hash_flow_meta_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (hash_flow_meta_push_valid),
        .push_data  (hash_flow_meta_push_data),
        .push_ready (hash_flow_meta_push_ready),
        .pop_valid  (hash_flow_meta_pop_valid),
        .pop_data   (hash_flow_meta_pop_data),
        .pop_ready  (hash_flow_meta_pop_ready)
    );

    flow_meta_t flow_meta_push_data;
    flow_meta_t flow_meta_pop_data;
    logic flow_meta_push_valid;
    logic flow_meta_push_ready;
    logic flow_meta_pop_valid;
    logic flow_meta_pop_ready;

    sync_ff_fifo #(
        .DEPTH            (META_FIFO_DEPTH),
        .T                (flow_meta_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_flow_meta_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (flow_meta_push_valid),
        .push_data  (flow_meta_push_data),
        .push_ready (flow_meta_push_ready),
        .pop_valid  (flow_meta_pop_valid),
        .pop_data   (flow_meta_pop_data),
        .pop_ready  (flow_meta_pop_ready)
    );

    mask_meta_t mask_meta_push_data;
    mask_meta_t mask_meta_pop_data;
    logic mask_meta_push_valid;
    logic mask_meta_push_ready;
    logic mask_meta_pop_valid;
    logic mask_meta_pop_ready;

    sync_ff_fifo #(
        .DEPTH            (MASK_META_FIFO_DEPTH),
        .T                (mask_meta_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_mask_meta_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (mask_meta_push_valid),
        .push_data  (mask_meta_push_data),
        .push_ready (mask_meta_push_ready),
        .pop_valid  (mask_meta_pop_valid),
        .pop_data   (mask_meta_pop_data),
        .pop_ready  (mask_meta_pop_ready)
    );

    ip_resp_meta_t ip_resp_meta_push_data;
    ip_resp_meta_t ip_resp_meta_pop_data;
    logic ip_resp_meta_push_valid;
    logic ip_resp_meta_push_ready;
    logic ip_resp_meta_pop_valid;
    logic ip_resp_meta_pop_ready;

    sync_ff_fifo #(
        .DEPTH            (META_FIFO_DEPTH),
        .T                (ip_resp_meta_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_ip_resp_meta_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (ip_resp_meta_push_valid),
        .push_data  (ip_resp_meta_push_data),
        .push_ready (ip_resp_meta_push_ready),
        .pop_valid  (ip_resp_meta_pop_valid),
        .pop_data   (ip_resp_meta_pop_data),
        .pop_ready  (ip_resp_meta_pop_ready)
    );

    packet_header_t packet_header_push_data;
    packet_header_t packet_header_pop_data;
    logic packet_header_push_valid;
    logic packet_header_push_ready;
    logic packet_header_pop_valid;
    logic packet_header_pop_ready;

    sync_ff_fifo #(
        .DEPTH            (PACKET_HEADER_FIFO_DEPTH),
        .T                (packet_header_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_packet_header_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (packet_header_push_valid),
        .push_data  (packet_header_push_data),
        .push_ready (packet_header_push_ready),
        .pop_valid  (packet_header_pop_valid),
        .pop_data   (packet_header_pop_data),
        .pop_ready  (packet_header_pop_ready)
    );

    packet_disposition_t disposition_push_data;
    packet_disposition_t disposition_pop_data;
    logic disposition_push_valid;
    logic disposition_push_ready;
    logic disposition_pop_valid;
    logic disposition_pop_ready;

    sync_ff_fifo #(
        .DEPTH            (META_FIFO_DEPTH),
        .T                (packet_disposition_t),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_packet_disposition_fifo (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (disposition_push_valid),
        .push_data  (disposition_push_data),
        .push_ready (disposition_push_ready),
        .pop_valid  (disposition_pop_valid),
        .pop_data   (disposition_pop_data),
        .pop_ready  (disposition_pop_ready)
    );

    logic [PACKET_BEAT_W-1:0] input_beat_count_r;
    logic input_would_exceed_max;
    logic input_can_accept;
    logic input_fire;
    logic input_done;

    assign input_would_exceed_max = (input_beat_count_r == PACKET_BEAT_W'(MAX_PACKET_BEATS - 1))
        && packet_in.tvalid && !packet_in.t.last;
    assign input_can_accept = !input_would_exceed_max
        && (!packet_in.tvalid || !packet_in.t.last || packet_meta_push_ready)
        && (!packet_in.tvalid || (input_beat_count_r != PACKET_BEAT_W'(IPV4_DST_BEAT_IDX))
            || packet_template_push_ready);
    assign input_fire = packet_in.tvalid && packet_in.tready;
    assign input_done = input_fire && packet_in.t.last;

    assign packet_in.tready = input_can_accept && u_main_fifo_in.tready && u_hash_packet.tready;

    assign u_hash_packet.t = packet_in.t;
    assign u_hash_packet.tvalid = packet_in.tvalid && input_can_accept && u_main_fifo_in.tready;

    assign u_main_fifo_in.t = packet_in.t;
    assign u_main_fifo_in.tvalid = packet_in.tvalid && input_can_accept && u_hash_packet.tready;

    assign packet_meta_push_valid = input_done;
    assign packet_meta_push_data.marker = 1'b1;
    assign packet_template_push_valid = input_fire
        && (input_beat_count_r == PACKET_BEAT_W'(IPV4_DST_BEAT_IDX));
    assign packet_template_push_data = packet_in.t;

    assign hash_push_valid = u_hash_out.tvalid;
    assign hash_push_data = u_hash_out.t.data[HASH_WIDTH-1:0];
    assign u_hash_out.tready = hash_push_ready;

    logic pair_lookup_fire;

    assign pair_lookup_fire = u_hash_flow_req.tvalid && u_hash_flow_req.tready;

    assign u_hash_flow_req.t.data = 32'(hash_pop_data);
    assign u_hash_flow_req.t.keep = '1;
    assign u_hash_flow_req.t.last = 1'b1;
    assign u_hash_flow_req.tvalid = packet_meta_pop_valid && hash_pop_valid && hash_flow_meta_push_ready;

    assign packet_meta_pop_ready = hash_pop_valid && u_hash_flow_req.tready && hash_flow_meta_push_ready;
    assign hash_pop_ready = packet_meta_pop_valid && u_hash_flow_req.tready && hash_flow_meta_push_ready;

    assign hash_flow_meta_push_valid = pair_lookup_fire;
    assign hash_flow_meta_push_data = packet_meta_pop_data;

    logic hash_flow_resp_fire;

    assign hash_flow_resp_fire = u_hash_flow_value.tvalid && u_hash_flow_value.tready;
    assign u_hash_flow_value.tready = hash_flow_meta_pop_valid && flow_meta_push_ready;
    assign hash_flow_meta_pop_ready = hash_flow_resp_fire;

    assign flow_meta_push_valid = hash_flow_resp_fire;
    assign flow_meta_push_data.base_flow = u_hash_flow_value.t.data[FLOW_ID_WIDTH-1:0];

    logic [MASK_CHUNKS-1:0] mask_req_ready_s;
    logic [MASK_CHUNKS-1:0] mask_resp_valid_s;
    logic [MASK_CHUNKS-1:0][31:0] mask_resp_data_s;
    logic mask_req_all_ready;
    logic mask_resp_all_valid;
    logic mask_resp_fire;
    logic mask_req_valid;
    logic mask_req_fire;

    assign mask_req_all_ready = (&mask_req_ready_s) && u_mask_copies_req.tready;
    assign mask_resp_all_valid = (&mask_resp_valid_s) && u_mask_copies_value.tvalid;
    assign mask_resp_fire = mask_resp_all_valid && mask_meta_push_ready;
    assign mask_req_valid = flow_meta_pop_valid;
    assign mask_req_fire = mask_req_valid && mask_req_all_ready;

    assign flow_meta_pop_ready = mask_req_all_ready;

    assign u_mask_copies_req.t.data = 32'(flow_meta_pop_data.base_flow);
    assign u_mask_copies_req.t.keep = '1;
    assign u_mask_copies_req.t.last = 1'b1;
    assign u_mask_copies_req.tvalid = mask_req_valid && mask_req_all_ready;
    assign u_mask_copies_value.tready = mask_resp_fire;

    for (genvar i = 0; i < MASK_CHUNKS; i++) begin : g_mask_req_broadcast
        assign mask_req_ready_s[i] = u_mask_req[i].tready;
        assign u_mask_req[i].t.data = 32'(flow_meta_pop_data.base_flow);
        assign u_mask_req[i].t.keep = '1;
        assign u_mask_req[i].t.last = 1'b1;
        assign u_mask_req[i].tvalid = mask_req_valid && mask_req_all_ready;
        assign mask_resp_valid_s[i] = u_mask_value_raw[i].tvalid;
        assign mask_resp_data_s[i] = u_mask_value_raw[i].t.data;
        assign u_mask_value_raw[i].tready = mask_resp_fire;
    end

    assign mask_meta_push_valid = mask_resp_fire;
    always_comb begin
        mask_meta_push_data.mask = '0;
        mask_meta_push_data.copies =
            u_mask_copies_value.t.data[FLOW_COUNT_W-1:0];
        for (int chunk = 0; chunk < MASK_CHUNKS; chunk++) begin
            for (int b = 0; b < 32; b++) begin
                int unsigned flow_idx;
                flow_idx = chunk * 32 + b;
                if (flow_idx < NUM_FLOWS) begin
                    mask_meta_push_data.mask[flow_idx] = mask_resp_data_s[chunk][b];
                end
            end
        end
    end

    logic ip_issue_active_r;
    logic [NUM_FLOWS-1:0] ip_issue_mask_r;
    logic [FLOW_COUNT_W-1:0] ip_issue_left_r;
    logic ip_resp_active_r;
    ip_resp_meta_t ip_resp_cur_r;
    logic [FLOW_COUNT_W-1:0] ip_resp_idx_r;
    logic [FLOW_COUNT_W-1:0] mask_meta_copies;
    logic [NUM_FLOWS-1:0] ip_issue_mask;
    logic flow_ip_resp_fire;
    logic ip_resp_final_pending;
    logic ip_resp_final_fire;
    logic ip_zero_mask_valid;
    logic ip_zero_mask_fire;
    logic [NUM_FLOWS-1:0] ip_issue_mask_after_req;
    selector_leaf_result_t selector_leaf_c [SELECTOR_LEAVES];
    selector_candidate_t selector_selected_c;
    logic [SELECTOR_LEAVES-1:0] selector_leaf_selected_c;
    selector_candidate_t selector_stage_r [FLOW_SELECTOR_TREE_DEPTH][SELECTOR_LEAVES];
    logic [FLOW_SELECTOR_TREE_DEPTH-1:0] selector_valid_r;
    logic selector_advance;
    logic selector_source_valid;
    logic selector_insert;
    logic selector_source_first;
    logic selector_pipe_empty;

    assign mask_meta_copies = mask_meta_pop_data.copies;
    assign ip_issue_mask = ip_issue_active_r ? ip_issue_mask_r : mask_meta_pop_data.mask;
    assign flow_ip_resp_fire = u_flow_ip_value.tvalid && u_flow_ip_value.tready;
    assign ip_resp_final_pending = u_flow_ip_value.tvalid && ip_resp_active_r
        && (ip_resp_idx_r == ip_resp_cur_r.copies - FLOW_COUNT_W'(1));
    assign ip_resp_final_fire = flow_ip_resp_fire && ip_resp_final_pending;
    assign selector_pipe_empty = !(|selector_valid_r);
    assign ip_zero_mask_valid = !ip_issue_active_r && selector_pipe_empty
        && !ip_resp_active_r && !ip_resp_meta_pop_valid && !u_flow_ip_value.tvalid
        && mask_meta_pop_valid && (mask_meta_pop_data.copies == '0)
        && packet_template_pop_valid;
    assign ip_zero_mask_fire = ip_zero_mask_valid && disposition_push_ready;

    assign selector_advance = !selector_valid_r[FLOW_SELECTOR_TREE_DEPTH-1]
        || u_flow_ip_req.tready;
    assign selector_source_first = !ip_issue_active_r;
    assign selector_source_valid = ip_issue_active_r || (mask_meta_pop_valid
        && (mask_meta_pop_data.copies != '0) && ip_resp_meta_push_ready
        && disposition_push_ready);
    assign selector_insert = selector_advance && selector_source_valid;

    always_comb begin
        for (int leaf = 0; leaf < SELECTOR_LEAVES; leaf++) begin
            logic [SELECTOR_LEAF_WIDTH-1:0] leaf_mask;
            leaf_mask = '0;
            for (int bit_idx = 0; bit_idx < SELECTOR_LEAF_WIDTH; bit_idx++) begin
                int unsigned flow_idx;
                flow_idx = leaf * SELECTOR_LEAF_WIDTH + bit_idx;
                if (flow_idx < NUM_FLOWS)
                    leaf_mask[bit_idx] = ip_issue_mask[flow_idx];
            end
            selector_leaf_c[leaf] = select_flow_leaf(leaf_mask, leaf * SELECTOR_LEAF_WIDTH);
        end

        selector_selected_c = '0;
        selector_leaf_selected_c = '0;
        for (int leaf = SELECTOR_LEAVES - 1; leaf >= 0; leaf--) begin
            if (selector_leaf_c[leaf].candidate.valid) begin
                selector_selected_c = selector_leaf_c[leaf].candidate;
                selector_leaf_selected_c = '0;
                selector_leaf_selected_c[leaf] = 1'b1;
            end
        end
    end

    always_comb begin
        for (int leaf = 0; leaf < SELECTOR_LEAVES; leaf++) begin
            ip_issue_mask_after_req[leaf * SELECTOR_LEAF_WIDTH +: SELECTOR_LEAF_WIDTH]
                = selector_leaf_selected_c[leaf]
                    ? selector_leaf_c[leaf].remaining_mask
                    : ip_issue_mask[leaf * SELECTOR_LEAF_WIDTH +: SELECTOR_LEAF_WIDTH];
        end
    end

    assign mask_meta_pop_ready = ip_zero_mask_fire
        || (selector_insert && selector_source_first);

    assign u_flow_ip_req.t.data = 32'(selector_stage_r[FLOW_SELECTOR_TREE_DEPTH-1][0].flow);
    assign u_flow_ip_req.t.keep = '1;
    assign u_flow_ip_req.t.last = 1'b1;
    assign u_flow_ip_req.tvalid = selector_valid_r[FLOW_SELECTOR_TREE_DEPTH-1]
        && selector_stage_r[FLOW_SELECTOR_TREE_DEPTH-1][0].valid;

    assign ip_resp_meta_push_valid = selector_insert && selector_source_first;
    assign ip_resp_meta_push_data.copies = mask_meta_copies;

    assign disposition_push_valid = ip_zero_mask_fire
        || (selector_insert && selector_source_first);
    assign disposition_push_data.drop = ip_zero_mask_fire;
    assign disposition_push_data.copies = ip_zero_mask_fire
        ? '0 : mask_meta_copies;

    assign ip_resp_meta_pop_ready = !ip_resp_active_r || ip_resp_final_fire;

    assign u_flow_ip_value.tready = ip_resp_active_r
        && packet_template_pop_valid && packet_header_push_ready;

    assign packet_header_push_valid = u_flow_ip_value.tvalid
        && ip_resp_active_r && packet_template_pop_valid;
    assign packet_header_push_data.header_beat = rewrite_ipv4_dst(
        packet_template_pop_data, u_flow_ip_value.t.data[31:0],
        PACKET_BEAT_W'(IPV4_DST_BEAT_IDX));
    assign packet_template_pop_ready = ip_zero_mask_fire || ip_resp_final_fire;

    // One packet is stored by beat index and read repeatedly.  Non-final
    // copies only advance and reset the read index; they do not rotate data
    // through a FIFO.  During the final copy, each accepted output beat frees
    // one location that may be replaced by the corresponding beat of the next
    // packet.  Coupling replacement writes to output progress makes overwrite
    // safety independent of downstream backpressure.
    typedef enum logic [1:0] {
        EGRESS_IDLE,
        EGRESS_LOAD,
        EGRESS_REPEAT,
        EGRESS_FINAL
    } egress_state_t;

    egress_state_t egress_state_r;
    logic load_drop_r;
    logic [FLOW_COUNT_W-1:0] load_copies_r;
    logic [PACKET_BEAT_W-1:0] store_write_idx_r;
    logic [PACKET_BEAT_W-1:0] replay_read_idx_r;
    logic load_start;
    logic load_fire;
    logic load_done_fire;
    logic next_desc_valid_r;
    logic next_desc_drop_r;
    logic [FLOW_COUNT_W-1:0] next_desc_copies_r;
    logic next_packet_done_r;
    logic next_desc_prefetch;
    logic next_desc_present;
    logic next_selected_drop;
    logic [FLOW_COUNT_W-1:0] next_selected_copies;
    logic next_load_fire;
    logic next_load_done_fire;

    logic output_first_beat_r;
    logic [FLOW_COUNT_W-1:0] output_copies_left_r;
    packet_chan_t output_header_beat_r;
    packet_chan_t output_source_t;
    logic output_source_valid;
    logic output_fire;
    logic output_packet_done_fire;
    logic output_descriptor_done_fire;

    (* ram_style = "registers" *)
    logic [$bits(packet_chan_t)-1:0] replay_mem [0:MAX_PACKET_BEATS-1];

    assign load_start = (egress_state_r == EGRESS_IDLE) && disposition_pop_valid;
    assign next_desc_prefetch = !next_desc_valid_r
        && disposition_pop_valid
        && ((egress_state_r == EGRESS_REPEAT)
            || (egress_state_r == EGRESS_FINAL)
            || ((egress_state_r == EGRESS_LOAD) && !load_drop_r));
    assign disposition_pop_ready = load_start || next_desc_prefetch;
    assign next_desc_present = next_desc_valid_r || next_desc_prefetch;
    assign next_selected_drop = next_desc_valid_r
        ? next_desc_drop_r : disposition_pop_data.drop;
    assign next_selected_copies = next_desc_valid_r
        ? next_desc_copies_r : disposition_pop_data.copies;

    assign u_main_fifo_out.tready = (egress_state_r == EGRESS_LOAD)
        || ((egress_state_r == EGRESS_FINAL)
            && next_desc_valid_r && !next_packet_done_r && output_fire);
    assign load_fire = (egress_state_r == EGRESS_LOAD)
        && u_main_fifo_out.tvalid;
    assign load_done_fire = load_fire && u_main_fifo_out.t.last;
    assign next_load_fire = (egress_state_r == EGRESS_FINAL)
        && next_desc_valid_r && !next_packet_done_r
        && u_main_fifo_out.tvalid && u_main_fifo_out.tready;
    assign next_load_done_fire = next_load_fire && u_main_fifo_out.t.last;

    assign output_source_t = packet_chan_t'(replay_mem[replay_read_idx_r]);
    assign output_source_valid = (egress_state_r == EGRESS_REPEAT)
        || (egress_state_r == EGRESS_FINAL);

    assign output_fire = output_source_valid
        && (!output_first_beat_r || packet_header_pop_valid)
        && packet_out.tready;
    assign output_packet_done_fire = output_fire && output_source_t.last;
    assign output_descriptor_done_fire = output_packet_done_fire
        && (egress_state_r == EGRESS_FINAL);

    always_comb begin
        packet_out.t = '0;
        packet_out.tvalid = 1'b0;
        if (output_source_valid) begin
            packet_out.t = output_source_t;
            if (output_first_beat_r && (IPV4_DST_BEAT_IDX == 0))
                packet_out.t = packet_header_pop_data.header_beat;
            else if (!output_first_beat_r
                && (replay_read_idx_r == PACKET_BEAT_W'(IPV4_DST_BEAT_IDX)))
                packet_out.t = output_header_beat_r;
            packet_out.tvalid = output_source_valid
                && (!output_first_beat_r || packet_header_pop_valid);
        end
    end

    assign packet_header_pop_ready = output_fire && output_first_beat_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            input_beat_count_r <= '0;
            ip_issue_active_r <= 1'b0;
            ip_issue_mask_r <= '0;
            ip_issue_left_r <= '0;
            selector_valid_r <= '0;
            for (int stage = 0; stage < FLOW_SELECTOR_TREE_DEPTH; stage++)
                for (int node = 0; node < SELECTOR_LEAVES; node++)
                    selector_stage_r[stage][node] <= '0;
            ip_resp_active_r <= 1'b0;
            ip_resp_cur_r <= '0;
            ip_resp_idx_r <= '0;
            egress_state_r <= EGRESS_IDLE;
            load_drop_r <= 1'b0;
            load_copies_r <= '0;
            store_write_idx_r <= '0;
            replay_read_idx_r <= '0;
            next_desc_valid_r <= 1'b0;
            next_desc_drop_r <= 1'b0;
            next_desc_copies_r <= '0;
            next_packet_done_r <= 1'b0;
            output_first_beat_r <= 1'b1;
            output_copies_left_r <= '0;
            output_header_beat_r <= '0;
        end else begin
            if (input_done) begin
                input_beat_count_r <= '0;
            end else if (input_fire) begin
                input_beat_count_r <= input_beat_count_r + PACKET_BEAT_W'(1);
            end

            if (selector_insert) begin
                ip_issue_mask_r <= ip_issue_mask_after_req;
                if (selector_source_first) begin
                    ip_issue_left_r <= mask_meta_copies - FLOW_COUNT_W'(1);
                    ip_issue_active_r <= (mask_meta_copies > FLOW_COUNT_W'(1));
                end else begin
                    ip_issue_left_r <= ip_issue_left_r - FLOW_COUNT_W'(1);
                    ip_issue_active_r <= (ip_issue_left_r > FLOW_COUNT_W'(1));
                end
            end

            if (selector_advance) begin
                selector_valid_r[0] <= selector_source_valid;
                for (int leaf = 0; leaf < SELECTOR_LEAVES; leaf++)
                    selector_stage_r[0][leaf] <= selector_leaf_c[leaf].candidate;

                for (int stage = 1; stage < FLOW_SELECTOR_TREE_DEPTH; stage++) begin
                    selector_valid_r[stage] <= selector_valid_r[stage-1];
                    for (int node = 0; node < SELECTOR_LEAVES; node++) begin
                        selector_stage_r[stage][node] <= '0;
                        if (node < (SELECTOR_LEAVES >> stage)) begin
                            if (selector_stage_r[stage-1][2*node].valid)
                                selector_stage_r[stage][node] <= selector_stage_r[stage-1][2*node];
                            else
                                selector_stage_r[stage][node] <= selector_stage_r[stage-1][2*node+1];
                        end
                    end
                end
            end

            if (!ip_resp_active_r && ip_resp_meta_pop_valid) begin
                ip_resp_active_r <= 1'b1;
                ip_resp_cur_r <= ip_resp_meta_pop_data;
                ip_resp_idx_r <= '0;
            end

            if (flow_ip_resp_fire) begin
                if (ip_resp_final_pending) begin
                    if (ip_resp_meta_pop_valid && ip_resp_meta_pop_ready) begin
                        ip_resp_active_r <= 1'b1;
                        ip_resp_cur_r <= ip_resp_meta_pop_data;
                        ip_resp_idx_r <= '0;
                    end else begin
                        ip_resp_active_r <= 1'b0;
                        ip_resp_cur_r <= '0;
                        ip_resp_idx_r <= '0;
                    end
                end else begin
                    ip_resp_idx_r <= ip_resp_idx_r + FLOW_COUNT_W'(1);
                end
            end

            if (next_desc_prefetch) begin
                next_desc_valid_r <= 1'b1;
                next_desc_drop_r <= disposition_pop_data.drop;
                next_desc_copies_r <= disposition_pop_data.copies;
                next_packet_done_r <= 1'b0;
            end

            if (next_load_done_fire)
                next_packet_done_r <= 1'b1;

            if (load_fire && !load_drop_r)
                replay_mem[store_write_idx_r] <= u_main_fifo_out.t;
            else if (next_load_fire && !next_desc_drop_r)
                replay_mem[store_write_idx_r] <= u_main_fifo_out.t;

            case (egress_state_r)
                EGRESS_IDLE: begin
                    if (load_start) begin
                        load_drop_r <= disposition_pop_data.drop;
                        load_copies_r <= disposition_pop_data.copies;
                        store_write_idx_r <= '0;
                        egress_state_r <= EGRESS_LOAD;
                    end
                end
                EGRESS_LOAD: begin
                    if (load_fire && !load_drop_r && !u_main_fifo_out.t.last)
                        store_write_idx_r <= store_write_idx_r
                            + PACKET_BEAT_W'(1);
                    if (load_done_fire) begin
                        load_drop_r <= 1'b0;
                        load_copies_r <= '0;
                        store_write_idx_r <= '0;
                        replay_read_idx_r <= '0;
                        if (load_drop_r) begin
                            output_copies_left_r <= '0;
                            egress_state_r <= EGRESS_IDLE;
                        end else begin
                            output_copies_left_r <= load_copies_r;
                            egress_state_r <= (load_copies_r
                                > FLOW_COUNT_W'(1))
                                ? EGRESS_REPEAT : EGRESS_FINAL;
                        end
                    end
                end
                EGRESS_REPEAT: begin
                    if (output_fire) begin
                        if (output_source_t.last) begin
                            replay_read_idx_r <= '0;
                            output_copies_left_r <= output_copies_left_r
                                - FLOW_COUNT_W'(1);
                            if (output_copies_left_r == FLOW_COUNT_W'(2)) begin
                                store_write_idx_r <= '0;
                                egress_state_r <= EGRESS_FINAL;
                            end
                        end else begin
                            replay_read_idx_r <= replay_read_idx_r
                                + PACKET_BEAT_W'(1);
                        end
                    end
                end
                EGRESS_FINAL: begin
                    if (output_fire) begin
                        if (output_source_t.last)
                            replay_read_idx_r <= '0;
                        else
                            replay_read_idx_r <= replay_read_idx_r
                                + PACKET_BEAT_W'(1);
                    end

                    if (next_load_fire && !next_desc_drop_r
                        && !u_main_fifo_out.t.last)
                        store_write_idx_r <= store_write_idx_r
                            + PACKET_BEAT_W'(1);

                    if (output_descriptor_done_fire) begin
                        next_desc_valid_r <= 1'b0;
                        next_desc_drop_r <= 1'b0;
                        next_desc_copies_r <= '0;
                        next_packet_done_r <= 1'b0;
                        replay_read_idx_r <= '0;

                        if (next_packet_done_r || next_load_done_fire) begin
                            store_write_idx_r <= '0;
                            if (next_selected_drop) begin
                                output_copies_left_r <= '0;
                                egress_state_r <= EGRESS_IDLE;
                            end else begin
                                output_copies_left_r <= next_selected_copies;
                                egress_state_r <= (next_selected_copies
                                    > FLOW_COUNT_W'(1))
                                    ? EGRESS_REPEAT : EGRESS_FINAL;
                            end
                        end else if (next_desc_present) begin
                            load_drop_r <= next_selected_drop;
                            load_copies_r <= next_selected_copies;
                            output_copies_left_r <= '0;
                            egress_state_r <= EGRESS_LOAD;
                        end else begin
                            store_write_idx_r <= '0;
                            output_copies_left_r <= '0;
                            egress_state_r <= EGRESS_IDLE;
                        end
                    end
                end
                default: begin
                    egress_state_r <= EGRESS_IDLE;
                    store_write_idx_r <= '0;
                    replay_read_idx_r <= '0;
                    output_copies_left_r <= '0;
                end
            endcase

            if ((egress_state_r == EGRESS_LOAD)
                && load_done_fire && !load_drop_r) begin
                output_first_beat_r <= 1'b1;
            end else if (output_fire) begin
                if (output_first_beat_r) begin
                    output_first_beat_r <= output_source_t.last;
                    output_header_beat_r <= packet_header_pop_data.header_beat;
                end
                if (output_source_t.last) begin
                    output_first_beat_r <= 1'b1;
                end else begin
                    output_first_beat_r <= 1'b0;
                end
            end
        end
    end

`ifndef SYNTHESIS
    logic [FLOW_ID_WIDTH-1:0] mask_lookup_base_q[$];

    always_ff @(posedge clk) begin
        if (!resetn) begin
            mask_lookup_base_q.delete();
        end else begin
            if ((load_fire && !load_drop_r)
                || (next_load_fire && !next_desc_drop_r)) begin
                assert (store_write_idx_r < MAX_PACKET_BEATS)
                    else $fatal(1,
                        "multicast: replay store write index %0d exceeds %0d beats",
                        store_write_idx_r, MAX_PACKET_BEATS);
            end

            if (next_load_fire && !next_desc_drop_r) begin
                assert (store_write_idx_r <= replay_read_idx_r)
                    else $fatal(1,
                        "multicast: next-packet write index %0d passed final-copy read index %0d",
                        store_write_idx_r, replay_read_idx_r);
            end

            if (mask_req_fire)
                mask_lookup_base_q.push_back(flow_meta_pop_data.base_flow);

            if (mask_resp_fire) begin
                logic [FLOW_ID_WIDTH-1:0] response_base_flow;
                assert (mask_lookup_base_q.size() != 0)
                    else $fatal(1, "multicast: mask response without a matching request");
                if (mask_lookup_base_q.size() != 0) begin
                    response_base_flow = mask_lookup_base_q.pop_front();
                    assert (mask_meta_push_data.copies
                        == popcount_flows(mask_meta_push_data.mask))
                        else $fatal(1,
                            "multicast: base flow %0d has programmed copies %0d, expected %0d",
                            response_base_flow, mask_meta_push_data.copies,
                            popcount_flows(mask_meta_push_data.mask));
                end
            end
        end
    end
`endif

endmodule
