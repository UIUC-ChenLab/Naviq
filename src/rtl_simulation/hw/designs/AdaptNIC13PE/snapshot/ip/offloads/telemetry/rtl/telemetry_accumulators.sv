// AXI-stream byte/packet accumulators (global totals + per-packet byte count).

`include "parser_pkg.sv"

module telemetry_accumulators #(
    parameter int unsigned DATA_WIDTH           = 512,
    parameter int unsigned TOTAL_BYTES_WIDTH    = 64,
    parameter int unsigned TOTAL_PACKETS_WIDTH    = 64,
    parameter int unsigned PACKET_BYTES_WIDTH   = 16,
    parameter int unsigned PACKET_FIFO_DEPTH      = 64
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis_in,

    input  logic packet_protocol_valid,
    // Same width as ipv4_hdr_t.protocol / hash_axis.t.user on the telemetry hash path.
    input  logic [parser_pkg::IPV4_PROTOCOL_W-1:0] packet_protocol,

    // High after a tlast beat is transferred; if !out_ready, ready drops (ingress stall).
    output logic out_valid,
    input  logic out_ready,
    output logic [TOTAL_BYTES_WIDTH-1:0] packet_bytes_out,
    output logic [TOTAL_BYTES_WIDTH-1:0] current_packet_bytes,
    output logic [TOTAL_BYTES_WIDTH-1:0]   total_bytes,
    output logic [TOTAL_PACKETS_WIDTH-1:0] total_packets,
    output logic [TOTAL_PACKETS_WIDTH-1:0] total_udp_packets,
    output logic [TOTAL_PACKETS_WIDTH-1:0] total_tcp_packets
);

    localparam int unsigned KEEP_W     = DATA_WIDTH / 8;
    localparam int unsigned KEEP_CNT_W = $clog2(KEEP_W + 1);
    localparam int unsigned COUNT_AXIS_W = $clog2(DATA_WIDTH);
    localparam int unsigned FIFO_ADDR_W = (PACKET_FIFO_DEPTH <= 1) ? 1 : $clog2(PACKET_FIFO_DEPTH);

    initial begin
        if (PACKET_FIFO_DEPTH < 2) begin
            $error("telemetry_accumulators: PACKET_FIFO_DEPTH (%0d) must be >= 2", PACKET_FIFO_DEPTH);
            $finish;
        end
        if (PACKET_BYTES_WIDTH < KEEP_CNT_W) begin
            $error("telemetry_accumulators: PACKET_BYTES_WIDTH (%0d) must be >= KEEP_CNT_W (%0d)",
                   PACKET_BYTES_WIDTH, KEEP_CNT_W);
            $finish;
        end
        if (PACKET_BYTES_WIDTH > TOTAL_BYTES_WIDTH) begin
            $error("telemetry_accumulators: PACKET_BYTES_WIDTH (%0d) must be <= TOTAL_BYTES_WIDTH (%0d)",
                   PACKET_BYTES_WIDTH, TOTAL_BYTES_WIDTH);
            $finish;
        end
    end

    ifc_axis #(.DATA_WIDTH(COUNT_AXIS_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        beat_count_axis (.axis_aclk(clk));

    axis_count_beat_size #(
        .DATA_WIDTH (DATA_WIDTH)
    ) u_count_beat_size (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_in),
        .m_axis (beat_count_axis)
    );

    logic counted_transaction;
    assign counted_transaction = beat_count_axis.tvalid && beat_count_axis.tready;

    logic [KEEP_CNT_W-1:0] keep_ones;
    assign keep_ones = beat_count_axis.t.data[KEEP_CNT_W-1:0];

    logic [PACKET_BYTES_WIDTH-1:0] beat_bytes_packet;
    logic [TOTAL_BYTES_WIDTH-1:0]  beat_bytes_total;
    assign beat_bytes_packet = {{(PACKET_BYTES_WIDTH-KEEP_CNT_W){1'b0}}, keep_ones};
    assign beat_bytes_total  = {{(TOTAL_BYTES_WIDTH-KEEP_CNT_W){1'b0}}, keep_ones};

    logic tlast_transaction;
    assign tlast_transaction = counted_transaction && beat_count_axis.t.last;

    logic [PACKET_BYTES_WIDTH-1:0] current_packet_bytes_r;
    logic [PACKET_BYTES_WIDTH-1:0] packet_bytes_next;
    assign packet_bytes_next = current_packet_bytes_r + beat_bytes_packet;
    assign current_packet_bytes = {{(TOTAL_BYTES_WIDTH-PACKET_BYTES_WIDTH){1'b0}}, current_packet_bytes_r};

    // Total bytes — never clear
    accumulator #(
        .DATA_BIT_WIDTH (TOTAL_BYTES_WIDTH),
        .INITIAL_VALUE  ('0)
    ) u_total_bytes (
        .clk              (clk),
        .resetn           (resetn),
        .clear            (1'b0),
        .enable           (counted_transaction),
        .accumulate_value (beat_bytes_total),
        .out              (total_bytes)
    );

    // Total packets — never clear
    accumulator #(
        .DATA_BIT_WIDTH (TOTAL_PACKETS_WIDTH),
        .INITIAL_VALUE  ('0)
    ) u_total_packets (
        .clk              (clk),
        .resetn           (resetn),
        .clear            (1'b0),
        .enable           (tlast_transaction),
        .accumulate_value ({{(TOTAL_PACKETS_WIDTH-1){1'b0}}, 1'b1}),
        .out              (total_packets)
    );

    // total UDP packets - never clear
    accumulator #(
        .DATA_BIT_WIDTH (TOTAL_PACKETS_WIDTH),
        .INITIAL_VALUE  ('0)
    ) u_total_udp_packets (
        .clk              (clk),
        .resetn           (resetn),
        .clear            (1'b0),
        .enable           (out_valid && out_ready && packet_protocol_valid && packet_protocol == 8'd17),
        .accumulate_value ({{(TOTAL_PACKETS_WIDTH-1){1'b0}}, 1'b1}),
        .out              (total_udp_packets)
    );

    // total TCP packets - never clear
    accumulator #(
        .DATA_BIT_WIDTH (TOTAL_PACKETS_WIDTH),
        .INITIAL_VALUE  ('0)
    ) u_total_tcp_packets (
        .clk              (clk),
        .resetn           (resetn),
        .clear            (1'b0),
        .enable           (out_valid && out_ready && packet_protocol_valid && packet_protocol == 8'd6),
        .accumulate_value ({{(TOTAL_PACKETS_WIDTH-1){1'b0}}, 1'b1}),
        .out              (total_tcp_packets)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            current_packet_bytes_r <= '0;
        end else if (counted_transaction) begin
            if (beat_count_axis.t.last)
                current_packet_bytes_r <= '0;
            else
                current_packet_bytes_r <= packet_bytes_next;
        end
    end

    logic [PACKET_BYTES_WIDTH-1:0] packet_fifo[PACKET_FIFO_DEPTH];
    logic [FIFO_ADDR_W-1:0] packet_fifo_wr_ptr;
    logic [FIFO_ADDR_W-1:0] packet_fifo_rd_ptr;
    logic [FIFO_ADDR_W:0]   packet_fifo_count;
    logic                   packet_fifo_pop;
    logic                   packet_fifo_push;
    logic                   packet_fifo_full;
    logic                   packet_fifo_empty;
    logic                   packet_fifo_pending_valid;
    logic [PACKET_BYTES_WIDTH-1:0] packet_fifo_pending_bytes;

    assign packet_fifo_empty = (packet_fifo_count == '0);
    assign packet_fifo_full  = (packet_fifo_count == PACKET_FIFO_DEPTH);
    assign packet_fifo_pop   = out_valid && out_ready;
    assign packet_fifo_push  = packet_fifo_pending_valid && (!packet_fifo_full || packet_fifo_pop);

    assign out_valid         = !packet_fifo_empty;
    assign packet_bytes_out  = {{(TOTAL_BYTES_WIDTH-PACKET_BYTES_WIDTH){1'b0}}, packet_fifo[packet_fifo_rd_ptr]};

    // Only a final counted beat may need to wait for FIFO space. Intermediate beats keep streaming.
    assign beat_count_axis.tready = !resetn ? 1'b0 :
        (!beat_count_axis.tvalid || !beat_count_axis.t.last || (!packet_fifo_full || packet_fifo_pop));

    always_ff @(posedge clk) begin
        if (!resetn) begin
            packet_fifo_wr_ptr <= '0;
            packet_fifo_rd_ptr <= '0;
            packet_fifo_count  <= '0;
            packet_fifo_pending_valid <= 1'b0;
            packet_fifo_pending_bytes <= '0;
        end else begin
            if (packet_fifo_push)
                packet_fifo[packet_fifo_wr_ptr] <= packet_fifo_pending_bytes;

            if (packet_fifo_push)
                packet_fifo_pending_valid <= 1'b0;

            if (tlast_transaction) begin
                packet_fifo_pending_valid <= 1'b1;
                packet_fifo_pending_bytes <= packet_bytes_next;
            end

            unique case ({packet_fifo_push, packet_fifo_pop})
                2'b10: begin
                    packet_fifo_wr_ptr <= packet_fifo_wr_ptr + 1'b1;
                    packet_fifo_count  <= packet_fifo_count + 1'b1;
                end
                2'b01: begin
                    packet_fifo_rd_ptr <= packet_fifo_rd_ptr + 1'b1;
                    packet_fifo_count  <= packet_fifo_count - 1'b1;
                end
                2'b11: begin
                    packet_fifo_wr_ptr <= packet_fifo_wr_ptr + 1'b1;
                    packet_fifo_rd_ptr <= packet_fifo_rd_ptr + 1'b1;
                end
                default: begin
                    packet_fifo_wr_ptr <= packet_fifo_wr_ptr;
                    packet_fifo_rd_ptr <= packet_fifo_rd_ptr;
                    packet_fifo_count  <= packet_fifo_count;
                end
            endcase
        end
    end

endmodule
