// Generic synchronous-read BRAM FIFO with a registered output slot.
// Parameter type T: packed payload type (e.g. packed struct). Backpressure when full.
// EXTRA_OUTPUT_REG appends one additional elastic output register without
// reducing the requested FIFO depth.
// MODE="FULL_CAPACITY" uses same-cycle push/pop credit for the registered
// ready path. MODE="CONSERVATIVE" bases ready only on current occupancy with
// one entry of registered-ready safety margin.

module sync_bram_fifo #(
    parameter int DEPTH = 16,
    parameter type T = logic,
    parameter bit EXTRA_OUTPUT_REG = 1'b0,
    parameter string MODE = "FULL_CAPACITY"
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

    localparam int DATA_WIDTH  = $bits(T);
    localparam int PTR_WIDTH   = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
    localparam int COUNT_WIDTH = $clog2(DEPTH + 1);

    localparam int RAM_BANK_WIDTH = 72;
    localparam int RAM_BANKS      = (DATA_WIDTH + RAM_BANK_WIDTH - 1) / RAM_BANK_WIDTH;
    localparam logic [COUNT_WIDTH:0] DEPTH_COUNT = (COUNT_WIDTH+1)'(DEPTH);
    localparam logic [COUNT_WIDTH:0] CONSERVATIVE_COUNT = (COUNT_WIDTH+1)'(DEPTH - 1);

    logic [PTR_WIDTH-1:0] head_ptr;
    logic [PTR_WIDTH-1:0] tail_ptr;
    logic [COUNT_WIDTH-1:0] ram_count;

    logic                  out_valid_r;
    logic [DATA_WIDTH-1:0] out_data_r;
    logic                  extra_valid_r;
    logic [DATA_WIDTH-1:0] extra_data_r;
    logic                  read_pending_r;
    logic [DATA_WIDTH-1:0] ram_read_data_r;

    logic [DATA_WIDTH-1:0] push_data_vec;
    assign push_data_vec = DATA_WIDTH'(push_data);

    logic [COUNT_WIDTH-1:0] total_count;
    logic [COUNT_WIDTH:0]   total_count_next;
    logic                   push_ready_next;
    logic                   push_ready_cut_r;

    logic push_fire;
    logic core_pop_ready;
    logic core_pop_fire;
    logic output_slot_free;
    logic pending_to_output;
    logic read_pending_stalls;
    logic read_pending_next;
    logic ram_read_fire;
    logic push_to_ram;

    assign pop_valid        = EXTRA_OUTPUT_REG ? extra_valid_r : out_valid_r;
    assign pop_data         = T'(EXTRA_OUTPUT_REG ? extra_data_r : out_data_r);
    assign core_pop_ready   = EXTRA_OUTPUT_REG ? (!extra_valid_r || pop_ready) : pop_ready;
    assign core_pop_fire    = out_valid_r && core_pop_ready;
    assign push_ready       = push_ready_cut_r;
    assign push_fire        = push_valid && push_ready;
    assign output_slot_free = !out_valid_r || core_pop_fire;

    assign total_count = ram_count + COUNT_WIDTH'(out_valid_r) + COUNT_WIDTH'(read_pending_r);

    // The core FIFO has one registered output slot and one pending RAM-read
    // register. EXTRA_OUTPUT_REG adds a stage after this core and is not counted
    // against DEPTH.
    assign pending_to_output  = output_slot_free && read_pending_r;
    assign read_pending_stalls = read_pending_r && !pending_to_output;
    assign read_pending_next = read_pending_stalls || ram_read_fire;

    assign ram_read_fire = (ram_count != '0) && !read_pending_stalls;
    assign push_to_ram = push_fire;

    generate
        for (genvar bank = 0; bank < RAM_BANKS; bank++) begin : g_ram_bank
            localparam int BANK_LO = bank * RAM_BANK_WIDTH;
            localparam int BANK_W  = ((BANK_LO + RAM_BANK_WIDTH) <= DATA_WIDTH)
                ? RAM_BANK_WIDTH : (DATA_WIDTH - BANK_LO);

            (* ram_style = "block" *) logic [BANK_W-1:0] mem [0:DEPTH-1];
            logic [BANK_W-1:0] bank_read_data_r;

            assign ram_read_data_r[BANK_LO +: BANK_W] = bank_read_data_r;

            always_ff @(posedge clk) begin
                if (push_to_ram) begin
                    mem[tail_ptr] <= push_data_vec[BANK_LO +: BANK_W];
                end
                if (ram_read_fire) begin
                    bank_read_data_r <= mem[head_ptr];
                end
            end
        end
    endgenerate

    always_comb begin
        total_count_next = {1'b0, total_count};
        case ({push_fire, core_pop_fire})
            2'b10: total_count_next = {1'b0, total_count} + 1'b1;
            2'b01: total_count_next = {1'b0, total_count} - 1'b1;
            default:;
        endcase

        if (MODE == "CONSERVATIVE")
            push_ready_next = ({1'b0, total_count} < CONSERVATIVE_COUNT);
        else
            push_ready_next = (total_count_next < DEPTH_COUNT);
    end

    function automatic logic [PTR_WIDTH-1:0] f_next_ptr(logic [PTR_WIDTH-1:0] p);
        return (p == (DEPTH - 1)) ? '0 : (p + 1);
    endfunction

    initial begin
        if (DEPTH <= 0) begin
            $error("sync_bram_fifo: DEPTH must be positive");
        end

        if ((MODE != "FULL_CAPACITY") && (MODE != "CONSERVATIVE")) begin
            $error("sync_bram_fifo: unsupported MODE %s", MODE);
        end

        if ((MODE == "CONSERVATIVE") && (DEPTH < 2)) begin
            $error("sync_bram_fifo: CONSERVATIVE mode requires DEPTH >= 2");
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            head_ptr           <= '0;
            tail_ptr           <= '0;
            ram_count          <= '0;
            out_valid_r        <= 1'b0;
            extra_valid_r      <= 1'b0;
            read_pending_r     <= 1'b0;
            push_ready_cut_r   <= 1'b1;
        end else begin
            if (push_to_ram) begin
                tail_ptr <= f_next_ptr(tail_ptr);
            end

            if (ram_read_fire) begin
                head_ptr <= f_next_ptr(head_ptr);
            end

            case ({push_to_ram, ram_read_fire})
                2'b10: ram_count <= ram_count + 1'b1;
                2'b01: ram_count <= ram_count - 1'b1;
                default:;
            endcase

            if (pending_to_output) begin
                out_data_r  <= ram_read_data_r;
                out_valid_r <= 1'b1;
            end else if (core_pop_fire) begin
                out_valid_r <= 1'b0;
            end

            if (EXTRA_OUTPUT_REG && core_pop_ready) begin
                extra_valid_r <= out_valid_r;
                if (out_valid_r)
                    extra_data_r <= out_data_r;
            end

            read_pending_r <= read_pending_next;
            push_ready_cut_r <= push_ready_next;
        end
    end

endmodule
