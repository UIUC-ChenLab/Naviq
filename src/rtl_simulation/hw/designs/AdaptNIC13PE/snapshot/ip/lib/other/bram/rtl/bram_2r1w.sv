// 2-read / 1-write BRAM built from two simple dual-port BRAMs.
//
// - One write port for parallel writes into both BRAM instances (same addr/data/we).
// - Read port 0 reads only BRAM 0.
// - Read port 1 reads only BRAM 1.

module bram_2r1w #(
    parameter int BRAM_WIDTH = 32,
    parameter int BRAM_DEPTH = 1024,
    localparam int BRAM_ADDR_WIDTH = (BRAM_DEPTH <= 1) ? 1 : $clog2(BRAM_DEPTH)
) (
    input  logic                       clk,

    // Write port (mirrored to both BRAMs)
    input  logic                       we_w,
    input  logic [BRAM_ADDR_WIDTH-1:0] addr_w,
    input  logic [BRAM_WIDTH-1:0]      din_w,

    // Read port 0 (BRAM 0 only)
    input  logic [BRAM_ADDR_WIDTH-1:0] addr_r0,
    output logic [BRAM_WIDTH-1:0]      dout_r0,

    // Read port 1 (BRAM 1 only)
    input  logic [BRAM_ADDR_WIDTH-1:0] addr_r1,
    output logic [BRAM_WIDTH-1:0]      dout_r1
);

    // BRAM 0: read0 + shared write
    simple_dual_port_bram #(
        .BRAM_WIDTH(BRAM_WIDTH),
        .BRAM_DEPTH(BRAM_DEPTH)
    ) u_bram0 (
        .clk   (clk),

        .we_w  (we_w),
        .addr_w(addr_w),
        .din_w (din_w),

        .addr_r(addr_r0),
        .dout_r(dout_r0)
    );

    // BRAM 1: read1 + shared write
    simple_dual_port_bram #(
        .BRAM_WIDTH(BRAM_WIDTH),
        .BRAM_DEPTH(BRAM_DEPTH)
    ) u_bram1 (
        .clk   (clk),

        .we_w  (we_w),
        .addr_w(addr_w),
        .din_w (din_w),

        .addr_r(addr_r1),
        .dout_r(dout_r1)
    );

endmodule
