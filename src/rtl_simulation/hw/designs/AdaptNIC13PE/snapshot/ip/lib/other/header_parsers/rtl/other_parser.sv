`include "ifc_axis.sv"

module other_parser #(
    parameter int DATA_WIDTH    = 512,
    parameter int HEADER_WIDTH  = 32,
    parameter logic [HEADER_WIDTH-1:0] HEADER_VALUE = '0
) (
    input  logic clk,
    input  logic resetn,

    ifc_axis.slave  s_axis_packet_in,
    ifc_axis.master m_axis_header_out,
    ifc_axis.master m_axis_payload_out
);

    logic in_packet_r;
    logic first_beat;
    logic fire;

    assign first_beat = !in_packet_r;

    always_comb begin
        m_axis_header_out.t = '0;
        m_axis_header_out.t.data = HEADER_VALUE;
        m_axis_header_out.t.keep = '1;
        m_axis_header_out.t.last = 1'b1;
        m_axis_header_out.tvalid = s_axis_packet_in.tvalid && first_beat && m_axis_payload_out.tready;

        m_axis_payload_out.t = s_axis_packet_in.t;
        m_axis_payload_out.tvalid = s_axis_packet_in.tvalid
            && (!first_beat || m_axis_header_out.tready);

        s_axis_packet_in.tready = m_axis_payload_out.tready
            && (!first_beat || m_axis_header_out.tready);
    end

    assign fire = s_axis_packet_in.tvalid && s_axis_packet_in.tready;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            in_packet_r <= 1'b0;
        end else if (fire) begin
            in_packet_r <= !s_axis_packet_in.t.last;
        end
    end

    initial begin
        if (DATA_WIDTH < 8 || DATA_WIDTH % 8 != 0 || (DATA_WIDTH & (DATA_WIDTH - 1)) != 0)
            $error("other_parser: DATA_WIDTH must be a byte-aligned power of two >= 8");
        if ($bits(m_axis_header_out.t.data) != HEADER_WIDTH)
            $error("other_parser: m_axis_header_out width mismatch");
    end

endmodule
