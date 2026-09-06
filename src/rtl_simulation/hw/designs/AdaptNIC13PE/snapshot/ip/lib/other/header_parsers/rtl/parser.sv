`include "ifc_axis.sv"
`include "parser_pkg.sv"
import parser_pkg::*;

module parser #(
    parameter int DATA_WIDTH  = 512,
    parameter bit SKIP_L2 = 1'b0,
    parameter bit SKIP_L3 = 1'b0,
    parameter bit SKIP_L4 = 1'b0,
    parameter bit HEADER_ONLY = 1'b0,
    parameter bit REPACK_PAYLOAD_OUT = 1'b1,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8,
    parameter int INTER_STAGE_FIFO_DEPTH = 12,
    parameter logic [15:0] DEFAULT_ETHERTYPE = 16'h0800,
    parameter logic [7:0]  DEFAULT_L4_PROTOCOL = 8'd0
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis_packet_in,
    ifc_axis.master m_axis_l2_header_out,
    ifc_axis.master m_axis_l3_header_out,
    ifc_axis.master m_axis_l4_header_out,
    ifc_axis.master m_axis_payload_out
);

    localparam int L2_W = parser_pkg::L2_HDR_AXIS_BITS;
    localparam int L3_W = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int L4_W = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int TDEST_WIDTH = 1;
    localparam int TID_WIDTH = 1;
    localparam int TUSER_WIDTH = 1;

    initial begin
        if (INTER_STAGE_FIFO_DEPTH < 2)
            $error("parser: INTER_STAGE_FIFO_DEPTH (%0d) must be at least 2", INTER_STAGE_FIFO_DEPTH);
        if ($bits(m_axis_l2_header_out.t.data) != L2_W)
            $error("parser: m_axis_l2_header_out width mismatch");
        if ($bits(m_axis_l3_header_out.t.data) != L3_W)
            $error("parser: m_axis_l3_header_out width mismatch");
        if ($bits(m_axis_l4_header_out.t.data) != L4_W)
            $error("parser: m_axis_l4_header_out width mismatch");
        if ($bits(m_axis_payload_out.t.data) != DATA_WIDTH)
            $error("parser: m_axis_payload_out width mismatch");
    end

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_l2_payload (.axis_aclk(clk)), u_l3_in (.axis_aclk(clk)),
        u_l3_payload (.axis_aclk(clk)), u_l4_in (.axis_aclk(clk)),
        u_payload_pre_pack (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L2_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_l2_hdr_raw (.axis_aclk(clk)), u_l2_hdr_fan [2] (.axis_aclk(clk)),
        u_l2_hdr_to_l3_pre (.axis_aclk(clk)), u_l2_hdr_to_l3 (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_l3_hdr_raw (.axis_aclk(clk)), u_l3_hdr_fan [2] (.axis_aclk(clk)),
        u_l3_hdr_to_l4_pre (.axis_aclk(clk)), u_l3_hdr_to_l4 (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_l4_hdr_raw (.axis_aclk(clk));

    localparam parser_pkg::l2_hdr_axis_t DEFAULT_L2_HDR_VALUE = '{
        status: parser_pkg::PARSER_STATUS_OK,
        kind: parser_pkg::L2_KIND_ETHERNET,
        header_len: 16'd0,
        ethertype: DEFAULT_ETHERTYPE,
        ethernet: '0
    };
    localparam parser_pkg::l3_hdr_axis_t DEFAULT_L3_HDR_VALUE = '{
        status: parser_pkg::PARSER_STATUS_OK,
        kind: parser_pkg::L3_KIND_IPV4,
        header_len: 16'd0,
        ethertype: DEFAULT_ETHERTYPE,
        protocol: DEFAULT_L4_PROTOCOL,
        pad: '0,
        ipv4: '0
    };

    generate
        if (!SKIP_L2) begin : g_l2
            l2_parser #(
                .DATA_WIDTH(DATA_WIDTH),
                .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT)
            ) u_l2_parser (
                .clk(clk), .resetn(resetn), .s_axis_packet_in(s_axis_packet_in),
                .m_axis_header_out(u_l2_hdr_raw), .m_axis_payload_out(u_l2_payload)
            );

            axis_multicast #(
                .DATA_WIDTH(L2_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
                .TUSER_WIDTH(TUSER_WIDTH), .NUM_DESTS(2)
            ) u_l2_header_fanout (
                .clk(clk), .resetn(resetn), .s_axis(u_l2_hdr_raw), .m_axis(u_l2_hdr_fan)
            );

            assign m_axis_l2_header_out.t = u_l2_hdr_fan[0].t;
            assign m_axis_l2_header_out.tvalid = u_l2_hdr_fan[0].tvalid;
            assign u_l2_hdr_fan[0].tready = m_axis_l2_header_out.tready;

            assign u_l2_hdr_to_l3_pre.t = u_l2_hdr_fan[1].t;
            assign u_l2_hdr_to_l3_pre.tvalid = u_l2_hdr_fan[1].tvalid;
            assign u_l2_hdr_fan[1].tready = u_l2_hdr_to_l3_pre.tready;

            axis_fifo #(
                .DEPTH            (24),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_l2_header_to_l3_q (
                .clk(clk), .resetn(resetn), .s_axis(u_l2_hdr_to_l3_pre), .m_axis(u_l2_hdr_to_l3)
            );

            axis_fifo #(
                .DEPTH            (INTER_STAGE_FIFO_DEPTH),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_l2_payload_to_l3_q (
                .clk(clk), .resetn(resetn), .s_axis(u_l2_payload), .m_axis(u_l3_in)
            );
        end else begin : g_skip_l2
            ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
                u_skip_l2_fan [2] (.axis_aclk(clk)),
                u_skip_l2_payload_sink (.axis_aclk(clk));

            axis_multicast #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
                .TUSER_WIDTH(TUSER_WIDTH), .NUM_DESTS(2)
            ) u_skip_l2_input_fanout (
                .clk(clk), .resetn(resetn), .s_axis(s_axis_packet_in), .m_axis(u_skip_l2_fan)
            );

            axis_fifo #(
                .DEPTH            (INTER_STAGE_FIFO_DEPTH),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_skip_l2_data_q (
                .clk(clk), .resetn(resetn), .s_axis(u_skip_l2_fan[0]), .m_axis(u_l3_in)
            );

            other_parser #(
                .DATA_WIDTH(DATA_WIDTH), .HEADER_WIDTH(L2_W),
                .HEADER_VALUE(DEFAULT_L2_HDR_VALUE)
            ) u_default_l2_meta (
                .clk(clk), .resetn(resetn), .s_axis_packet_in(u_skip_l2_fan[1]),
                .m_axis_header_out(u_l2_hdr_to_l3_pre),
                .m_axis_payload_out(u_skip_l2_payload_sink)
            );
            assign u_skip_l2_payload_sink.tready = 1'b1;

            axis_fifo #(
                .DEPTH            (INTER_STAGE_FIFO_DEPTH),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_skip_l2_header_to_l3_q (
                .clk(clk), .resetn(resetn), .s_axis(u_l2_hdr_to_l3_pre), .m_axis(u_l2_hdr_to_l3)
            );

            always_comb begin
                m_axis_l2_header_out.t = '0;
                m_axis_l2_header_out.tvalid = 1'b0;
            end
        end

        if (!SKIP_L3) begin : g_l3
            l3_parser #(
                .DATA_WIDTH(DATA_WIDTH),
                .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT),
                .IPV4_ETHERTYPE(DEFAULT_ETHERTYPE)
            ) u_l3_parser (
                .clk(clk), .resetn(resetn), .s_axis_packet_in(u_l3_in),
                .s_axis_l2_header_in(u_l2_hdr_to_l3), .m_axis_header_out(u_l3_hdr_raw),
                .m_axis_payload_out(u_l3_payload)
            );

            axis_multicast #(
                .DATA_WIDTH(L3_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
                .TUSER_WIDTH(TUSER_WIDTH), .NUM_DESTS(2)
            ) u_l3_header_fanout (
                .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_raw), .m_axis(u_l3_hdr_fan)
            );

            assign m_axis_l3_header_out.t = u_l3_hdr_fan[0].t;
            assign m_axis_l3_header_out.tvalid = u_l3_hdr_fan[0].tvalid;
            assign u_l3_hdr_fan[0].tready = m_axis_l3_header_out.tready;

            assign u_l3_hdr_to_l4_pre.t = u_l3_hdr_fan[1].t;
            assign u_l3_hdr_to_l4_pre.tvalid = u_l3_hdr_fan[1].tvalid;
            assign u_l3_hdr_fan[1].tready = u_l3_hdr_to_l4_pre.tready;

            axis_fifo #(
                .DEPTH            (24),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_l3_header_to_l4_q (
                .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_to_l4_pre), .m_axis(u_l3_hdr_to_l4)
            );

            axis_fifo #(
                .DEPTH            (INTER_STAGE_FIFO_DEPTH),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_l3_payload_to_l4_q (
                .clk(clk), .resetn(resetn), .s_axis(u_l3_payload), .m_axis(u_l4_in)
            );
        end else begin : g_skip_l3
            ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
                u_skip_l3_fan [2] (.axis_aclk(clk));
            ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
                u_skip_l3_payload_sink (.axis_aclk(clk));

            axis_multicast #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
                .TUSER_WIDTH(TUSER_WIDTH), .NUM_DESTS(2)
            ) u_skip_l3_input_fanout (
                .clk(clk), .resetn(resetn), .s_axis(u_l3_in), .m_axis(u_skip_l3_fan)
            );

            axis_fifo #(
                .DEPTH            (INTER_STAGE_FIFO_DEPTH),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_skip_l3_data_q (
                .clk(clk), .resetn(resetn), .s_axis(u_skip_l3_fan[0]), .m_axis(u_l4_in)
            );

            other_parser #(
                .DATA_WIDTH(DATA_WIDTH), .HEADER_WIDTH(L3_W), .HEADER_VALUE(DEFAULT_L3_HDR_VALUE)
            ) u_default_l3_meta (
                .clk(clk), .resetn(resetn), .s_axis_packet_in(u_skip_l3_fan[1]),
                .m_axis_header_out(u_l3_hdr_to_l4_pre), .m_axis_payload_out(u_skip_l3_payload_sink)
            );
            assign u_skip_l3_payload_sink.tready = 1'b1;

            axis_fifo #(
                .DEPTH            (INTER_STAGE_FIFO_DEPTH),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_skip_l3_header_to_l4_q (
                .clk(clk), .resetn(resetn), .s_axis(u_l3_hdr_to_l4_pre), .m_axis(u_l3_hdr_to_l4)
            );

            always_comb begin
                m_axis_l3_header_out.t = '0;
                m_axis_l3_header_out.tvalid = 1'b0;
            end
        end

        if (!SKIP_L4) begin : g_l4
            l4_parser #(
                .DATA_WIDTH(DATA_WIDTH),
                .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT),
                .HEADER_ONLY(HEADER_ONLY)
            ) u_l4_parser (
                .clk(clk), .resetn(resetn), .s_axis_packet_in(u_l4_in),
                .s_axis_l3_header_in(u_l3_hdr_to_l4), .m_axis_header_out(u_l4_hdr_raw),
                .m_axis_payload_out(u_payload_pre_pack)
            );

            axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                        .MODE("CONSERVATIVE")) u_l4_header_rs (
                .clk(clk), .resetn(resetn), .s_axis(u_l4_hdr_raw), .m_axis(m_axis_l4_header_out)
            );
        end else begin : g_skip_l4
            if (!HEADER_ONLY) begin : g_payload_passthrough
                axis_fifo #(.DEPTH(8), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                            .MODE("CONSERVATIVE")) u_skip_l4_payload_rs (
                    .clk(clk), .resetn(resetn), .s_axis(u_l4_in),
                    .m_axis(u_payload_pre_pack)
                );
            end else begin : g_payload_sink
                assign u_l4_in.tready = 1'b1;
                always_comb begin
                    u_payload_pre_pack.t = '0;
                    u_payload_pre_pack.tvalid = 1'b0;
                end
            end

            always_comb begin
                m_axis_l4_header_out.t = '0;
                m_axis_l4_header_out.tvalid = 1'b0;
            end
            assign u_l3_hdr_to_l4.tready = 1'b1;
        end
    endgenerate


    generate
        if (HEADER_ONLY) begin : g_header_only_payload_out
            always_comb begin
                m_axis_payload_out.t = '0;
                m_axis_payload_out.tvalid = 1'b0;
            end
        end else if (REPACK_PAYLOAD_OUT) begin : g_repack_payload_out
            axis_fragment_packer #(
                .DATA_WIDTH  (DATA_WIDTH),
                .PAGE_COUNT  (FRAGMENT_PACKER_PAGE_COUNT),
                .FIFO_MODE   ("CONSERVATIVE")
            ) u_payload_final_packer (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (u_payload_pre_pack),
                .m_axis (m_axis_payload_out)
            );
        end else begin : g_strip_only_payload_out
            axis_fifo #(
                .DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")
            ) u_payload_out_rs (
                .clk    (clk),
                .resetn (resetn),
                .s_axis (u_payload_pre_pack),
                .m_axis (m_axis_payload_out)
            );
        end
    endgenerate

endmodule
