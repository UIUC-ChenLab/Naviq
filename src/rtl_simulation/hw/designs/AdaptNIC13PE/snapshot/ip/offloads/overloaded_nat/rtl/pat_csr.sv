// pat_csr — AXI-Lite control/status registers for the PAT.
//
// Register map:
//   0x00  PUBLIC_IP    RW   Configured public IPv4 address
//   0x04  BASE_PORT    RW   Base port number (translated port = base + entry_id)
//   0x08  TIMEOUT      RW   Aging timeout in timestamp ticks (16-bit)
//   0x0C  ENABLE       RW   bit 0: PAT enable (0 = bypass all)
//   0x10  STATUS       RO   bit 0: free_list_empty; bits[15:4]: active_entries
//   0x14  PKT_FWD_HIT  RO   Forward hit counter (32-bit)
//   0x18  PKT_FWD_MISS RO   Forward miss counter
//   0x1C  PKT_REV_HIT  RO   Reverse hit counter
//   0x20  PKT_REV_MISS RO   Reverse miss (drop) counter
//   0x24  PKT_BYPASS   RO   Bypassed packet counter

`include "ifc_axil.sv"

module pat_csr (
    input  logic clk,
    input  logic resetn,

    ifc_axil.slave ctrl,

    // Configuration outputs
    output logic [31:0] csr_public_ip,
    output logic [15:0] csr_base_port,
    output logic [15:0] csr_timeout,
    output logic        csr_enable,

    // Status inputs
    input  logic        status_free_empty,
    input  logic [11:0] status_active_entries,

    // Counter increment strobes (active for one cycle)
    input  logic        cnt_fwd_hit,
    input  logic        cnt_fwd_miss,
    input  logic        cnt_rev_hit,
    input  logic        cnt_rev_miss,
    input  logic        cnt_bypass,

    // Timestamp output (free-running 16-bit counter)
    output logic [15:0] csr_timestamp
);

    // -------------------------------------------------------------------------
    // Registers
    // -------------------------------------------------------------------------
    logic [31:0] reg_public_ip;
    logic [15:0] reg_base_port;
    logic [15:0] reg_timeout;
    logic        reg_enable;

    logic [31:0] cnt_fwd_hit_r;
    logic [31:0] cnt_fwd_miss_r;
    logic [31:0] cnt_rev_hit_r;
    logic [31:0] cnt_rev_miss_r;
    logic [31:0] cnt_bypass_r;

    logic [15:0] timestamp_r;

    assign csr_public_ip = reg_public_ip;
    assign csr_base_port = reg_base_port;
    assign csr_timeout   = reg_timeout;
    assign csr_enable    = reg_enable;
    assign csr_timestamp = timestamp_r;

    // Free-running timestamp
    always_ff @(posedge clk) begin
        if (!resetn)
            timestamp_r <= '0;
        else
            timestamp_r <= timestamp_r + 1;
    end

    // Counters
    always_ff @(posedge clk) begin
        if (!resetn) begin
            cnt_fwd_hit_r  <= '0;
            cnt_fwd_miss_r <= '0;
            cnt_rev_hit_r  <= '0;
            cnt_rev_miss_r <= '0;
            cnt_bypass_r   <= '0;
        end else begin
            if (cnt_fwd_hit)  cnt_fwd_hit_r  <= cnt_fwd_hit_r  + 1;
            if (cnt_fwd_miss) cnt_fwd_miss_r <= cnt_fwd_miss_r + 1;
            if (cnt_rev_hit)  cnt_rev_hit_r  <= cnt_rev_hit_r  + 1;
            if (cnt_rev_miss) cnt_rev_miss_r <= cnt_rev_miss_r + 1;
            if (cnt_bypass)   cnt_bypass_r   <= cnt_bypass_r   + 1;
        end
    end

    // -------------------------------------------------------------------------
    // AXI-Lite write channel
    // -------------------------------------------------------------------------
    // Simple: accept AW+W together, respond B immediately.
    logic aw_fire, w_fire;
    assign aw_fire = ctrl.aw_valid && ctrl.aw_ready;
    assign w_fire  = ctrl.w_valid  && ctrl.w_ready;

    // Latch write address (AW may arrive before W)
    logic        aw_pending_r;
    logic [31:0] aw_addr_r;

    assign ctrl.aw_ready = 1'b1;  // always accept AW
    assign ctrl.w_ready  = aw_pending_r || ctrl.aw_valid;  // accept W when we have an address

    always_ff @(posedge clk) begin
        if (!resetn) begin
            aw_pending_r <= 1'b0;
            aw_addr_r    <= '0;
            reg_public_ip <= '0;
            reg_base_port <= '0;
            reg_timeout   <= 16'd1000;  // default timeout
            reg_enable    <= 1'b0;
        end else begin
            // Latch AW
            if (aw_fire && !w_fire) begin
                aw_pending_r <= 1'b1;
                aw_addr_r    <= ctrl.aw.addr;
            end

            // Process write when both AW and W are available
            if (w_fire) begin
                logic [31:0] addr;
                addr = aw_pending_r ? aw_addr_r : ctrl.aw.addr;
                aw_pending_r <= 1'b0;

                case (addr[7:0])
                    8'h00: reg_public_ip <= ctrl.w.data;
                    8'h04: reg_base_port <= ctrl.w.data[15:0];
                    8'h08: reg_timeout   <= ctrl.w.data[15:0];
                    8'h0C: reg_enable    <= ctrl.w.data[0];
                    default: ;  // ignore writes to RO registers
                endcase
            end
        end
    end

    // B response — always OK
    logic b_pending_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            b_pending_r <= 1'b0;
        end else begin
            if (w_fire)
                b_pending_r <= 1'b1;
            if (ctrl.b_valid && ctrl.b_ready)
                b_pending_r <= 1'b0;
        end
    end

    assign ctrl.b_valid  = b_pending_r;
    assign ctrl.b.resp   = 2'b00;  // OKAY
    assign ctrl.b.user   = '0;

    // -------------------------------------------------------------------------
    // AXI-Lite read channel
    // -------------------------------------------------------------------------
    assign ctrl.ar_ready = 1'b1;  // always accept AR

    logic        r_pending_r;
    logic [31:0] r_data_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            r_pending_r <= 1'b0;
            r_data_r    <= '0;
        end else begin
            if (ctrl.ar_valid && ctrl.ar_ready) begin
                r_pending_r <= 1'b1;
                case (ctrl.ar.addr[7:0])
                    8'h00: r_data_r <= reg_public_ip;
                    8'h04: r_data_r <= {16'b0, reg_base_port};
                    8'h08: r_data_r <= {16'b0, reg_timeout};
                    8'h0C: r_data_r <= {31'b0, reg_enable};
                    8'h10: r_data_r <= {16'b0, status_active_entries, 3'b0, status_free_empty};
                    8'h14: r_data_r <= cnt_fwd_hit_r;
                    8'h18: r_data_r <= cnt_fwd_miss_r;
                    8'h1C: r_data_r <= cnt_rev_hit_r;
                    8'h20: r_data_r <= cnt_rev_miss_r;
                    8'h24: r_data_r <= cnt_bypass_r;
                    default: r_data_r <= 32'hDEAD_BEEF;
                endcase
            end
            if (ctrl.r_valid && ctrl.r_ready)
                r_pending_r <= 1'b0;
        end
    end

    assign ctrl.r_valid  = r_pending_r;
    assign ctrl.r.data   = r_data_r;
    assign ctrl.r.resp   = 2'b00;  // OKAY
    assign ctrl.r.user   = '0;

endmodule
