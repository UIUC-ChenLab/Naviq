`ifndef AXIS_PACKET_REBUILDER_SV
`define AXIS_PACKET_REBUILDER_SV

`include "ifc_axis.sv"

module axis_packet_rebuilder #(
    parameter int DATA_WIDTH            = 512,
    parameter int NUM_SOURCES           = 16,
    parameter int MAX_PACKET_SIZE_BYTES = 1500,
    parameter int TID_WIDTH             = (NUM_SOURCES <= 1) ? 1 : $clog2(NUM_SOURCES)
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;
    localparam int BEATS_PER_SOURCE =
        (MAX_PACKET_SIZE_BYTES + KEEP_WIDTH - 1) / KEEP_WIDTH;
    localparam int PACKET_COUNT_WIDTH =
        (BEATS_PER_SOURCE <= 1) ? 1 : $clog2(BEATS_PER_SOURCE + 1);
    localparam int URAM_DEPTH = NUM_SOURCES * BEATS_PER_SOURCE;
    localparam int URAM_ADDR_WIDTH = (URAM_DEPTH <= 1) ? 1 : $clog2(URAM_DEPTH);
    localparam int URAM_WIDTH = DATA_WIDTH + KEEP_WIDTH;
    localparam int REQUIRED_TID_WIDTH = (NUM_SOURCES <= 1) ? 1 : $clog2(NUM_SOURCES);

    logic uram_we;
    logic [URAM_ADDR_WIDTH-1:0] uram_write_address;
    logic [URAM_WIDTH-1:0] uram_write_data;
    logic [URAM_ADDR_WIDTH-1:0] uram_read_address;
    logic [URAM_WIDTH-1:0] uram_read_data;

    logic [NUM_SOURCES-1:0] completed;
    logic [PACKET_COUNT_WIDTH-1:0] packet_lengths [NUM_SOURCES];
    logic retire_valid;
    logic [TID_WIDTH-1:0] retire_source;

    rebuilder_ingress #(
        .DATA_WIDTH            (DATA_WIDTH),
        .NUM_SOURCES           (NUM_SOURCES),
        .MAX_PACKET_SIZE_BYTES (MAX_PACKET_SIZE_BYTES),
        .TID_WIDTH             (TID_WIDTH)
    ) u_ingress (
        .clk            (clk),
        .resetn         (resetn),
        .s_tdata        (s_axis.t.data),
        .s_tkeep        (s_axis.t.keep),
        .s_tid          (s_axis.t.id),
        .s_tlast        (s_axis.t.last),
        .s_tvalid       (s_axis.tvalid),
        .s_tready       (s_axis.tready),
        .retire_valid   (retire_valid),
        .retire_source  (retire_source),
        .uram_we        (uram_we),
        .uram_addr      (uram_write_address),
        .uram_data      (uram_write_data),
        .completed      (completed),
        .packet_lengths (packet_lengths)
    );

    simple_dual_port_uram #(
        .URAM_WIDTH       (URAM_WIDTH),
        .URAM_DEPTH       (URAM_DEPTH),
        .EXTRA_OUTPUT_REG (1'b1)
    ) u_packet_memory (
        .clk    (clk),
        .we_w   (uram_we),
        .addr_w (uram_write_address),
        .din_w  (uram_write_data),
        .addr_r (uram_read_address),
        .dout_r (uram_read_data)
    );

    uram_egress #(
        .DATA_WIDTH            (DATA_WIDTH),
        .NUM_SOURCES           (NUM_SOURCES),
        .MAX_PACKET_SIZE_BYTES (MAX_PACKET_SIZE_BYTES),
        .TID_WIDTH             (TID_WIDTH)
    ) u_egress (
        .clk               (clk),
        .resetn            (resetn),
        .completed         (completed),
        .packet_lengths    (packet_lengths),
        .uram_read_address (uram_read_address),
        .uram_read_data    (uram_read_data),
        .retire_valid      (retire_valid),
        .retire_source     (retire_source),
        .m_axis            (m_axis)
    );

    initial begin
        if (DATA_WIDTH <= 0 || (DATA_WIDTH % 8) != 0) begin
            $error("axis_packet_rebuilder: DATA_WIDTH must be positive and byte aligned");
            $finish;
        end
        if (NUM_SOURCES < 1 || NUM_SOURCES > 32) begin
            $error("axis_packet_rebuilder: NUM_SOURCES must be from 1 through 32");
            $finish;
        end
        if (MAX_PACKET_SIZE_BYTES <= 0) begin
            $error("axis_packet_rebuilder: MAX_PACKET_SIZE_BYTES must be positive");
            $finish;
        end
        if (TID_WIDTH < REQUIRED_TID_WIDTH) begin
            $error("axis_packet_rebuilder: TID_WIDTH is too small for NUM_SOURCES");
            $finish;
        end
        if ($bits(s_axis.t.data) != DATA_WIDTH || $bits(m_axis.t.data) != DATA_WIDTH) begin
            $error("axis_packet_rebuilder: AXIS data width does not match DATA_WIDTH");
            $finish;
        end
        if ($bits(s_axis.t.id) != TID_WIDTH || $bits(m_axis.t.id) != TID_WIDTH) begin
            $error("axis_packet_rebuilder: AXIS id width does not match TID_WIDTH");
            $finish;
        end
    end

endmodule

`endif
