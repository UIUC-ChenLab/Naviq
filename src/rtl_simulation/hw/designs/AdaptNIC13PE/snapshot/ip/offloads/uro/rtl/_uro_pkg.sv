`ifndef URO_PKG_DEFINED
`define URO_PKG_DEFINED

package uro_pkg;

    localparam int IPV4_HDR_BYTES = 20;
    localparam int UDP_HDR_BYTES  = 8;
    localparam int URO_HDR_BYTES  = IPV4_HDR_BYTES + UDP_HDR_BYTES;

    typedef struct packed {
        logic [7:0]  protocol;
        logic [31:0] src_addr;
        logic [31:0] dst_addr;
        logic [15:0] src_port;
        logic [15:0] dst_port;
    } uro_key_t;

    localparam int URO_KEY_BITS = $bits(uro_key_t);

    typedef enum logic [2:0] {
        URO_BANK_FREE    = 3'd0,
        URO_BANK_FILLING = 3'd1,
        URO_BANK_READY   = 3'd3,
        URO_BANK_DRAIN   = 3'd4
    } uro_bank_state_t;

endpackage

`endif
