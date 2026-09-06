// true dual-port BRAM

module true_dual_port_bram #(
    parameter int BRAM_WIDTH = 32,
    parameter int BRAM_DEPTH = 1024,
    parameter bit INIT_VALID_ZERO = 1'b0,
    parameter int VALID_BIT_INDEX = BRAM_WIDTH - 1,
    parameter int RAM_BANK_WIDTH = 72,
    localparam int BRAM_ADDR_WIDTH = (BRAM_DEPTH <= 1) ? 1 : $clog2(BRAM_DEPTH)
) (
    input  logic                         clk,

    input  logic                         we_a,
    input  logic [BRAM_ADDR_WIDTH-1:0]   addr_a,
    input  logic [BRAM_WIDTH-1:0]        din_a,
    output logic [BRAM_WIDTH-1:0]        dout_a,

    input  logic                         we_b,
    input  logic [BRAM_ADDR_WIDTH-1:0]   addr_b,
    input  logic [BRAM_WIDTH-1:0]        din_b,
    output logic [BRAM_WIDTH-1:0]        dout_b
);

    initial begin
        if (BRAM_WIDTH <= 0) begin
            $error("true_dual_port_bram: BRAM_WIDTH must be positive");
            $finish;
        end
        if (BRAM_DEPTH <= 0) begin
            $error("true_dual_port_bram: BRAM_DEPTH must be positive");
            $finish;
        end
        if (RAM_BANK_WIDTH <= 0) begin
            $error("true_dual_port_bram: RAM_BANK_WIDTH must be positive");
            $finish;
        end
        if (VALID_BIT_INDEX < 0 || VALID_BIT_INDEX >= BRAM_WIDTH) begin
            $error("true_dual_port_bram: VALID_BIT_INDEX (%0d) out of range for BRAM_WIDTH (%0d)",
                   VALID_BIT_INDEX, BRAM_WIDTH);
            $finish;
        end
    end

    localparam int RAM_BANKS = (BRAM_WIDTH + RAM_BANK_WIDTH - 1) / RAM_BANK_WIDTH;

    generate
        for (genvar bank = 0; bank < RAM_BANKS; bank++) begin : g_ram_bank
            localparam int BANK_LO = bank * RAM_BANK_WIDTH;
            localparam int BANK_W = ((BANK_LO + RAM_BANK_WIDTH) <= BRAM_WIDTH)
                ? RAM_BANK_WIDTH : (BRAM_WIDTH - BANK_LO);

            (* ram_style = "block" *) logic [BANK_W-1:0] mem [0:BRAM_DEPTH-1];

            initial begin
                if (INIT_VALID_ZERO) begin
                    for (int i = 0; i < BRAM_DEPTH; i++) begin
                        mem[i] = '0;
                    end
                end
            end

            always_ff @(posedge clk) begin
                if (we_a) begin
                    mem[addr_a] <= din_a[BANK_LO +: BANK_W];
                end
                dout_a[BANK_LO +: BANK_W] <= mem[addr_a];
            end

            always_ff @(posedge clk) begin
                if (we_b) begin
                    mem[addr_b] <= din_b[BANK_LO +: BANK_W];
                end
                dout_b[BANK_LO +: BANK_W] <= mem[addr_b];
            end
        end
    endgenerate

endmodule
