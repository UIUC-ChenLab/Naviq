`ifndef BUILD_PSEUDO_HEADER_SV
`define BUILD_PSEUDO_HEADER_SV

`include "ifc_axis.sv"
`include "parser_pkg.sv"
`include "axi_struct_macros.svh"
import parser_pkg::*;

module checksum_axis_byte_source #(
    parameter int DATA_WIDTH       = 512,
    parameter int MAX_BYTES        = 64,
    parameter int BYTE_COUNT_WIDTH = $clog2(MAX_BYTES + 1)
) (
    input logic clk,
    input logic resetn,

    input  logic [MAX_BYTES*8-1:0]        s_data,
    input  logic [BYTE_COUNT_WIDTH-1:0]   s_byte_count,
    input  logic                          s_valid,
    output logic                          s_ready,

    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH   = DATA_WIDTH / 8;
    localparam int OFFSET_WIDTH = (MAX_BYTES <= 1) ? 1 : $clog2(MAX_BYTES + 1);

    logic [MAX_BYTES*8-1:0]      data_r;
    logic [BYTE_COUNT_WIDTH-1:0] byte_count_r;
    logic [OFFSET_WIDTH-1:0]     offset_r;
    logic                        active_r;
    logic                        output_last;
    logic                        output_fire;
    logic                        input_fire;

    initial begin
        if (DATA_WIDTH < 16 || DATA_WIDTH % 8 != 0 || (DATA_WIDTH & (DATA_WIDTH - 1)) != 0)
            $error("checksum_axis_byte_source: DATA_WIDTH must be a byte-aligned power of two >= 16");
        if (MAX_BYTES < 1)
            $error("checksum_axis_byte_source: MAX_BYTES must be at least 1");
        if ($bits(m_axis.t.data) != DATA_WIDTH)
            $error("checksum_axis_byte_source: m_axis data width mismatch");
    end

    assign output_last = (unsigned'(offset_r) + KEEP_WIDTH) >= unsigned'(byte_count_r);
    assign output_fire = active_r && m_axis.tready;
    assign s_ready     = !active_r || (output_fire && output_last);
    assign input_fire  = s_valid && s_ready;

    always_comb begin
        m_axis.t       = '0;
        m_axis.t.id    = '0;
        m_axis.t.dest  = '0;
        m_axis.t.user  = '0;
        m_axis.t.last  = output_last;
        m_axis.tvalid  = active_r;

        for (int i = 0; i < KEEP_WIDTH; i++) begin
            int unsigned src_idx;
            src_idx = unsigned'(offset_r) + i;
            if (src_idx < MAX_BYTES && src_idx < unsigned'(byte_count_r)) begin
                m_axis.t.data[8*i +: 8] = data_r[8*src_idx +: 8];
                m_axis.t.keep[i] = 1'b1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            active_r <= 1'b0;
        end else begin
            if (output_fire && !output_last) begin
                offset_r <= offset_r + OFFSET_WIDTH'(KEEP_WIDTH);
            end else if (output_fire && output_last && !input_fire) begin
                active_r <= 1'b0;
                offset_r <= '0;
            end

            if (input_fire) begin
                active_r     <= 1'b1;
                offset_r     <= '0;
                data_r       <= s_data;
                byte_count_r <= s_byte_count;
            end
        end
    end

endmodule

// Stage one: native L3/L4 parser headers produce one pseudo-header beat and
// one strip-byte-count beat.
// One header beat (t.last) produces one pseudo-header beat + one strip-byte-count beat; outputs pass through
// internal synchronization + small FF FIFOs to the module masters.
module build_pseudo_hdr_stage_one #(
    parameter int PSEUDO_DATA_WIDTH     = 512,
    parameter int TOTAL_HDR_BYTES_WIDTH = 16

) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_l3_header_in,
    ifc_axis.slave  s_axis_l4_header_in,
    ifc_axis.master m_axis_pseudo_hdr_out,
    ifc_axis.master m_axis_total_hdr_bytes_out
);

    localparam int L3_HDR_WIDTH = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_WIDTH = parser_pkg::L4_HDR_AXIS_BITS;

    ifc_axis #(.DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_header_join_q_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_header_join_q_out (.axis_aclk(clk));

    axis_ff_fifo_cut #(.DEPTH(4)) u_l3_header_join_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_l3_header_in),
        .m_axis (u_l3_header_join_q_out)
    );

    axis_ff_fifo_cut #(.DEPTH(4)) u_l4_header_join_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_l4_header_in),
        .m_axis (u_l4_header_join_q_out)
    );

    localparam int PSEUDO_MAX_BYTES = parser_pkg::TCP_PSEUDO_HDR_BITS / 8;
    localparam int PSEUDO_COUNT_W   = $clog2(PSEUDO_MAX_BYTES + 1);
    localparam int TCP_PSEUDO_BYTES = parser_pkg::TCP_PSEUDO_HDR_BITS / 8;
    localparam int UDP_PSEUDO_BYTES = parser_pkg::UDP_PSEUDO_HDR_BITS / 8;

    initial begin
        if ($bits(s_axis_l3_header_in.t.data) != L3_HDR_WIDTH)
            $error("build_pseudo_hdr_stage_one: s_axis_l3_header_in width mismatch");
        if ($bits(s_axis_l4_header_in.t.data) != L4_HDR_WIDTH)
            $error("build_pseudo_hdr_stage_one: s_axis_l4_header_in width mismatch");
        if ($bits(m_axis_total_hdr_bytes_out.t.data) != TOTAL_HDR_BYTES_WIDTH)
            $error("build_pseudo_hdr_stage_one: total_hdr m_axis data width mismatch");
        if ($bits(m_axis_pseudo_hdr_out.t.data) != PSEUDO_DATA_WIDTH)
            $error("build_pseudo_hdr_stage_one: pseudo m_axis data width mismatch");
        if (TOTAL_HDR_BYTES_WIDTH > PSEUDO_DATA_WIDTH)
            $error("build_pseudo_hdr_stage_one: TOTAL_HDR_BYTES_WIDTH must be <= pseudo output width");
    end

    ipv4_hdr_t ipv4_hdr;
    tcp_hdr_t  tcp_hdr;
    udp_hdr_t  udp_hdr;

    l3_hdr_axis_t l3_hdr;
    l4_hdr_axis_t l4_hdr;
    assign l3_hdr = l3_hdr_axis_t'(u_l3_header_join_q_out.t.data);
    assign l4_hdr = l4_hdr_axis_t'(u_l4_header_join_q_out.t.data);
    assign ipv4_hdr = l3_hdr.ipv4;
    assign tcp_hdr  = l4_hdr.tcp;
    assign udp_hdr  = l4_hdr.udp;

    udp_pseudo_hdr_t udp_pseudo_hdr;
    tcp_pseudo_hdr_t tcp_pseudo_hdr;

    logic [TOTAL_HDR_BYTES_WIDTH-1:0] strip_hdr_bytes_comb;

    logic is_tcp;
    logic [PSEUDO_MAX_BYTES*8-1:0] pseudo_wire_data;
    logic [PSEUDO_COUNT_W-1:0] pseudo_wire_bytes;

    always_comb begin
        udp_pseudo_hdr = '0;
        tcp_pseudo_hdr = '0;
        strip_hdr_bytes_comb = {ipv4_hdr.ihl, 2'b00} + 16'd8;
        pseudo_wire_data = '0;
        pseudo_wire_bytes = PSEUDO_COUNT_W'(UDP_PSEUDO_BYTES);

        udp_pseudo_hdr.src_addr      = ipv4_hdr.src_addr;
        udp_pseudo_hdr.dst_addr      = ipv4_hdr.dst_addr;
        udp_pseudo_hdr.zero          = 8'h00;
        udp_pseudo_hdr.protocol      = ipv4_hdr.protocol;
        udp_pseudo_hdr.pseudo_length = udp_hdr.length;
        udp_pseudo_hdr.src_port      = udp_hdr.src_port;
        udp_pseudo_hdr.dst_port      = udp_hdr.dst_port;
        udp_pseudo_hdr.udp_length    = udp_hdr.length;
        udp_pseudo_hdr.checksum      = 16'h0000;

        tcp_pseudo_hdr.src_addr    = ipv4_hdr.src_addr;
        tcp_pseudo_hdr.dst_addr    = ipv4_hdr.dst_addr;
        tcp_pseudo_hdr.zeroes      = 8'h00;
        tcp_pseudo_hdr.protocol    = ipv4_hdr.protocol;
        tcp_pseudo_hdr.length      = ipv4_hdr.total_length - {ipv4_hdr.ihl, 2'b00};
        tcp_pseudo_hdr.src_port    = tcp_hdr.src_port;
        tcp_pseudo_hdr.dst_port    = tcp_hdr.dst_port;
        tcp_pseudo_hdr.seq_num     = tcp_hdr.seq_num;
        tcp_pseudo_hdr.ack_num     = tcp_hdr.ack_num;
        tcp_pseudo_hdr.data_offset = tcp_hdr.data_offset;
        tcp_pseudo_hdr.reserved    = tcp_hdr.reserved;
        tcp_pseudo_hdr.ns          = tcp_hdr.ns;
        tcp_pseudo_hdr.cwr         = tcp_hdr.cwr;
        tcp_pseudo_hdr.ece         = tcp_hdr.ece;
        tcp_pseudo_hdr.urg         = tcp_hdr.urg;
        tcp_pseudo_hdr.ack         = tcp_hdr.ack;
        tcp_pseudo_hdr.psh         = tcp_hdr.psh;
        tcp_pseudo_hdr.rst         = tcp_hdr.rst;
        tcp_pseudo_hdr.syn         = tcp_hdr.syn;
        tcp_pseudo_hdr.fin         = tcp_hdr.fin;
        tcp_pseudo_hdr.window      = tcp_hdr.window;
        tcp_pseudo_hdr.checksum    = 16'h0000;
        tcp_pseudo_hdr.urgent_ptr  = tcp_hdr.urgent_ptr;

        is_tcp = (l4_hdr.kind == L4_KIND_TCP);

        if (is_tcp) begin
            strip_hdr_bytes_comb = {ipv4_hdr.ihl, 2'b00} + {tcp_hdr.data_offset, 2'b00};
            pseudo_wire_bytes = PSEUDO_COUNT_W'(TCP_PSEUDO_BYTES);

            pseudo_wire_data[parser_pkg::TCP_PSEUDO_HDR_BITS-1:0] = pack_tcp_pseudo_hdr_wire(tcp_pseudo_hdr);
        end else begin
            pseudo_wire_data[parser_pkg::UDP_PSEUDO_HDR_BITS-1:0] = pack_udp_pseudo_hdr_wire(udp_pseudo_hdr);
        end
    end

    // Output synchronization on pseudo + strip-count; module outputs are buffered in small FF FIFOs.
    ifc_axis #(.DATA_WIDTH(TOTAL_HDR_BYTES_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_out_hdr_bytes (.axis_aclk(clk));

    ifc_axis #(.DATA_WIDTH(PSEUDO_DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_pseudo_pre_rs (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(TOTAL_HDR_BYTES_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_bytes_pre_rs (.axis_aclk(clk));

    logic u_out_pseudo_ready;

    checksum_axis_byte_source #(
        .DATA_WIDTH       (PSEUDO_DATA_WIDTH),
        .MAX_BYTES        (PSEUDO_MAX_BYTES),
        .BYTE_COUNT_WIDTH (PSEUDO_COUNT_W)
    ) u_pseudo_source (
        .clk          (clk),
        .resetn       (resetn),
        .s_data       (pseudo_wire_data),
        .s_byte_count (pseudo_wire_bytes),
        .s_valid      (u_l3_header_join_q_out.tvalid && u_l4_header_join_q_out.tvalid && u_out_hdr_bytes.tready),
        .s_ready      (u_out_pseudo_ready),
        .m_axis       (u_pseudo_pre_rs)
    );

    assign u_out_hdr_bytes.t.data  = strip_hdr_bytes_comb;
    assign u_out_hdr_bytes.t.keep  = '1;
    assign u_out_hdr_bytes.t.last  = 1'b1;
    assign u_out_hdr_bytes.tvalid  = u_l3_header_join_q_out.tvalid && u_l4_header_join_q_out.tvalid && u_out_pseudo_ready;

    assign u_bytes_pre_rs.t.data  = u_out_hdr_bytes.t.data;
    assign u_bytes_pre_rs.t.keep  = u_out_hdr_bytes.t.keep;
    assign u_bytes_pre_rs.t.id    = u_out_hdr_bytes.t.id;
    assign u_bytes_pre_rs.t.dest  = u_out_hdr_bytes.t.dest;
    assign u_bytes_pre_rs.t.user  = u_out_hdr_bytes.t.user;
    assign u_bytes_pre_rs.t.last  = u_out_hdr_bytes.t.last;
    assign u_bytes_pre_rs.tvalid  = u_out_hdr_bytes.tvalid;
    assign u_out_hdr_bytes.tready = u_bytes_pre_rs.tready;

    assign u_l3_header_join_q_out.tready = u_l3_header_join_q_out.tvalid && u_l4_header_join_q_out.tvalid
        && u_out_pseudo_ready && u_out_hdr_bytes.tready;
    assign u_l4_header_join_q_out.tready = u_l3_header_join_q_out.tvalid && u_l4_header_join_q_out.tvalid
        && u_out_pseudo_ready && u_out_hdr_bytes.tready;

    axis_ff_fifo_cut #(.DEPTH(4)) u_reg_pseudo_out (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_pseudo_pre_rs),
        .m_axis (m_axis_pseudo_hdr_out)
    );

    axis_ff_fifo_cut #(.DEPTH(4)) u_reg_total_hdr_bytes_out (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_bytes_pre_rs),
        .m_axis (m_axis_total_hdr_bytes_out)
    );

endmodule

// UDP/TCP pseudo-header builder for checksum: native L3/L4 parser headers + payload stream.
// PACKET_DATA_WIDTH: input payload / internal combine datapath width.
// CHECKSUM_OPERANDS_WIDTH: output to checksum engine (must equal PACKET_DATA_WIDTH until operand repack exists).
module build_pseudo_hdr #(
    parameter int PACKET_DATA_WIDTH           = 512,
    parameter int CHECKSUM_OPERANDS_WIDTH     = 512,
    parameter int PACK_BYTES_BASE_STAGE_WIDTH = 32,
    parameter int TOTAL_HDR_BYTES_WIDTH       = 16,
    parameter int PSEUDO_FIFO_DEPTH           = 8,
    parameter int FRAGMENT_PACKER_PAGE_COUNT  = 8
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis_l3_header_in,
    ifc_axis.slave  s_axis_l4_header_in,
    ifc_axis.slave  s_axis_packet_in,
    ifc_axis.master m_axis_total_hdr_bytes_out,
    ifc_axis.master m_axis_checksum_operands_out
);

    localparam int L3_HDR_WIDTH = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_HDR_WIDTH = parser_pkg::L4_HDR_AXIS_BITS;
    ifc_axis #(.DATA_WIDTH(L3_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l3_header_pre_stage (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_HDR_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_l4_header_pre_stage (.axis_aclk(clk));

    axis_ff_fifo_cut #(.DEPTH(4)) u_l3_header_pre_stage_rs (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_l3_header_in),
        .m_axis (u_l3_header_pre_stage)
    );

    axis_ff_fifo_cut #(.DEPTH(4)) u_l4_header_pre_stage_rs (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_l4_header_in),
        .m_axis (u_l4_header_pre_stage)
    );

    ifc_axis #(.DATA_WIDTH(CHECKSUM_OPERANDS_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_pseudo_mid (.axis_aclk(clk));

    ifc_axis #(.DATA_WIDTH(CHECKSUM_OPERANDS_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_pseudo_q_out (.axis_aclk(clk));

    build_pseudo_hdr_stage_one #(
        .PSEUDO_DATA_WIDTH     (CHECKSUM_OPERANDS_WIDTH),
        .TOTAL_HDR_BYTES_WIDTH (TOTAL_HDR_BYTES_WIDTH)
    ) u_stage_one (
        .clk                        (clk),
        .resetn                     (resetn),
        .s_axis_l3_header_in        (u_l3_header_pre_stage),
        .s_axis_l4_header_in        (u_l4_header_pre_stage),
        .m_axis_pseudo_hdr_out      (u_pseudo_mid),
        .m_axis_total_hdr_bytes_out (m_axis_total_hdr_bytes_out)
    );

    axis_fifo #(
        .DEPTH            (PSEUDO_FIFO_DEPTH),
        .USE_BRAM         (1'b0),
        .MODE             ("CONSERVATIVE")
    ) u_pseudo_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_pseudo_mid),
        .m_axis (u_pseudo_q_out)
    );

    // Small FF FIFOs before assembly shorten the critical path into the merge stage.
    ifc_axis #(.DATA_WIDTH(PACKET_DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1),
               .TUSER_WIDTH(1)) u_payload_pre_combine (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(PACKET_DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_pseudo_pre_combine (.axis_aclk(clk));

    axis_ff_fifo_cut #(.DEPTH(4)) u_pkt_pre_strip_rs (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis_packet_in),
        .m_axis (u_payload_pre_combine)
    );

    axis_ff_fifo_cut #(.DEPTH(4)) u_pseudo_pre_combine_rs (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_pseudo_q_out),
        .m_axis (u_pseudo_pre_combine)
    );

    axis_combine_repack #(
        .FIRST_STREAM_IS_A          (1),
        .DATA_WIDTH                 (PACKET_DATA_WIDTH),
        .FRAGMENT_PACKER_PAGE_COUNT (FRAGMENT_PACKER_PAGE_COUNT)
    ) u_combine (
        .clk      (clk),
        .resetn   (resetn),
        .s_axis_a (u_pseudo_pre_combine),
        .s_axis_b (u_payload_pre_combine),
        .m_axis   (m_axis_checksum_operands_out)
    );

endmodule

`endif
