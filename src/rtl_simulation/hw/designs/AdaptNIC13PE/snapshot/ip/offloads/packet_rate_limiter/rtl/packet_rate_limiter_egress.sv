// Applies one ordered atomic admit/drop decision to each fully buffered packet.
module packet_rate_limiter_egress (
    input logic clk,
    input logic resetn,
    ifc_axis.slave  packet_buffer_in,
    ifc_axis.master packet_out,

    input  logic decision_valid,
    output logic decision_ready,
    input  logic decision_admit,

    output logic packet_pop
);

    logic gate_active_r;
    logic gate_admit_r;

    assign packet_pop = packet_buffer_in.tvalid && packet_buffer_in.tready;
    wire packet_last_pop = packet_pop && packet_buffer_in.t.last;

    // Refill the gate on the same edge that completes the current packet.
    assign decision_ready = packet_buffer_in.tvalid &&
                            (!gate_active_r || packet_last_pop);

    always_comb begin
        packet_out.t = '0;
        packet_out.t.data = packet_buffer_in.t.data;
        packet_out.t.keep = packet_buffer_in.t.keep;
        packet_out.t.id = $bits(packet_out.t.id)'(packet_buffer_in.t.id);
        packet_out.t.dest = $bits(packet_out.t.dest)'(packet_buffer_in.t.dest);
        packet_out.t.user = $bits(packet_out.t.user)'(packet_buffer_in.t.user);
        packet_out.t.last = packet_buffer_in.t.last;
        packet_out.tvalid = gate_active_r && gate_admit_r &&
                            packet_buffer_in.tvalid;

        packet_buffer_in.tready = gate_active_r &&
            (gate_admit_r ? packet_out.tready : 1'b1);
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            gate_active_r <= 1'b0;
            gate_admit_r <= 1'b0;
        end else begin
            if (decision_valid && decision_ready) begin
                gate_active_r <= 1'b1;
                gate_admit_r <= decision_admit;
            end else if (packet_last_pop) begin
                gate_active_r <= 1'b0;
            end
        end
    end

endmodule
