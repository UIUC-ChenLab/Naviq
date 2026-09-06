module accumulator #(
    parameter int unsigned DATA_BIT_WIDTH = 64,
    parameter logic [DATA_BIT_WIDTH-1:0] INITIAL_VALUE = '0
) (
    input  logic                        clk,
    input  logic                        resetn,

    input  logic                        clear,
    input  logic                        enable,
    input  logic [DATA_BIT_WIDTH-1:0]   accumulate_value,
    output logic [DATA_BIT_WIDTH-1:0]   out
);

    logic [DATA_BIT_WIDTH-1:0] acc;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            acc <= INITIAL_VALUE;
        end else if (clear && enable) begin
            // Clear in the same cycle as an add (e.g. new packet first beat)
            acc <= INITIAL_VALUE + accumulate_value;
        end else if (clear) begin
            acc <= INITIAL_VALUE;
        end else if (enable) begin
            acc <= acc + accumulate_value;
        end
    end

    assign out = acc;

endmodule