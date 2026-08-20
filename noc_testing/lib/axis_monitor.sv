`timescale 1ns/1ps

// SystemVerilog AXI-Stream Performance Monitor
// - Measures latency and bandwidth between two monitor points (in/out).
// - Intended for simulation-only; prints statistics at the end.
// - Tracks packets based on TLAST signal.
// - Latency is measured from the start of a packet at 'in' to the end of the packet at 'out'.

module axis_monitor #(
    parameter integer TDATA_WIDTH    = 512,
    parameter integer LAT_FIFO_DEPTH = 512, // Determines how many packets can be in-flight
    parameter integer SRC_ID         = 0  // Unique identifier for this monitor instance
)(
    // Clock and reset
    input  wire aclk,
    input  wire aresetn,

    // Ingress monitor interface (e.g., before NoC)
    input  wire [TDATA_WIDTH-1:0]      in_tdata,
    input  wire                        in_tvalid,
    input  wire                        in_tready,
    input  wire                        in_tlast,
    input  wire [(TDATA_WIDTH/8)-1:0]  in_tkeep,

    // Egress monitor interface (e.g., after NoC)
    input  wire [TDATA_WIDTH-1:0]      out_tdata,
    input  wire                        out_tvalid,
    input  wire                        out_tready,
    input  wire [(TDATA_WIDTH/8)-1:0]  out_tkeep,
    input  wire                        out_tlast
);

    // --- Internal Parameter and Type Declarations ---
    localparam integer TDATA_BYTES = TDATA_WIDTH / 8;
    
    // --- Signal and Variable Declarations ---
    time      start_time;
    time      ingress_end_time;
    longint   total_bytes_in;
    longint   total_bytes_out;
    longint   total_latency;
    longint   packet_count;
    longint   min_latency;
    longint   max_latency;
    time      end_time;
    time      clk_period;
    time      last_clk_time;

    // Latency tracking FIFO
    // Stores the clock timestamp when a packet's first beat is seen at the input.
    time      latency_fifo[LAT_FIFO_DEPTH-1:0];
    integer   fifo_wr_ptr;
    integer   fifo_rd_ptr;
    integer   fifo_count;

    // --- Logic Implementation ---

    // Initial block to set initial values at the start of simulation
    initial begin
        start_time      = 0;
        ingress_end_time= 0;
        end_time        = 0;
        total_bytes_in  = 0;
        total_bytes_out = 0;
        total_latency   = 0;
        packet_count    = 0;
        min_latency     = -1; // Use -1 to indicate not yet set
        max_latency     = 0;
        fifo_wr_ptr     = 0;
        fifo_rd_ptr     = 0;
        fifo_count      = 0;
        clk_period      = 0;
        last_clk_time   = 0;
    end

    // --- Clock Period Measurement ---
    always @(posedge aclk) begin
        if (aresetn) begin
            // Capture the clock period on the second rising edge after reset
            // $time is scaled to the timescale precision (ps)
            if (last_clk_time != 0 && clk_period == 0) begin
                clk_period = $time - last_clk_time;
            end
            last_clk_time = $time;
        end else begin
            last_clk_time = 0;
            clk_period    = 0;
        end
    end
    
    // Delay tlast by one cycle to detect the start of a new packet
    reg in_tlast_d1 = 1'b1;
    always @(posedge aclk) begin
        if (!aresetn) begin
            in_tlast_d1 <= 1'b1;
        end else begin
            if (in_tvalid && in_tready) begin
               in_tlast_d1 <= in_tlast;
            end
        end
    end

    // Monitor Ingress Port
    always @(posedge aclk) begin
        if (!aresetn) begin
            // Reset logic can be added here if needed, but initial block covers simulation start
        end else begin
            // A transaction is occurring on the input
            if (in_tvalid && in_tready) begin
                // Capture the start time on the very first beat of a new stream of packets
                if (start_time == 0) begin
                    start_time = $time;
                end
                ingress_end_time = $time;
                
                // On the first beat of a packet (identified by the previous beat having TLAST asserted),
                // record its start time. in_tlast_d1 is initialized to 1 to catch the very first packet.
                if (in_tlast_d1) begin
                     if (fifo_count < LAT_FIFO_DEPTH) begin
                        latency_fifo[fifo_wr_ptr] = $time;
                        fifo_wr_ptr = (fifo_wr_ptr + 1) % LAT_FIFO_DEPTH;
                        fifo_count = fifo_count + 1;
                    end else begin
                        $display("ERROR: SRC_ID %0d :: Latency FIFO overflow at time %t ps!", SRC_ID, $time);
                    end
                end

                // Accumulate total bytes transferred
//                total_bytes_in = total_bytes_in + count_set_bits(in_tkeep);
                total_bytes_in = total_bytes_in + $countones(out_tkeep);
                
            end
        end
    end

    integer current_beat_bytes;
    
    // Monitor Egress Port
    always @(posedge aclk) begin
        if (!aresetn) begin
            // Reset logic
        end else begin
            // A transaction is occurring on the output
            if (out_tvalid && out_tready) begin
                end_time = $time; // Track the time of the last egress transaction
                // If this is the last beat of a packet, calculate latency
                if (out_tlast) begin
                    if (fifo_count > 0) begin
                        time     packet_start_time;
                        longint  current_latency;

                        packet_start_time = latency_fifo[fifo_rd_ptr];
                        fifo_rd_ptr = (fifo_rd_ptr + 1) % LAT_FIFO_DEPTH;
                        fifo_count = fifo_count - 1;
                        
                        current_latency = $time - packet_start_time;

                        // Update statistics
                        if (min_latency == -1 || current_latency < min_latency) begin
                            min_latency = current_latency;
                        end
                        if (current_latency > max_latency) begin
                            max_latency = current_latency;
                        end
                        total_latency = total_latency + current_latency;
                        packet_count = packet_count + 1;

                    end else begin
                         $display("WARNING: SRC_ID %0d :: Saw TLAST on output with no corresponding packet start at time %t. FIFO may be out of sync.", SRC_ID, $time);
                    end
                end
                 // Accumulate total bytes transferred on output for BW calculation
                current_beat_bytes = $countones(out_tkeep);

                // 2. Add it to the running total
                total_bytes_out = total_bytes_out + current_beat_bytes;
    
                // 3. Print a comprehensive debug message
//                $display("DEBUG @ %t ps: bytes_this_beat=%d, total_bytes_out=%d, tkeep=%b",
//                         $time,
//                         current_beat_bytes, // Prints the result of $countones
//                         total_bytes_out,    // Prints the longint cumulative total
//                         out_tkeep);         // Prints the tkeep value in binary
           
            end
        end
    end


    // --- Final Report Generation ---
    final begin
        real      total_time_sec;
        real      clk_period_ps;
        real      avg_latency_cycles;
        real      min_latency_cycles;
        real      max_latency_cycles;
        real      bandwidth_MBps;

        if (packet_count > 0 && clk_period > 0) begin
            // Calculations
            real duration = ingress_end_time - start_time;
//            real duration = end_time - start_time
            if (duration > 0) begin
                total_time_sec = duration * 1.0e-9; 
//                bandwidth_mbps = (total_bytes_out / total_time_sec) / (1024.0*1024.0);
            bandwidth_MBps = (total_bytes_out / total_time_sec) / 1.0e6;
            end else begin
                total_time_sec = 0;
                bandwidth_MBps = 0;
            end

            // clk_period is measured in ns (e.g., 1 for a 1ns clock); convert to ps for display.
            clk_period_ps      = clk_period * 1000.0; 

            min_latency_cycles = real'(min_latency) / real'(clk_period);
            max_latency_cycles = real'(max_latency) / real'(clk_period);
            avg_latency_cycles = (real'(total_latency) / real'(packet_count)) / real'(clk_period);

            // Print Report
            $display("=========================================================");
            $display(">>>>>> SRC_ID %0d :: AXIS_PMON :: BW ANALYSIS >>>>>>", SRC_ID);
            $display("=========================================================");
            $display("AXI Clock Period = %0.0f ps", clk_period_ps);
            $display("Min Write Latency = %0.2f axi clock cycles", min_latency_cycles);
            $display("Max Write Latency = %0.2f axi clock cycles", max_latency_cycles);
            $display("Avg Write Latency = %0.2f axi clock cycles", avg_latency_cycles);
            $display("Actual Achieved Write Bandwidth = %f MBps", bandwidth_MBps);
            $display("=========================================================");

        end else begin
            $display("=========================================================");
            $display(">>>>>> SRC_ID %0d :: AXIS_PMON :: NO TRAFFIC DETECTED >>>>>>", SRC_ID);
            $display("=========================================================");
        end
    end

endmodule


