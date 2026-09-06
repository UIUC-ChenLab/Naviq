`include "ifc_axis.sv"

// Transparent packet offload backed by a conservative-mode BRAM AXIS FIFO.
module dummy_fifo #(
    parameter int DATA_WIDTH = 512,
    parameter int FIFO_DEPTH = 16,
    parameter bit EXTRA_OUTPUT_REG = 1'b0
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  packet_in,
    ifc_axis.master packet_out
);

    initial begin
        if (DATA_WIDTH < 8 || (DATA_WIDTH % 8) != 0) begin
            $error("dummy_fifo: DATA_WIDTH must be positive and byte aligned");
            $finish;
        end
        if ($bits(packet_in.t.data) != DATA_WIDTH ||
            $bits(packet_out.t.data) != DATA_WIDTH) begin
            $error("dummy_fifo: AXIS interface data widths must match DATA_WIDTH");
            $finish;
        end
        if (FIFO_DEPTH < 2) begin
            $error("dummy_fifo: FIFO_DEPTH must be at least 2 in conservative mode");
            $finish;
        end
        if ($bits(packet_in.t) != $bits(packet_out.t)) begin
            $error("dummy_fifo: input and output AXIS sideband widths must match");
            $finish;
        end
    end

    axis_fifo #(
        .DEPTH            (FIFO_DEPTH),
        .USE_BRAM         (1'b1),
        .EXTRA_OUTPUT_REG (EXTRA_OUTPUT_REG),
        .MODE             ("CONSERVATIVE")
    ) u_axis_fifo (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (packet_in),
        .m_axis (packet_out)
    );

endmodule

