// AXI-Stream packet FIFO. Wraps axis_fifo and only releases complete packets.

`include "ifc_axis.sv"

module axis_packet_fifo #(
    parameter int DEPTH = 16,
    parameter int DATA_WIDTH  = 512,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH   = 16,
    parameter int TUSER_WIDTH = 16,
    parameter string MODE = "FULL_CAPACITY"
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int COUNT_WIDTH = $clog2(DEPTH + 1);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) fifo_axis (.axis_aclk(clk));

    logic [COUNT_WIDTH-1:0] packet_count_r;

    initial begin
        if ($bits(s_axis.t.data) != DATA_WIDTH) begin
            $error("axis_packet_fifo: s_axis.t.data width does not match DATA_WIDTH");
        end
        if ($bits(m_axis.t.data) != DATA_WIDTH) begin
            $error("axis_packet_fifo: m_axis.t.data width does not match DATA_WIDTH");
        end
        if ($bits(s_axis.t.dest) != TDEST_WIDTH || $bits(m_axis.t.dest) != TDEST_WIDTH) begin
            $error("axis_packet_fifo: axis tdest width does not match TDEST_WIDTH");
        end
        if ($bits(s_axis.t.id) != TID_WIDTH || $bits(m_axis.t.id) != TID_WIDTH) begin
            $error("axis_packet_fifo: axis tid width does not match TID_WIDTH");
        end
        if ($bits(s_axis.t.user) != TUSER_WIDTH || $bits(m_axis.t.user) != TUSER_WIDTH) begin
            $error("axis_packet_fifo: axis tuser width does not match TUSER_WIDTH");
        end
    end

    logic s_packet_hs;
    assign s_packet_hs = s_axis.tvalid && s_axis.tready && s_axis.t.last;
    logic m_packet_hs;
    assign m_packet_hs = m_axis.tvalid && m_axis.tready && m_axis.t.last;
    logic packet_available;
    assign packet_available = (packet_count_r != '0);

    axis_fifo #(
        .DEPTH (DEPTH),
        .MODE  (MODE)
    ) u_fifo (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis),
        .m_axis (fifo_axis.master)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            packet_count_r <= '0;
        end else begin
            case ({s_packet_hs, m_packet_hs})
                2'b10: packet_count_r <= packet_count_r + 1'b1;
                2'b01: packet_count_r <= packet_count_r - 1'b1;
                default:;
            endcase
        end
    end

    assign m_axis.t            = fifo_axis.t;
    assign m_axis.tvalid       = fifo_axis.tvalid && packet_available;
    assign fifo_axis.tready    = m_axis.tready && packet_available;

endmodule
