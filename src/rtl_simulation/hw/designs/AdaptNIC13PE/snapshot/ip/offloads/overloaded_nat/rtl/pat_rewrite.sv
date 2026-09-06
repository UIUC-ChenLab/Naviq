// pat_rewrite — Rewrites IP/port fields by absolute packet byte offset.
//
// Receives:
//   - Buffered raw packet beats from pat_pkt_buf (AXIS FIFO)
//   - Lookup result (hit/miss/bypass + entry_id)
//   - Rewrite data (new IP + new port from CSR or entry_meta)
//
// Behavior:
//   - Outbound hit/miss-resolved: overwrite src_ip (bytes 12-15) and src_port (bytes 20-21)
//   - Inbound hit: overwrite dst_ip (bytes 16-19) and dst_port (bytes 22-23)
//   - Bypass: pass through unchanged
//   - Inbound miss: drop (suppress tvalid)
//
// Works for any byte-aligned DATA_WIDTH.  The packet is assumed to be raw IPv4
// starting at byte 0.

`include "ifc_axis.sv"
import pat_pkg::*;

module pat_rewrite #(
    parameter int DATA_WIDTH = 512
) (
    input  logic clk,
    input  logic resetn,

    // Buffered packet input (from pat_pkt_buf)
    ifc_axis.slave  pkt_in,

    // Rewrite command (valid when lookup is complete for this packet)
    input  logic        rw_valid,
    output logic        rw_ready,
    input  logic        rw_is_outbound,
    input  logic        rw_is_bypass,
    input  logic        rw_hit,          // 0 on inbound miss → drop
    input  logic [31:0] rw_new_ip,       // outbound: public_ip; inbound: private_ip
    input  logic [15:0] rw_new_port,     // outbound: base+eid; inbound: private_port

    // Rewritten packet output
    ifc_axis.master pkt_out
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;

    localparam int BYTE_POS_W = 16;

    logic        have_cmd_r;
    logic        cmd_outbound_r;
    logic        cmd_bypass_r;
    logic        cmd_hit_r;
    logic [31:0] cmd_ip_r;
    logic [15:0] cmd_port_r;
    logic [BYTE_POS_W-1:0] beat_base_r;

    logic should_drop;
    assign should_drop = !cmd_bypass_r && !cmd_hit_r;

    wire forward_fire = have_cmd_r && !should_drop && pkt_in.tvalid && pkt_out.tready;
    wire drop_fire    = have_cmd_r && should_drop && pkt_in.tvalid;
    wire packet_done  = (forward_fire || drop_fire) && pkt_in.t.last;

    assign rw_ready = !have_cmd_r || packet_done;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            have_cmd_r    <= 1'b0;
            beat_base_r   <= '0;
        end else begin
            if (forward_fire || drop_fire) begin
                if (pkt_in.t.last) begin
                    have_cmd_r  <= 1'b0;
                    beat_base_r <= '0;
                end else begin
                    beat_base_r <= beat_base_r + BYTE_POS_W'(KEEP_WIDTH);
                end
            end

            if (rw_valid && rw_ready) begin
                have_cmd_r     <= 1'b1;
                cmd_outbound_r <= rw_is_outbound;
                cmd_bypass_r   <= rw_is_bypass;
                cmd_hit_r      <= rw_hit;
                cmd_ip_r       <= rw_new_ip;
                cmd_port_r     <= rw_new_port;
                if (!have_cmd_r || packet_done)
                    beat_base_r <= '0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Output mux
    // -------------------------------------------------------------------------
    logic [DATA_WIDTH-1:0] rewritten_data;

    always_comb begin
        rewritten_data = pkt_in.t.data;

        if (have_cmd_r && !cmd_bypass_r && cmd_hit_r) begin
            for (int i = 0; i < KEEP_WIDTH; i++) begin
                automatic logic [BYTE_POS_W-1:0] pos = beat_base_r + BYTE_POS_W'(i);
                if (cmd_outbound_r) begin
                    unique case (pos)
                        16'd12: rewritten_data[i*8 +: 8] = cmd_ip_r[31:24];
                        16'd13: rewritten_data[i*8 +: 8] = cmd_ip_r[23:16];
                        16'd14: rewritten_data[i*8 +: 8] = cmd_ip_r[15:8];
                        16'd15: rewritten_data[i*8 +: 8] = cmd_ip_r[7:0];
                        16'd20: rewritten_data[i*8 +: 8] = cmd_port_r[15:8];
                        16'd21: rewritten_data[i*8 +: 8] = cmd_port_r[7:0];
                        default: ;
                    endcase
                end else begin
                    unique case (pos)
                        16'd16: rewritten_data[i*8 +: 8] = cmd_ip_r[31:24];
                        16'd17: rewritten_data[i*8 +: 8] = cmd_ip_r[23:16];
                        16'd18: rewritten_data[i*8 +: 8] = cmd_ip_r[15:8];
                        16'd19: rewritten_data[i*8 +: 8] = cmd_ip_r[7:0];
                        16'd22: rewritten_data[i*8 +: 8] = cmd_port_r[15:8];
                        16'd23: rewritten_data[i*8 +: 8] = cmd_port_r[7:0];
                        default: ;
                    endcase
                end
            end
        end
    end

    // AXIS output
    assign pkt_out.t.data = rewritten_data;
    assign pkt_out.t.keep = pkt_in.t.keep;
    assign pkt_out.t.id   = $bits(pkt_out.t.id)'(pkt_in.t.id);
    assign pkt_out.t.dest = $bits(pkt_out.t.dest)'(pkt_in.t.dest);
    assign pkt_out.t.user = $bits(pkt_out.t.user)'(pkt_in.t.user);
    assign pkt_out.t.last = pkt_in.t.last;

    // Valid: suppress for dropped packets; otherwise forward when we have data
    assign pkt_out.tvalid = have_cmd_r && !should_drop && pkt_in.tvalid;

    assign pkt_in.tready = have_cmd_r ? (should_drop ? 1'b1 : pkt_out.tready) : 1'b0;

endmodule
