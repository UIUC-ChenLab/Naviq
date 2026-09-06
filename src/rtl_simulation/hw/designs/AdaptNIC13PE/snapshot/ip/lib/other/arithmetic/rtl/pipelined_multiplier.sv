module pipelined_multiplier #(
    parameter int A_WIDTH = 16,
    parameter int B_WIDTH = 16,
    parameter bit SIGNED  = 1'b0
) (
    input  logic                             clk,
    input  logic                             rst_n,
    input  logic                             in_valid,
    input  logic [A_WIDTH-1:0]               a,
    input  logic [B_WIDTH-1:0]               b,
    output logic                             out_valid,
    output logic [A_WIDTH+B_WIDTH-1:0]       p
);

    logic [A_WIDTH-1:0]         a_q;
    logic [B_WIDTH-1:0]         b_q;
    logic [A_WIDTH+B_WIDTH-1:0] p_q;
    logic [1:0]                 valid_pipe;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_q        <= '0;
            b_q        <= '0;
            p_q        <= '0;
            valid_pipe <= '0;
        end else begin
            valid_pipe[0] <= in_valid;
            valid_pipe[1] <= valid_pipe[0];

            a_q <= a;
            b_q <= b;

            if (SIGNED)
                p_q <= $signed(a_q) * $signed(b_q);
            else
                p_q <= a_q * b_q;
        end
    end

    assign p         = p_q;
    assign out_valid = valid_pipe[1];

endmodule

module pipelined_multiplier_axis #(
    parameter int A_WIDTH = 16,
    parameter int B_WIDTH = 16,
    parameter bit SIGNED  = 1'b0
) (
    input  logic                       clk,
    input  logic                       resetn,

    input  logic [A_WIDTH-1:0]         s_a,
    input  logic [B_WIDTH-1:0]         s_b,
    input  logic                       s_valid,
    output logic                       s_ready,

    output logic [A_WIDTH+B_WIDTH-1:0] m_product,
    output logic                       m_valid,
    input  logic                       m_ready
);

    logic [A_WIDTH-1:0]         a_q;
    logic [B_WIDTH-1:0]         b_q;
    logic [A_WIDTH+B_WIDTH-1:0] p_q;
    logic                       ab_valid_q;
    logic                       p_valid_q;
    logic                       ab_ready;
    logic                       p_ready;

    assign p_ready = !p_valid_q || m_ready;
    assign ab_ready = !ab_valid_q || p_ready;
    assign s_ready = ab_ready;

    assign m_product = p_q;
    assign m_valid = p_valid_q;

    always_ff @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            a_q        <= '0;
            b_q        <= '0;
            p_q        <= '0;
            ab_valid_q <= 1'b0;
            p_valid_q  <= 1'b0;
        end else begin
            if (p_ready) begin
                p_valid_q <= ab_valid_q;
                if (SIGNED) begin
                    p_q <= $signed(a_q) * $signed(b_q);
                end else begin
                    p_q <= a_q * b_q;
                end
            end

            if (ab_ready) begin
                ab_valid_q <= s_valid;
                a_q <= s_a;
                b_q <= s_b;
            end
        end
    end

endmodule