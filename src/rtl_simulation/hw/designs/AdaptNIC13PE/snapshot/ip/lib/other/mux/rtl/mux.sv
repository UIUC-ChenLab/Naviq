`ifndef MUX_SV
`define MUX_SV

// Generic combinational N-to-1 valid/ready mux.
//
// The selected input drives the output payload and valid. Only the selected
// input receives downstream ready. Invalid selects route from input 0 so
// hardware behavior is deterministic.
module mux #(
    parameter type T = logic,
    parameter int  NUM_INPUTS = 1,
    parameter int  SELECT_WIDTH = (NUM_INPUTS <= 1) ? 1 : $clog2(NUM_INPUTS)
) (
    input  logic [SELECT_WIDTH-1:0] select,

    input  logic s_valid [NUM_INPUTS],
    input  T     s_data  [NUM_INPUTS],
    output logic s_ready [NUM_INPUTS],

    output logic m_valid,
    output T     m_data,
    input  logic m_ready
);

    localparam int SEL_WIDTH     = (NUM_INPUTS <= 1) ? 1 : $clog2(NUM_INPUTS);
    localparam int SELECT_VALUES = 1 << SELECT_WIDTH;

    logic [SEL_WIDTH-1:0] select_safe_c;
    logic                 select_valid_c;

    if (SELECT_VALUES > NUM_INPUTS) begin : g_select_valid_check
        assign select_valid_c = select < SELECT_WIDTH'(NUM_INPUTS);
    end else begin : g_select_valid_const
        assign select_valid_c = 1'b1;
    end

    assign select_safe_c = select_valid_c ? SEL_WIDTH'(select) : '0;
    assign m_valid       = s_valid[select_safe_c];
    assign m_data        = s_data[select_safe_c];

    for (genvar i = 0; i < NUM_INPUTS; i++) begin : g_inputs
        assign s_ready[i] = (select_safe_c == SEL_WIDTH'(i)) ? m_ready : 1'b0;
    end

`ifndef SYNTHESIS
    always_comb begin
        if (!select_valid_c) begin
            $error("mux: invalid select %0d for NUM_INPUTS=%0d; routing from input 0",
                   select, NUM_INPUTS);
        end
    end
`endif

    initial begin
        if (NUM_INPUTS < 1) begin
            $error("mux: NUM_INPUTS must be >= 1, got %0d", NUM_INPUTS);
            $finish;
        end

        if (SELECT_WIDTH < SEL_WIDTH) begin
            $error("mux: SELECT_WIDTH (%0d) is too small for NUM_INPUTS=%0d",
                   SELECT_WIDTH, NUM_INPUTS);
            $finish;
        end
    end

endmodule
`endif
