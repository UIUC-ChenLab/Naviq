`ifndef AES_CTR_TUNNEL_RX_PKG_SV
`define AES_CTR_TUNNEL_RX_PKG_SV

package aes_ctr_tunnel_rx_pkg;
    localparam int IPV4_MIN_BYTES       = 20;
    localparam int ESP_PROTO            = 50;
    localparam int ESP_TUNNEL_HDR_BYTES = 12;
    localparam int ESP_NEXT_HEADER_IPV4 = 4;
endpackage

`endif
