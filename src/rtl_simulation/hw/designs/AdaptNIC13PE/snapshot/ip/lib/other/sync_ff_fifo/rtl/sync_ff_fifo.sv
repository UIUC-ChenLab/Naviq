// Generic register-backed FIFO. Parameter type T: packed payload type.
// FF storage always exposes the register-file entry at the removal pointer
// directly. EXTRA_OUTPUT_REG appends one additional elastic output register
// without reducing the requested FIFO depth.
// MODE="FULL_CAPACITY" uses same-cycle push/pop credit for the registered
// ready path. MODE="CONSERVATIVE" bases ready only on current occupancy with
// one entry of registered-ready safety margin.

module sync_ff_fifo #(
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
    localparam logic [COUNT_WIDTH:0] DEPTH_COUNT = (COUNT_WIDTH+1)'(DEPTH);
    localparam logic [COUNT_WIDTH:0] CONSERVATIVE_COUNT = (COUNT_WIDTH+1)'(DEPTH - 1);

    (* ram_style = "registers" *) logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    logic [PTR_WIDTH-1:0] head_ptr;
    logic [PTR_WIDTH-1:0] tail_ptr;
    logic [COUNT_WIDTH-1:0] count_r;
    logic                  extra_valid_r;
    logic [DATA_WIDTH-1:0] extra_data_r;
    logic                  push_ready_cut_r;

    logic [DATA_WIDTH-1:0] push_data_vec;
    logic [DATA_WIDTH-1:0] core_data;
    logic                  core_valid;
    logic                  core_pop_fire;
    logic                  push_fire;
    logic [COUNT_WIDTH:0]  ready_count_next;
    logic                  push_ready_next;

    assign push_data_vec = DATA_WIDTH'(push_data);
    assign core_valid = (count_r != '0);
    assign core_data = mem[head_ptr];
    assign core_pop_fire = EXTRA_OUTPUT_REG
        ? (extra_valid_r && pop_ready)
        : (core_valid && pop_ready);
    assign pop_valid = EXTRA_OUTPUT_REG ? extra_valid_r : core_valid;
    assign pop_data = T'(EXTRA_OUTPUT_REG ? extra_data_r : core_data);
    assign push_ready = push_ready_cut_r;
    assign push_fire = push_valid && push_ready;

    always_comb begin
        ready_count_next = {1'b0, count_r};
        case ({push_fire, core_pop_fire})
            2'b10: ready_count_next = {1'b0, count_r} + 1'b1;
            2'b01: ready_count_next = {1'b0, count_r} - 1'b1;
            default:;
        endcase

        if (MODE == "CONSERVATIVE")
            push_ready_next = ({1'b0, count_r} < CONSERVATIVE_COUNT);
        else
            push_ready_next = (ready_count_next < DEPTH_COUNT);
    end

    function automatic logic [PTR_WIDTH-1:0] f_next_ptr(logic [PTR_WIDTH-1:0] p);
        return (p == (DEPTH - 1)) ? '0 : (p + 1);
    endfunction

    initial begin
        if (DEPTH <= 0) begin
            $error("sync_ff_fifo: DEPTH must be positive");
        end

        if ((MODE != "FULL_CAPACITY") && (MODE != "CONSERVATIVE")) begin
            $error("sync_ff_fifo: unsupported MODE %s", MODE);
        end

        if ((MODE == "CONSERVATIVE") && (DEPTH < 2)) begin
            $error("sync_ff_fifo: CONSERVATIVE mode requires DEPTH >= 2");
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            head_ptr <= '0;
            tail_ptr <= '0;
            count_r <= '0;
            extra_valid_r <= 1'b0;
            push_ready_cut_r <= 1'b1;
        end else begin
            if (push_fire) begin
                mem[tail_ptr] <= push_data_vec;
                tail_ptr <= f_next_ptr(tail_ptr);
            end

            if (core_pop_fire)
                head_ptr <= f_next_ptr(head_ptr);

            case ({push_fire, core_pop_fire})
                2'b10: count_r <= count_r + 1'b1;
                2'b01: count_r <= count_r - 1'b1;
                default:;
            endcase

            if (EXTRA_OUTPUT_REG) begin
                if (core_pop_fire) begin
                    if (count_r > COUNT_WIDTH'(1)) begin
                        extra_valid_r <= 1'b1;
                        extra_data_r <= mem[f_next_ptr(head_ptr)];
                    end else if (push_fire) begin
                        // Replacing the last entry: the push targets the next
                        // head location, so bypass it into the registered view.
                        extra_valid_r <= 1'b1;
                        extra_data_r <= push_data_vec;
                    end else begin
                        extra_valid_r <= 1'b0;
                    end
                end else begin
                    // The registered output mirrors the current FIFO head.
                    // A downstream stall also stalls head_ptr, so repeatedly
                    // sampling this entry preserves AXI-Stream stability.
                    extra_valid_r <= core_valid;
                    extra_data_r <= core_data;
                end
            end

            push_ready_cut_r <= push_ready_next;
        end
    end

endmodule
