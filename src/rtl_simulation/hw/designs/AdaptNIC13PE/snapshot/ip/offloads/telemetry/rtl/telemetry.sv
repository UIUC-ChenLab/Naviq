// Telemetry - parameterized AXI Stream datapath + AXIL slave for counters / status.

`include "parser_pkg.sv"

module telemetry #(
    parameter int unsigned NUM_TRACKED_FLOWS    = 4096,
    parameter int unsigned TOTAL_BYTES_WIDTH    = 32,
    parameter int unsigned TOTAL_PACKETS_WIDTH  = 32,
    parameter int unsigned DATA_WIDTH = 512
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  packet_in,
    ifc_axil.slave  ctrl_in,
    ifc_axis.master packet_out
);

    initial begin
        if (NUM_TRACKED_FLOWS < 1) begin
            $error("telemetry: NUM_TRACKED_FLOWS (%0d) must be >= 1", NUM_TRACKED_FLOWS);
            $finish;
        end
        if (TOTAL_BYTES_WIDTH < 1) begin
            $error("telemetry: TOTAL_BYTES_WIDTH (%0d) must be >= 1", TOTAL_BYTES_WIDTH);
            $finish;
        end
        if (TOTAL_PACKETS_WIDTH < 1) begin
            $error("telemetry: TOTAL_PACKETS_WIDTH (%0d) must be >= 1", TOTAL_PACKETS_WIDTH);
            $finish;
        end
        if (DATA_WIDTH < 8 || DATA_WIDTH % 8 != 0 || (DATA_WIDTH & (DATA_WIDTH - 1)) != 0) begin
            $error("telemetry: DATA_WIDTH must be a byte-aligned power of two >= 8, got %0d",
                   DATA_WIDTH);
            $finish;
        end
        if ($bits(packet_in.t.data) != DATA_WIDTH) begin
            $error("telemetry: packet_in.t.data width (%0d) must equal DATA_WIDTH (%0d)",
                   $bits(packet_in.t.data), DATA_WIDTH);
            $finish;
        end
        if ($bits(packet_out.t.data) != DATA_WIDTH) begin
            $error("telemetry: packet_out.t.data width (%0d) must equal DATA_WIDTH (%0d)",
                   $bits(packet_out.t.data), DATA_WIDTH);
            $finish;
        end
        if ($bits(packet_in.t.id) != 1 || $bits(packet_in.t.dest) != 1 || $bits(packet_in.t.user) != 1 ||
            $bits(packet_out.t.id) != 1 || $bits(packet_out.t.dest) != 1 || $bits(packet_out.t.user) != 1) begin
            $error("telemetry: AXIS id/dest/user sidebands are unsupported and must be 1 bit wide");
            $finish;
        end
    end

    localparam int HASH_WIDTH   = 12;
    localparam int FLOW_ADDR_W  = $clog2(NUM_TRACKED_FLOWS);
    localparam int FLOW_STATS_W = TOTAL_BYTES_WIDTH + TOTAL_PACKETS_WIDTH;
    localparam int HASH_FIFO_DEPTH = 32;
    localparam int HASH_FIFO_ADDR_W = $clog2(HASH_FIFO_DEPTH);

    function automatic int unsigned next_pow2(input int unsigned value);
        int unsigned result;
        begin
            result = 1;
            while (result < value)
                result = result << 1;
            return result;
        end
    endfunction

    localparam int unsigned HASH_AXIS_MIN_WIDTH = (HASH_WIDTH > FLOW_ADDR_W) ? HASH_WIDTH : FLOW_ADDR_W;
    localparam int unsigned HASH_AXIS_DATA_WIDTH = next_pow2((HASH_AXIS_MIN_WIDTH < 8) ? 8 : HASH_AXIS_MIN_WIDTH);

    logic datapath_resetn;
    logic init_busy;
    logic [FLOW_ADDR_W-1:0] init_addr;
    logic                   bram_we;
    logic [FLOW_ADDR_W-1:0] bram_addr_w;
    logic [FLOW_STATS_W-1:0] bram_din_w;

    assign datapath_resetn = resetn && !init_busy;

    // wires
    logic accumulate_valid;
    logic accumulate_ready;
    logic [TOTAL_BYTES_WIDTH-1:0]   packet_bytes_out;
    logic [TOTAL_BYTES_WIDTH-1:0]   total_bytes;
    logic [TOTAL_PACKETS_WIDTH-1:0] total_packets;
    logic [TOTAL_PACKETS_WIDTH-1:0] total_udp_packets;
    logic [TOTAL_PACKETS_WIDTH-1:0] total_tcp_packets;
    logic [TOTAL_BYTES_WIDTH-1:0]   current_packet_bytes;


    ifc_axis #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) calculation_split (
        .axis_aclk (clk)
    );


    ifc_axis #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) hash_packet_in (
        .axis_aclk (clk)
    );

    ifc_axis #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) hash_packet_q (
        .axis_aclk (clk)
    );

    ifc_axis #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) accumulator_packet_cut_in (
        .axis_aclk (clk)
    );

    ifc_axis #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) accumulator_packet_in (
        .axis_aclk (clk)
    );

    // parse_and_hash_packet hash beat; hash in t.data[HASH_WIDTH-1:0].
    ifc_axis #(
        .DATA_WIDTH (HASH_AXIS_DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) hash_axis (
        .axis_aclk (clk)
    );

    ifc_axis #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) axis_split_1_out [2] (
        .axis_aclk (clk)
    );

    axis_multicast #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1),
        .NUM_DESTS (2)
    ) u_axis_split_1 (
        .clk (clk),
        .resetn (datapath_resetn),

        .s_axis(packet_in),
        .m_axis(axis_split_1_out)
    );

    assign packet_out.t = axis_split_1_out[0].t;
    assign packet_out.tvalid = axis_split_1_out[0].tvalid;
    assign axis_split_1_out[0].tready = packet_out.tready;
    assign calculation_split.t = axis_split_1_out[1].t;
    assign calculation_split.tvalid = axis_split_1_out[1].tvalid;
    assign axis_split_1_out[1].tready = calculation_split.tready;

    ifc_axis #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1)
    ) axis_split_2_out [2] (
        .axis_aclk (clk)
    );

    axis_multicast #(
        .DATA_WIDTH (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH (1),
        .TUSER_WIDTH (1),
        .NUM_DESTS (2)
    ) u_axis_split_2 (
        .clk (clk),
        .resetn (datapath_resetn),

        .s_axis(calculation_split),
        .m_axis(axis_split_2_out)
    );

    assign hash_packet_in.t = axis_split_2_out[0].t;
    assign hash_packet_in.tvalid = axis_split_2_out[0].tvalid;
    assign axis_split_2_out[0].tready = hash_packet_in.tready;
    assign accumulator_packet_cut_in.t = axis_split_2_out[1].t;
    assign accumulator_packet_cut_in.tvalid = axis_split_2_out[1].tvalid;
    assign axis_split_2_out[1].tready = accumulator_packet_cut_in.tready;

    axis_fifo #(
        .DEPTH            (32),
        .USE_BRAM         (1'b1),
        .EXTRA_OUTPUT_REG (1'b1),
        .MODE             ("CONSERVATIVE")
    ) u_hash_packet_q (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (hash_packet_in),
        .m_axis (hash_packet_q)
    );

    axis_register_slice #(
        .MODE ("ISOLATE"),
        .NUM_STAGES (2)
    ) u_accumulator_packet_ready_cut (
        .clk    (clk),
        .resetn (datapath_resetn),
        .s_axis (accumulator_packet_cut_in),
        .m_axis (accumulator_packet_in)
    );

    // get address
    parse_and_hash_packet #(
        .DATA_WIDTH (DATA_WIDTH),
        .OUTPUT_DATA_WIDTH (HASH_AXIS_DATA_WIDTH),
        .TDEST_WIDTH       (1),
        .TID_WIDTH         (1),
        .TUSER_WIDTH       (1)
    ) u_parse_and_hash_packet (
        .clk        (clk),
        .resetn     (datapath_resetn),
        .packet_in  (hash_packet_q),
        .packet_out (hash_axis)
    );


    logic bram_transaction;

    logic [FLOW_ADDR_W-1:0] hash_fifo_addr[HASH_FIFO_DEPTH];
    logic [HASH_FIFO_ADDR_W-1:0] hash_fifo_wr_ptr;
    logic [HASH_FIFO_ADDR_W-1:0] hash_fifo_rd_ptr;
    logic [HASH_FIFO_ADDR_W:0]   hash_fifo_count;
    logic                        hash_fifo_push;
    logic                        hash_fifo_pop;
    logic                        hash_fifo_full;
    logic                        hash_fifo_valid;
    logic [FLOW_ADDR_W-1:0]      hash_fifo_addr_out;

    assign hash_fifo_valid       = (hash_fifo_count != '0);
    assign hash_fifo_full        = (hash_fifo_count == HASH_FIFO_DEPTH);
    assign hash_fifo_addr_out    = hash_fifo_addr[hash_fifo_rd_ptr];
    assign hash_fifo_pop         = bram_transaction;
    assign hash_axis.tready      = !hash_fifo_full || hash_fifo_pop;
    assign hash_fifo_push        = hash_axis.tvalid && hash_axis.tready;

    assign bram_transaction = hash_fifo_valid && accumulate_valid;
    assign accumulate_ready = hash_fifo_valid;

    // accumulators
    telemetry_accumulators #(
        .DATA_WIDTH (DATA_WIDTH),
        .TOTAL_BYTES_WIDTH (TOTAL_BYTES_WIDTH),
        .TOTAL_PACKETS_WIDTH (TOTAL_PACKETS_WIDTH)
    ) u_telemetry_accumulators (
        .clk (clk),
        .resetn (datapath_resetn),
        .s_axis_in (accumulator_packet_in),

        .packet_protocol_valid (1'b0),
        .packet_protocol ('0),

        .out_valid(accumulate_valid),
        .out_ready(accumulate_ready),
        .packet_bytes_out(packet_bytes_out),
        .current_packet_bytes(current_packet_bytes),
        .total_bytes(total_bytes),
        .total_packets (total_packets),
        .total_udp_packets (total_udp_packets),
        .total_tcp_packets (total_tcp_packets)
    );

    // write to bram
    logic                           rmw_read_valid;
    logic [FLOW_ADDR_W-1:0]         rmw_read_addr;
    logic [TOTAL_BYTES_WIDTH-1:0]   rmw_read_packet_bytes;
    logic                           rmw_exec_valid;
    logic [FLOW_ADDR_W-1:0]         rmw_exec_addr;
    logic [TOTAL_BYTES_WIDTH-1:0]   rmw_exec_packet_bytes;
    logic [FLOW_STATS_W-1:0]        rmw_exec_base;
    logic [FLOW_STATS_W-1:0]        bram_write_data;
    logic                           last_write_valid;
    logic [FLOW_ADDR_W-1:0]         last_write_addr;
    logic [FLOW_STATS_W-1:0]        last_write_data;

    // BRAM word layout: [packet_count | byte_count] (MSB..LSB).
    assign bram_write_data = {
        rmw_exec_base[FLOW_STATS_W-1:TOTAL_BYTES_WIDTH] + 1'b1,
        rmw_exec_base[TOTAL_BYTES_WIDTH-1:0] + rmw_exec_packet_bytes
    };

    always_ff @(posedge clk) begin
        if (!resetn) begin
            hash_fifo_wr_ptr <= '0;
            hash_fifo_rd_ptr <= '0;
            hash_fifo_count  <= '0;
            rmw_read_valid      <= '0;
            rmw_read_addr       <= '0;
            rmw_read_packet_bytes <= '0;
            rmw_exec_valid      <= '0;
            rmw_exec_addr       <= '0;
            rmw_exec_packet_bytes <= '0;
            rmw_exec_base       <= '0;
            last_write_valid    <= '0;
            last_write_addr     <= '0;
            last_write_data     <= '0;
        end else begin
            if (hash_fifo_push) begin
                hash_fifo_addr[hash_fifo_wr_ptr] <= hash_axis.t.data[FLOW_ADDR_W-1:0];
            end

            unique case ({hash_fifo_push, hash_fifo_pop})
                2'b10: begin
                    hash_fifo_wr_ptr <= hash_fifo_wr_ptr + 1'b1;
                    hash_fifo_count  <= hash_fifo_count + 1'b1;
                end
                2'b01: begin
                    hash_fifo_rd_ptr <= hash_fifo_rd_ptr + 1'b1;
                    hash_fifo_count  <= hash_fifo_count - 1'b1;
                end
                2'b11: begin
                    hash_fifo_wr_ptr <= hash_fifo_wr_ptr + 1'b1;
                    hash_fifo_rd_ptr <= hash_fifo_rd_ptr + 1'b1;
                end
                default: begin
                    hash_fifo_wr_ptr <= hash_fifo_wr_ptr;
                    hash_fifo_rd_ptr <= hash_fifo_rd_ptr;
                    hash_fifo_count  <= hash_fifo_count;
                end
            endcase

            if (rmw_exec_valid) begin
                last_write_valid <= 1'b1;
                last_write_addr  <= rmw_exec_addr;
                last_write_data  <= bram_write_data;
            end

            rmw_exec_valid <= rmw_read_valid;
            rmw_exec_addr  <= rmw_read_addr;
            rmw_exec_packet_bytes <= rmw_read_packet_bytes;
            if (rmw_exec_valid && (rmw_exec_addr == rmw_read_addr))
                rmw_exec_base <= bram_write_data;
            else if (last_write_valid && (last_write_addr == rmw_read_addr))
                rmw_exec_base <= last_write_data;
            else
                rmw_exec_base <= flow_stats;

            rmw_read_valid <= bram_transaction;
            if (bram_transaction) begin
                rmw_read_addr         <= hash_fifo_addr_out;
                rmw_read_packet_bytes <= packet_bytes_out;
            end
        end
    end

    logic [FLOW_STATS_W-1:0] flow_stats;
    logic [FLOW_STATS_W-1:0] flow_stats_axil;

    function automatic logic [31:0] flow_stats_dword(
        input logic [FLOW_STATS_W-1:0] value,
        input logic [1:0]              dword_idx
    );
        flow_stats_dword = '0;
        for (int bit_idx = 0; bit_idx < 32; bit_idx++) begin
            if ((int'(dword_idx) * 32 + bit_idx) < FLOW_STATS_W)
                flow_stats_dword[bit_idx] = value[int'(dword_idx) * 32 + bit_idx];
        end
    endfunction

    assign bram_we     = init_busy || rmw_exec_valid;
    assign bram_addr_w = init_busy ? init_addr : rmw_exec_addr;
    assign bram_din_w  = init_busy ? '0 : bram_write_data;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            init_busy <= 1'b1;
            init_addr <= '0;
        end else if (init_busy) begin
            if (init_addr == FLOW_ADDR_W'(NUM_TRACKED_FLOWS - 1)) begin
                init_busy <= 1'b0;
            end else begin
                init_addr <= init_addr + 1'b1;
            end
        end
    end

    // AXIL map (32-bit word addresses = byte_addr >> 2):
    //   Flow rows are packed as byte counter dwords followed by packet counter dwords.
    //   For the default harness configuration this is two 32b dwords per flow:
    //     [flow*8 + 0] bytes[31:0], [flow*8 + 4] packets[31:0].
    //   [NUM_FLOW_BYTES + 0] total_bytes[31:0]
    //   [NUM_FLOW_BYTES + 4] total_packets[31:0]
    //   [NUM_FLOW_BYTES + 8] current_packet_bytes[31:0]
    localparam int unsigned FLOW_STATS_DWORDS    = (FLOW_STATS_W + 31) / 32;
    localparam int unsigned BYTES_PER_FLOW_SLOT  = FLOW_STATS_DWORDS * 4;
    localparam int unsigned FLOW_SLOT_ADDR_LSB   = $clog2(BYTES_PER_FLOW_SLOT);
    localparam int unsigned NUM_FLOW_BYTES       = NUM_TRACKED_FLOWS * BYTES_PER_FLOW_SLOT;

    logic [FLOW_ADDR_W-1:0] bram_addr_r1;

    bram_2r1w #(
        .BRAM_WIDTH (FLOW_STATS_W),
        .BRAM_DEPTH (NUM_TRACKED_FLOWS)
    ) telemetry_bram (
        .clk (clk),
        .we_w(bram_we),
        .addr_w(bram_addr_w),
        .din_w(bram_din_w),
        .addr_r0(hash_fifo_addr_out),
        .dout_r0(flow_stats),
        .addr_r1(bram_addr_r1),
        .dout_r1(flow_stats_axil)
    );

    // -------------------------------------------------------------------------
    // AXI4-Lite slave (reads: per-flow BRAM via port 1 + global CSRs; writes: acknowledge only)
    // -------------------------------------------------------------------------

    // // AXI Lite FSM to read from BRAM or global counters
    // // AXIL read path to be implemented (CSR / FIFO to host).
    // assign ctrl_in.aw_ready = 1'b1;
    // assign ctrl_in.w_ready  = 1'b1;
    // assign ctrl_in.ar_ready = 1'b1;
    // assign ctrl_in.b        = '0;
    // assign ctrl_in.b_valid  = 1'b0;
    // assign ctrl_in.r        = '0;
    // assign ctrl_in.r_valid  = 1'b0;
    
    typedef enum logic [2:0] {
        AXIL_RD_IDLE,
        AXIL_RD_WAIT_BRAM,
        AXIL_RD_BRAM_DOUT,
        AXIL_RD_WAIT_R
    } axil_rd_state_t;

    axil_rd_state_t axil_rd_state;
    logic [1:0]     axil_bram_dw_q;

    assign ctrl_in.ar_ready = (axil_rd_state == AXIL_RD_IDLE) && !(ctrl_in.r_valid && !ctrl_in.r_ready);

    // Write: single-beat aw+w -> b (no storage)
    logic axil_b_valid_r;
    always_ff @(posedge clk) begin
        if (!resetn)
            axil_b_valid_r <= 1'b0;
        else begin
            if (ctrl_in.b_valid && ctrl_in.b_ready)
                axil_b_valid_r <= 1'b0;
            else if (ctrl_in.aw_valid && ctrl_in.aw_ready && ctrl_in.w_valid && ctrl_in.w_ready)
                axil_b_valid_r <= 1'b1;
        end
    end

    assign ctrl_in.aw_ready = ctrl_in.w_valid && (!axil_b_valid_r || ctrl_in.b_ready);
    assign ctrl_in.w_ready  = ctrl_in.aw_valid && (!axil_b_valid_r || ctrl_in.b_ready);
    assign ctrl_in.b_valid  = axil_b_valid_r;
    assign ctrl_in.b.resp   = 2'b00;
    assign ctrl_in.b.user   = '0;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            axil_rd_state   <= AXIL_RD_IDLE;
            axil_bram_dw_q  <= '0;
            bram_addr_r1    <= '0;
            ctrl_in.r_valid <= 1'b0;
            ctrl_in.r.data  <= '0;
            ctrl_in.r.resp  <= 2'b00;
            ctrl_in.r.user  <= '0;
        end else begin
            unique case (axil_rd_state)
                AXIL_RD_IDLE: begin
                    if (ctrl_in.ar_valid && ctrl_in.ar_ready) begin
                        axil_bram_dw_q <= ctrl_in.ar.addr[3:2];
                        if (ctrl_in.ar.addr[1:0] != 2'b00) begin
                            // Unaligned
                            ctrl_in.r_valid <= 1'b1;
                            ctrl_in.r.data  <= 32'h0;
                            ctrl_in.r.resp  <= 2'b10;
                            axil_rd_state   <= AXIL_RD_WAIT_R;
                        end else if (ctrl_in.ar.addr < 32'(NUM_FLOW_BYTES)) begin
                            bram_addr_r1    <= ctrl_in.ar.addr[FLOW_ADDR_W+FLOW_SLOT_ADDR_LSB-1:FLOW_SLOT_ADDR_LSB];
                            axil_bram_dw_q  <= ctrl_in.ar.addr[FLOW_SLOT_ADDR_LSB-1:2];
                            axil_rd_state   <= AXIL_RD_WAIT_BRAM;
                        end else if (ctrl_in.ar.addr >= 32'(NUM_FLOW_BYTES) &&
                                     ctrl_in.ar.addr < 32'(NUM_FLOW_BYTES) + 32'd12) begin
                            unique case ((ctrl_in.ar.addr - 32'(NUM_FLOW_BYTES)) >> 2)
                                2'd0: begin
                                    ctrl_in.r.data <= total_bytes[31:0];
                                    ctrl_in.r.resp <= 2'b00;
                                end
                                2'd1: begin
                                    ctrl_in.r.data <= total_packets[31:0];
                                    ctrl_in.r.resp <= 2'b00;
                                end
                                2'd2: begin
                                    ctrl_in.r.data <= current_packet_bytes[31:0];
                                    ctrl_in.r.resp <= 2'b00;
                                end
                                default: begin
                                    ctrl_in.r.data <= 32'h0;
                                    ctrl_in.r.resp <= 2'b10;
                                end
                            endcase
                            ctrl_in.r_valid <= 1'b1;
                            axil_rd_state   <= AXIL_RD_WAIT_R;
                        end else begin
                            ctrl_in.r_valid <= 1'b1;
                            ctrl_in.r.data  <= 32'h0;
                            ctrl_in.r.resp  <= 2'b10;
                            axil_rd_state   <= AXIL_RD_WAIT_R;
                        end
                    end
                end
                AXIL_RD_WAIT_BRAM: begin
                    // Synchronous BRAM dout updates one cycle after addr_r1; wait one cycle then sample.
                    axil_rd_state <= AXIL_RD_BRAM_DOUT;
                end
                AXIL_RD_BRAM_DOUT: begin
                    ctrl_in.r_valid <= 1'b1;
                    ctrl_in.r.resp  <= 2'b00;
                    ctrl_in.r.data  <= flow_stats_dword(flow_stats_axil, axil_bram_dw_q);
                    axil_rd_state <= AXIL_RD_WAIT_R;
                end
                AXIL_RD_WAIT_R: begin
                    if (ctrl_in.r_valid && ctrl_in.r_ready) begin
                        ctrl_in.r_valid <= 1'b0;
                        axil_rd_state   <= AXIL_RD_IDLE;
                    end
                end
                default: axil_rd_state <= AXIL_RD_IDLE;
            endcase
        end
    end

endmodule
