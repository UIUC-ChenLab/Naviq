`include "ifc_axis.sv"
`include "_uro_pkg.sv"
`include "parser_pkg.sv"

module uro_packet_capture #(
    parameter int DATA_WIDTH                 = 512,
    parameter int TABLE_ADDR_WIDTH           = 4,
    parameter int DESC_DEPTH                 = 32,
    parameter int BEAT_DESC_DEPTH            = 256,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8,
    parameter int PACKET_BEAT_COUNT_WIDTH    =
        $clog2((65535 + DATA_WIDTH/8 - 1) / (DATA_WIDTH/8) + 3)
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave packet_in,

    output logic desc_valid,
    input  logic desc_ready,
    output uro_pkg::uro_key_t desc_key,
    output logic [TABLE_ADDR_WIDTH-1:0] desc_hash,
    output logic desc_eligible,
    output logic [15:0] desc_payload_bytes,
    output logic [PACKET_BEAT_COUNT_WIDTH-1:0] desc_payload_beats,

    ifc_axis.master parsed_payload
);
    localparam int L2_W = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int L3_W = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_W = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int MAX_PACKET_BEATS =
        (65535 + DATA_WIDTH/8 - 1) / (DATA_WIDTH/8) + 2;
    localparam int PARSER_DATA_WIDTH = (DATA_WIDTH < 256) ? 256 : DATA_WIDTH;

    typedef struct packed {
        uro_pkg::uro_key_t key;
        logic [TABLE_ADDR_WIDTH-1:0] hash;
        logic eligible;
        logic [15:0] payload_bytes;
        logic [PACKET_BEAT_COUNT_WIDTH-1:0] payload_beats;
    } desc_t;

    typedef logic [PACKET_BEAT_COUNT_WIDTH-1:0] beat_count_t;

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
               .TUSER_WIDTH(1))
        parser_packet_in (clk), raw_packet_in (clk),
        raw_payload_unbuffered (clk), raw_payload (clk), counted_payload (clk);
    ifc_axis #(.DATA_WIDTH(PARSER_DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
               .TUSER_WIDTH(1))
        parser_core_in (clk), parser_core_payload (clk);
    ifc_axis #(.DATA_WIDTH(L2_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        l2_unused (clk);
    ifc_axis #(.DATA_WIDTH(L3_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        l3_axis (clk), l3_q (clk);
    ifc_axis #(.DATA_WIDTH(L4_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        l4_axis (clk), l4_q (clk);

    parser_pkg::l3_hdr_axis_t joined_l3;
    parser_pkg::l4_hdr_axis_t joined_l4;
    logic joined_eligible;
    logic [15:0] joined_payload_bytes;
    uro_pkg::uro_key_t joined_key;
    logic [TABLE_ADDR_WIDTH-1:0] joined_hash;
    desc_t desc_push, desc_pop;
    logic desc_push_valid, desc_push_ready;
    beat_count_t payload_beat_count_r, payload_beat_count_n;
    beat_count_t beat_desc_push, beat_desc_pop;
    logic beat_desc_push_valid, beat_desc_push_ready;
    logic beat_desc_pop_valid, beat_desc_pop_ready;
    wire desc_push_fire = desc_push_valid && desc_push_ready;
    wire raw_payload_fire = raw_payload.tvalid && raw_payload.tready;

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
               .TUSER_WIDTH(1)) packet_fan [2] (clk);
    axis_multicast #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(1), .NUM_DESTS(2)
    ) u_packet_fanout (
        .clk(clk), .resetn(resetn), .s_axis(packet_in), .m_axis(packet_fan)
    );
    assign parser_packet_in.t = packet_fan[0].t;
    assign parser_packet_in.tvalid = packet_fan[0].tvalid;
    assign packet_fan[0].tready = parser_packet_in.tready;
    assign raw_packet_in.t = packet_fan[1].t;
    assign raw_packet_in.tvalid = packet_fan[1].tvalid;
    assign packet_fan[1].tready = raw_packet_in.tready;

    uro_fixed_header_strip #(
        .DATA_WIDTH(DATA_WIDTH), .HEADER_BYTES(uro_pkg::URO_HDR_BYTES)
    ) u_raw_payload_strip (
        .clk(clk), .resetn(resetn),
        .packet_in(raw_packet_in), .payload_out(raw_payload_unbuffered)
    );

    // Isolate the fixed-strip state and terminal-marker decision from the
    // whole-packet staging FIFO's capacity path without reducing throughput.
    // The registered output also prevents the FF FIFO head pointer from
    // entering the downstream staging FIFO's registered-ready calculation.
    axis_fifo #(
        .DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b1),
        .MODE("CONSERVATIVE")
    ) u_raw_payload_boundary (
        .clk(clk), .resetn(resetn),
        .s_axis(raw_payload_unbuffered), .m_axis(raw_payload)
    );

    generate
        if (DATA_WIDTH < 256) begin : g_parser_width_adapter
            uro_axis_upsizer #(
                .INPUT_DATA_WIDTH(DATA_WIDTH),
                .OUTPUT_DATA_WIDTH(PARSER_DATA_WIDTH)
            ) u_parser_upsizer (
                .clk(clk), .resetn(resetn),
                .s_axis(parser_packet_in), .m_axis(parser_core_in)
            );
        end else begin : g_parser_native_width
            assign parser_core_in.t = parser_packet_in.t;
            assign parser_core_in.tvalid = parser_packet_in.tvalid;
            assign parser_packet_in.tready = parser_core_in.tready;
        end
    endgenerate

    parser #(
        .DATA_WIDTH(PARSER_DATA_WIDTH),
        .SKIP_L2(1'b1),
        .HEADER_ONLY(1'b1),
        .DEFAULT_ETHERTYPE(16'h0800),
        .REPACK_PAYLOAD_OUT(1'b0),
        .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT)
    ) u_parser (
        .clk(clk), .resetn(resetn),
        .s_axis_packet_in(parser_core_in),
        .m_axis_l2_header_out(l2_unused),
        .m_axis_l3_header_out(l3_axis),
        .m_axis_l4_header_out(l4_axis),
        .m_axis_payload_out(parser_core_payload)
    );
    assign l2_unused.tready = 1'b1;
    assign parser_core_payload.tready = 1'b1;

    axis_fifo #(
        .DEPTH(DESC_DEPTH), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")
    ) u_l3_q (
        .clk(clk), .resetn(resetn), .s_axis(l3_axis), .m_axis(l3_q)
    );
    axis_fifo #(
        .DEPTH(DESC_DEPTH), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")
    ) u_l4_q (
        .clk(clk), .resetn(resetn), .s_axis(l4_axis), .m_axis(l4_q)
    );

    axis_packet_fifo #(
        .DEPTH(MAX_PACKET_BEATS), .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_payload_q (
        .clk(clk), .resetn(resetn),
        .s_axis(counted_payload), .m_axis(parsed_payload)
    );

    // Count the exact payload beats accepted by the staging FIFO. The final
    // count travels beside the packet so neither dispatch nor a queue has to
    // reconstruct raw FIFO occupancy from a byte length.
    always_comb begin
        counted_payload.t = raw_payload.t;
        counted_payload.tvalid = raw_payload.tvalid &&
            (!raw_payload.t.last || beat_desc_push_ready);
        raw_payload.tready = counted_payload.tready &&
            (!raw_payload.t.last || beat_desc_push_ready);

        payload_beat_count_n = payload_beat_count_r;
        beat_desc_push_valid = 1'b0;
        beat_desc_push = payload_beat_count_r + 1'b1;
        if (raw_payload_fire) begin
            if (raw_payload.t.last) begin
                beat_desc_push_valid = 1'b1;
                payload_beat_count_n = '0;
            end else begin
                payload_beat_count_n = payload_beat_count_r + 1'b1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn)
            payload_beat_count_r <= '0;
        else begin
            payload_beat_count_r <= payload_beat_count_n;
        end
    end

    sync_ff_fifo #(
        .DEPTH(BEAT_DESC_DEPTH), .T(beat_count_t),
        .EXTRA_OUTPUT_REG(1'b1), .MODE("CONSERVATIVE")
    ) u_beat_desc_q (
        .clk(clk), .resetn(resetn),
        .push_valid(beat_desc_push_valid), .push_data(beat_desc_push),
        .push_ready(beat_desc_push_ready),
        .pop_valid(beat_desc_pop_valid), .pop_data(beat_desc_pop),
        .pop_ready(beat_desc_pop_ready)
    );

    assign joined_l3 = parser_pkg::l3_hdr_axis_t'(l3_q.t.data);
    assign joined_l4 = parser_pkg::l4_hdr_axis_t'(l4_q.t.data);

    uro_rx_stage #(
        .TABLE_ADDR_WIDTH(TABLE_ADDR_WIDTH)
    ) u_rx_stage (
        .l3(joined_l3), .l4(joined_l4),
        .eligible(joined_eligible),
        .payload_bytes(joined_payload_bytes),
        .key(joined_key), .hash(joined_hash)
    );

    // Join the parser's packet-ordered L3 and L4 metadata atomically.
    assign desc_push_valid = l3_q.tvalid && l4_q.tvalid && beat_desc_pop_valid;
    assign l3_q.tready = desc_push_fire;
    assign l4_q.tready = desc_push_fire;
    assign beat_desc_pop_ready = desc_push_fire;
    always_comb begin
        desc_push = '0;
        desc_push.key = joined_key;
        desc_push.hash = joined_hash;
        desc_push.eligible = joined_eligible;
        desc_push.payload_bytes = joined_payload_bytes;
        desc_push.payload_beats = beat_desc_pop;
    end

    sync_ff_fifo #(
        .DEPTH(DESC_DEPTH), .T(desc_t), .MODE("CONSERVATIVE")
    ) u_desc_q (
        .clk(clk), .resetn(resetn),
        .push_valid(desc_push_valid), .push_data(desc_push),
        .push_ready(desc_push_ready),
        .pop_valid(desc_valid), .pop_data(desc_pop), .pop_ready(desc_ready)
    );

    assign desc_key = desc_pop.key;
    assign desc_hash = desc_pop.hash;
    assign desc_eligible = desc_pop.eligible;
    assign desc_payload_bytes = desc_pop.payload_bytes;
    assign desc_payload_beats = desc_pop.payload_beats;
endmodule

// The shared parser operates at 256 bits and wider. This adapter is only used
// for URO's supported narrow-width configurations.
module uro_axis_upsizer #(
    parameter int INPUT_DATA_WIDTH = 64,
    parameter int OUTPUT_DATA_WIDTH = 256
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave s_axis,
    ifc_axis.master m_axis
);
    localparam int INPUT_BYTES = INPUT_DATA_WIDTH / 8;
    localparam int OUTPUT_BYTES = OUTPUT_DATA_WIDTH / 8;
    localparam int RATIO = OUTPUT_DATA_WIDTH / INPUT_DATA_WIDTH;
    localparam int SLOT_WIDTH = (RATIO <= 1) ? 1 : $clog2(RATIO);

    logic [OUTPUT_DATA_WIDTH-1:0] data_r;
    logic [OUTPUT_BYTES-1:0] keep_r;
    logic [SLOT_WIDTH-1:0] slot_r;
    logic out_valid_r, out_last_r;
    wire out_fire = out_valid_r && m_axis.tready;
    wire in_fire = s_axis.tvalid && s_axis.tready;
    wire completes_word = (slot_r == SLOT_WIDTH'(RATIO-1));

    assign s_axis.tready = !out_valid_r || m_axis.tready;
    always_comb begin
        m_axis.t = '0;
        m_axis.t.data = data_r;
        m_axis.t.keep = keep_r;
        m_axis.t.last = out_last_r;
        m_axis.tvalid = out_valid_r;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            data_r <= '0;
            keep_r <= '0;
            slot_r <= '0;
            out_valid_r <= 1'b0;
            out_last_r <= 1'b0;
        end else begin
            if (out_fire) begin
                out_valid_r <= 1'b0;
                data_r <= '0;
                keep_r <= '0;
            end
            if (in_fire) begin
                data_r[slot_r*INPUT_DATA_WIDTH +: INPUT_DATA_WIDTH] <= s_axis.t.data;
                keep_r[slot_r*INPUT_BYTES +: INPUT_BYTES] <= s_axis.t.keep;
                if (s_axis.t.last || completes_word) begin
                    out_valid_r <= 1'b1;
                    out_last_r <= s_axis.t.last;
                    slot_r <= '0;
                end else begin
                    slot_r <= slot_r + 1'b1;
                end
            end
        end
    end

    initial begin
        if (OUTPUT_DATA_WIDTH <= INPUT_DATA_WIDTH ||
            (OUTPUT_DATA_WIDTH % INPUT_DATA_WIDTH) != 0)
            $error("uro_axis_upsizer: widths must have an integer ratio > 1");
    end
endmodule
