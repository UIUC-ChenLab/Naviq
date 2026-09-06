`include "ifc_axis.sv"
`include "ifc_axil.sv"
`include "parser_pkg.sv"

module packet_engine_egress_hash_pipeline #(
    parameter int NUM_OUTPUTS          = 1,
    parameter int DATA_WIDTH           = 512,
    parameter int unsigned OFFLOAD_ID  = 0,
    parameter int unsigned TID_BASE    = 2 * OFFLOAD_ID,
    parameter int NUM_FLOWS            = 4096,
    parameter int HASH_FIFO_DEPTH      = 64
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis [NUM_OUTPUTS],
    ifc_axil.slave  flow_ctrl,
    ifc_axil.slave  next_hop_ctrl
);

    import parser_pkg::*;
    localparam int TDEST_WIDTH = 10;
    // Next-hop MMIO word: [9:0] destination, [10] path-local NMU lane.
    localparam int NEXT_HOP_WIDTH = TDEST_WIDTH + 1;
    localparam int TID_WIDTH = 6;
    localparam int TUSER_WIDTH = 1;
    localparam int STEERING_TUPLE_WIDTH = 104;
    localparam int FLOW_ASSOCIATIVITY = 4;
    localparam int FLOW_TABLE_DEPTH = NUM_FLOWS / FLOW_ASSOCIATIVITY;
    localparam int FLOW_SET_WIDTH = $clog2(FLOW_TABLE_DEPTH);
    localparam int FLOW_VALUE_WIDTH = $clog2(NUM_FLOWS);
    localparam int FLOW_WAY_WIDTH = $clog2(FLOW_ASSOCIATIVITY);
    localparam int EGRESS_SELECT_WIDTH =
        (NUM_OUTPUTS <= 1) ? 1 : $clog2(NUM_OUTPUTS);
    localparam int TOEPLITZ_KEY_WIDTH = 320;
    localparam logic [TOEPLITZ_KEY_WIDTH-1:0] TOEPLITZ_KEY =
        320'h6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa;

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH)
    ) u_metadata_axis (.axis_aclk(clk)), u_fanout_axis [2] (.axis_aclk(clk)),
      u_payload_axis (.axis_aclk(clk)), u_steered_axis (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_parser_axis (.axis_aclk(clk)), u_parser_payload (.axis_aclk(clk));

    assign u_metadata_axis.t.data = s_axis.t.data;
    assign u_metadata_axis.t.keep = s_axis.t.keep;
    assign u_metadata_axis.t.id = TID_WIDTH'(s_axis.t.id);
    assign u_metadata_axis.t.dest = TDEST_WIDTH'(s_axis.t.dest);
    assign u_metadata_axis.t.user = TUSER_WIDTH'(s_axis.t.user);
    assign u_metadata_axis.t.last = s_axis.t.last;
    assign u_metadata_axis.tvalid = s_axis.tvalid;
    assign s_axis.tready = u_metadata_axis.tready;

    axis_multicast #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH),
        .NUM_DESTS(2)
    ) u_fanout (
        .clk(clk), .resetn(resetn), .s_axis(u_metadata_axis.slave),
        .m_axis(u_fanout_axis)
    );

    axis_packet_fifo #(
        .DEPTH(HASH_FIFO_DEPTH), .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
        .TUSER_WIDTH(TUSER_WIDTH), .MODE("CONSERVATIVE")
    ) u_payload_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_fanout_axis[0]),
        .m_axis(u_payload_axis)
    );

    assign u_parser_axis.t.data = u_fanout_axis[1].t.data;
    assign u_parser_axis.t.keep = u_fanout_axis[1].t.keep;
    assign u_parser_axis.t.id = u_fanout_axis[1].t.id[0];
    assign u_parser_axis.t.dest = u_fanout_axis[1].t.dest[0];
    assign u_parser_axis.t.user = u_fanout_axis[1].t.user[0];
    assign u_parser_axis.t.last = u_fanout_axis[1].t.last;
    assign u_parser_axis.tvalid = u_fanout_axis[1].tvalid;
    assign u_fanout_axis[1].tready = u_parser_axis.tready;

    ifc_axis #(
        .DATA_WIDTH(parser_pkg::L2_HDR_AXIS_BITS), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_l2_header (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(parser_pkg::L3_HDR_AXIS_BITS), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_l3_header (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(parser_pkg::L4_HDR_AXIS_BITS), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_l4_header (.axis_aclk(clk));

    parser #(
        .DATA_WIDTH(DATA_WIDTH), .SKIP_L2(1'b1),
        .SKIP_L3(1'b0), .SKIP_L4(1'b0),
        .HEADER_ONLY(1'b0), .REPACK_PAYLOAD_OUT(1'b0),
        .FRAGMENT_PACKER_PAGE_COUNT(8), .INTER_STAGE_FIFO_DEPTH(12),
        .DEFAULT_ETHERTYPE(16'h0800), .DEFAULT_L4_PROTOCOL(8'd0)
    ) u_parser (
        .clk(clk), .resetn(resetn), .s_axis_packet_in(u_parser_axis),
        .m_axis_l2_header_out(u_l2_header), .m_axis_l3_header_out(u_l3_header),
        .m_axis_l4_header_out(u_l4_header), .m_axis_payload_out(u_parser_payload)
    );
    assign u_l2_header.tready = 1'b1;
    assign u_parser_payload.tready = 1'b1;

    parser_pkg::l3_hdr_axis_t l3_header_c;
    parser_pkg::l4_hdr_axis_t l4_header_c;
    parser_pkg::ipv4_hdr_t ipv4_header_c;
    parser_pkg::tcp_hdr_t tcp_header_c;
    parser_pkg::udp_hdr_t udp_header_c;
    logic l3_fifo_valid_c;
    logic l3_fifo_ready_c;
    parser_pkg::l3_hdr_axis_t l3_fifo_data_c;
    logic l4_fifo_valid_c;
    logic l4_fifo_ready_c;
    parser_pkg::l4_hdr_axis_t l4_fifo_data_c;
    logic headers_valid_c;
    logic tuple_eligible_c;
    logic [15:0] tuple_src_port_c;
    logic [15:0] tuple_dst_port_c;
    logic [STEERING_TUPLE_WIDTH-1:0] tuple_c;
    logic [FLOW_SET_WIDTH-1:0] tuple_hash_c;

    sync_bram_fifo #(
        .DEPTH(HASH_FIFO_DEPTH), .T(parser_pkg::l3_hdr_axis_t),
        .MODE("CONSERVATIVE")
    ) u_l3_header_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(u_l3_header.tvalid),
        .push_data(parser_pkg::l3_hdr_axis_t'(u_l3_header.t.data)),
        .push_ready(u_l3_header.tready),
        .pop_valid(l3_fifo_valid_c), .pop_data(l3_fifo_data_c),
        .pop_ready(l3_fifo_ready_c)
    );

    sync_bram_fifo #(
        .DEPTH(HASH_FIFO_DEPTH), .T(parser_pkg::l4_hdr_axis_t),
        .MODE("CONSERVATIVE")
    ) u_l4_header_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(u_l4_header.tvalid),
        .push_data(parser_pkg::l4_hdr_axis_t'(u_l4_header.t.data)),
        .push_ready(u_l4_header.tready),
        .pop_valid(l4_fifo_valid_c), .pop_data(l4_fifo_data_c),
        .pop_ready(l4_fifo_ready_c)
    );

    assign l3_header_c = l3_fifo_data_c;
    assign l4_header_c = l4_fifo_data_c;
    assign ipv4_header_c = l3_header_c.ipv4;
    assign tcp_header_c = l4_header_c.tcp;
    assign udp_header_c = l4_header_c.udp;
    assign headers_valid_c = l3_fifo_valid_c && l4_fifo_valid_c;
    assign tuple_eligible_c =
        (l3_header_c.status == parser_pkg::PARSER_STATUS_OK) &&
        (l3_header_c.kind == parser_pkg::L3_KIND_IPV4);
    assign tuple_src_port_c =
        (l4_header_c.kind == parser_pkg::L4_KIND_TCP) ? tcp_header_c.src_port :
        (l4_header_c.kind == parser_pkg::L4_KIND_UDP) ? udp_header_c.src_port : 16'b0;
    assign tuple_dst_port_c =
        (l4_header_c.kind == parser_pkg::L4_KIND_TCP) ? tcp_header_c.dst_port :
        (l4_header_c.kind == parser_pkg::L4_KIND_UDP) ? udp_header_c.dst_port : 16'b0;
    assign tuple_c = {
        ipv4_header_c.protocol, tuple_dst_port_c, tuple_src_port_c,
        ipv4_header_c.dst_addr, ipv4_header_c.src_addr
    };

    toeplitz_hash #(
        .HASH_WIDTH(FLOW_SET_WIDTH), .TUPLE_WIDTH(STEERING_TUPLE_WIDTH),
        .GENERIC_TUPLE_MODE(1'b0),
        .TOEPLITZ_KEY_W(TOEPLITZ_KEY_WIDTH), .TOEPLITZ_KEY(TOEPLITZ_KEY)
    ) u_toeplitz_hash (
        .tuple_bits(tuple_c), .hash_value(tuple_hash_c)
    );

    ifc_axis #(.DATA_WIDTH(32), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_flow_index (.axis_aclk(clk)), u_flow_value (.axis_aclk(clk)),
        u_next_hop_req (.axis_aclk(clk)), u_next_hop_value (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(STEERING_TUPLE_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_flow_key (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(STEERING_TUPLE_WIDTH + FLOW_SET_WIDTH),
        .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_flow_error (.axis_aclk(clk));

    logic eligibility_push_valid;
    logic eligibility_push_ready;
    logic eligibility_pop_valid;
    logic eligibility_pop_data;
    logic eligibility_pop_ready;
    logic decision_push_valid;
    logic decision_push_ready;
    logic decision_pop_valid;
    logic decision_pop_data;
    logic decision_pop_ready;

    sync_bram_fifo #(
        .DEPTH(HASH_FIFO_DEPTH), .T(logic), .MODE("CONSERVATIVE")
    ) u_eligibility_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(eligibility_push_valid), .push_data(tuple_eligible_c),
        .push_ready(eligibility_push_ready),
        .pop_valid(eligibility_pop_valid), .pop_data(eligibility_pop_data),
        .pop_ready(eligibility_pop_ready)
    );

    sync_bram_fifo #(
        .DEPTH(HASH_FIFO_DEPTH), .T(logic), .MODE("CONSERVATIVE")
    ) u_decision_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(decision_push_valid),
        .push_data(eligibility_pop_data && u_flow_value.tvalid),
        .push_ready(decision_push_ready),
        .pop_valid(decision_pop_valid), .pop_data(decision_pop_data),
        .pop_ready(decision_pop_ready)
    );

    always_comb begin
        logic lookup_inputs_ready;
        logic result_available;
        logic result_is_hit;

        lookup_inputs_ready = u_flow_index.tready && u_flow_key.tready;
        eligibility_push_valid = headers_valid_c &&
            (!tuple_eligible_c || lookup_inputs_ready);
        l3_fifo_ready_c = eligibility_push_ready &&
            (!tuple_eligible_c || lookup_inputs_ready) && l4_fifo_valid_c;
        l4_fifo_ready_c = eligibility_push_ready &&
            (!tuple_eligible_c || lookup_inputs_ready) && l3_fifo_valid_c;

        u_flow_index.t = '0;
        u_flow_key.t = '0;
        u_flow_index.t.data = 32'(tuple_hash_c);
        u_flow_key.t.data = tuple_c;
        u_flow_index.t.keep = '1;
        u_flow_key.t.keep = '1;
        u_flow_index.t.last = 1'b1;
        u_flow_key.t.last = 1'b1;
        u_flow_index.tvalid = headers_valid_c && tuple_eligible_c &&
            eligibility_push_ready && u_flow_key.tready;
        u_flow_key.tvalid = headers_valid_c && tuple_eligible_c &&
            eligibility_push_ready && u_flow_index.tready;

        result_available = !eligibility_pop_data ||
            u_flow_value.tvalid || u_flow_error.tvalid;
        result_is_hit = eligibility_pop_data && u_flow_value.tvalid;
        decision_push_valid = eligibility_pop_valid && result_available &&
            (!result_is_hit || u_next_hop_req.tready);
        eligibility_pop_ready = decision_push_valid && decision_push_ready;
        u_flow_value.tready = eligibility_pop_ready && eligibility_pop_data;
        u_flow_error.tready = eligibility_pop_ready && eligibility_pop_data;

        u_next_hop_req.t = '0;
        u_next_hop_req.t.data = u_flow_value.t.data;
        u_next_hop_req.t.keep = '1;
        u_next_hop_req.t.last = 1'b1;
        u_next_hop_req.tvalid = eligibility_pop_valid && eligibility_pop_data &&
            u_flow_value.tvalid && decision_push_ready;
    end

    logic [FLOW_WAY_WIDTH-1:0] unused_flow_way;
    logic [FLOW_WAY_WIDTH-1:0] unused_mgmt_way;
    logic unused_runtime_ready;
    logic unused_mgmt_commit;
    logic [FLOW_SET_WIDTH-1:0] unused_mgmt_set;

    axil_hash_table #(
        .TABLE_DEPTH(FLOW_TABLE_DEPTH), .KEY_WIDTH(STEERING_TUPLE_WIDTH),
        .VALUE_WIDTH(FLOW_VALUE_WIDTH),
        .RUNTIME_VALUE_WIDTH(0), .ASSOCIATIVITY(FLOW_ASSOCIATIVITY)
    ) u_flow_table (
        .clk(clk), .resetn(resetn), .ctrl_in(flow_ctrl),
        .s_axis_lookup_index(u_flow_index), .s_axis_key(u_flow_key),
        .m_axis_value(u_flow_value), .m_axis_error(u_flow_error),
        .m_axis_value_way(unused_flow_way),
        .runtime_update_valid(1'b0), .runtime_update_ready(unused_runtime_ready),
        .runtime_update_set('0), .runtime_update_way('0),
        .runtime_update_data('0), .mgmt_write_commit(unused_mgmt_commit),
        .mgmt_write_set(unused_mgmt_set), .mgmt_write_way(unused_mgmt_way)
    );

    lookup_table #(
        .TABLE_DEPTH(NUM_FLOWS), .TABLE_VALUE_WIDTH(NEXT_HOP_WIDTH),
        .ENABLE_AXIL_READ(1)
    ) u_next_hop_table (
        .clk(clk), .resetn(resetn), .ctrl_in(next_hop_ctrl),
        .s_axis_lookup(u_next_hop_req), .m_axis_value(u_next_hop_value)
    );

    logic route_active_r;
    logic route_forward_r;
    logic [NEXT_HOP_WIDTH-1:0] route_word_r;
    logic decision_available_c;
    logic route_valid_c;
    logic route_forward_c;
    logic [NEXT_HOP_WIDTH-1:0] route_word_c;
    logic route_lane_c;
    logic payload_fire_c;
    logic decision_fire_c;

    assign decision_available_c = decision_pop_valid &&
        (!decision_pop_data || u_next_hop_value.tvalid);
    assign route_valid_c = route_active_r || decision_available_c;
    assign route_word_c = route_active_r ? route_word_r :
        NEXT_HOP_WIDTH'(u_next_hop_value.t.data);
    assign route_lane_c = route_word_c[TDEST_WIDTH];
    assign route_forward_c = route_active_r ? route_forward_r :
        (decision_pop_data && (int'(route_lane_c) < NUM_OUTPUTS));

    assign u_steered_axis.t.data = u_payload_axis.t.data;
    assign u_steered_axis.t.keep = u_payload_axis.t.keep;
    // Independent output NMUs need distinct identities at downstream rebuilders.
    // The lookup response holds the first stalled beat; the latched route
    // holds all remaining beats, including a stalled TLAST. Never reroute a
    // blocked lane onto the other NMU.
    assign u_steered_axis.t.id = TID_WIDTH'(TID_BASE + int'(route_lane_c));
    assign u_steered_axis.t.dest = route_word_c[TDEST_WIDTH-1:0];
    assign u_steered_axis.t.user = u_payload_axis.t.user;
    assign u_steered_axis.t.last = u_payload_axis.t.last;
    assign u_steered_axis.tvalid =
        route_valid_c && route_forward_c && u_payload_axis.tvalid;
    assign u_payload_axis.tready = route_valid_c &&
        (route_forward_c ? u_steered_axis.tready : 1'b1);
    assign payload_fire_c = u_payload_axis.tvalid && u_payload_axis.tready;
    assign decision_fire_c = payload_fire_c && !route_active_r;
    assign decision_pop_ready = decision_fire_c;
    assign u_next_hop_value.tready = decision_fire_c && decision_pop_data;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            route_active_r <= 1'b0;
            route_forward_r <= 1'b0;
            route_word_r <= '0;
        end else if (payload_fire_c) begin
            if (!route_active_r) begin
                route_active_r <= !u_payload_axis.t.last;
                route_forward_r <= route_forward_c;
                route_word_r <= route_word_c;
            end else if (u_payload_axis.t.last) begin
                route_active_r <= 1'b0;
            end
        end
    end

    generate
        if (NUM_OUTPUTS == 2) begin : g_output_demux
            axis_packet_demux #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
                .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH),
                .NUM_MASTERS(2), .SELECT_WIDTH(EGRESS_SELECT_WIDTH),
                .BROADCAST_DATA(1'b0)
            ) u_demux (
                .clk(clk), .resetn(resetn), .select(route_lane_c),
                .s_axis(u_steered_axis.slave), .m_axis(m_axis)
            );
        end else begin : g_single_output
            assign m_axis[0].t = u_steered_axis.t;
            assign m_axis[0].tvalid = u_steered_axis.tvalid;
            assign u_steered_axis.tready = m_axis[0].tready;
        end
    endgenerate


    initial begin
        if (NUM_OUTPUTS < 1 || NUM_OUTPUTS > 2) begin
            $error("packet_engine_egress_pipeline: NUM_OUTPUTS must be 1 or 2");
            $finish;
        end
        if (HASH_FIFO_DEPTH < 2) begin
            $error("packet_engine_egress_hash_pipeline: HASH_FIFO_DEPTH must be at least 2");
            $finish;
        end
        if (NUM_FLOWS < 64 || (NUM_FLOWS & (NUM_FLOWS - 1)) != 0 ||
            NUM_FLOWS > 8192) begin
            $error("packet_engine_egress_hash_pipeline: NUM_FLOWS must be a power of two from 64 through 8192");
            $finish;
        end
        if ($bits(s_axis.t.data) != DATA_WIDTH || $bits(s_axis.t.dest) != 1 ||
            $bits(s_axis.t.id) != 1 || $bits(s_axis.t.user) != 1) begin
            $error("packet_engine_egress_pipeline: input must use one-bit sidebands");
            $finish;
        end
        if ($bits(m_axis[0].t.data) != DATA_WIDTH ||
            $bits(m_axis[0].t.dest) != TDEST_WIDTH ||
            $bits(m_axis[0].t.id) != TID_WIDTH ||
            $bits(m_axis[0].t.user) != TUSER_WIDTH) begin
            $error("packet_engine_egress_pipeline: output does not use packet-engine AXIS widths");
            $finish;
        end
    end

endmodule

module packet_engine_egress_header_pipeline #(
    parameter int NUM_OUTPUTS             = 1,
    parameter int DATA_WIDTH              = 512,
    parameter int unsigned OFFLOAD_ID     = 0,
    parameter int unsigned TID_BASE       = 2 * OFFLOAD_ID,
    parameter int NUM_FLOWS               = 4096,
    parameter int STEERING_HEADER_BYTES   = 2
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis [NUM_OUTPUTS],
    ifc_axil.slave  next_hop_ctrl
);
    localparam int TDEST_WIDTH = 10;
    localparam int NEXT_HOP_WIDTH = TDEST_WIDTH + 1;
    localparam int TID_WIDTH = 6;
    localparam int HEADER_WIDTH = 8 * STEERING_HEADER_BYTES;
    localparam int FLOW_INDEX_WIDTH = $clog2(NUM_FLOWS);
    localparam int LOOKUP_WIDTH =
        (HEADER_WIDTH > FLOW_INDEX_WIDTH) ? HEADER_WIDTH : FLOW_INDEX_WIDTH;
    localparam int EGRESS_SELECT_WIDTH =
        (NUM_OUTPUTS <= 1) ? 1 : $clog2(NUM_OUTPUTS);

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(HEADER_WIDTH)
    ) u_payload_axis (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_header_axis (.axis_aclk(clk)), u_combined_axis (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(LOOKUP_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_next_hop_req (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(32), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_next_hop_value (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(1)
    ) u_steered_axis (.axis_aclk(clk));

    logic packet_active_r;
    logic drop_active_r;
    logic [HEADER_WIDTH-1:0] header_index_c;
    logic header_index_valid_c;
    logic first_valid_accept_c;
    logic input_fire_c;

    always_comb begin
        header_index_c = '0;
        for (int byte_index = 0; byte_index < STEERING_HEADER_BYTES; ++byte_index)
            header_index_c[(STEERING_HEADER_BYTES-1-byte_index)*8 +: 8] =
                s_axis.t.user[byte_index*8 +: 8];
    end
    assign header_index_valid_c = $unsigned(header_index_c) < NUM_FLOWS;
    assign first_valid_accept_c = u_payload_axis.tready &&
        u_header_axis.tready && u_next_hop_req.tready;

    assign u_payload_axis.t = s_axis.t;
    assign u_payload_axis.tvalid = s_axis.tvalid &&
        (packet_active_r || (!drop_active_r && header_index_valid_c &&
         u_header_axis.tready && u_next_hop_req.tready));

    always_comb begin
        u_header_axis.t = '0;
        u_header_axis.t.data[HEADER_WIDTH-1:0] = s_axis.t.user;
        u_header_axis.t.keep[STEERING_HEADER_BYTES-1:0] = '1;
        u_header_axis.t.last = 1'b1;
        u_header_axis.tvalid = s_axis.tvalid && !packet_active_r &&
            !drop_active_r && header_index_valid_c &&
            u_payload_axis.tready && u_next_hop_req.tready;

        u_next_hop_req.t = '0;
        u_next_hop_req.t.data = header_index_c;
        u_next_hop_req.t.keep = '1;
        u_next_hop_req.t.last = 1'b1;
        u_next_hop_req.tvalid = s_axis.tvalid && !packet_active_r &&
            !drop_active_r && header_index_valid_c &&
            u_payload_axis.tready && u_header_axis.tready;
    end

    assign s_axis.tready = packet_active_r ? u_payload_axis.tready :
        drop_active_r ? 1'b1 :
        header_index_valid_c ? first_valid_accept_c : 1'b1;
    assign input_fire_c = s_axis.tvalid && s_axis.tready;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            packet_active_r <= 1'b0;
            drop_active_r <= 1'b0;
        end else if (input_fire_c) begin
            if (packet_active_r)
                packet_active_r <= !s_axis.t.last;
            else if (drop_active_r)
                drop_active_r <= !s_axis.t.last;
            else if (header_index_valid_c)
                packet_active_r <= !s_axis.t.last;
            else
                drop_active_r <= !s_axis.t.last;
        end
    end

    axis_combine_repack #(
        .FIRST_STREAM_IS_A(1), .DATA_WIDTH(DATA_WIDTH)
    ) u_reappend_header (
        .clk(clk), .resetn(resetn), .s_axis_a(u_header_axis.slave),
        .s_axis_b(u_payload_axis.slave), .m_axis(u_combined_axis.master)
    );

    lookup_table #(
        .TABLE_DEPTH(NUM_FLOWS), .TABLE_VALUE_WIDTH(NEXT_HOP_WIDTH),
        .ENABLE_AXIL_READ(1)
    ) u_next_hop_table (
        .clk(clk), .resetn(resetn), .ctrl_in(next_hop_ctrl),
        .s_axis_lookup(u_next_hop_req), .m_axis_value(u_next_hop_value)
    );

    logic route_active_r;
    logic [NEXT_HOP_WIDTH-1:0] route_word_r;
    logic route_push_ready;
    logic route_pop_valid;
    logic [NEXT_HOP_WIDTH-1:0] route_pop_data;
    logic route_pop_ready;
    logic route_available_c;
    logic [NEXT_HOP_WIDTH-1:0] route_word_c;
    logic route_lane_c;
    logic route_forward_c;
    logic output_fire_c;

    // Decouple lookup completion from the packet repacking latency.  Holding
    // responses in the lookup table until the corresponding packet reached
    // this point limited the number of packets in flight to the table's two
    // response slots and created a packet-rate feedback loop.
    sync_ff_fifo #(
        .DEPTH(32), .T(logic [NEXT_HOP_WIDTH-1:0]), .MODE("FULL_CAPACITY")
    ) u_route_fifo (
        .clk(clk), .resetn(resetn),
        .push_valid(u_next_hop_value.tvalid),
        .push_data(NEXT_HOP_WIDTH'(u_next_hop_value.t.data)),
        .push_ready(route_push_ready),
        .pop_valid(route_pop_valid), .pop_data(route_pop_data),
        .pop_ready(route_pop_ready)
    );

    assign u_next_hop_value.tready = route_push_ready;
    assign route_available_c = route_active_r || route_pop_valid;
    assign route_word_c = route_active_r ? route_word_r : route_pop_data;
    assign route_lane_c = route_word_c[TDEST_WIDTH];
    assign route_forward_c = int'(route_lane_c) < NUM_OUTPUTS;
    assign u_steered_axis.t.data = u_combined_axis.t.data;
    assign u_steered_axis.t.keep = u_combined_axis.t.keep;
    assign u_steered_axis.t.id = TID_WIDTH'(TID_BASE + int'(route_lane_c));
    assign u_steered_axis.t.dest = route_word_c[TDEST_WIDTH-1:0];
    assign u_steered_axis.t.user = '0;
    assign u_steered_axis.t.last = u_combined_axis.t.last;
    assign u_steered_axis.tvalid = u_combined_axis.tvalid &&
        route_available_c && route_forward_c;
    // An unavailable physical lane is a whole-packet drop. Drain it while
    // consuming one route token, even when the existing output is blocked.
    assign u_combined_axis.tready = route_available_c &&
        (route_forward_c ? u_steered_axis.tready : 1'b1);
    assign output_fire_c = u_combined_axis.tvalid && u_combined_axis.tready;
    assign route_pop_ready = output_fire_c && !route_active_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            route_active_r <= 1'b0;
            route_word_r <= '0;
        end else if (output_fire_c) begin
            if (!route_active_r) begin
                route_active_r <= !u_combined_axis.t.last;
                route_word_r <= route_pop_data;
            end else if (u_combined_axis.t.last) begin
                route_active_r <= 1'b0;
            end
        end
    end

    generate
        if (NUM_OUTPUTS == 2) begin : g_output_demux
            axis_packet_demux #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
                .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(1),
                .NUM_MASTERS(2), .SELECT_WIDTH(EGRESS_SELECT_WIDTH),
                .BROADCAST_DATA(1'b0)
            ) u_demux (
                .clk(clk), .resetn(resetn), .select(route_lane_c),
                .s_axis(u_steered_axis.slave), .m_axis(m_axis)
            );
        end else begin : g_single_output
            assign m_axis[0].t = u_steered_axis.t;
            assign m_axis[0].tvalid = u_steered_axis.tvalid;
            assign u_steered_axis.tready = m_axis[0].tready;
        end
    endgenerate

    initial begin
        if (NUM_OUTPUTS < 1 || NUM_OUTPUTS > 2)
            $error("packet_engine_egress_header_pipeline: NUM_OUTPUTS must be 1 or 2");
        if ($bits(s_axis.t.user) != HEADER_WIDTH)
            $error("packet_engine_egress_header_pipeline: input tuser width mismatch");
    end
endmodule

module packet_engine_egress_pipeline #(
    parameter int NUM_OUTPUTS             = 1,
    parameter int DATA_WIDTH              = 512,
    parameter int unsigned OFFLOAD_ID     = 0,
    parameter int unsigned TID_BASE       = 2 * OFFLOAD_ID,
    parameter int NUM_FLOWS               = 4096,
    parameter int HASH_FIFO_DEPTH         = 64,
    parameter int STEERING_MODE           = 0,
    parameter int STEERING_HEADER_BYTES   = 2
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis [NUM_OUTPUTS],
    ifc_axil.slave  flow_ctrl,
    ifc_axil.slave  next_hop_ctrl
);
    localparam int HEADER_WIDTH = 8 * STEERING_HEADER_BYTES;

    generate
        if (STEERING_MODE == 0) begin : g_hash_steering
            packet_engine_egress_hash_pipeline #(
                .NUM_OUTPUTS(NUM_OUTPUTS), .DATA_WIDTH(DATA_WIDTH),
                .OFFLOAD_ID(OFFLOAD_ID), .TID_BASE(TID_BASE), .NUM_FLOWS(NUM_FLOWS),
                .HASH_FIFO_DEPTH(HASH_FIFO_DEPTH)
            ) u_hash_pipeline (
                .clk(clk), .resetn(resetn), .s_axis(s_axis), .m_axis(m_axis),
                .flow_ctrl(flow_ctrl), .next_hop_ctrl(next_hop_ctrl)
            );
        end else begin : g_header_steering
            // TBD: only dummy_fifo is currently verified to preserve this
            // widened per-beat tuser value through the offload.
            axil_dummy_okay_slave u_unused_flow_ctrl (
                .clk(clk), .resetn(resetn), .ctrl_in(flow_ctrl)
            );
            packet_engine_egress_header_pipeline #(
                .NUM_OUTPUTS(NUM_OUTPUTS), .DATA_WIDTH(DATA_WIDTH),
                .OFFLOAD_ID(OFFLOAD_ID), .TID_BASE(TID_BASE), .NUM_FLOWS(NUM_FLOWS),
                .STEERING_HEADER_BYTES(STEERING_HEADER_BYTES)
            ) u_header_pipeline (
                .clk(clk), .resetn(resetn), .s_axis(s_axis), .m_axis(m_axis),
                .next_hop_ctrl(next_hop_ctrl)
            );
        end
    endgenerate

    initial begin
        if (TID_BASE >= 64 || NUM_OUTPUTS > 64 - TID_BASE)
            $fatal(1, "packet_engine_egress_pipeline: output TIDs exceed six-bit interface");
        if (STEERING_MODE < 0 || STEERING_MODE > 1)
            $error("packet_engine_egress_pipeline: STEERING_MODE must be 0 or 1");
        if (STEERING_HEADER_BYTES < 1 || STEERING_HEADER_BYTES > DATA_WIDTH / 8)
            $error("packet_engine_egress_pipeline: STEERING_HEADER_BYTES must fit one data beat");
        if (HASH_FIFO_DEPTH < 2)
            $error("packet_engine_egress_pipeline: HASH_FIFO_DEPTH must be at least 2");
        if ($bits(s_axis.t.user) != ((STEERING_MODE == 1) ? HEADER_WIDTH : 1))
            $error("packet_engine_egress_pipeline: input tuser width does not match steering mode");
    end
endmodule
