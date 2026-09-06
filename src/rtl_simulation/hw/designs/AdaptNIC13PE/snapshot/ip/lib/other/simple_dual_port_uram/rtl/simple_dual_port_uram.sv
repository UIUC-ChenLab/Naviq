module simple_dual_port_uram #(
    parameter int URAM_WIDTH = 72,
    parameter int URAM_DEPTH = 4096,
    parameter bit EXTRA_OUTPUT_REG = 1'b0,
    localparam int URAM_ADDR_WIDTH = (URAM_DEPTH <= 1) ? 1 : $clog2(URAM_DEPTH)
) (
    input  logic                       clk,
    input  logic                       we_w,
    input  logic [URAM_ADDR_WIDTH-1:0] addr_w,
    input  logic [URAM_WIDTH-1:0]      din_w,
    input  logic [URAM_ADDR_WIDTH-1:0] addr_r,
    output logic [URAM_WIDTH-1:0]      dout_r
);

    localparam int NATIVE_URAM_WIDTH = 72;
    localparam int NATIVE_URAM_DEPTH = 4096;
    localparam int WIDTH_BANKS = (URAM_WIDTH + NATIVE_URAM_WIDTH - 1) / NATIVE_URAM_WIDTH;
    localparam int DEPTH_BANKS = (URAM_DEPTH + NATIVE_URAM_DEPTH - 1) / NATIVE_URAM_DEPTH;

    initial begin
        if (URAM_WIDTH <= 0) begin
            $error("simple_dual_port_uram: URAM_WIDTH must be positive");
            $finish;
        end
        if (URAM_DEPTH <= 0) begin
            $error("simple_dual_port_uram: URAM_DEPTH must be positive");
            $finish;
        end
    end

    generate
        for (genvar bank = 0; bank < WIDTH_BANKS; bank++) begin : g_width_bank
            localparam int BANK_LO = bank * NATIVE_URAM_WIDTH;
            localparam int BANK_WIDTH = ((BANK_LO + NATIVE_URAM_WIDTH) <= URAM_WIDTH)
                ? NATIVE_URAM_WIDTH : (URAM_WIDTH - BANK_LO);

            (* ram_style = "ultra", ram_decomp = "power", cascade_height = DEPTH_BANKS *)
            logic [BANK_WIDTH-1:0] mem [0:URAM_DEPTH-1];
            logic [BANK_WIDTH-1:0] ram_dout;

            always_ff @(posedge clk) begin
                if (we_w) begin
                    mem[addr_w] <= din_w[BANK_LO +: BANK_WIDTH];
                end
                ram_dout <= mem[addr_r];
            end

            if (EXTRA_OUTPUT_REG) begin : g_extra_output_reg
                logic [BANK_WIDTH-1:0] output_reg;

                always_ff @(posedge clk) begin
                    output_reg <= ram_dout;
                end

                assign dout_r[BANK_LO +: BANK_WIDTH] = output_reg;
            end else begin : g_no_extra_output_reg
                assign dout_r[BANK_LO +: BANK_WIDTH] = ram_dout;
            end
        end
    endgenerate

endmodule
