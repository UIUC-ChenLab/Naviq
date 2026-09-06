module generic_counter #(
    parameter int WIDTH = 16,
    parameter logic [WIDTH-1:0] RESET_VALUE = '0,
    parameter logic [WIDTH-1:0] START_VALUE = RESET_VALUE,
    parameter logic [WIDTH-1:0] DEFAULT_STEP = WIDTH'(1),
    parameter bit SATURATE_AT_TERMINAL = 1'b0
) (
    input  logic             clk,
    input  logic             resetn,

    input  logic             load,
    input  logic [WIDTH-1:0] load_value,
    input  logic             enable,
    input  logic             increment,
    input  logic [WIDTH-1:0] step_value,

    output logic [WIDTH-1:0] count,
    output logic             at_zero,
    output logic             at_max,
    output logic             terminal
);

    logic [WIDTH-1:0] step;
    logic [WIDTH-1:0] next_count;

    initial begin
        if (WIDTH < 1) begin
            $error("generic_counter: WIDTH must be >= 1");
            $finish;
        end
    end

    assign step = (step_value == '0) ? DEFAULT_STEP : step_value;
    assign at_zero = (count == '0);
    assign at_max = &count;
    assign terminal = increment ? at_max : at_zero;

    always_comb begin
        if (increment) begin
            if (SATURATE_AT_TERMINAL && ({1'b0, count} + {1'b0, step}) > {1'b0, {WIDTH{1'b1}}})
                next_count = '1;
            else
                next_count = count + step;
        end else begin
            if (SATURATE_AT_TERMINAL && count < step)
                next_count = '0;
            else
                next_count = count - step;
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            count <= START_VALUE;
        end else if (load) begin
            count <= load_value;
        end else if (enable) begin
            count <= next_count;
        end
    end

endmodule
