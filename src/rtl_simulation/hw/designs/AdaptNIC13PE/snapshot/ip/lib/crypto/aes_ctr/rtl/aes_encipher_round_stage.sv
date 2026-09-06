module aes_encipher_round_stage #(
    parameter bit FINAL_ROUND = 1'b0
) (
    input  logic [127:0] state_in,
    input  logic [127:0] round_key,
    output logic [127:0] state_out
);

    logic [127:0] subbytes_state;
    logic [127:0] shiftrows_state;
    logic [127:0] mixcolumns_state;

    function automatic [7:0] gm2(input [7:0] op);
        begin
            gm2 = {op[6:0], 1'b0} ^ (8'h1b & {8{op[7]}});
        end
    endfunction

    function automatic [7:0] gm3(input [7:0] op);
        begin
            gm3 = gm2(op) ^ op;
        end
    endfunction

    function automatic [31:0] mixw(input [31:0] w);
        logic [7:0] b0, b1, b2, b3;
        logic [7:0] mb0, mb1, mb2, mb3;
        begin
            b0 = w[31:24];
            b1 = w[23:16];
            b2 = w[15:08];
            b3 = w[07:00];

            mb0 = gm2(b0) ^ gm3(b1) ^ b2      ^ b3;
            mb1 = b0      ^ gm2(b1) ^ gm3(b2) ^ b3;
            mb2 = b0      ^ b1      ^ gm2(b2) ^ gm3(b3);
            mb3 = gm3(b0) ^ b1      ^ b2      ^ gm2(b3);

            mixw = {mb0, mb1, mb2, mb3};
        end
    endfunction

    function automatic [127:0] mixcolumns(input [127:0] data);
        logic [31:0] w0, w1, w2, w3;
        logic [31:0] ws0, ws1, ws2, ws3;
        begin
            w0 = data[127:096];
            w1 = data[095:064];
            w2 = data[063:032];
            w3 = data[031:000];

            ws0 = mixw(w0);
            ws1 = mixw(w1);
            ws2 = mixw(w2);
            ws3 = mixw(w3);

            mixcolumns = {ws0, ws1, ws2, ws3};
        end
    endfunction

    function automatic [127:0] shiftrows(input [127:0] data);
        logic [31:0] w0, w1, w2, w3;
        logic [31:0] ws0, ws1, ws2, ws3;
        begin
            w0 = data[127:096];
            w1 = data[095:064];
            w2 = data[063:032];
            w3 = data[031:000];

            ws0 = {w0[31:24], w1[23:16], w2[15:08], w3[07:00]};
            ws1 = {w1[31:24], w2[23:16], w3[15:08], w0[07:00]};
            ws2 = {w2[31:24], w3[23:16], w0[15:08], w1[07:00]};
            ws3 = {w3[31:24], w0[23:16], w1[15:08], w2[07:00]};

            shiftrows = {ws0, ws1, ws2, ws3};
        end
    endfunction

    aes_sbox u_sbox0 (
        .sboxw     (state_in[127:096]),
        .new_sboxw (subbytes_state[127:096])
    );

    aes_sbox u_sbox1 (
        .sboxw     (state_in[095:064]),
        .new_sboxw (subbytes_state[095:064])
    );

    aes_sbox u_sbox2 (
        .sboxw     (state_in[063:032]),
        .new_sboxw (subbytes_state[063:032])
    );

    aes_sbox u_sbox3 (
        .sboxw     (state_in[031:000]),
        .new_sboxw (subbytes_state[031:000])
    );

    assign shiftrows_state  = shiftrows(subbytes_state);
    assign mixcolumns_state = mixcolumns(shiftrows_state);
    assign state_out        = (FINAL_ROUND ? shiftrows_state : mixcolumns_state) ^ round_key;

endmodule

`default_nettype wire
