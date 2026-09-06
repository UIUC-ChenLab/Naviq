`include "ifc_axis.sv"

// Prepends the configured IPv4/UDP aggregate header and updates its length
// fields. The shared repacker emits a dense packet for any AXIS data width.
module uro_output_formatter #(
    parameter int DATA_WIDTH          = 512,
    parameter int BYTE_COUNT_WIDTH    = 14,
    parameter int AGGREGATE_META_WIDTH = 8*28 + BYTE_COUNT_WIDTH
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave aggregate_payload,
    ifc_axis.master packet_out,
    output logic empty
);
    localparam int DATA_BYTES = DATA_WIDTH / 8;
    localparam int HEADER_BYTES = 28;
    localparam int HEADER_OFFSET_WIDTH = $clog2(HEADER_BYTES + 1);

    logic active_r, payload_done_r;
    logic [8*HEADER_BYTES-1:0] header_r;
    logic [HEADER_OFFSET_WIDTH-1:0] header_offset_r;
    logic active_n, payload_done_n;
    logic [8*HEADER_BYTES-1:0] header_n;
    logic [HEADER_OFFSET_WIDTH-1:0] header_offset_n;
    logic [15:0] ip_length_c, udp_length_c;

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
        .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) header_axis (clk), payload_axis (clk), packet_axis (clk);

    always_comb begin
        ip_length_c = 16'(HEADER_BYTES) +
            16'(aggregate_payload.t.user[0 +: BYTE_COUNT_WIDTH]);
        udp_length_c = 16'(8) +
            16'(aggregate_payload.t.user[0 +: BYTE_COUNT_WIDTH]);

        header_axis.t = '0;
        header_axis.tvalid = active_r && (header_offset_r < HEADER_BYTES);
        for (int lane = 0; lane < DATA_BYTES; lane++) begin
            int byte_index;
            byte_index = int'(header_offset_r) + lane;
            if (byte_index < HEADER_BYTES) begin
                header_axis.t.data[lane*8 +: 8] =
                    header_r[byte_index*8 +: 8];
                header_axis.t.keep[lane] = 1'b1;
            end
        end
        header_axis.t.last =
            (int'(header_offset_r) + DATA_BYTES) >= HEADER_BYTES;

        payload_axis.t.data = aggregate_payload.t.data;
        payload_axis.t.keep = aggregate_payload.t.keep;
        payload_axis.t.last = aggregate_payload.t.last;
        payload_axis.t.id = '0;
        payload_axis.t.dest = '0;
        payload_axis.t.user = '0;
        payload_axis.tvalid = aggregate_payload.tvalid &&
                              active_r && !payload_done_r;
        aggregate_payload.tready = payload_axis.tready &&
                                   active_r && !payload_done_r;
    end

    axis_combine_repack #(
        .FIRST_STREAM_IS_A(1), .DATA_WIDTH(DATA_WIDTH)
    ) u_header_repack (
        .clk(clk), .resetn(resetn),
        .s_axis_a(header_axis), .s_axis_b(payload_axis),
        .m_axis(packet_axis)
    );

    always_comb begin
        active_n = active_r;
        payload_done_n = payload_done_r;
        header_n = header_r;
        header_offset_n = header_offset_r;

        if (!active_r && aggregate_payload.tvalid) begin
            active_n = 1'b1;
            payload_done_n = 1'b0;
            header_n = aggregate_payload.t.user[
                BYTE_COUNT_WIDTH +: 8*HEADER_BYTES];
            header_n[2*8 +: 8] = ip_length_c[15:8];
            header_n[3*8 +: 8] = ip_length_c[7:0];
            header_n[24*8 +: 8] = udp_length_c[15:8];
            header_n[25*8 +: 8] = udp_length_c[7:0];
            header_offset_n = '0;
        end
        if (header_axis.tvalid && header_axis.tready) begin
            if (header_axis.t.last)
                header_offset_n = HEADER_OFFSET_WIDTH'(HEADER_BYTES);
            else
                header_offset_n = header_offset_r +
                                  HEADER_OFFSET_WIDTH'(DATA_BYTES);
        end
        if (aggregate_payload.tvalid && aggregate_payload.tready &&
            aggregate_payload.t.last) begin
            payload_done_n = 1'b1;
        end
        if (packet_axis.tvalid && packet_axis.tready && packet_axis.t.last) begin
            active_n = 1'b0;
            payload_done_n = 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            active_r <= 1'b0;
            payload_done_r <= 1'b0;
            header_r <= '0;
            header_offset_r <= '0;
        end else begin
            active_r <= active_n;
            payload_done_r <= payload_done_n;
            header_r <= header_n;
            header_offset_r <= header_offset_n;
        end
    end

    always_comb begin
        packet_out.t = packet_axis.t;
        packet_out.tvalid = packet_axis.tvalid;
        packet_axis.tready = packet_out.tready;
        empty = !active_r && !packet_axis.tvalid;
    end
endmodule
