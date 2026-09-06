`include "ifc_axis.sv"
`include "parser_pkg.sv"
`include "aes_ctr_tunnel_rx_pkg.sv"

module aes_ctr_rx_ingress #(
    parameter int DATA_WIDTH = 512,
    parameter int SA_TABLE_DEPTH = 1024,
    parameter int SA_ID_WIDTH = (SA_TABLE_DEPTH <= 1) ? 1 : $clog2(SA_TABLE_DEPTH),
    parameter int DESC_WIDTH = 16
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave packet_in,
    ifc_axis.master aes_packet_out,
    ifc_axis.master aes_meta_out,
    ifc_axis.master rx_desc_out
);
    import parser_pkg::*;
    import aes_ctr_tunnel_rx_pkg::*;

    localparam int AES_WIDTH = 128;
    localparam int META_WIDTH = ((SA_ID_WIDTH + 1 + 64 + 7) / 8) * 8;
    localparam int TUN_HDR_WIDTH = 96;
    localparam int CTX_WIDTH = 1 + 16 + SA_ID_WIDTH + 64;

    ifc_axis #(.DATA_WIDTH(L3_HDR_AXIS_BITS), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        l3_hdr(clk), l3_fan[2](clk), l3_q(clk);
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        ipv4_payload(clk), payload_fan[2](clk), strip_input_q(clk), stripped(clk);
    ifc_axis #(.DATA_WIDTH(16), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)) remove_in(clk);
    ifc_axis #(.DATA_WIDTH(TUN_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        tun_hdr_in(clk), tun_hdr_q(clk);
    ifc_axis #(.DATA_WIDTH(AES_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)) serialized(clk);
    ifc_axis #(.DATA_WIDTH(CTX_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)) ctx_in(clk), ctx_q(clk);

    ipv4_parser #(.DATA_WIDTH(DATA_WIDTH)) u_ipv4_parser (
        .clk(clk), .resetn(resetn), .s_axis_packet_in(packet_in),
        .m_axis_header_out(l3_hdr), .m_axis_payload_out(ipv4_payload));

    axis_multicast #(.DATA_WIDTH(L3_HDR_AXIS_BITS), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(1), .NUM_DESTS(2)) u_l3_fanout (
        .clk(clk), .resetn(resetn), .s_axis(l3_hdr), .m_axis(l3_fan));

    axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")) u_l3_fifo (
        .clk(clk), .resetn(resetn), .s_axis(l3_fan[0]), .m_axis(l3_q));

    always_comb begin
        remove_in.t = '0;
        remove_in.t.data = 16'(ESP_TUNNEL_HDR_BYTES);
        remove_in.t.keep = '1;
        remove_in.t.last = 1'b1;
    end
    assign remove_in.tvalid = l3_fan[1].tvalid;
    assign l3_fan[1].tready = remove_in.tready;

    axis_multicast #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
        .TUSER_WIDTH(1), .NUM_DESTS(2)) u_payload_fanout (
        .clk(clk), .resetn(resetn), .s_axis(ipv4_payload), .m_axis(payload_fan));

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")) u_strip_input_fifo (
        .clk(clk), .resetn(resetn), .s_axis(payload_fan[0]), .m_axis(strip_input_q));

    axis_strip_repack #(.DATA_WIDTH(DATA_WIDTH), .STRIP_WIDTH(16)) u_strip_tunnel_header (
        .clk(clk), .resetn(resetn), .s_axis(strip_input_q),
        .s_axis_remove(remove_in), .m_axis(stripped));

    logic scan_first_r;
    always_comb begin
        tun_hdr_in.t = '0;
        for (int i = 0; i < ESP_TUNNEL_HDR_BYTES; i++)
            tun_hdr_in.t.data[8*i +: 8] = payload_fan[1].t.data[8*i +: 8];
        tun_hdr_in.t.keep = '1;
        tun_hdr_in.t.last = 1'b1;
    end
    assign tun_hdr_in.tvalid = payload_fan[1].tvalid && scan_first_r;
    assign payload_fan[1].tready = !scan_first_r || tun_hdr_in.tready;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            scan_first_r <= 1'b1;
        end else if (payload_fan[1].tvalid && payload_fan[1].tready) begin
            scan_first_r <= payload_fan[1].t.last;
        end
    end

    axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")) u_tunnel_header_fifo (
        .clk(clk), .resetn(resetn), .s_axis(tun_hdr_in), .m_axis(tun_hdr_q));

    axis_serializer #(.INPUT_DATA_WIDTH(DATA_WIDTH), .OUTPUT_DATA_WIDTH(AES_WIDTH)) u_serializer (
        .clk(clk), .resetn(resetn), .s_axis(stripped), .m_axis(serialized));

    l3_hdr_axis_t parsed_l3;
    logic [31:0] spi_word;
    logic [63:0] sequence_word;
    logic ctx_valid;
    assign parsed_l3 = l3_hdr_axis_t'(l3_q.t.data);
    assign spi_word = {tun_hdr_q.t.data[7:0], tun_hdr_q.t.data[15:8],
                       tun_hdr_q.t.data[23:16], tun_hdr_q.t.data[31:24]};
    assign sequence_word = {tun_hdr_q.t.data[39:32], tun_hdr_q.t.data[47:40],
                            tun_hdr_q.t.data[55:48], tun_hdr_q.t.data[63:56],
                            tun_hdr_q.t.data[71:64], tun_hdr_q.t.data[79:72],
                            tun_hdr_q.t.data[87:80], tun_hdr_q.t.data[95:88]};
    assign ctx_valid = (parsed_l3.status == PARSER_STATUS_OK) &&
                       (parsed_l3.protocol == 8'(ESP_PROTO)) &&
                       (parsed_l3.ipv4.total_length >= 16'(IPV4_MIN_BYTES + ESP_TUNNEL_HDR_BYTES + 2)) &&
                       (spi_word < SA_TABLE_DEPTH);

    always_comb begin
        ctx_in.t = '0;
        ctx_in.t.data[0] = ctx_valid;
        ctx_in.t.data[1 +: 16] = parsed_l3.ipv4.total_length - 16'(IPV4_MIN_BYTES + ESP_TUNNEL_HDR_BYTES);
        ctx_in.t.data[17 +: SA_ID_WIDTH] = spi_word[SA_ID_WIDTH-1:0];
        ctx_in.t.data[17 + SA_ID_WIDTH +: 64] = sequence_word;
        ctx_in.t.keep = '1;
        ctx_in.t.last = 1'b1;
    end
    assign ctx_in.tvalid = l3_q.tvalid && tun_hdr_q.tvalid;
    assign l3_q.tready = ctx_in.tready && tun_hdr_q.tvalid;
    assign tun_hdr_q.tready = ctx_in.tready && l3_q.tvalid;

    axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")) u_context_fifo (
        .clk(clk), .resetn(resetn), .s_axis(ctx_in), .m_axis(ctx_q));

    // Keep one context prefetched ahead of the packet currently being
    // serialized.  Its AES metadata and RX descriptor can be accepted by the
    // downstream FIFOs while the current packet is still in flight, allowing
    // adjacent packets to occupy consecutive 128-bit AES cycles.
    logic pending_full_r;
    logic pending_packet_valid_r;
    logic [15:0] pending_enc_len_r;
    logic [SA_ID_WIDTH-1:0] pending_sa_id_r;
    logic [63:0] pending_sequence_r;
    logic pending_meta_sent_r;
    logic pending_desc_sent_r;
    logic active_r;
    logic active_packet_valid_r;

    wire meta_fire = aes_meta_out.tvalid && aes_meta_out.tready;
    wire desc_fire = rx_desc_out.tvalid && rx_desc_out.tready;
    wire pending_meta_done = !pending_packet_valid_r || pending_meta_sent_r || meta_fire;
    wire pending_desc_done = !pending_packet_valid_r || pending_desc_sent_r || desc_fire;
    wire pending_ready = pending_full_r && pending_meta_done && pending_desc_done;
    wire active_end = active_r && serialized.tvalid && serialized.tready && serialized.t.last;
    wire promote_pending = pending_ready && (!active_r || active_end);

    assign ctx_q.tready = !pending_full_r;
    always_comb begin
        aes_meta_out.t = '0;
        aes_meta_out.t.data[SA_ID_WIDTH-1:0] = pending_sa_id_r;
        aes_meta_out.t.data[SA_ID_WIDTH] = 1'b1;
        aes_meta_out.t.data[SA_ID_WIDTH+1 +: 64] = pending_sequence_r;
        aes_meta_out.t.keep = '1;
        aes_meta_out.t.last = 1'b1;
        rx_desc_out.t = '0;
        rx_desc_out.t.data[15:0] = pending_enc_len_r;
        rx_desc_out.t.keep = '1;
        rx_desc_out.t.last = 1'b1;
        aes_packet_out.t = serialized.t;
    end
    assign aes_meta_out.tvalid = pending_full_r && pending_packet_valid_r &&
                                 !pending_meta_sent_r;
    assign rx_desc_out.tvalid = pending_full_r && pending_packet_valid_r &&
                                !pending_desc_sent_r;
    assign aes_packet_out.tvalid = active_r && active_packet_valid_r && serialized.tvalid;
    assign serialized.tready = active_r &&
                               (active_packet_valid_r ? aes_packet_out.tready : 1'b1);

    always_ff @(posedge clk) begin
        if (!resetn) begin
            pending_full_r <= 1'b0;
            pending_packet_valid_r <= 1'b0;
            pending_enc_len_r <= '0;
            pending_sa_id_r <= '0;
            pending_sequence_r <= '0;
            pending_meta_sent_r <= 1'b0;
            pending_desc_sent_r <= 1'b0;
            active_r <= 1'b0;
            active_packet_valid_r <= 1'b0;
        end else begin
            if (promote_pending) begin
                pending_full_r <= 1'b0;
                pending_meta_sent_r <= 1'b0;
                pending_desc_sent_r <= 1'b0;
            end else if (ctx_q.tvalid && ctx_q.tready) begin
                pending_full_r <= 1'b1;
                pending_packet_valid_r <= ctx_q.t.data[0];
                pending_enc_len_r <= ctx_q.t.data[1 +: 16];
                pending_sa_id_r <= ctx_q.t.data[17 +: SA_ID_WIDTH];
                pending_sequence_r <= ctx_q.t.data[17 + SA_ID_WIDTH +: 64];
                pending_meta_sent_r <= 1'b0;
                pending_desc_sent_r <= 1'b0;
            end else begin
                if (meta_fire)
                    pending_meta_sent_r <= 1'b1;
                if (desc_fire)
                    pending_desc_sent_r <= 1'b1;
            end

            if (promote_pending) begin
                active_r <= 1'b1;
                active_packet_valid_r <= pending_packet_valid_r;
            end else if (active_end) begin
                active_r <= 1'b0;
                active_packet_valid_r <= 1'b0;
            end
        end
    end
endmodule
