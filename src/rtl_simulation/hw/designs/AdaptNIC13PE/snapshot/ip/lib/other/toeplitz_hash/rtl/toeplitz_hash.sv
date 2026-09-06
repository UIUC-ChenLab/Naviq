module toeplitz_hash #(
    parameter int HASH_WIDTH = 12,      // Must be <= 32
    parameter int TUPLE_WIDTH = 104,    // Fixed at 104 bits
    parameter bit GENERIC_TUPLE_MODE = 1'b0,
    parameter int TOEPLITZ_KEY_W = 320, // Must be at least 159 bits
    parameter logic [TOEPLITZ_KEY_W-1:0] TOEPLITZ_KEY =
        320'h6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa
) (
    input  logic [TUPLE_WIDTH-1:0] tuple_bits,
    output logic [HASH_WIDTH-1:0]  hash_value
);

    localparam int KEY_IDX_W       = $clog2(TOEPLITZ_KEY_W);
    localparam int RSS_TUPLE_WIDTH = 128;
    localparam int RSS_HASH_WIDTH  = 32;

    initial begin
        if (HASH_WIDTH < 4) begin
            $error("toeplitz_hash: HASH_WIDTH is less than 4");
            $finish;
        end
        if (HASH_WIDTH > 13) begin
            $error("toeplitz_hash: HASH_WIDTH is greater than 13");
            $finish;
        end
        if (!GENERIC_TUPLE_MODE && TUPLE_WIDTH != 104) begin
            $error("toeplitz_hash: this implementation expects TUPLE_WIDTH=104");
            $finish;
        end
        if (!GENERIC_TUPLE_MODE && TOEPLITZ_KEY_W < (RSS_TUPLE_WIDTH + RSS_HASH_WIDTH - 1)) begin
            $error("toeplitz_hash: key width (%0d) is too small for RSS tuple/hash widths (%0d/%0d)",
                   TOEPLITZ_KEY_W, RSS_TUPLE_WIDTH, RSS_HASH_WIDTH);
            $finish;
        end
        if (GENERIC_TUPLE_MODE && TOEPLITZ_KEY_W < (TUPLE_WIDTH + RSS_HASH_WIDTH - 1)) begin
            $error("toeplitz_hash: key width (%0d) is too small for generic tuple/hash widths (%0d/%0d)",
                   TOEPLITZ_KEY_W, TUPLE_WIDTH, RSS_HASH_WIDTH);
            $finish;
        end
    end

    // Returns one bit from the Toeplitz key.
    function automatic logic key_bit(
        input logic [KEY_IDX_W-1:0] idx_in
    );
        int unsigned idx;
        begin
            idx = int'(idx_in);
            key_bit = TOEPLITZ_KEY[TOEPLITZ_KEY_W-1-idx];
        end
    endfunction

    // Returns the 32-bit Toeplitz window starting at bit offset start_idx.
    function automatic logic [RSS_HASH_WIDTH-1:0] toeplitz_window_slice_rss32(
        input int unsigned start_idx
    );
        logic [RSS_HASH_WIDTH-1:0] slice;
        logic [KEY_IDX_W-1:0] idx_cast;
        int i;
        begin
            slice = '0;
            for (i = 0; i < RSS_HASH_WIDTH; i++) begin
                idx_cast = KEY_IDX_W'(start_idx + i);
                slice[RSS_HASH_WIDTH-1-i] = key_bit(idx_cast);
            end
            toeplitz_window_slice_rss32 = slice;
        end
    endfunction

    // Maps the internal 104-bit tuple to a virtual 128-bit RSS tuple:
    //   word0[31:0]   = src_ip
    //   word1[63:32]  = dst_ip
    //   word2[95:64]  = src_port | dst_port
    //   word3[127:96] = protocol << 24
    //
    // Internal tuple layout:
    //   [31:0]   = src_ip
    //   [63:32]  = dst_ip
    //   [79:64]  = src_port
    //   [95:80]  = dst_port
    //   [103:96] = protocol
    //
    // virtual bit order is walked MSB-first across the 128-bit tuple.
    function automatic logic virtual_tuple_bit(
        input logic [TUPLE_WIDTH-1:0] tuple_in,
        input int unsigned bit_idx
    ); 
        begin
            virtual_tuple_bit = 1'b0;

            if (bit_idx < 32) begin
                // word0 = src_ip
                virtual_tuple_bit = tuple_in[31 - bit_idx];
            end else if (bit_idx < 64) begin
                // word1 = dst_ip
                virtual_tuple_bit = tuple_in[95 - bit_idx];
            end else if (bit_idx < 96) begin
                // word2 = src_port | dst_port
                virtual_tuple_bit = tuple_in[159 - bit_idx];
            end else if (bit_idx < 104) begin
                // word3[31:24] = protocol
                virtual_tuple_bit = tuple_in[199 - bit_idx];
            end
            // bit_idx 104..127 => zero padding
        end
    endfunction

    // Computes the 32-bit RSS Toeplitz hash over the 128-bit tuple,
    // then truncates to HASH_WIDTH.
    function automatic logic [HASH_WIDTH-1:0] toeplitz_hash_words_dpdk(
        input logic [TUPLE_WIDTH-1:0] tuple_in
    );
        logic [RSS_HASH_WIDTH-1:0] accum  [0:31];
        logic [RSS_HASH_WIDTH-1:0] stage1 [0:15];
        logic [RSS_HASH_WIDTH-1:0] stage2 [0:7];
        logic [RSS_HASH_WIDTH-1:0] stage3 [0:3];
        logic [RSS_HASH_WIDTH-1:0] stage4 [0:1];
        logic [RSS_HASH_WIDTH-1:0] win_slice;
        logic [RSS_HASH_WIDTH-1:0] full_hash;
        int i;
        int p;
        begin
            for (i = 0; i < 32; i++) begin
                accum[i] = '0;
            end
            
            // Collect per-bit Toeplitz contributions into 32 partial XOR groups.
            for (p = 0; p < RSS_TUPLE_WIDTH; p++) begin
                if (virtual_tuple_bit(tuple_in, p)) begin
                    win_slice = toeplitz_window_slice_rss32(p);
                    accum[p % 32] = accum[p % 32] ^ win_slice;
                end
            end

            // Reduce the partial groups through a balanced XOR tree.
            for (i = 0; i < 16; i++) begin
                stage1[i] = accum[2*i] ^ accum[2*i+1];
            end
            for (i = 0; i < 8; i++) begin
                stage2[i] = stage1[2*i] ^ stage1[2*i+1];
            end
            for (i = 0; i < 4; i++) begin
                stage3[i] = stage2[2*i] ^ stage2[2*i+1];
            end

            stage4[0] = stage3[0] ^ stage3[1];
            stage4[1] = stage3[2] ^ stage3[3];

            full_hash = stage4[0] ^ stage4[1];
            toeplitz_hash_words_dpdk = full_hash[HASH_WIDTH-1:0];
        end
    endfunction

    // Generic mode walks tuple_bits MSB-first directly. This keeps the legacy
    // 104-bit RSS/DPDK mapping unchanged while allowing exact-match keys that
    // are not RSS 5-tuples.
    function automatic logic [HASH_WIDTH-1:0] toeplitz_hash_generic_msb(
        input logic [TUPLE_WIDTH-1:0] tuple_in
    );
        logic [RSS_HASH_WIDTH-1:0] accum  [0:31];
        logic [RSS_HASH_WIDTH-1:0] stage1 [0:15];
        logic [RSS_HASH_WIDTH-1:0] stage2 [0:7];
        logic [RSS_HASH_WIDTH-1:0] stage3 [0:3];
        logic [RSS_HASH_WIDTH-1:0] stage4 [0:1];
        logic [RSS_HASH_WIDTH-1:0] win_slice;
        logic [RSS_HASH_WIDTH-1:0] full_hash;
        int i;
        int p;
        begin
            for (i = 0; i < 32; i++) begin
                accum[i] = '0;
            end

            for (p = 0; p < TUPLE_WIDTH; p++) begin
                if (tuple_in[TUPLE_WIDTH - 1 - p]) begin
                    win_slice = toeplitz_window_slice_rss32(p);
                    accum[p % 32] = accum[p % 32] ^ win_slice;
                end
            end

            for (i = 0; i < 16; i++) begin
                stage1[i] = accum[2*i] ^ accum[2*i+1];
            end
            for (i = 0; i < 8; i++) begin
                stage2[i] = stage1[2*i] ^ stage1[2*i+1];
            end
            for (i = 0; i < 4; i++) begin
                stage3[i] = stage2[2*i] ^ stage2[2*i+1];
            end

            stage4[0] = stage3[0] ^ stage3[1];
            stage4[1] = stage3[2] ^ stage3[3];

            full_hash = stage4[0] ^ stage4[1];
            toeplitz_hash_generic_msb = full_hash[HASH_WIDTH-1:0];
        end
    endfunction

    generate
        if (GENERIC_TUPLE_MODE) begin : g_generic_tuple
            assign hash_value = toeplitz_hash_generic_msb(tuple_bits);
        end else begin : g_rss_tuple
            assign hash_value = toeplitz_hash_words_dpdk(tuple_bits);
        end
    endgenerate

endmodule
