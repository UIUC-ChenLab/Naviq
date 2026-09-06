`include "ifc_axis.sv"
`include "aes_ctr_tunnel_rx_pkg.sv"

module aes_ctr_rx_egress #(
    parameter int DATA_WIDTH = 512,
    parameter int SA_ID_WIDTH = 10,
    parameter int MAX_PACKET_BYTES = 2048,
    parameter int DESC_WIDTH = 16
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave aes_packet_in,
    ifc_axis.slave aes_meta_in,
    ifc_axis.slave rx_desc_in,
    ifc_axis.master packet_out
);
    import aes_ctr_tunnel_rx_pkg::*;
    localparam int AES_WIDTH = 128;
    localparam int AES_BYTES = 16;
    localparam int DROP_BIT = 64 + SA_ID_WIDTH;
    localparam int DATA_FIFO_DEPTH = 2 * ((MAX_PACKET_BYTES + AES_BYTES - 1) / AES_BYTES);
    localparam int COMP_WIDTH = 24;

    ifc_axis #(.DATA_WIDTH(AES_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        data_fifo_in(clk), data_fifo_out(clk);
    ifc_axis #(.DATA_WIDTH(COMP_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        comp_in(clk), comp_out(clk);
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)) fragment(clk), packed_axis(clk);

    axis_fifo #(.DEPTH(DATA_FIFO_DEPTH), .USE_BRAM(1'b1), .MODE("FULL_CAPACITY")) u_packet_fifo (
        .clk(clk), .resetn(resetn), .s_axis(data_fifo_in), .m_axis(data_fifo_out));
    axis_fifo #(.DEPTH(16), .USE_BRAM(1'b0), .MODE("CONSERVATIVE")) u_completion_fifo (
        .clk(clk), .resetn(resetn), .s_axis(comp_in), .m_axis(comp_out));

    typedef enum logic [1:0] {WAIT_CONTEXT, STORE_PACKET} store_state_t;
    store_state_t store_state_r;
    logic [15:0] enc_len_r;
    logic first_plain_r;
    logic [7:0] first_byte_r;
    integer pad_lane_c;
    integer next_lane_c;
    logic [7:0] pad_len_c;
    logic [7:0] next_header_c;
    logic [15:0] inner_len_c;
    logic trailer_good_c;
    logic [15:0] trailer_enc_len_c;
    logic [7:0] trailer_first_byte_c;

    wire context_valid = aes_meta_in.tvalid && rx_desc_in.tvalid;
    wire context_drop = aes_meta_in.t.data[DROP_BIT];
    wire context_fire = context_valid && aes_meta_in.tready && rx_desc_in.tready;
    wire context_store = (store_state_r == WAIT_CONTEXT) && context_valid && !context_drop;
    wire store_window = (store_state_r == STORE_PACKET) || context_store;

    always_comb begin
        data_fifo_in.t = aes_packet_in.t;
        data_fifo_in.tvalid = store_window && aes_packet_in.tvalid &&
                              (!aes_packet_in.t.last || comp_in.tready);
        aes_packet_in.tready = store_window && data_fifo_in.tready &&
                               (!aes_packet_in.t.last || comp_in.tready);

        comp_in.t = '0;
        comp_in.t.keep = '1;
        comp_in.t.last = 1'b1;
        comp_in.tvalid = 1'b0;
        aes_meta_in.tready = 1'b0;
        rx_desc_in.tready = 1'b0;
        pad_lane_c = 0;
        next_lane_c = 0;
        pad_len_c = '0;
        next_header_c = '0;
        inner_len_c = '0;
        trailer_good_c = 1'b0;
        trailer_enc_len_c = (store_state_r == WAIT_CONTEXT) ?
            rx_desc_in.t.data[15:0] : enc_len_r;
        trailer_first_byte_c = (store_state_r == WAIT_CONTEXT || first_plain_r) ?
            aes_packet_in.t.data[7:0] : first_byte_r;

        if (store_state_r == WAIT_CONTEXT) begin
            aes_meta_in.tready = rx_desc_in.tvalid && (context_drop ? comp_in.tready : 1'b1);
            rx_desc_in.tready = aes_meta_in.tvalid && (context_drop ? comp_in.tready : 1'b1);
            if (context_valid && context_drop) begin
                comp_in.tvalid = 1'b1;
                comp_in.t.data[0] = 1'b1;
                comp_in.t.data[1] = 1'b0;
            end
        end
        if (store_window && aes_packet_in.tvalid && aes_packet_in.t.last) begin
            pad_lane_c = (int'(trailer_enc_len_c) - 2) & 15;
            next_lane_c = (int'(trailer_enc_len_c) - 1) & 15;
            pad_len_c = aes_packet_in.t.data[8*pad_lane_c +: 8];
            next_header_c = aes_packet_in.t.data[8*next_lane_c +: 8];
            inner_len_c = trailer_enc_len_c - 16'(pad_len_c) - 16'd2;
            trailer_good_c = (trailer_enc_len_c >= 16'(IPV4_MIN_BYTES + 2)) &&
                   (next_header_c == 8'(ESP_NEXT_HEADER_IPV4)) &&
                   ({8'd0, pad_len_c} + 16'd2 <= trailer_enc_len_c) &&
                   (inner_len_c >= 16'(IPV4_MIN_BYTES)) &&
                   (trailer_first_byte_c[7:4] == 4'd4);
            comp_in.tvalid = aes_packet_in.tvalid;
            comp_in.t.data[0] = !trailer_good_c;
            comp_in.t.data[1] = 1'b1;
            comp_in.t.data[2 +: 16] = inner_len_c;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            store_state_r <= WAIT_CONTEXT;
            enc_len_r <= '0;
            first_plain_r <= 1'b1;
            first_byte_r <= '0;
        end else begin
            if (store_state_r == WAIT_CONTEXT && context_fire && !context_drop) begin
                enc_len_r <= rx_desc_in.t.data[15:0];
                first_plain_r <= 1'b1;
                store_state_r <= STORE_PACKET;
            end
            if (aes_packet_in.tvalid && aes_packet_in.tready) begin
                if (store_state_r == WAIT_CONTEXT || first_plain_r) begin
                    first_byte_r <= aes_packet_in.t.data[7:0];
                    first_plain_r <= 1'b0;
                end
                if (aes_packet_in.t.last)
                    store_state_r <= WAIT_CONTEXT;
            end
        end
    end

    typedef enum logic [1:0] {GET_COMPLETION, RELEASE_PACKET, DRAIN_TAIL} release_state_t;
    release_state_t release_state_r;
    logic release_drop_r;
    logic release_has_data_r;
    logic [15:0] release_remaining_r;
    wire data_fire = data_fifo_out.tvalid && data_fifo_out.tready;
    wire release_finishes = (release_state_r == RELEASE_PACKET) && data_fire &&
        data_fifo_out.t.last &&
        (release_drop_r || (!release_drop_r && release_remaining_r <= AES_BYTES));
    wire drain_finishes = (release_state_r == DRAIN_TAIL) && data_fire &&
        data_fifo_out.t.last;

    assign comp_out.tready = (release_state_r == GET_COMPLETION) ||
                             release_finishes || drain_finishes;
    always_comb begin
        fragment.t = '0;
        fragment.t.data[127:0] = data_fifo_out.t.data;
        fragment.t.keep[15:0] = data_fifo_out.t.keep;
        fragment.tvalid = (release_state_r == RELEASE_PACKET) && !release_drop_r && data_fifo_out.tvalid;
        if (release_remaining_r <= AES_BYTES) begin
            fragment.t.keep[15:0] = '0;
            for (int i = 0; i < AES_BYTES; i++)
                fragment.t.keep[i] = (i < release_remaining_r);
            fragment.t.last = 1'b1;
        end
        data_fifo_out.tready = ((release_state_r == RELEASE_PACKET) &&
            (release_drop_r ? 1'b1 : fragment.tready)) || (release_state_r == DRAIN_TAIL);
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            release_state_r <= GET_COMPLETION;
            release_drop_r <= 1'b0;
            release_has_data_r <= 1'b0;
            release_remaining_r <= '0;
        end else begin
            if (release_state_r == GET_COMPLETION && comp_out.tvalid) begin
                release_drop_r <= comp_out.t.data[0];
                release_has_data_r <= comp_out.t.data[1];
                release_remaining_r <= comp_out.t.data[2 +: 16];
                if (!comp_out.t.data[1])
                    release_state_r <= GET_COMPLETION;
                else
                    release_state_r <= RELEASE_PACKET;
            end else if (release_state_r == RELEASE_PACKET && data_fire) begin
                if (release_drop_r) begin
                    if (data_fifo_out.t.last) begin
                        if (comp_out.tvalid) begin
                            release_drop_r <= comp_out.t.data[0];
                            release_has_data_r <= comp_out.t.data[1];
                            release_remaining_r <= comp_out.t.data[2 +: 16];
                            release_state_r <= comp_out.t.data[1] ? RELEASE_PACKET : GET_COMPLETION;
                        end else begin
                            release_state_r <= GET_COMPLETION;
                        end
                    end
                end else if (release_remaining_r <= AES_BYTES) begin
                    release_remaining_r <= '0;
                    if (!data_fifo_out.t.last) begin
                        release_state_r <= DRAIN_TAIL;
                    end else if (comp_out.tvalid) begin
                        release_drop_r <= comp_out.t.data[0];
                        release_has_data_r <= comp_out.t.data[1];
                        release_remaining_r <= comp_out.t.data[2 +: 16];
                        release_state_r <= comp_out.t.data[1] ? RELEASE_PACKET : GET_COMPLETION;
                    end else begin
                        release_state_r <= GET_COMPLETION;
                    end
                end else begin
                    release_remaining_r <= release_remaining_r - 16'(AES_BYTES);
                end
            end else if (release_state_r == DRAIN_TAIL && data_fire && data_fifo_out.t.last) begin
                if (comp_out.tvalid) begin
                    release_drop_r <= comp_out.t.data[0];
                    release_has_data_r <= comp_out.t.data[1];
                    release_remaining_r <= comp_out.t.data[2 +: 16];
                    release_state_r <= comp_out.t.data[1] ? RELEASE_PACKET : GET_COMPLETION;
                end else begin
                    release_state_r <= GET_COMPLETION;
                end
            end
        end
    end

    axis_fragment_packer #(.DATA_WIDTH(DATA_WIDTH), .PAGE_COUNT(8)) u_output_packer (
        .clk(clk), .resetn(resetn), .s_axis(fragment), .m_axis(packed_axis));
    always_comb begin
        packet_out.t = '0;
        packet_out.t.data = packed_axis.t.data;
        packet_out.t.keep = packed_axis.t.keep;
        packet_out.t.last = packed_axis.t.last;
    end
    assign packet_out.tvalid = packed_axis.tvalid;
    assign packed_axis.tready = packet_out.tready;
endmodule
