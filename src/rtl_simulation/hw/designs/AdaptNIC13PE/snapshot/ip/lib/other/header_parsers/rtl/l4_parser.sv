`include "ifc_axis.sv"
`include "parser_pkg.sv"
import parser_pkg::*;

module l4_parser #(
    parameter int DATA_WIDTH  = 512,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8,
    parameter bit HEADER_ONLY = 1'b0
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis_packet_in,
    ifc_axis.slave  s_axis_l3_header_in,
    ifc_axis.master m_axis_header_out,
    ifc_axis.master m_axis_payload_out
);

    localparam int L4_W = parser_pkg::L4_HDR_AXIS_BITS;
    localparam int TDEST_WIDTH = 1;
    localparam int TID_WIDTH = 1;
    localparam int TUSER_WIDTH = 1;
    localparam int ROUTE_TCP   = 0;
    localparam int ROUTE_UDP   = 1;
    localparam int ROUTE_OTHER = 2;

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_packet_in (.axis_aclk(clk)), u_payload_out (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(parser_pkg::L3_HDR_AXIS_BITS), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_l3_header_in (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_header_out (.axis_aclk(clk));

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_packet_in_rs (
        .clk(clk), .resetn(resetn), .s_axis(s_axis_packet_in), .m_axis(u_packet_in)
    );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b1),
                .MODE("CONSERVATIVE")) u_l3_header_in_rs (
        .clk(clk), .resetn(resetn), .s_axis(s_axis_l3_header_in), .m_axis(u_l3_header_in)
    );

    parser_pkg::l3_hdr_axis_t l3_hdr;
    logic [1:0] route_sel_c;
    assign l3_hdr = parser_pkg::l3_hdr_axis_t'(u_l3_header_in.t.data);

    always_comb begin
        route_sel_c = 2'(ROUTE_OTHER);
        if (l3_hdr.status == parser_pkg::PARSER_STATUS_OK && l3_hdr.kind == parser_pkg::L3_KIND_IPV4) begin
            if (l3_hdr.protocol == 8'd6)
                route_sel_c = 2'(ROUTE_TCP);
            else if (l3_hdr.protocol == 8'd17)
                route_sel_c = 2'(ROUTE_UDP);
        end
    end

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_in [3] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_hdr [3] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_hdr_q [3] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_payload [3] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_payload_q [3] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_payload_mux_in [3] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(L4_W), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_hdr_to_q [3] (.axis_aclk(clk));
    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        u_branch_payload_to_q [3] (.axis_aclk(clk));

    tcp_parser #(
        .DATA_WIDTH(DATA_WIDTH),
        .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT)
    ) u_tcp_parser (
        .clk(clk), .resetn(resetn), .s_axis_packet_in(u_branch_in[ROUTE_TCP]),
        .m_axis_header_out(u_branch_hdr[ROUTE_TCP]),
        .m_axis_payload_out(u_branch_payload[ROUTE_TCP])
    );

    udp_parser #(
        .DATA_WIDTH(DATA_WIDTH),
        .FRAGMENT_PACKER_PAGE_COUNT(FRAGMENT_PACKER_PAGE_COUNT)
    ) u_udp_parser (
        .clk(clk), .resetn(resetn), .s_axis_packet_in(u_branch_in[ROUTE_UDP]),
        .m_axis_header_out(u_branch_hdr[ROUTE_UDP]),
        .m_axis_payload_out(u_branch_payload[ROUTE_UDP])
    );

    parser_pkg::l4_hdr_axis_t other_hdr_value;
    logic other_in_packet_r;
    logic other_first;
    logic other_fire;

    always_comb begin
        other_hdr_value = '0;
        other_hdr_value.status = (l3_hdr.status == parser_pkg::PARSER_STATUS_OK)
            ? parser_pkg::PARSER_STATUS_OTHER : l3_hdr.status;
        other_hdr_value.kind = parser_pkg::L4_KIND_OTHER;
        other_hdr_value.protocol = l3_hdr.protocol;
    end

    assign other_first = !other_in_packet_r;
    assign other_fire = u_branch_in[ROUTE_OTHER].tvalid && u_branch_in[ROUTE_OTHER].tready;

    always_comb begin
        u_branch_hdr[ROUTE_OTHER].t = '0;
        u_branch_hdr[ROUTE_OTHER].t.data = other_hdr_value;
        u_branch_hdr[ROUTE_OTHER].t.keep = '1;
        u_branch_hdr[ROUTE_OTHER].t.last = 1'b1;
        u_branch_hdr[ROUTE_OTHER].tvalid = u_branch_in[ROUTE_OTHER].tvalid
            && other_first && u_branch_payload[ROUTE_OTHER].tready;

        u_branch_payload[ROUTE_OTHER].t = u_branch_in[ROUTE_OTHER].t;
        u_branch_payload[ROUTE_OTHER].tvalid = u_branch_in[ROUTE_OTHER].tvalid
            && (!other_first || u_branch_hdr[ROUTE_OTHER].tready);

        u_branch_in[ROUTE_OTHER].tready = u_branch_payload[ROUTE_OTHER].tready
            && (!other_first || u_branch_hdr[ROUTE_OTHER].tready);
    end

    always_ff @(posedge clk) begin
        if (!resetn)
            other_in_packet_r <= 1'b0;
        else if (other_fire)
            other_in_packet_r <= !u_branch_in[ROUTE_OTHER].t.last;
    end

    typedef enum logic {WAIT_META, STREAM_PACKET} state_t;
    state_t state_r;
    logic [1:0] active_route_r;
    logic first_fire;
    logic branch_ready_c;

    ifc_axis #(.DATA_WIDTH(8), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1))
        u_hdr_route_in (.axis_aclk(clk)), u_hdr_route_out (.axis_aclk(clk)),
        u_payload_route_in (.axis_aclk(clk)), u_payload_route_out (.axis_aclk(clk)),
        u_payload_route_select (.axis_aclk(clk));

    always_comb begin
        branch_ready_c = 1'b0;
        case (state_r == WAIT_META ? route_sel_c : active_route_r)
            2'(ROUTE_TCP):   branch_ready_c = u_branch_in[ROUTE_TCP].tready;
            2'(ROUTE_UDP):   branch_ready_c = u_branch_in[ROUTE_UDP].tready;
            default:         branch_ready_c = u_branch_in[ROUTE_OTHER].tready;
        endcase
    end

    wire route_push_ready = u_hdr_route_in.tready &&
                            (HEADER_ONLY || u_payload_route_in.tready);
    assign first_fire = (state_r == WAIT_META) && u_packet_in.tvalid &&
        u_l3_header_in.tvalid && branch_ready_c && route_push_ready;

    assign u_packet_in.tready = (state_r == WAIT_META)
        ? (u_l3_header_in.tvalid && branch_ready_c && route_push_ready)
        : branch_ready_c;
    assign u_l3_header_in.tready = first_fire;

    for (genvar i = 0; i < 3; i++) begin : g_branch_drive
        assign u_branch_in[i].t = u_packet_in.t;
        assign u_branch_in[i].tvalid = u_packet_in.tvalid && (
            (state_r == WAIT_META && u_l3_header_in.tvalid && route_push_ready &&
             route_sel_c == 2'(i))
            || (state_r == STREAM_PACKET && active_route_r == 2'(i)));
    end

    for (genvar i = 0; i < 3; i++) begin : g_output_q
        assign u_branch_hdr_to_q[i].t = u_branch_hdr[i].t;
        assign u_branch_hdr_to_q[i].tvalid = u_branch_hdr[i].tvalid;
        assign u_branch_hdr[i].tready = u_branch_hdr_to_q[i].tready;

        axis_fifo #(
            .DEPTH    (4),
            .USE_BRAM (1'b0),
            .MODE     ("CONSERVATIVE")
        ) u_hdr_q (
            .clk(clk), .resetn(resetn), .s_axis(u_branch_hdr_to_q[i]), .m_axis(u_branch_hdr_q[i])
        );

        if (!HEADER_ONLY) begin : g_payload_q
            assign u_branch_payload_to_q[i].t = u_branch_payload[i].t;
            assign u_branch_payload_to_q[i].tvalid = u_branch_payload[i].tvalid;
            assign u_branch_payload[i].tready = u_branch_payload_to_q[i].tready;

            axis_fifo #(
                .DEPTH            (4),
                .USE_BRAM         (1'b0),
                .EXTRA_OUTPUT_REG (1'b1),
                .MODE             ("CONSERVATIVE")
            ) u_payload_q (
                .clk(clk), .resetn(resetn), .s_axis(u_branch_payload_to_q[i]),
                .m_axis(u_branch_payload_q[i])
            );
        end else begin : g_payload_sink
            assign u_branch_payload[i].tready = 1'b1;
        end
    end

    always_comb begin
        u_hdr_route_in.t = '0;
        u_hdr_route_in.t.data[1:0] = route_sel_c;
        u_hdr_route_in.t.keep = '1;
        u_hdr_route_in.t.last = 1'b1;
        u_hdr_route_in.tvalid = first_fire;

        u_payload_route_in.t = '0;
        u_payload_route_in.t.data[1:0] = route_sel_c;
        u_payload_route_in.t.keep = '1;
        u_payload_route_in.t.last = 1'b1;
        u_payload_route_in.tvalid = first_fire && !HEADER_ONLY;
    end


    axis_fifo #(
        .DEPTH    (32),
        .USE_BRAM (1'b0),
        .MODE     ("CONSERVATIVE")
    ) u_hdr_route_q (
        .clk(clk), .resetn(resetn), .s_axis(u_hdr_route_in), .m_axis(u_hdr_route_out)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            state_r <= WAIT_META;
            active_route_r <= '0;
        end else if (u_packet_in.tvalid && u_packet_in.tready) begin
            if (state_r == WAIT_META) begin
                active_route_r <= route_sel_c;
                state_r <= u_packet_in.t.last ? WAIT_META : STREAM_PACKET;
            end else if (u_packet_in.t.last) begin
                state_r <= WAIT_META;
            end
        end
    end

    logic [1:0] hdr_route;
    assign hdr_route = u_hdr_route_out.t.data[1:0];

    always_comb begin
        u_header_out.t = '0;
        u_header_out.tvalid = 1'b0;
        u_branch_hdr_q[ROUTE_TCP].tready = 1'b0;
        u_branch_hdr_q[ROUTE_UDP].tready = 1'b0;
        u_branch_hdr_q[ROUTE_OTHER].tready = 1'b0;
        case (hdr_route)
            2'(ROUTE_TCP): begin
                u_header_out.t = u_branch_hdr_q[ROUTE_TCP].t;
                u_header_out.tvalid = u_hdr_route_out.tvalid && u_branch_hdr_q[ROUTE_TCP].tvalid;
                u_branch_hdr_q[ROUTE_TCP].tready = u_header_out.tready && u_header_out.tvalid;
            end
            2'(ROUTE_UDP): begin
                u_header_out.t = u_branch_hdr_q[ROUTE_UDP].t;
                u_header_out.tvalid = u_hdr_route_out.tvalid && u_branch_hdr_q[ROUTE_UDP].tvalid;
                u_branch_hdr_q[ROUTE_UDP].tready = u_header_out.tready && u_header_out.tvalid;
            end
            default: begin
                u_header_out.t = u_branch_hdr_q[ROUTE_OTHER].t;
                u_header_out.tvalid = u_hdr_route_out.tvalid && u_branch_hdr_q[ROUTE_OTHER].tvalid;
                u_branch_hdr_q[ROUTE_OTHER].tready = u_header_out.tready && u_header_out.tvalid;
            end
        endcase
        u_hdr_route_out.tready = u_header_out.tready && u_header_out.tvalid;
    end

    logic [1:0] payload_route_select;
    logic payload_out_fire;
    logic payload_out_last_fire;

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_header_out_rs (
        .clk(clk), .resetn(resetn), .s_axis(u_header_out), .m_axis(m_axis_header_out)
    );

    generate
        if (!HEADER_ONLY) begin : g_payload_path
            axis_fifo #(
                .DEPTH    (32),
                .USE_BRAM (1'b0),
                .MODE     ("CONSERVATIVE")
            ) u_payload_route_q (
                .clk(clk), .resetn(resetn), .s_axis(u_payload_route_in),
                .m_axis(u_payload_route_out)
            );

            assign payload_out_fire = u_payload_out.tvalid && u_payload_out.tready;
            assign payload_out_last_fire = payload_out_fire && u_payload_out.t.last;
            assign payload_route_select = u_payload_route_select.t.data[1:0];
            assign u_payload_route_select.tready = payload_out_last_fire;

            axis_fifo #(
                .DEPTH    (4),
                .USE_BRAM (1'b0),
                .MODE     ("CONSERVATIVE")
            ) u_payload_route_select_q (
                .clk(clk), .resetn(resetn), .s_axis(u_payload_route_out),
                .m_axis(u_payload_route_select)
            );

            for (genvar i = 0; i < 3; i++) begin : g_payload_mux_gate
                assign u_payload_mux_in[i].t = u_branch_payload_q[i].t;
                assign u_payload_mux_in[i].tvalid = u_payload_route_select.tvalid &&
                                                    u_branch_payload_q[i].tvalid;
                assign u_branch_payload_q[i].tready = u_payload_route_select.tvalid &&
                                                      u_payload_mux_in[i].tready;
            end

            axis_packet_mux #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH), .TID_WIDTH(TID_WIDTH),
                .TUSER_WIDTH(TUSER_WIDTH), .NUM_SLAVES(3)
            ) u_payload_mux (
                .clk(clk), .resetn(resetn), .select(payload_route_select),
                .s_axis(u_payload_mux_in), .m_axis(u_payload_out)
            );

    axis_fifo #(.DEPTH(4), .USE_BRAM(1'b0), .EXTRA_OUTPUT_REG(1'b0),
                .MODE("CONSERVATIVE")) u_payload_out_rs (
                .clk(clk), .resetn(resetn), .s_axis(u_payload_out),
                .m_axis(m_axis_payload_out)
            );
        end else begin : g_header_only
            assign u_payload_route_in.tready = 1'b1;
            always_comb begin
                m_axis_payload_out.t = '0;
                m_axis_payload_out.tvalid = 1'b0;
            end
        end
    endgenerate

endmodule
