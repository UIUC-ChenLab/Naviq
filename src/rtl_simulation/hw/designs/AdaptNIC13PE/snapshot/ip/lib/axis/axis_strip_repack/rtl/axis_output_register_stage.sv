// Output register (stage 3): single AXI-Stream pipeline stage (register_slice) for downstream readers.
// tid/tdest/tuser are 1-bit on the interface and intentionally left undriven (don't care).

`include "ifc_axis.sv"

module axis_output_register_stage #(
    parameter int DATA_WIDTH = 512,
    parameter string MODE      = "STANDARD",
    parameter int NUM_STAGES   = 1
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;

    typedef struct packed {
        logic [DATA_WIDTH-1:0] data;
        logic [KEEP_WIDTH-1:0] keep;
        logic                  last;
    } payload_t;

    payload_t push_data;
    payload_t pop_data;
    logic     pop_valid;

    assign push_data.data = s_axis.t.data;
    assign push_data.keep = s_axis.t.keep;
    assign push_data.last = s_axis.t.last;

    register_slice #(
        .T          (payload_t),
        .MODE       (MODE),
        .NUM_STAGES (NUM_STAGES)
    ) u_reg (
        .clk        (clk),
        .resetn     (resetn),
        .push_valid (s_axis.tvalid),
        .push_data  (push_data),
        .push_ready (s_axis.tready),
        .pop_valid  (pop_valid),
        .pop_data   (pop_data),
        .pop_ready  (m_axis.tready)
    );

    assign m_axis.tvalid = pop_valid;
    assign m_axis.t.data = pop_data.data;
    assign m_axis.t.keep = pop_data.keep;
    assign m_axis.t.last = pop_data.last;

endmodule
