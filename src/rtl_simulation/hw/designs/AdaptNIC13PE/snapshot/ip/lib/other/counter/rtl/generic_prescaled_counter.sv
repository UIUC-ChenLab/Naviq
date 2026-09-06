module generic_prescaled_counter #(
    parameter int COUNTER_WIDTH = 32,
    parameter int PRESCALER_WIDTH = 8,
    parameter logic [COUNTER_WIDTH-1:0] COUNTER_START_VALUE = '0
) (
    input  logic                       clk,
    input  logic                       resetn,

    input  logic                       enable,
    input  logic                       increment,
    input  logic [COUNTER_WIDTH-1:0]   step_value,
    input  logic [PRESCALER_WIDTH-1:0] prescale_value,

    output logic [COUNTER_WIDTH-1:0]   count,
    output logic [PRESCALER_WIDTH-1:0] prescale_count,
    output logic                       prescale_terminal
);

    logic unused_counter_at_zero;
    logic unused_counter_at_max;
    logic unused_counter_terminal;
    logic unused_prescale_at_zero;
    logic unused_prescale_at_max;
    logic unused_prescale_terminal;

    initial begin
        if (COUNTER_WIDTH < 1 || PRESCALER_WIDTH < 1) begin
            $error("generic_prescaled_counter: widths must be >= 1");
            $finish;
        end
    end

    assign prescale_terminal = enable && (prescale_count >= prescale_value);

    generic_counter #(
        .WIDTH(COUNTER_WIDTH),
        .START_VALUE(COUNTER_START_VALUE),
        .DEFAULT_STEP(COUNTER_WIDTH'(1)),
        .SATURATE_AT_TERMINAL(1'b0)
    ) u_counter (
        .clk(clk),
        .resetn(resetn),
        .load(1'b0),
        .load_value('0),
        .enable(prescale_terminal),
        .increment(increment),
        .step_value(step_value),
        .count(count),
        .at_zero(unused_counter_at_zero),
        .at_max(unused_counter_at_max),
        .terminal(unused_counter_terminal)
    );

    generic_counter #(
        .WIDTH(PRESCALER_WIDTH),
        .START_VALUE('0),
        .DEFAULT_STEP(PRESCALER_WIDTH'(1)),
        .SATURATE_AT_TERMINAL(1'b0)
    ) u_prescaler (
        .clk(clk),
        .resetn(resetn),
        .load(prescale_terminal),
        .load_value('0),
        .enable(enable && !prescale_terminal),
        .increment(1'b1),
        .step_value(PRESCALER_WIDTH'(1)),
        .count(prescale_count),
        .at_zero(unused_prescale_at_zero),
        .at_max(unused_prescale_at_max),
        .terminal(unused_prescale_terminal)
    );

endmodule
