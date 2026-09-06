`include "ifc_axis.sv"
`include "ifc_axil.sv"
`include "parser_pkg.sv"
`include "aes_ctr_tunnel_tx_pkg.sv"

module aes_ctr_tx_ingress #(
    parameter int DATA_WIDTH = 512,
    parameter int SA_TABLE_DEPTH = 1024,
    parameter int SA_ID_WIDTH = (SA_TABLE_DEPTH <= 1) ? 1 : $clog2(SA_TABLE_DEPTH),
    parameter int HASH_WIDTH = 12,
    parameter int DESC_WIDTH = ((SA_ID_WIDTH + 16 + 64 + 7) / 8) * 8
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave packet_in,
    ifc_axil.slave hash_ctrl,
    ifc_axil.slave tunnel_ctrl,
    ifc_axis.master aes_packet_out,
    ifc_axis.master aes_meta_out,
    ifc_axis.master tx_desc_out
);
    import parser_pkg::*;
    import aes_ctr_tunnel_tx_pkg::*;
    localparam int AES_DATA_WIDTH = 128;
    localparam int HASH_TABLE_DEPTH = 1 << HASH_WIDTH;
    localparam int DESC_SA_LSB = 0;
    localparam int DESC_LEN_LSB = DESC_SA_LSB + SA_ID_WIDTH;
    localparam int DESC_SRC_LSB = DESC_LEN_LSB + 16;
    localparam int DESC_DST_LSB = DESC_SRC_LSB + 32;
    localparam int TUNNEL_DST_LSB = 0;
    localparam int TUNNEL_SRC_LSB = TUNNEL_DST_LSB + 32;
    localparam int TUNNEL_VALID_BIT = TUNNEL_SRC_LSB + 32;
    localparam int TUNNEL_ENTRY_WIDTH = TUNNEL_VALID_BIT + 1;

    // Input fanout and raw-packet buffering
    // -------------------------------------
    // The parser remains on the wide branch. The packet-storage branch is
    // serialized immediately so downstream payload stages use the AES width.
    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) ingress_axis(clk), fork_axis[2](clk);
    ifc_axis #(
        .DATA_WIDTH  (AES_DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) serialized_axis(clk), raw_axis(clk);

    always_comb begin
        ingress_axis.t      = '0;
        ingress_axis.t.data = packet_in.t.data;
        ingress_axis.t.keep = packet_in.t.keep;
        ingress_axis.t.last = packet_in.t.last;
    end
    assign ingress_axis.tvalid = packet_in.tvalid;
    assign packet_in.tready    = ingress_axis.tready;

    axis_multicast #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1),
        .NUM_DESTS   (2)
    ) u_input_fork (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (ingress_axis),
        .m_axis  (fork_axis)
    );

    axis_serializer #(
        .INPUT_DATA_WIDTH  (DATA_WIDTH),
        .OUTPUT_DATA_WIDTH (AES_DATA_WIDTH)
    ) u_serializer (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (fork_axis[0]),
        .m_axis  (serialized_axis)
    );

    axis_fifo #(
        .DEPTH    (TX_RAW_FIFO_DEPTH),
        .USE_BRAM (1'b1),
        .MODE     ("CONSERVATIVE")
    ) u_raw_fifo (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (serialized_axis),
        .m_axis  (raw_axis)
    );

    // Header parsing and tuple construction
    // -------------------------------------
    ifc_axis #(
        .DATA_WIDTH  (L2_HDR_AXIS_BITS),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l2_hdr(clk);
    ifc_axis #(
        .DATA_WIDTH  (L3_HDR_AXIS_BITS),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l3_hdr_raw(clk), l3_hdr(clk);
    ifc_axis #(
        .DATA_WIDTH  (L4_HDR_AXIS_BITS),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) l4_hdr_raw(clk), l4_hdr(clk);
    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) payload_unused(clk);

    parser #(
        .DATA_WIDTH         (DATA_WIDTH),
        .SKIP_L2            (1'b1),
        .HEADER_ONLY        (1'b1),
        .REPACK_PAYLOAD_OUT (1'b0),
        .DEFAULT_ETHERTYPE  (16'h0800)
    ) u_parser (
        .clk                  (clk),
        .resetn               (resetn),
        .s_axis_packet_in     (fork_axis[1]),
        .m_axis_l2_header_out (l2_hdr),
        .m_axis_l3_header_out (l3_hdr_raw),
        .m_axis_l4_header_out (l4_hdr_raw),
        .m_axis_payload_out   (payload_unused)
    );
    assign l2_hdr.tready = 1'b1;
    assign payload_unused.tready = 1'b1;

    // Decouple the parser's independently produced L3 and L4 records from
    // the tuple join.  Without these queues, holding L3 ready low until L4
    // became valid prevented the parser from retiring its L3 output and
    // throttled short packets at the multicast input.
    axis_fifo #(
        .DEPTH    (TX_DESC_FIFO_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_l3_meta_fifo (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (l3_hdr_raw),
        .m_axis  (l3_hdr)
    );
    axis_fifo #(
        .DEPTH    (TX_DESC_FIFO_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_l4_meta_fifo (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (l4_hdr_raw),
        .m_axis  (l4_hdr)
    );

    l3_hdr_axis_t l3;
    l4_hdr_axis_t l4;
    logic [103:0] tuple;
    logic [HASH_WIDTH-1:0] tuple_hash;
    always_comb begin
        l3 = l3_hdr_axis_t'(l3_hdr.t.data);
        l4 = l4_hdr_axis_t'(l4_hdr.t.data);
        tuple = {
            l3.ipv4.protocol,
            (l4.kind == L4_KIND_TCP) ? l4.tcp.dst_port : l4.udp.dst_port,
            (l4.kind == L4_KIND_TCP) ? l4.tcp.src_port : l4.udp.src_port,
            l3.ipv4.dst_addr,
            l3.ipv4.src_addr
        };
    end

    toeplitz_hash #(
        .HASH_WIDTH  (HASH_WIDTH),
        .TUPLE_WIDTH (104)
    ) u_hash (
        .tuple_bits (tuple),
        .hash_value (tuple_hash)
    );

    // Hash-to-SA lookup and descriptor generation
    // -------------------------------------------
    logic [TUNNEL_ENTRY_WIDTH-1:0] tunnel_lookup_data;
    logic [TUNNEL_ENTRY_WIDTH-1:0] tunnel_mgmt_read_data;
    logic [TUNNEL_ENTRY_WIDTH-1:0] tunnel_mgmt_write_data;
    logic [SA_ID_WIDTH-1:0] tunnel_lookup_addr;
    logic [SA_ID_WIDTH-1:0] tunnel_lookup_addr_r;
    logic [SA_ID_WIDTH-1:0] tunnel_mgmt_addr_r;
    logic tunnel_mgmt_write_en;

    localparam int LOOKUP_CTX_LEN_LSB = 0;
    localparam int LOOKUP_CTX_WIDTH = 16;
    localparam int HASH_ERROR_WIDTH = HASH_WIDTH * 2;

    ifc_axis #(
        .DATA_WIDTH(16), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) table_index(clk), table_key(clk), table_value(clk);
    ifc_axis #(
        .DATA_WIDTH(HASH_ERROR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) table_error(clk);
    ifc_axis #(
        .DATA_WIDTH(LOOKUP_CTX_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) lookup_ctx_in(clk), lookup_ctx_q(clk);
    ifc_axis #(
        .DATA_WIDTH(16), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) lookup_result_in(clk), lookup_result_q(clk);

    logic table_value_way;
    logic table_mgmt_write_commit;
    logic [HASH_WIDTH-1:0] table_mgmt_write_set;
    logic table_mgmt_write_way;

    axil_hash_table #(
        .TABLE_DEPTH   (HASH_TABLE_DEPTH),
        .KEY_WIDTH     (HASH_WIDTH),
        .VALUE_WIDTH   (SA_ID_WIDTH),
        .ASSOCIATIVITY (1)
    ) u_hash_table (
        .clk                (clk),
        .resetn             (resetn),
        .ctrl_in            (hash_ctrl),
        .s_axis_lookup_index(table_index),
        .s_axis_key         (table_key),
        .m_axis_value       (table_value),
        .m_axis_error       (table_error),
        .m_axis_value_way   (table_value_way),
        .runtime_update_valid(1'b0),
        .runtime_update_set ('0),
        .runtime_update_way ('0),
        .runtime_update_data('0),
        .mgmt_write_commit  (table_mgmt_write_commit),
        .mgmt_write_set     (table_mgmt_write_set),
        .mgmt_write_way     (table_mgmt_write_way)
    );

    axis_fifo #(
        .DEPTH    (TX_DESC_FIFO_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_lookup_ctx_fifo (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (lookup_ctx_in),
        .m_axis  (lookup_ctx_q)
    );

    always_comb begin
        lookup_result_in.t = '0;
        lookup_result_in.t.data[SA_ID_WIDTH-1:0] =
            table_value.t.data[SA_ID_WIDTH-1:0];
        lookup_result_in.t.data[SA_ID_WIDTH] = table_value.tvalid;
        lookup_result_in.t.keep = '1;
        lookup_result_in.t.last = 1'b1;
    end
    assign lookup_result_in.tvalid = table_value.tvalid || table_error.tvalid;
    assign table_value.tready       = lookup_result_in.tready;
    assign table_error.tready       = lookup_result_in.tready;

    axis_fifo #(
        .DEPTH    (4),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_lookup_result_fifo (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (lookup_result_in),
        .m_axis  (lookup_result_q)
    );

    ifc_axis #(
        .DATA_WIDTH(DESC_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) desc_in(clk), desc_q(clk), desc_fan[3](clk);

    logic lookup_req_ready;
    logic header_fire;
    logic [SA_ID_WIDTH-1:0] lookup_sa;
    logic lookup_hit;
    logic lookup_result_ready;
    logic tunnel_lookup_fire;
    logic tunnel_lookup_ready;
    logic tunnel_lookup_valid_r;
    logic [SA_ID_WIDTH-1:0] tunnel_lookup_sa_r;
    logic [15:0] tunnel_lookup_len_r;

    assign lookup_req_ready =
        table_index.tready && table_key.tready && lookup_ctx_in.tready;
    assign l3_hdr.tready = l4_hdr.tvalid && lookup_req_ready;
    assign l4_hdr.tready = l3_hdr.tvalid && lookup_req_ready;
    assign header_fire =
        l3_hdr.tvalid && l4_hdr.tvalid && l3_hdr.tready && l4_hdr.tready;

    always_comb begin
        table_index.t = '0;
        table_index.t.data[HASH_WIDTH-1:0] = tuple_hash;
        table_index.t.keep = '1;
        table_index.t.last = 1'b1;

        table_key.t = table_index.t;

        lookup_ctx_in.t = '0;
        lookup_ctx_in.t.data[LOOKUP_CTX_LEN_LSB +: 16] = l3.ipv4.total_length;
        lookup_ctx_in.t.keep = '1;
        lookup_ctx_in.t.last = 1'b1;
    end
    assign table_index.tvalid   = header_fire;
    assign table_key.tvalid     = header_fire;
    assign lookup_ctx_in.tvalid = header_fire;

    assign lookup_sa  = lookup_result_q.t.data[SA_ID_WIDTH-1:0];
    assign lookup_hit = lookup_result_q.t.data[SA_ID_WIDTH];
    assign tunnel_lookup_ready = !tunnel_lookup_valid_r ||
        !tunnel_lookup_data[TUNNEL_VALID_BIT] || desc_in.tready;
    assign lookup_result_ready = lookup_ctx_q.tvalid &&
        (!lookup_hit || tunnel_lookup_ready);
    assign lookup_result_q.tready = lookup_result_ready;
    assign lookup_ctx_q.tready = lookup_result_q.tvalid && lookup_result_ready;
    assign tunnel_lookup_fire = lookup_result_q.tvalid && lookup_ctx_q.tvalid &&
        lookup_hit && tunnel_lookup_ready;
    assign tunnel_lookup_addr = tunnel_lookup_fire ? lookup_sa : tunnel_lookup_addr_r;

    true_dual_port_bram #(
        .BRAM_WIDTH      (TUNNEL_ENTRY_WIDTH),
        .BRAM_DEPTH      (SA_TABLE_DEPTH),
        .INIT_VALID_ZERO (1'b1),
        .VALID_BIT_INDEX (TUNNEL_VALID_BIT)
    ) u_tunnel_table (
        .clk    (clk),
        .we_a   (1'b0),
        .addr_a (tunnel_lookup_addr),
        .din_a  ('0),
        .dout_a (tunnel_lookup_data),
        .we_b   (tunnel_mgmt_write_en),
        .addr_b (tunnel_mgmt_addr_r),
        .din_b  (tunnel_mgmt_write_data),
        .dout_b (tunnel_mgmt_read_data)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            tunnel_lookup_valid_r <= 1'b0;
            tunnel_lookup_addr_r <= '0;
            tunnel_lookup_sa_r <= '0;
            tunnel_lookup_len_r <= '0;
        end else begin
            if (tunnel_lookup_fire) begin
                tunnel_lookup_valid_r <= 1'b1;
                tunnel_lookup_addr_r <= lookup_sa;
                tunnel_lookup_sa_r <= lookup_sa;
                tunnel_lookup_len_r <= lookup_ctx_q.t.data[LOOKUP_CTX_LEN_LSB +: 16];
            end else if (tunnel_lookup_ready) begin
                tunnel_lookup_valid_r <= 1'b0;
            end
        end
    end

    always_comb begin
        desc_in.t = '0;
        desc_in.t.data[DESC_SA_LSB +: SA_ID_WIDTH] = tunnel_lookup_sa_r;
        desc_in.t.data[DESC_LEN_LSB +: 16] = tunnel_lookup_len_r;
        desc_in.t.data[DESC_SRC_LSB +: 32] =
            tunnel_lookup_data[TUNNEL_SRC_LSB +: 32];
        desc_in.t.data[DESC_DST_LSB +: 32] =
            tunnel_lookup_data[TUNNEL_DST_LSB +: 32];
        desc_in.t.keep = '1;
        desc_in.t.last = 1'b1;
        desc_in.tvalid = tunnel_lookup_valid_r &&
            tunnel_lookup_data[TUNNEL_VALID_BIT];
    end

    axis_fifo #(
        .DEPTH    (TX_DESC_FIFO_DEPTH),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_desc_fifo (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (desc_in),
        .m_axis  (desc_q)
    );

    axis_multicast #(
        .DATA_WIDTH  (DESC_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1),
        .NUM_DESTS   (3)
    ) u_desc_fanout (
        .clk     (clk),
        .resetn  (resetn),
        .s_axis  (desc_q),
        .m_axis  (desc_fan)
    );

    // ESP trailer append and AES stream outputs
    // -----------------------------------------
    ifc_axis #(
        .DATA_WIDTH(AES_DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) trailer_axis(clk), combined_axis(clk);

    logic [1:0] trailer_pad_len;
    logic [15:0] trailer_inner_len;

    assign trailer_inner_len = desc_fan[0].t.data[DESC_LEN_LSB +: 16];
    assign trailer_pad_len = 2'((4 - ((trailer_inner_len + 2) & 3)) & 3);

    always_comb begin
        trailer_axis.t = '0;
        trailer_axis.t.last = 1'b1;
        unique case (trailer_pad_len)
            2'd0: begin
                trailer_axis.t.data[8 * 0 +: 8] = 8'd0;
                trailer_axis.t.data[8 * 1 +: 8] = 8'(ESP_NEXT_HEADER_IPV4);
                trailer_axis.t.keep[1:0] = 2'b11;
            end
            2'd1: begin
                trailer_axis.t.data[8 * 1 +: 8] = 8'd1;
                trailer_axis.t.data[8 * 2 +: 8] = 8'(ESP_NEXT_HEADER_IPV4);
                trailer_axis.t.keep[2:0] = 3'b111;
            end
            2'd2: begin
                trailer_axis.t.data[8 * 2 +: 8] = 8'd2;
                trailer_axis.t.data[8 * 3 +: 8] = 8'(ESP_NEXT_HEADER_IPV4);
                trailer_axis.t.keep[3:0] = 4'b1111;
            end
            default: begin
                trailer_axis.t.data[8 * 3 +: 8] = 8'd3;
                trailer_axis.t.data[8 * 4 +: 8] = 8'(ESP_NEXT_HEADER_IPV4);
                trailer_axis.t.keep[4:0] = 5'b11111;
            end
        endcase
    end
    assign trailer_axis.tvalid = desc_fan[0].tvalid;
    assign desc_fan[0].tready  = trailer_axis.tready;

    axis_combine_repack #(
        .FIRST_STREAM_IS_A (1),
        .DATA_WIDTH        (AES_DATA_WIDTH)
    ) u_append_esp_trailer (
        .clk      (clk),
        .resetn   (resetn),
        .s_axis_a (raw_axis),
        .s_axis_b (trailer_axis),
        .m_axis   (combined_axis)
    );

    always_comb begin
        aes_meta_out.t = '0;
        aes_meta_out.t.data[SA_ID_WIDTH-1:0] =
            desc_fan[1].t.data[DESC_SA_LSB +: SA_ID_WIDTH];
        aes_meta_out.t.keep = '1;
        aes_meta_out.t.last = 1'b1;
    end
    assign aes_meta_out.tvalid = desc_fan[1].tvalid;
    assign desc_fan[1].tready  = aes_meta_out.tready;

    assign tx_desc_out.t       = desc_fan[2].t;
    assign tx_desc_out.tvalid  = desc_fan[2].tvalid;
    assign desc_fan[2].tready  = tx_desc_out.tready;

    assign aes_packet_out.t      = combined_axis.t;
    assign aes_packet_out.tvalid = combined_axis.tvalid;
    assign combined_axis.tready  = aes_packet_out.tready;

    // Tunnel table AXI-Lite control
    // -----------------------------
    logic tunnel_bvalid_r;
    logic tunnel_rvalid_r;

    logic tunnel_write_fire;
    logic tunnel_read_fire;

    typedef enum logic [1:0] {
        TUNNEL_MGMT_IDLE,
        TUNNEL_MGMT_READ,
        TUNNEL_MGMT_WRITE
    } tunnel_mgmt_state_t;

    tunnel_mgmt_state_t tunnel_mgmt_state_r;
    logic [1:0] tunnel_mgmt_word_r;
    logic [31:0] tunnel_mgmt_wdata_r;
    logic tunnel_mgmt_in_range_r;

    assign tunnel_ctrl.aw_ready = tunnel_ctrl.w_valid && !tunnel_bvalid_r &&
                                  (tunnel_mgmt_state_r == TUNNEL_MGMT_IDLE);
    assign tunnel_ctrl.w_ready  = tunnel_ctrl.aw_valid && !tunnel_bvalid_r &&
                                  (tunnel_mgmt_state_r == TUNNEL_MGMT_IDLE);
    assign tunnel_write_fire =
        tunnel_ctrl.aw_valid && tunnel_ctrl.aw_ready &&
        tunnel_ctrl.w_valid && tunnel_ctrl.w_ready;

    assign tunnel_ctrl.b_valid = tunnel_bvalid_r;
    assign tunnel_ctrl.b.resp  = '0;
    assign tunnel_ctrl.b.user  = '0;

    assign tunnel_ctrl.ar_ready = !tunnel_rvalid_r;
    assign tunnel_read_fire = tunnel_ctrl.ar_valid && tunnel_ctrl.ar_ready;
    assign tunnel_ctrl.r_valid = tunnel_rvalid_r;
    assign tunnel_ctrl.r.data  = '0;
    assign tunnel_ctrl.r.resp  = '0;
    assign tunnel_ctrl.r.user  = '0;

    always_comb begin
        tunnel_mgmt_write_en = 1'b0;
        tunnel_mgmt_write_data = tunnel_mgmt_read_data;

        if (tunnel_mgmt_state_r == TUNNEL_MGMT_WRITE && tunnel_mgmt_in_range_r) begin
            unique case (tunnel_mgmt_word_r)
                2'd0: begin
                    tunnel_mgmt_write_en = 1'b1;
                    tunnel_mgmt_write_data[TUNNEL_VALID_BIT] = tunnel_mgmt_wdata_r[0];
                end
                2'd1: begin
                    tunnel_mgmt_write_en = 1'b1;
                    tunnel_mgmt_write_data[TUNNEL_SRC_LSB +: 32] = tunnel_mgmt_wdata_r;
                end
                2'd2: begin
                    tunnel_mgmt_write_en = 1'b1;
                    tunnel_mgmt_write_data[TUNNEL_DST_LSB +: 32] = tunnel_mgmt_wdata_r;
                end
                default: begin
                end
            endcase
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            tunnel_bvalid_r <= 1'b0;
            tunnel_rvalid_r <= 1'b0;
            tunnel_mgmt_state_r <= TUNNEL_MGMT_IDLE;
            tunnel_mgmt_addr_r <= '0;
            tunnel_mgmt_word_r <= '0;
            tunnel_mgmt_wdata_r <= '0;
            tunnel_mgmt_in_range_r <= 1'b0;
        end else begin
            if (tunnel_bvalid_r && tunnel_ctrl.b_ready) begin
                tunnel_bvalid_r <= 1'b0;
            end
            if (tunnel_rvalid_r && tunnel_ctrl.r_ready) begin
                tunnel_rvalid_r <= 1'b0;
            end
            if (tunnel_read_fire) begin
                tunnel_rvalid_r <= 1'b1;
            end

            unique case (tunnel_mgmt_state_r)
                TUNNEL_MGMT_IDLE: begin
                    if (tunnel_write_fire) begin
                        tunnel_mgmt_addr_r <=
                            tunnel_ctrl.aw.addr[SA_ID_WIDTH+3:4];
                        tunnel_mgmt_word_r <= tunnel_ctrl.aw.addr[3:2];
                        tunnel_mgmt_wdata_r <= tunnel_ctrl.w.data;
                        tunnel_mgmt_in_range_r <=
                            ((tunnel_ctrl.aw.addr >> 4) < SA_TABLE_DEPTH);
                        tunnel_mgmt_state_r <= TUNNEL_MGMT_READ;
                    end
                end
                TUNNEL_MGMT_READ: begin
                    tunnel_mgmt_state_r <= TUNNEL_MGMT_WRITE;
                end
                TUNNEL_MGMT_WRITE: begin
                    tunnel_bvalid_r <= 1'b1;
                    tunnel_mgmt_state_r <= TUNNEL_MGMT_IDLE;
                end
                default: tunnel_mgmt_state_r <= TUNNEL_MGMT_IDLE;
            endcase
        end
    end
endmodule
