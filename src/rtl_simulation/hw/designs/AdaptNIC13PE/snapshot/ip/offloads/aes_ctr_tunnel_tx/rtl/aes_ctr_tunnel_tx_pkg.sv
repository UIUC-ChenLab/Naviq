`ifndef AES_CTR_TUNNEL_TX_PKG_SV
`define AES_CTR_TUNNEL_TX_PKG_SV

package aes_ctr_tunnel_tx_pkg;

    localparam int AES_BLOCK_BITS  = 128;
    localparam int AES_BLOCK_BYTES = 16;
    localparam int AES_KEY_BITS    = 256;
    localparam int AES_KEY_WORDS   = AES_KEY_BITS / 32;

    localparam int IPV4_MIN_BYTES       = 20;
    localparam int ESP_PROTO            = 50;
    localparam int ESP_TUNNEL_HDR_BYTES = 12;
    localparam int ESP_NEXT_HEADER_IPV4 = 4;

    localparam int SA_ENTRY_WORDS = 16;
    localparam int SA_WORD_VALID  = 0;
    localparam int SA_WORD_OUTER_SRC = 1;
    localparam int SA_WORD_OUTER_DST = 2;
    localparam int SA_WORD_SALT      = 3;
    localparam int SA_WORD_KEY_BASE  = 4;
    localparam int SA_WORD_SEQ_LO    = 12;
    localparam int SA_WORD_SEQ_HI    = 13;

    localparam logic [31:0] TX_SA_BASE_ADDR    = 32'h0000_0000;
    // Each TX SA occupies the 16 words below.  A 64-byte stride keeps the
    // complete TX control map inside the packet engine's 0x40000 aperture.
    localparam int TX_SA_STRIDE = 64;
    localparam logic [31:0] TX_MATCH_BASE_ADDR = 32'h0001_0000;
    localparam logic [31:0] TX_TUNNEL_BASE_ADDR = 32'h0002_0000;
    localparam int TX_RAW_FIFO_DEPTH = 256;
    localparam int TX_DESC_FIFO_DEPTH = 16;

    localparam int MATCH_ENTRY_WORDS = 4;
    localparam int MATCH_WORD_VALID  = 0;
    localparam int MATCH_WORD_HASH   = 1;
    localparam int MATCH_WORD_SA_ID  = 2;

    typedef struct packed {
        logic        valid;
        logic [31:0] outer_src_ip;
        logic [31:0] outer_dst_ip;
        logic [31:0] salt;
        logic [255:0] key;
        logic [63:0] next_seq;
    } sa_entry_t;

    function automatic int unsigned esp_pad_len_4(input int unsigned inner_len);
        esp_pad_len_4 = (4 - ((inner_len + 2) & 3)) & 3;
    endfunction

endpackage

`endif
