// Generic valid/ready register slice.
//
// MODE="STANDARD": NUM_STAGES one-entry elastic stages. This is the lowest-area
// pipeline mode, but ready can propagate combinationally through the stages.
// MODE="ISOLATE": NUM_STAGES-entry relay queue with a registered output slot.
// push_ready is driven only from registered occupancy, so downstream ready does
// not feed upstream ready.

module register_slice #(
    parameter type T = logic,
    parameter string MODE = "STANDARD",
    parameter int NUM_STAGES = 1
) (
    input  logic clk,
    input  logic resetn,

    input  logic push_valid,
    input  T     push_data,
    output logic push_ready,

    output logic pop_valid,
    output T     pop_data,
    input  logic pop_ready
);

    initial begin
        if (NUM_STAGES < 1)
            $error("register_slice: NUM_STAGES (%0d) must be >= 1", NUM_STAGES);
        if ((MODE == "ISOLATE") && (NUM_STAGES < 2))
            $error("register_slice: MODE=ISOLATE requires NUM_STAGES >= 2");
    end

    generate
        if (MODE == "STANDARD") begin : g_register
            logic [NUM_STAGES-1:0] stage_valid_r;
            logic [NUM_STAGES-1:0] stage_ready;
            T stage_data_r [NUM_STAGES];

            // Preserve the old single-stage debug hierarchy used by a few tests.
            logic full;
            assign full = stage_valid_r[0];

            logic [NUM_STAGES:0] valid_bus;
            logic [NUM_STAGES:0] ready_bus;
            T data_bus [NUM_STAGES + 1];

            assign valid_bus[0] = push_valid;
            assign data_bus[0]  = push_data;
            assign push_ready   = ready_bus[0];

            assign pop_valid = valid_bus[NUM_STAGES];
            assign pop_data  = data_bus[NUM_STAGES];
            assign ready_bus[NUM_STAGES] = pop_ready;

            for (genvar i = 0; i < NUM_STAGES; i++) begin : g_stage
                assign valid_bus[i + 1] = stage_valid_r[i];
                assign data_bus[i + 1]  = stage_data_r[i];
                assign stage_ready[i]   = !stage_valid_r[i] || ready_bus[i + 1];
                assign ready_bus[i]     = stage_ready[i];

                always_ff @(posedge clk) begin
                    if (!resetn) begin
                        stage_valid_r[i] <= 1'b0;
                    end else if (ready_bus[i]) begin
                        stage_valid_r[i] <= valid_bus[i];
                        // Data is don't-care while valid is low. Loading it
                        // whenever the slot advances prevents valid/control
                        // logic from becoming a wide register-enable path.
                        stage_data_r[i] <= data_bus[i];
                    end
                end
            end
        end else if (MODE == "ISOLATE") begin : g_isolate
            localparam int RAM_DEPTH = NUM_STAGES - 1;
            localparam int PTR_W     = (RAM_DEPTH <= 1) ? 1 : $clog2(RAM_DEPTH);
            localparam int COUNT_W   = $clog2(NUM_STAGES + 1);

            T fifo_data_r [RAM_DEPTH];
            T out_data_r;
            logic [PTR_W-1:0] wr_ptr_r;
            logic [PTR_W-1:0] rd_ptr_r;
            logic [COUNT_W-1:0] ram_count_r;
            logic [COUNT_W-1:0] count_r;
            logic out_valid_r;

            logic push_fire;
            logic pop_fire;
            logic output_slot_free;
            logic ram_to_output;
            logic push_to_output;
            logic push_to_ram;

            function automatic logic [PTR_W-1:0] ptr_inc(input logic [PTR_W-1:0] ptr);
                if (ptr == PTR_W'(RAM_DEPTH - 1))
                    ptr_inc = '0;
                else
                    ptr_inc = ptr + PTR_W'(1'b1);
            endfunction

            assign push_ready = (count_r < COUNT_W'(NUM_STAGES));
            assign pop_valid  = out_valid_r;
            assign pop_data   = out_data_r;

            assign push_fire = push_valid && push_ready;
            assign pop_fire  = pop_valid && pop_ready;
            assign output_slot_free = !out_valid_r || pop_fire;
            assign ram_to_output = output_slot_free && (ram_count_r != '0);
            assign push_to_output = output_slot_free && (ram_count_r == '0) && push_fire;
            assign push_to_ram = push_fire && !push_to_output;

            always_ff @(posedge clk) begin
                if (!resetn) begin
                    wr_ptr_r <= '0;
                    rd_ptr_r <= '0;
                    ram_count_r <= '0;
                    count_r <= '0;
                    out_valid_r <= 1'b0;
                end else begin
                    if (push_to_ram) begin
                        fifo_data_r[wr_ptr_r] <= push_data;
                        wr_ptr_r <= ptr_inc(wr_ptr_r);
                    end

                    if (ram_to_output)
                        rd_ptr_r <= ptr_inc(rd_ptr_r);

                    if (output_slot_free) begin
                        // output_slot_free is already established by the outer
                        // condition. Select the data source only from registered
                        // RAM occupancy so downstream ready does not also feed
                        // the wide output-data mux select.
                        if (ram_count_r != '0) begin
                            out_valid_r <= 1'b1;
                            out_data_r <= fifo_data_r[rd_ptr_r];
                        end else begin
                            out_valid_r <= push_to_output;
                            // As above, invalid data is don't-care; do not put
                            // valid on the wide data-register enable path.
                            out_data_r <= push_data;
                        end
                    end

                    unique case ({push_to_ram, ram_to_output})
                        2'b10: ram_count_r <= ram_count_r + COUNT_W'(1'b1);
                        2'b01: ram_count_r <= ram_count_r - COUNT_W'(1'b1);
                        default: ram_count_r <= ram_count_r;
                    endcase

                    unique case ({push_fire, pop_fire})
                        2'b10: count_r <= count_r + COUNT_W'(1'b1);
                        2'b01: count_r <= count_r - COUNT_W'(1'b1);
                        default: count_r <= count_r;
                    endcase
                end
            end
        end else begin : g_invalid_mode
            initial $error("register_slice: unsupported MODE '%s'", MODE);
        end
    endgenerate

endmodule
