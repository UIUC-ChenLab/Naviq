`include "ifc_axis.sv"
`include "parser_pkg.sv"
import parser_pkg::*;

module l3_parser #(
    parameter int DATA_WIDTH  = 512,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8,
    parameter logic [15:0] IPV4_ETHERTYPE = 16'h0800
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis_packet_in,
    ifc_axis.slave  s_axis_l2_header_in,
    ifc_axis.master m_axis_header_out,
    ifc_axis.master m_axis_payload_out);

    localparam int L3_W = parser_pkg::L3_HDR_AXIS_BITS;
    localparam int TDEST_WIDTH = 1;
    localparam int TID_WIDTH = 1;
    localparam int TUSER_WIDTH = 1;
    localparam int ROUTE_IPV4  = 0;
    localparam int ROUTE_OTHER = 1;

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_packet_in (.axis_aclk(clk)), u_payload_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(parser_pkg::L2_HDR_AXIS_BITS), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_l2_header_in (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_header_out (.axis_aclk(clk));

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_packet_in_rs (
        .clk(clk), .resetn(resetn), .s_axis(s_axis_packet_in), .m_axis(u_packet_in)
    );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b1),
                .MODE("CONSERVATIVE")) u_l2_header_in_rs (
        .clk(clk), .resetn(resetn), .s_axis(s_axis_l2_header_in), .m_axis(u_l2_header_in)
    );

    parser_pkg::l2_hdr_axis_t l2_hdr;
    assign l2_hdr = parser_pkg::l2_hdr_axis_t'(u_l2_header_in.t.data);

    logic route_sel_c;
    assign route_sel_c = !((l2_hdr.status == parser_pkg::PARSER_STATUS_OK)
        && (l2_hdr.ethertype == IPV4_ETHERTYPE));

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_in [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_hdr_raw [2] (.axis_aclk(clk)), u_branch_hdr [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_hdr_q [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_payload_raw [2] (.axis_aclk(clk)), u_branch_payload [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_payload_q [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_payload_mux_in [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L3_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_hdr_to_q [2] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_payload_to_q [2] (.axis_aclk(clk));

    parser_pkg::l3_hdr_axis_t other_hdr_value;
    always_comb begin
        other_hdr_value = '0;
        other_hdr_value.status = parser_pkg::PARSER_STATUS_OTHER;
        other_hdr_value.kind = parser_pkg::L3_KIND_OTHER;
        other_hdr_value.ethertype = l2_hdr.ethertype;
    end

    ipv4_parser #(
        .DATA_WIDTH(DATA_WIDTH),
        .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT),
        .ETHERTYPE(IPV4_ETHERTYPE)
    ) u_ipv4_parser (
        .clk(clk), .resetn(resetn), .s_axis_packet_in(u_branch_in[ROUTE_IPV4]),
        .m_axis_header_out(u_branch_hdr_raw[ROUTE_IPV4]),
        .m_axis_payload_out(u_branch_payload_raw[ROUTE_IPV4])
    );

    // Unsupported L3 packets pass through unchanged with a packet-aligned tagged header.
    logic other_in_packet_r;
    logic other_first;
    logic other_fire;
    assign other_first = !other_in_packet_r;
    assign other_fire = u_branch_in[ROUTE_OTHER].tvalid && u_branch_in[ROUTE_OTHER].tready;

    always_comb begin
        u_branch_hdr_raw[ROUTE_OTHER].t = '0;
        u_branch_hdr_raw[ROUTE_OTHER].t.data = other_hdr_value;
        u_branch_hdr_raw[ROUTE_OTHER].t.keep = '1;
        u_branch_hdr_raw[ROUTE_OTHER].t.last = 1'b1;
        u_branch_hdr_raw[ROUTE_OTHER].tvalid = u_branch_in[ROUTE_OTHER].tvalid
            && other_first && u_branch_payload_raw[ROUTE_OTHER].tready;

        u_branch_payload_raw[ROUTE_OTHER].t = u_branch_in[ROUTE_OTHER].t;
        u_branch_payload_raw[ROUTE_OTHER].tvalid = u_branch_in[ROUTE_OTHER].tvalid
            && (!other_first || u_branch_hdr_raw[ROUTE_OTHER].tready);

        u_branch_in[ROUTE_OTHER].tready = u_branch_payload_raw[ROUTE_OTHER].tready
            && (!other_first || u_branch_hdr_raw[ROUTE_OTHER].tready);
    end

    always_ff @(posedge clk) begin
        if (!resetn)
            other_in_packet_r <= 1'b0;
        else if (other_fire)
            other_in_packet_r <= !u_branch_in[ROUTE_OTHER].t.last;
    end

    axis_fifo #(
        .DEPTH    (4),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_ipv4_header_timing_q (
        .clk(clk), .resetn(resetn), .s_axis(u_branch_hdr_raw[ROUTE_IPV4]),
        .m_axis(u_branch_hdr[ROUTE_IPV4])
    );

    axis_fifo #(
        .DEPTH    (4),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_ipv4_payload_timing_q (
        .clk(clk), .resetn(resetn), .s_axis(u_branch_payload_raw[ROUTE_IPV4]),
        .m_axis(u_branch_payload[ROUTE_IPV4])
    );

    axis_fifo #(
        .DEPTH    (2),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_other_header_timing_q (
        .clk(clk), .resetn(resetn), .s_axis(u_branch_hdr_raw[ROUTE_OTHER]),
        .m_axis(u_branch_hdr[ROUTE_OTHER])
    );

    assign u_branch_payload[ROUTE_OTHER].t = u_branch_payload_raw[ROUTE_OTHER].t;
    assign u_branch_payload[ROUTE_OTHER].tvalid = u_branch_payload_raw[ROUTE_OTHER].tvalid;
    assign u_branch_payload_raw[ROUTE_OTHER].tready = u_branch_payload[ROUTE_OTHER].tready;

    typedef enum logic {WAIT_META, STREAM_PACKET} state_t;
    state_t state_r;
    logic active_route_r;
    logic first_fire;
    logic branch_ready_c;

    ifc_axis #(.DATA_WIDTH(8), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_hdr_route_in (.axis_aclk(clk)), u_hdr_route_out (.axis_aclk(clk)),
        u_payload_route_in (.axis_aclk(clk)), u_payload_route_out (.axis_aclk(clk)),
        u_payload_route_select (.axis_aclk(clk));

    assign branch_ready_c = (state_r == WAIT_META)
        ? (route_sel_c ? u_branch_in[ROUTE_OTHER].tready : u_branch_in[ROUTE_IPV4].tready)
        : (active_route_r ? u_branch_in[ROUTE_OTHER].tready : u_branch_in[ROUTE_IPV4].tready);

    assign first_fire = (state_r == WAIT_META) && u_packet_in.tvalid && u_l2_header_in.tvalid
        && branch_ready_c;

    assign u_packet_in.tready = (state_r == WAIT_META)
        ? (u_l2_header_in.tvalid && branch_ready_c)
        : branch_ready_c;
    assign u_l2_header_in.tready = first_fire;

    for (genvar i = 0; i < 2; i++) begin : g_branch_drive
        assign u_branch_in[i].t = u_packet_in.t;
        assign u_branch_in[i].tvalid = u_packet_in.tvalid && (
            (state_r == WAIT_META && u_l2_header_in.tvalid && route_sel_c == (i == ROUTE_OTHER))
            || (state_r == STREAM_PACKET && active_route_r == (i == ROUTE_OTHER)));
    end

    logic [1:0] hdr_route_req;
    logic [1:0] payload_route_req;
    logic [1:0] payload_in_packet_r;
    logic [1:0] payload_to_q_fire;
    logic [1:0] payload_to_q_last;

    for (genvar i = 0; i < 2; i++) begin : g_output_q
        assign u_branch_hdr_to_q[i].t = u_branch_hdr[i].t;
        assign u_branch_hdr_to_q[i].tvalid = u_branch_hdr[i].tvalid && u_hdr_route_in.tready;
        assign u_branch_hdr[i].tready = u_branch_hdr_to_q[i].tready && u_hdr_route_in.tready;
        assign hdr_route_req[i] = u_branch_hdr[i].tvalid && u_branch_hdr_to_q[i].tready;

        assign u_branch_payload_to_q[i].t = u_branch_payload[i].t;
        assign u_branch_payload_to_q[i].tvalid = u_branch_payload[i].tvalid
            && (payload_in_packet_r[i] || u_payload_route_in.tready);
        assign u_branch_payload[i].tready = u_branch_payload_to_q[i].tready
            && (payload_in_packet_r[i] || u_payload_route_in.tready);
        assign payload_route_req[i] = u_branch_payload[i].tvalid
            && u_branch_payload_to_q[i].tready && !payload_in_packet_r[i];
        assign payload_to_q_fire[i] = u_branch_payload_to_q[i].tvalid && u_branch_payload_to_q[i].tready;
        assign payload_to_q_last[i] = u_branch_payload_to_q[i].t.last;

        axis_fifo #(
            .DEPTH    (4),
            .USE_BRAM (1'b0),
            .MODE     ("CONSERVATIVE")
        ) u_hdr_q (
            .clk(clk), .resetn(resetn), .s_axis(u_branch_hdr_to_q[i]), .m_axis(u_branch_hdr_q[i])
        );
        axis_fifo #(
            .DEPTH            (4),
            .USE_BRAM         (1'b0),
            .EXTRA_OUTPUT_REG (1'b1),
            .MODE             ("CONSERVATIVE")
        ) u_payload_q (
            .clk(clk), .resetn(resetn), .s_axis(u_branch_payload_to_q[i]), .m_axis(u_branch_payload_q[i])
        );
    end

    always_comb begin
        u_hdr_route_in.t = '0;
        u_hdr_route_in.t.data[0] = hdr_route_req[ROUTE_OTHER];
        u_hdr_route_in.t.keep = '1;
        u_hdr_route_in.t.last = 1'b1;
        u_hdr_route_in.tvalid = |hdr_route_req;

        u_payload_route_in.t = '0;
        u_payload_route_in.t.data[0] = payload_route_req[ROUTE_OTHER];
        u_payload_route_in.t.keep = '1;
        u_payload_route_in.t.last = 1'b1;
        u_payload_route_in.tvalid = |payload_route_req;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            payload_in_packet_r <= '0;
        end else begin
            for (int i = 0; i < 2; i++) begin
                if (payload_to_q_fire[i])
                    payload_in_packet_r[i] <= !payload_to_q_last[i];
            end
        end
    end

    axis_fifo #(
        .DEPTH    (12),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_hdr_route_q (
        .clk(clk), .resetn(resetn), .s_axis(u_hdr_route_in), .m_axis(u_hdr_route_out)
    );
    axis_fifo #(
        .DEPTH    (16),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_payload_route_q (
        .clk(clk), .resetn(resetn), .s_axis(u_payload_route_in), .m_axis(u_payload_route_out)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            state_r <= WAIT_META;
            active_route_r <= 1'b0;
        end else if (u_packet_in.tvalid && u_packet_in.tready) begin
            if (state_r == WAIT_META) begin
                active_route_r <= route_sel_c;
                state_r <= u_packet_in.t.last ? WAIT_META : STREAM_PACKET;
            end else if (u_packet_in.t.last) begin
                state_r <= WAIT_META;
            end
        end
    end

    logic hdr_route;
    assign hdr_route = u_hdr_route_out.t.data[0];

    always_comb begin
        u_header_out.t = hdr_route ? u_branch_hdr_q[ROUTE_OTHER].t : u_branch_hdr_q[ROUTE_IPV4].t;
        u_header_out.tvalid = u_hdr_route_out.tvalid
            && (hdr_route ? u_branch_hdr_q[ROUTE_OTHER].tvalid : u_branch_hdr_q[ROUTE_IPV4].tvalid);
        u_branch_hdr_q[ROUTE_IPV4].tready = u_header_out.tready && u_hdr_route_out.tvalid
            && !hdr_route && u_branch_hdr_q[ROUTE_IPV4].tvalid;
        u_branch_hdr_q[ROUTE_OTHER].tready = u_header_out.tready && u_hdr_route_out.tvalid
            && hdr_route && u_branch_hdr_q[ROUTE_OTHER].tvalid;
        u_hdr_route_out.tready = u_header_out.tready && u_header_out.tvalid;
    end

    logic payload_route_select;
    logic payload_out_fire;
    logic payload_out_last_fire;

    assign payload_out_fire = u_payload_out.tvalid && u_payload_out.tready;
    assign payload_out_last_fire = payload_out_fire && u_payload_out.t.last;
    assign payload_route_select = u_payload_route_select.t.data[0];
    assign u_payload_route_select.tready = payload_out_last_fire;

    axis_fifo #(
        .DEPTH    (4),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_payload_route_select_q (
        .clk(clk), .resetn(resetn), .s_axis(u_payload_route_out), .m_axis(u_payload_route_select)
    );

    for (genvar i = 0; i < 2; i++) begin : g_payload_mux_gate
        assign u_payload_mux_in[i].t = u_branch_payload_q[i].t;
        assign u_payload_mux_in[i].tvalid = u_payload_route_select.tvalid && u_branch_payload_q[i].tvalid;
        assign u_branch_payload_q[i].tready = u_payload_route_select.tvalid && u_payload_mux_in[i].tready;
    end

    axis_packet_mux #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
        .TUSER_WIDTH(TUSER_WIDTH), .NUM_SLAVES(2)
    ) u_payload_mux (
        .clk(clk), .resetn(resetn), .select(payload_route_select),
        .s_axis(u_payload_mux_in), .m_axis(u_payload_out)
    );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_header_out_rs (
        .clk(clk), .resetn(resetn), .s_axis(u_header_out), .m_axis(m_axis_header_out)
    );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_payload_out_rs (
        .clk(clk), .resetn(resetn), .s_axis(u_payload_out), .m_axis(m_axis_payload_out)
    );

endmodule
