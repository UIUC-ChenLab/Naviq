`include "ifc_axis.sv"

module axis_count_packet_size #(
    parameter int DATA_WIDTH = 512,
    parameter int SIZE_WIDTH = 32
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH       = DATA_WIDTH / 8;
    localparam int BEAT_COUNT_WIDTH = $clog2(DATA_WIDTH);

    initial begin
        if ((DATA_WIDTH % 8) != 0) begin
            $error("axis_count_packet_size: DATA_WIDTH must be a multiple of 8");
            $finish;
        end
        if ((SIZE_WIDTH % 8) != 0) begin
            $error("axis_count_packet_size: SIZE_WIDTH must be a multiple of 8");
            $finish;
        end
        if ($bits(s_axis.t.data) != DATA_WIDTH) begin
            $error("axis_count_packet_size: s_axis data width must match DATA_WIDTH");
            $finish;
        end
        if ($bits(m_axis.t.data) != SIZE_WIDTH) begin
            $error("axis_count_packet_size: m_axis data width must match SIZE_WIDTH");
            $finish;
        end
    end

    logic [SIZE_WIDTH-1:0] count_r;
    logic [SIZE_WIDTH-1:0] size_r;
    logic                  size_valid_r;

    ifc_axis #(
        .DATA_WIDTH  (BEAT_COUNT_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_beat_count (clk);

    logic [SIZE_WIDTH-1:0] next_packet_size;
    logic                  count_hs;
    logic                  output_hs;

    axis_count_beat_size #(
        .DATA_WIDTH (DATA_WIDTH)
    ) u_count_beat_size (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (s_axis),
        .m_axis (u_beat_count.master)
    );

    assign u_beat_count.tready = !u_beat_count.t.last || !size_valid_r || m_axis.tready;
    assign next_packet_size = count_r + SIZE_WIDTH'(u_beat_count.t.data);
    assign count_hs  = u_beat_count.tvalid && u_beat_count.tready;
    assign output_hs = m_axis.tvalid && m_axis.tready;

    assign m_axis.t.data  = size_r;
    assign m_axis.t.keep  = '1;
    assign m_axis.t.id    = '0;
    assign m_axis.t.dest  = '0;
    assign m_axis.t.user  = '0;
    assign m_axis.t.last  = 1'b1;
    assign m_axis.tvalid  = size_valid_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            count_r      <= '0;
            size_r       <= '0;
            size_valid_r <= 1'b0;
        end else begin
            if (count_hs) begin
                if (u_beat_count.t.last) begin
                    count_r <= '0;
                    size_r  <= next_packet_size;
                end else begin
                    count_r <= next_packet_size;
                end
            end

            unique case ({count_hs && u_beat_count.t.last, output_hs})
                2'b10: size_valid_r <= 1'b1;
                2'b01: size_valid_r <= 1'b0;
                default: size_valid_r <= size_valid_r;
            endcase
        end
    end

endmodule
