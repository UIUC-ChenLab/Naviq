// Simple dual-port BRAM: one synchronous write port and one synchronous read port.

module simple_dual_port_bram #(
    parameter int BRAM_WIDTH = 32,
    parameter int BRAM_DEPTH = 1024,
    localparam int BRAM_ADDR_WIDTH = (BRAM_DEPTH <= 1) ? 1 : $clog2(BRAM_DEPTH)
) (
    input  logic                       clk,

    input  logic                       we_w,
    input  logic [BRAM_ADDR_WIDTH-1:0] addr_w,
    input  logic [BRAM_WIDTH-1:0]      din_w,

    input  logic [BRAM_ADDR_WIDTH-1:0] addr_r,
    output logic [BRAM_WIDTH-1:0]      dout_r
);

    logic [BRAM_WIDTH-1:0] mem[BRAM_DEPTH];

    always_ff @(posedge clk) begin
        if (we_w)
            mem[addr_w] <= din_w;
        dout_r <= mem[addr_r];
    end

endmodule
