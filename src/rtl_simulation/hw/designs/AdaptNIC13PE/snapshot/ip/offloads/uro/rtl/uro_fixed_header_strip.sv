`include "ifc_axis.sv"

// Remove a fixed prefix from the first beat of each packet without packing
// across beat boundaries. URO requires the complete IPv4/UDP header to fit in
// that beat, so data content never participates in valid/ready control.
module uro_fixed_header_strip #(
    parameter int DATA_WIDTH   = 512,
    parameter int HEADER_BYTES = 28
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave packet_in,
    ifc_axis.master payload_out
);
    localparam int DATA_BYTES = DATA_WIDTH / 8;
    logic first_beat_r;
    wire input_fire = packet_in.tvalid && packet_in.tready;

    always_comb begin
        payload_out.t = packet_in.t;
        if (first_beat_r) begin
            payload_out.t.data = packet_in.t.data >> (HEADER_BYTES * 8);
            payload_out.t.keep = packet_in.t.keep >> HEADER_BYTES;
        end
        // A malformed/header-only packet deliberately produces a valid,
        // zero-keep terminal marker so its ordered metadata can still retire.
        payload_out.tvalid = packet_in.tvalid;
        packet_in.tready = payload_out.tready;
    end

    always_ff @(posedge clk) begin
        if (!resetn)
            first_beat_r <= 1'b1;
        else if (input_fire)
            first_beat_r <= packet_in.t.last;
    end

    initial begin
        if (DATA_WIDTH < 8 || DATA_WIDTH % 8 != 0)
            $error("uro_fixed_header_strip: DATA_WIDTH must be byte aligned");
        if (HEADER_BYTES < 1)
            $error("uro_fixed_header_strip: HEADER_BYTES must be positive");
        if (DATA_BYTES <= HEADER_BYTES) begin
            $error("uro_fixed_header_strip: fixed header must fit within one beat");
            $finish;
        end
    end
endmodule
