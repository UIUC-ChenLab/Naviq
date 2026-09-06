// IPv4/UDP UDP segmentation offload.
//
// packet_in is an Ethernet-stripped IPv4/UDP packet. The parser extracts the
// IPv4/UDP header and payload; the emit FSM reuses the parsed header fields and
// rewrites IPv4 total length and UDP length for each emitted segment.

`include "ifc_axis.sv"
`include "ifc_axil.sv"
`include "parser_pkg.sv"

import parser_pkg::*;

module uso #(
    parameter int DATA_WIDTH       = 512,
    parameter int MAX_SEGMENT_SIZE = 8192,
    parameter int MAX_CHUNK_SIZE   = 16384
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  packet_in,
    ifc_axil.slave  ctrl_in,
    ifc_axis.master packet_out,
    output logic    tlast_context
);

    localparam int DATA_BYTES = DATA_WIDTH / 8;
    localparam int IPV4_HDR_BYTES = 20;
    localparam int UDP_HDR_BYTES = parser_pkg::UDP_HDR_BITS / 8;
    localparam int HEADER_BYTES = IPV4_HDR_BYTES + UDP_HDR_BYTES;
    localparam int L2_HDR_BITS = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int L3_HDR_BITS = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_BITS = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int HEADER_DESC_BITS = parser_pkg::IPV4_HDR_BITS + parser_pkg::UDP_HDR_BITS;
    localparam int SIZE_WIDTH = 32;
    localparam int BEAT_COUNT_AXIS_W = $clog2(DATA_WIDTH);
    localparam int BYTE_COUNT_W = $clog2(MAX_CHUNK_SIZE + MAX_SEGMENT_SIZE + DATA_BYTES + 1);
    localparam int HEADER_OFFSET_W = $clog2(HEADER_BYTES + DATA_BYTES + 1);
    localparam int PAYLOAD_FIFO_DEPTH = (2 * MAX_CHUNK_SIZE + DATA_BYTES - 1) / DATA_BYTES;
    localparam int TARGET_MIN_BYTES = 64;

    typedef enum logic [1:0] {
        EMIT_IDLE,
        EMIT_HEADER,
        EMIT_PAYLOAD,
        EMIT_DROP
    } emit_state_t;

    emit_state_t emit_state_r;

    ipv4_hdr_t ipv4_hdr_r;
    udp_hdr_t  udp_hdr_r;
    logic [BYTE_COUNT_W-1:0] payload_remaining_r;
    logic [BYTE_COUNT_W-1:0] segment_remaining_r;
    logic [BYTE_COUNT_W-1:0] segment_payload_bytes_r;
    logic [HEADER_OFFSET_W-1:0] header_offset_r;

    logic [7:0] segment_onehot_r;
    logic [BYTE_COUNT_W-1:0] segment_target_bytes;
    logic segment_enabled;

    logic aw_seen_r;
    logic [31:0] aw_addr_r;
    logic w_seen_r;
    logic [31:0] w_data_r;
    logic b_valid_r;
    logic r_valid_r;
    logic [31:0] r_data_r;

    function automatic logic [7:0] normalize_onehot(input logic [31:0] value);
        normalize_onehot = 8'h00;
        if (value[0]) normalize_onehot = 8'h01;
        else if (value[1]) normalize_onehot = 8'h02;
        else if (value[2]) normalize_onehot = 8'h04;
        else if (value[3]) normalize_onehot = 8'h08;
        else if (value[4]) normalize_onehot = 8'h10;
        else if (value[5]) normalize_onehot = 8'h20;
        else if (value[6]) normalize_onehot = 8'h40;
        else if (value[7]) normalize_onehot = 8'h80;
    endfunction

    function automatic logic [BYTE_COUNT_W-1:0] decode_segment_bytes(input logic [7:0] onehot);
        unique case (onehot)
            8'h01: decode_segment_bytes = BYTE_COUNT_W'(64);
            8'h02: decode_segment_bytes = BYTE_COUNT_W'(128);
            8'h04: decode_segment_bytes = BYTE_COUNT_W'(256);
            8'h08: decode_segment_bytes = BYTE_COUNT_W'(512);
            8'h10: decode_segment_bytes = BYTE_COUNT_W'(1024);
            8'h20: decode_segment_bytes = BYTE_COUNT_W'(2048);
            8'h40: decode_segment_bytes = BYTE_COUNT_W'(4096);
            8'h80: decode_segment_bytes = BYTE_COUNT_W'(8192);
            default: decode_segment_bytes = '0;
        endcase
    endfunction

    function automatic logic [DATA_BYTES-1:0] keep_from_count(input int unsigned byte_count);
        keep_from_count = '0;
        for (int i = 0; i < DATA_BYTES; i++) begin
            keep_from_count[i] = (i < byte_count);
        end
    endfunction

    function automatic logic [7:0] header_byte(
        input int unsigned byte_idx,
        input ipv4_hdr_t ipv4_hdr,
        input udp_hdr_t udp_hdr,
        input logic [BYTE_COUNT_W-1:0] payload_bytes
    );
        logic [15:0] ipv4_total_length;
        logic [15:0] udp_length;
        begin
            ipv4_total_length = 16'(HEADER_BYTES) + 16'(payload_bytes);
            udp_length = 16'(UDP_HDR_BYTES) + 16'(payload_bytes);
            header_byte = 8'h00;

            unique case (byte_idx)
                0:  header_byte = {ipv4_hdr.version, ipv4_hdr.ihl};
                1:  header_byte = {ipv4_hdr.dscp, ipv4_hdr.ecn};
                2:  header_byte = ipv4_total_length[15:8];
                3:  header_byte = ipv4_total_length[7:0];
                4:  header_byte = ipv4_hdr.identification[15:8];
                5:  header_byte = ipv4_hdr.identification[7:0];
                6:  header_byte = {ipv4_hdr.flags, ipv4_hdr.fragment_offset[12:8]};
                7:  header_byte = ipv4_hdr.fragment_offset[7:0];
                8:  header_byte = ipv4_hdr.ttl;
                9:  header_byte = ipv4_hdr.protocol;
                10: header_byte = ipv4_hdr.header_checksum[15:8];
                11: header_byte = ipv4_hdr.header_checksum[7:0];
                12: header_byte = ipv4_hdr.src_addr[31:24];
                13: header_byte = ipv4_hdr.src_addr[23:16];
                14: header_byte = ipv4_hdr.src_addr[15:8];
                15: header_byte = ipv4_hdr.src_addr[7:0];
                16: header_byte = ipv4_hdr.dst_addr[31:24];
                17: header_byte = ipv4_hdr.dst_addr[23:16];
                18: header_byte = ipv4_hdr.dst_addr[15:8];
                19: header_byte = ipv4_hdr.dst_addr[7:0];
                20: header_byte = udp_hdr.src_port[15:8];
                21: header_byte = udp_hdr.src_port[7:0];
                22: header_byte = udp_hdr.dst_port[15:8];
                23: header_byte = udp_hdr.dst_port[7:0];
                24: header_byte = udp_length[15:8];
                25: header_byte = udp_length[7:0];
                26: header_byte = udp_hdr.checksum[15:8];
                27: header_byte = udp_hdr.checksum[7:0];
                default: header_byte = 8'h00;
            endcase
        end
    endfunction

    function automatic logic [BYTE_COUNT_W-1:0] min_payload(
        input logic [BYTE_COUNT_W-1:0] remaining,
        input logic [BYTE_COUNT_W-1:0] target
    );
        min_payload = (remaining > target) ? target : remaining;
    endfunction

    initial begin
        if (DATA_WIDTH < 8 || (DATA_WIDTH % 8) != 0 || ((DATA_WIDTH & (DATA_WIDTH - 1)) != 0)) begin
            $error("uso: DATA_WIDTH must be a byte-aligned power of two >= 8");
            $finish;
        end
        if (DATA_WIDTH > 512) begin
            $error("uso: DATA_WIDTH > 512 is not supported by the fixed segment-size emit path");
            $finish;
        end
        if (MAX_SEGMENT_SIZE < 8192) begin
            $error("uso: MAX_SEGMENT_SIZE must be at least 8192");
            $finish;
        end
        if (MAX_CHUNK_SIZE < TARGET_MIN_BYTES) begin
            $error("uso: MAX_CHUNK_SIZE must be at least 64");
            $finish;
        end
    end

    assign segment_target_bytes = decode_segment_bytes(segment_onehot_r);
    assign segment_enabled = (segment_onehot_r != 8'h00);

    assign ctrl_in.aw_ready = resetn && !aw_seen_r && !b_valid_r;
    assign ctrl_in.w_ready  = resetn && !w_seen_r && !b_valid_r;
    assign ctrl_in.b.resp   = 2'b00;
    assign ctrl_in.b.user   = '0;
    assign ctrl_in.b_valid  = b_valid_r;
    assign ctrl_in.ar_ready = resetn && !r_valid_r;
    assign ctrl_in.r.data   = r_data_r;
    assign ctrl_in.r.resp   = 2'b00;
    assign ctrl_in.r.user   = '0;
    assign ctrl_in.r_valid  = r_valid_r;

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_input_fifo_axis (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_parser_in (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L2_HDR_BITS), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l2_header_unused (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_HDR_BITS), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_header (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_BITS), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_header (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_parser_payload (.axis_aclk(clk));

    always_comb begin
        u_input_fifo_axis.t = '0;
        u_input_fifo_axis.t.data = packet_in.t.data;
        u_input_fifo_axis.t.keep = packet_in.t.keep;
        u_input_fifo_axis.t.last = packet_in.t.last;
        u_input_fifo_axis.tvalid = packet_in.tvalid;
        packet_in.tready = u_input_fifo_axis.tready;
    end

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b1), .MODE("CONSERVATIVE")) u_input_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_input_fifo_axis.slave), .m_axis(u_parser_in.master)
    );

    parser #(
        .DATA_WIDTH(DATA_WIDTH),
        .SKIP_L2(1'b1), .DEFAULT_ETHERTYPE(16'h0800)
    ) u_parser (
        .clk(clk), .resetn(resetn), .s_axis_packet_in(u_parser_in.slave),
        .m_axis_l2_header_out(u_l2_header_unused.master), .m_axis_l3_header_out(u_l3_header.master),
        .m_axis_l4_header_out(u_l4_header.master), .m_axis_payload_out(u_parser_payload.master)
    );

    assign u_l2_header_unused.tready = 1'b1;

    ifc_axis #(.DATA_WIDTH(HEADER_DESC_BITS), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_header_fifo_in (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(HEADER_DESC_BITS), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_header_fifo_out (.axis_aclk(clk));

    l3_hdr_axis_t parsed_l3;
    l4_hdr_axis_t parsed_l4;
    assign parsed_l3 = l3_hdr_axis_t'(u_l3_header.t.data);
    assign parsed_l4 = l4_hdr_axis_t'(u_l4_header.t.data);

    always_comb begin
        u_header_fifo_in.t = '0;
        u_header_fifo_in.t.data = {parsed_l3.ipv4, parsed_l4.udp};
        u_header_fifo_in.t.keep = '1;
        u_header_fifo_in.t.last = 1'b1;
        u_header_fifo_in.tvalid = u_l3_header.tvalid && u_l4_header.tvalid;
        u_l3_header.tready = u_l4_header.tvalid && u_header_fifo_in.tready;
        u_l4_header.tready = u_l3_header.tvalid && u_header_fifo_in.tready;
    end

    axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b1), .MODE("CONSERVATIVE")) u_header_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_header_fifo_in.slave), .m_axis(u_header_fifo_out.master)
    );

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_fan [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_fifo_raw (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_count_in (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_fifo_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(SIZE_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_size_count (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(SIZE_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_size_fifo_out (.axis_aclk(clk));

    axis_multicast #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1), .NUM_DESTS(2)) u_payload_fanout (
        .clk(clk), .resetn(resetn), .s_axis(u_parser_payload.slave), .m_axis(u_payload_fan)
    );

    axis_fifo #(.DEPTH(PAYLOAD_FIFO_DEPTH), .USE_BRAM(1'b1), .EXTRA_OUTPUT_REG(1'b1), .MODE("CONSERVATIVE")) u_payload_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_payload_fan[0].slave), .m_axis(u_payload_fifo_raw.master)
    );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b1), .MODE("CONSERVATIVE")) u_payload_emit_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_payload_fifo_raw.slave), .m_axis(u_payload_count_in.master)
    );

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_count_axis (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(BEAT_COUNT_AXIS_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_beat_count (.axis_aclk(clk));

    logic payload_count_stage1_valid_r;
    logic [DATA_WIDTH-1:0] payload_count_stage1_data_r;
    logic [DATA_BYTES-1:0] payload_count_stage1_keep_r;
    logic payload_count_stage1_last_r;
    logic payload_count_stage2_valid_r;
    logic [DATA_WIDTH-1:0] payload_count_stage2_data_r;
    logic [DATA_BYTES-1:0] payload_count_stage2_keep_r;
    logic payload_count_stage2_last_r;
    logic payload_count_stage3_valid_r;
    logic [DATA_WIDTH-1:0] payload_count_stage3_data_r;
    logic [DATA_BYTES-1:0] payload_count_stage3_keep_r;
    logic payload_count_stage3_last_r;
    logic payload_count_stage1_ready;
    logic payload_count_stage2_ready;
    logic payload_count_stage3_ready;

    always_comb begin
        u_payload_count_axis.t = '0;
        u_payload_count_axis.t.data = u_payload_count_in.t.data;
        u_payload_count_axis.t.keep = u_payload_count_in.t.keep;
        u_payload_count_axis.t.last = u_payload_count_in.t.last;
        u_payload_count_axis.tvalid = u_payload_count_in.tvalid && payload_count_stage1_ready;
        u_payload_count_in.tready = u_payload_count_axis.tready && payload_count_stage1_ready;

        u_payload_fifo_out.t = '0;
        u_payload_fifo_out.t.data = payload_count_stage3_data_r;
        u_payload_fifo_out.t.keep = payload_count_stage3_keep_r;
        u_payload_fifo_out.t.last = payload_count_stage3_last_r;
        u_payload_fifo_out.tvalid = payload_count_stage3_valid_r && u_payload_beat_count.tvalid;
    end

    axis_count_beat_size #(
        .DATA_WIDTH(DATA_WIDTH)
    ) u_payload_count_beat_size (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_payload_count_axis.slave),
        .m_axis (u_payload_beat_count.master)
    );

    assign u_payload_beat_count.tready = payload_count_stage3_valid_r
        && u_payload_fifo_out.tready;
    assign payload_count_stage3_ready = !payload_count_stage3_valid_r
        || (u_payload_beat_count.tvalid && u_payload_fifo_out.tready);
    assign payload_count_stage2_ready = !payload_count_stage2_valid_r
        || payload_count_stage3_ready;
    assign payload_count_stage1_ready = !payload_count_stage1_valid_r
        || payload_count_stage2_ready;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            payload_count_stage1_valid_r <= 1'b0;
            payload_count_stage2_valid_r <= 1'b0;
            payload_count_stage3_valid_r <= 1'b0;
        end else begin
            if (payload_count_stage3_ready) begin
                payload_count_stage3_valid_r <= payload_count_stage2_valid_r;
                if (payload_count_stage2_valid_r) begin
                    payload_count_stage3_data_r <= payload_count_stage2_data_r;
                    payload_count_stage3_keep_r <= payload_count_stage2_keep_r;
                    payload_count_stage3_last_r <= payload_count_stage2_last_r;
                end
            end

            if (payload_count_stage2_ready) begin
                payload_count_stage2_valid_r <= payload_count_stage1_valid_r;
                if (payload_count_stage1_valid_r) begin
                    payload_count_stage2_data_r <= payload_count_stage1_data_r;
                    payload_count_stage2_keep_r <= payload_count_stage1_keep_r;
                    payload_count_stage2_last_r <= payload_count_stage1_last_r;
                end
            end

            if (payload_count_stage1_ready) begin
                payload_count_stage1_valid_r <= u_payload_count_in.tvalid
                    && u_payload_count_axis.tready;
                if (u_payload_count_in.tvalid && u_payload_count_axis.tready) begin
                    payload_count_stage1_data_r <= u_payload_count_in.t.data;
                    payload_count_stage1_keep_r <= u_payload_count_in.t.keep;
                    payload_count_stage1_last_r <= u_payload_count_in.t.last;
                end
            end
        end
    end

    // synthesis translate_off
    always_ff @(posedge clk) begin
        if (resetn && (payload_count_stage3_valid_r || u_payload_beat_count.tvalid)) begin
            assert(payload_count_stage3_valid_r == u_payload_beat_count.tvalid);
            if (payload_count_stage3_valid_r && u_payload_beat_count.tvalid)
                assert(payload_count_stage3_last_r == u_payload_beat_count.t.last);
        end
    end
    // synthesis translate_on

    axis_count_packet_size #(.DATA_WIDTH(DATA_WIDTH), .SIZE_WIDTH(SIZE_WIDTH)) u_payload_size_counter (
        .clk(clk), .resetn(resetn), .s_axis(u_payload_fan[1].slave), .m_axis(u_size_count.master)
    );

    axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b1), .MODE("CONSERVATIVE")) u_size_fifo (
        .clk(clk), .resetn(resetn), .s_axis(u_size_count.slave), .m_axis(u_size_fifo_out.master)
    );

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_header_emit (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_payload_emit (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_combined_out (.axis_aclk(clk));

    axis_combine_repack #(.FIRST_STREAM_IS_A(1), .DATA_WIDTH(DATA_WIDTH)) u_segment_combine (
        .clk(clk), .resetn(resetn), .s_axis_a(u_header_emit.slave), .s_axis_b(u_payload_emit.slave), .m_axis(u_combined_out.master)
    );

    assign packet_out.t.data = u_combined_out.t.data;
    assign packet_out.t.keep = u_combined_out.t.keep;
    assign packet_out.t.id   = '0;
    assign packet_out.t.dest = '0;
    assign packet_out.t.user = '0;
    assign packet_out.t.last = u_combined_out.t.last;
    assign packet_out.tvalid = u_combined_out.tvalid;
    assign u_combined_out.tready = packet_out.tready;

    logic ctx_push_valid;
    logic ctx_push_ready;
    logic ctx_push_data;
    logic ctx_pop_valid;
    logic ctx_pop_data;
    logic output_last_fire;

    assign output_last_fire = packet_out.tvalid && packet_out.tready && packet_out.t.last;
    assign tlast_context = packet_out.tvalid && packet_out.t.last && ctx_pop_valid && ctx_pop_data;

    sync_ff_fifo #(.DEPTH(16), .T(logic), .EXTRA_OUTPUT_REG(1'b0), .MODE("CONSERVATIVE")) u_context_fifo (
        .clk(clk), .resetn(resetn), .push_valid(ctx_push_valid), .push_data(ctx_push_data), .push_ready(ctx_push_ready),
        .pop_valid(ctx_pop_valid), .pop_data(ctx_pop_data), .pop_ready(output_last_fire)
    );

    logic [BYTE_COUNT_W-1:0] payload_beat_bytes;
    logic [BYTE_COUNT_W-1:0] payload_remaining_base;
    logic [BYTE_COUNT_W-1:0] segment_remaining_base;
    logic [BYTE_COUNT_W-1:0] payload_remaining_after;
    logic [BYTE_COUNT_W-1:0] segment_remaining_after;
    logic payload_segment_last;
    logic payload_final_segment;
    logic payload_issue_valid_r;
    logic [DATA_WIDTH-1:0] payload_issue_data_r;
    logic [DATA_BYTES-1:0] payload_issue_keep_r;
    logic payload_issue_segment_last_r;
    logic payload_issue_final_segment_r;
    logic [BYTE_COUNT_W-1:0] payload_issue_remaining_after_r;
    logic [BYTE_COUNT_W-1:0] payload_issue_segment_after_r;
    logic payload_issue_ready;
    logic payload_issue_capture;
    logic payload_issue_can_emit;
    logic header_fire;
    logic payload_fire;
    logic start_ready;
    logic start_fire;
    logic drop_fire;

    assign payload_beat_bytes = BYTE_COUNT_W'(u_payload_beat_count.t.data);
    assign payload_remaining_base = payload_fire ? payload_issue_remaining_after_r : payload_remaining_r;
    assign segment_remaining_base = payload_fire ? payload_issue_segment_after_r : segment_remaining_r;
    assign payload_remaining_after = (payload_remaining_base > payload_beat_bytes) ? (payload_remaining_base - payload_beat_bytes) : '0;
    assign segment_remaining_after = (segment_remaining_base > payload_beat_bytes) ? (segment_remaining_base - payload_beat_bytes) : '0;
    assign payload_segment_last = (payload_beat_bytes >= segment_remaining_base) || u_payload_fifo_out.t.last;
    assign payload_final_segment = (payload_remaining_after == '0) || u_payload_fifo_out.t.last;
    assign payload_issue_can_emit = !payload_issue_segment_last_r || ctx_push_ready;
    assign header_fire = u_header_emit.tvalid && u_header_emit.tready;
    assign payload_fire = u_payload_emit.tvalid && u_payload_emit.tready;
    assign payload_issue_ready = !payload_issue_valid_r || (payload_fire && !payload_issue_segment_last_r);
    assign payload_issue_capture = (emit_state_r == EMIT_PAYLOAD) && u_payload_fifo_out.tvalid && u_payload_fifo_out.tready;
    assign start_ready = u_header_fifo_out.tvalid && u_size_fifo_out.tvalid && u_payload_fifo_out.tvalid;
    assign start_fire = (emit_state_r == EMIT_IDLE) && start_ready;
    assign drop_fire = (emit_state_r == EMIT_DROP) && u_payload_fifo_out.tvalid && u_payload_fifo_out.tready;

    always_comb begin
        int unsigned remaining_header_bytes;
        int unsigned header_keep_bytes;

        u_header_emit.t = '0;
        u_header_emit.tvalid = 1'b0;
        remaining_header_bytes = (header_offset_r < HEADER_BYTES) ? (HEADER_BYTES - int'(header_offset_r)) : 0;
        header_keep_bytes = (remaining_header_bytes > DATA_BYTES) ? DATA_BYTES : remaining_header_bytes;

        if (emit_state_r == EMIT_HEADER) begin
            u_header_emit.tvalid = 1'b1;
            u_header_emit.t.keep = keep_from_count(header_keep_bytes);
            u_header_emit.t.last = (remaining_header_bytes <= DATA_BYTES);
            for (int i = 0; i < DATA_BYTES; i++) begin
                u_header_emit.t.data[i * 8 +: 8] =
                    header_byte(int'(header_offset_r) + i, ipv4_hdr_r, udp_hdr_r, segment_payload_bytes_r);
            end
        end
    end

    always_comb begin
        u_payload_emit.t = '0;
        u_payload_emit.t.data = payload_issue_data_r;
        u_payload_emit.t.keep = payload_issue_keep_r;
        u_payload_emit.t.last = payload_issue_segment_last_r;
        u_payload_emit.tvalid = (emit_state_r == EMIT_PAYLOAD) && payload_issue_valid_r && payload_issue_can_emit;

        u_payload_fifo_out.tready = 1'b0;
        if (emit_state_r == EMIT_PAYLOAD) begin
            u_payload_fifo_out.tready = payload_issue_ready;
        end else if (emit_state_r == EMIT_DROP) begin
            u_payload_fifo_out.tready = 1'b1;
        end

        ctx_push_valid = payload_fire && payload_issue_segment_last_r;
        ctx_push_data = payload_issue_final_segment_r;

        u_header_fifo_out.tready = start_fire;
        u_size_fifo_out.tready = start_fire;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            payload_issue_valid_r <= 1'b0;
            payload_issue_data_r <= '0;
            payload_issue_keep_r <= '0;
            payload_issue_segment_last_r <= 1'b0;
            payload_issue_final_segment_r <= 1'b0;
            payload_issue_remaining_after_r <= '0;
            payload_issue_segment_after_r <= '0;
        end else begin
            if (payload_issue_capture) begin
                payload_issue_valid_r <= 1'b1;
                payload_issue_data_r <= u_payload_fifo_out.t.data;
                payload_issue_keep_r <= u_payload_fifo_out.t.keep;
                payload_issue_segment_last_r <= payload_segment_last;
                payload_issue_final_segment_r <= payload_final_segment;
                payload_issue_remaining_after_r <= payload_remaining_after;
                payload_issue_segment_after_r <= segment_remaining_after;
            end else if (payload_fire) begin
                payload_issue_valid_r <= 1'b0;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            aw_seen_r <= 1'b0;
            aw_addr_r <= '0;
            w_seen_r <= 1'b0;
            w_data_r <= '0;
            b_valid_r <= 1'b0;
            r_valid_r <= 1'b0;
            r_data_r <= '0;
            segment_onehot_r <= 8'h00;
            emit_state_r <= EMIT_IDLE;
            ipv4_hdr_r <= '0;
            udp_hdr_r <= '0;
            payload_remaining_r <= '0;
            segment_remaining_r <= '0;
            segment_payload_bytes_r <= '0;
            header_offset_r <= '0;
        end else begin
            logic aw_accept;
            logic w_accept;
            logic write_ready;

            aw_accept = ctrl_in.aw_valid && ctrl_in.aw_ready;
            w_accept = ctrl_in.w_valid && ctrl_in.w_ready;
            write_ready = ((aw_seen_r || aw_accept) && (w_seen_r || w_accept) && !b_valid_r);

            if (aw_accept) begin
                aw_seen_r <= 1'b1;
                aw_addr_r <= ctrl_in.aw.addr;
            end
            if (w_accept) begin
                w_seen_r <= 1'b1;
                w_data_r <= ctrl_in.w.data;
            end

            if (write_ready) begin
                if (((aw_accept ? ctrl_in.aw.addr : aw_addr_r) & 32'hffff_fffc) == 32'h0000_0000) begin
                    logic [31:0] write_data;
                    write_data = w_accept ? ctrl_in.w.data : w_data_r;
                    segment_onehot_r <= normalize_onehot(write_data);
                end
                aw_seen_r <= 1'b0;
                w_seen_r <= 1'b0;
                b_valid_r <= 1'b1;
            end else if (b_valid_r && ctrl_in.b_ready) begin
                b_valid_r <= 1'b0;
            end

            if (ctrl_in.ar_valid && ctrl_in.ar_ready) begin
                r_valid_r <= 1'b1;
                if ((ctrl_in.ar.addr & 32'hffff_fffc) == 32'h0000_0000) begin
                    r_data_r <= {24'h0, segment_onehot_r};
                end else begin
                    r_data_r <= 32'h0;
                end
            end else if (r_valid_r && ctrl_in.r_ready) begin
                r_valid_r <= 1'b0;
            end

            unique case (emit_state_r)
                EMIT_IDLE: begin
                    if (start_fire) begin
                        {ipv4_hdr_r, udp_hdr_r} <= u_header_fifo_out.t.data;
                        payload_remaining_r <= BYTE_COUNT_W'(u_size_fifo_out.t.data);
                        if (segment_enabled && (u_size_fifo_out.t.data != '0)) begin
                            segment_payload_bytes_r <= min_payload(BYTE_COUNT_W'(u_size_fifo_out.t.data), segment_target_bytes);
                            segment_remaining_r <= min_payload(BYTE_COUNT_W'(u_size_fifo_out.t.data), segment_target_bytes);
                            header_offset_r <= '0;
                            emit_state_r <= EMIT_HEADER;
                        end else begin
                            emit_state_r <= EMIT_DROP;
                        end
                    end
                end

                EMIT_HEADER: begin
                    if (header_fire) begin
                        if (u_header_emit.t.last) begin
                            header_offset_r <= '0;
                            emit_state_r <= EMIT_PAYLOAD;
                        end else begin
                            header_offset_r <= header_offset_r + HEADER_OFFSET_W'(DATA_BYTES);
                        end
                    end
                end

                EMIT_PAYLOAD: begin
                    if (payload_fire) begin
                        payload_remaining_r <= payload_issue_remaining_after_r;
                        segment_remaining_r <= payload_issue_segment_after_r;

                        if (payload_issue_segment_last_r) begin
                            if (payload_issue_final_segment_r) begin
                                emit_state_r <= EMIT_IDLE;
                                segment_remaining_r <= '0;
                                segment_payload_bytes_r <= '0;
                            end else begin
                                segment_payload_bytes_r <= min_payload(payload_issue_remaining_after_r, segment_target_bytes);
                                segment_remaining_r <= min_payload(payload_issue_remaining_after_r, segment_target_bytes);
                                header_offset_r <= '0;
                                emit_state_r <= EMIT_HEADER;
                            end
                        end
                    end
                end

                EMIT_DROP: begin
                    if (drop_fire && u_payload_fifo_out.t.last) begin
                        emit_state_r <= EMIT_IDLE;
                    end
                end

                default: begin
                    emit_state_r <= EMIT_IDLE;
                end
            endcase
        end
    end

endmodule
