`ifndef DEMUX_SV
`define DEMUX_SV

// Generic combinational 1-to-N valid/ready demux.
//
// The selected output receives the input payload and valid. Input ready follows
// only the selected output ready. Invalid selects route to output 0 so hardware
// behavior is deterministic.
module demux #(
    parameter type T = logic,
    parameter int  NUM_OUTPUTS = 1,
    parameter int  SELECT_WIDTH = (NUM_OUTPUTS <= 1) ? 1 : $clog2(NUM_OUTPUTS),
    // AXI-style users may broadcast payload bits because they are don't-care
    // whenever the corresponding valid is low.  This avoids synthesizing a
    // wide zero/data mux on every output.
    parameter bit  BROADCAST_DATA = 1'b0
) (
    input  logic [SELECT_WIDTH-1:0] select,

    input  logic s_valid,
    input  T     s_data,
    output logic s_ready,

    output logic m_valid [NUM_OUTPUTS],
    output T     m_data  [NUM_OUTPUTS],
    input  logic m_ready [NUM_OUTPUTS]
);

    localparam int SEL_WIDTH     = (NUM_OUTPUTS <= 1) ? 1 : $clog2(NUM_OUTPUTS);
    localparam int SELECT_VALUES = 1 << SELECT_WIDTH;

    logic [SEL_WIDTH-1:0] select_safe_c;
    logic                 select_valid_c;

    if (SELECT_VALUES > NUM_OUTPUTS) begin : g_select_valid_check
        assign select_valid_c = select < SELECT_WIDTH'(NUM_OUTPUTS);
    end else begin : g_select_valid_const
        assign select_valid_c = 1'b1;
    end

    assign select_safe_c = select_valid_c ? SEL_WIDTH'(select) : '0;
    assign s_ready       = m_ready[select_safe_c];

    always_comb begin
        for (int i = 0; i < NUM_OUTPUTS; i++) begin
            m_data[i]  = BROADCAST_DATA ? s_data : '0;
            m_valid[i] = 1'b0;
        end

        if (!BROADCAST_DATA)
            m_data[select_safe_c] = s_data;
        m_valid[select_safe_c] = s_valid;
    end

`ifndef SYNTHESIS
    always_comb begin
        if (s_valid && !select_valid_c) begin
            $error("demux: invalid select %0d for NUM_OUTPUTS=%0d; routing to output 0",
                   select, NUM_OUTPUTS);
        end
    end
`endif

    initial begin
        if (NUM_OUTPUTS < 1) begin
            $error("demux: NUM_OUTPUTS must be >= 1, got %0d", NUM_OUTPUTS);
            $finish;
        end

        if (SELECT_WIDTH < SEL_WIDTH) begin
            $error("demux: SELECT_WIDTH (%0d) is too small for NUM_OUTPUTS=%0d",
                   SELECT_WIDTH, NUM_OUTPUTS);
            $finish;
        end
    end

endmodule
`endif
