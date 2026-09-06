`ifndef PARSER_PKG_DEFINED
`define PARSER_PKG_DEFINED

package parser_pkg;

    // -------------------------------------------------------------------------
    // Layer parser status and classification
    // -------------------------------------------------------------------------
    typedef enum logic [7:0] {
        PARSER_STATUS_OK        = 8'd0,
        PARSER_STATUS_SHORT     = 8'd1,
        PARSER_STATUS_MALFORMED = 8'd2,
        PARSER_STATUS_OTHER     = 8'd3,
        PARSER_STATUS_FRAGMENT  = 8'd4,
        PARSER_STATUS_SKIPPED   = 8'd5
    } parser_status_t;

    typedef enum logic [7:0] {
        L2_KIND_ETHERNET = 8'd1,
        L2_KIND_OTHER    = 8'd255
    } l2_kind_t;

    typedef enum logic [7:0] {
        L3_KIND_IPV4  = 8'd1,
        L3_KIND_OTHER = 8'd255
    } l3_kind_t;

    typedef enum logic [7:0] {
        L4_KIND_TCP   = 8'd6,
        L4_KIND_UDP   = 8'd17,
        L4_KIND_OTHER = 8'd255
    } l4_kind_t;

    // -------------------------------------------------------------------------
    // Ethernet II header - 14 bytes
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic [47:0] dst_mac;
        logic [47:0] src_mac;
        logic [15:0] ethertype;
    } ethernet_hdr_t;

    // -------------------------------------------------------------------------
    // IPv4 base header (RFC 791) - options are not represented in this parser.
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic [3:0]  version;
        logic [3:0]  ihl;
        logic [5:0]  dscp;
        logic [1:0]  ecn;
        logic [15:0] total_length;
        logic [15:0] identification;
        logic [2:0]  flags;
        logic [12:0] fragment_offset;
        logic [7:0]  ttl;
        logic [7:0]  protocol;
        logic [15:0] header_checksum;
        logic [31:0] src_addr;
        logic [31:0] dst_addr;
    } ipv4_hdr_t;

    localparam int IPV4_PROTOCOL_W = 8;

    // -------------------------------------------------------------------------
    // UDP header (RFC 768) - 8 bytes
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic [15:0] src_port;
        logic [15:0] dst_port;
        logic [15:0] length;
        logic [15:0] checksum;
    } udp_hdr_t;

    // -------------------------------------------------------------------------
    // TCP base header (RFC 793) - options are not represented in this parser.
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic [15:0] src_port;
        logic [15:0] dst_port;
        logic [31:0] seq_num;
        logic [31:0] ack_num;
        logic [3:0]  data_offset;  // header length in 32-bit words
        logic [2:0]  reserved;
        logic        ns;           // ECN-nonce (RFC 3540)
        logic        cwr;          // congestion window reduced
        logic        ece;          // ECN echo
        logic        urg;
        logic        ack;
        logic        psh;
        logic        rst;
        logic        syn;
        logic        fin;
        logic [15:0] window;
        logic [15:0] checksum;
        logic [15:0] urgent_ptr;
    } tcp_hdr_t;

    // -------------------------------------------------------------------------
    // Packet-aligned layer header records carried on AXIS header streams.
    // -------------------------------------------------------------------------
    typedef struct packed {
        parser_status_t status;
        l2_kind_t       kind;
        logic [15:0]    header_len;
        logic [15:0]    ethertype;
        ethernet_hdr_t  ethernet;
    } l2_hdr_axis_t;

    typedef struct packed {
        parser_status_t status;
        l3_kind_t       kind;
        logic [15:0]    header_len;
        logic [15:0]    ethertype;
        logic [7:0]     protocol;
        logic [7:0]     pad;
        ipv4_hdr_t      ipv4;
    } l3_hdr_axis_t;

    typedef struct packed {
        parser_status_t status;
        l4_kind_t       kind;
        logic [15:0]    header_len;
        logic [7:0]     protocol;
        logic [7:0]     pad;
        tcp_hdr_t       tcp;
        udp_hdr_t       udp;
    } l4_hdr_axis_t;

    // TCP psuedo-header for checksum (without the payload)
    typedef struct packed {
        logic [31:0] src_addr;
        logic [31:0] dst_addr;
        logic [7:0]  zeroes;
        logic [7:0]  protocol;
        logic [15:0] length;
        logic [15:0] src_port;
        logic [15:0] dst_port;
        logic [31:0] seq_num;
        logic [31:0] ack_num;
        logic [3:0]  data_offset;
        logic [2:0]  reserved;
        logic        ns;           // ECN-nonce (RFC 3540)
        logic        cwr;          // congestion window reduced
        logic        ece;          // ECN echo
        logic        urg;
        logic        ack;
        logic        psh;
        logic        rst;
        logic        syn;
        logic        fin;
        logic [15:0] window;
        logic [15:0] checksum;
        logic [15:0] urgent_ptr;
    } tcp_pseudo_hdr_t;

    // UDP pseudo-header for checksum (RFC pseudo 12B + UDP header with checksum zeroed)
    typedef struct packed {
        logic [31:0] src_addr;
        logic [31:0] dst_addr;
        logic [7:0]  zero;
        logic [7:0]  protocol;
        logic [15:0] pseudo_length;  // L4 length field in 12-byte pseudo (same as udp_hdr.length)
        logic [15:0] src_port;
        logic [15:0] dst_port;
        logic [15:0] udp_length;      // UDP header length field (duplicate wire value)
        logic [15:0] checksum;        // forced to 0 for checksum accumulation
    } udp_pseudo_hdr_t;

    // Width constants for packing into AXIS tdata
    localparam int IPV4_HDR_BITS = $bits(ipv4_hdr_t);
    localparam int TCP_HDR_BITS  = $bits(tcp_hdr_t);
    localparam int UDP_HDR_BITS  = $bits(udp_hdr_t);
    localparam int ETHERNET_HDR_BITS = $bits(ethernet_hdr_t);
    localparam int L2_HDR_AXIS_BITS  = $bits(l2_hdr_axis_t);
    localparam int L3_HDR_AXIS_BITS  = $bits(l3_hdr_axis_t);
    localparam int L4_HDR_AXIS_BITS  = $bits(l4_hdr_axis_t);
    localparam int UDP_PSEUDO_HDR_BITS = $bits(udp_pseudo_hdr_t);
    localparam int TCP_PSEUDO_HDR_BITS = $bits(tcp_pseudo_hdr_t);
    localparam int PSEUDO_HDR_BITS_MAX = (TCP_PSEUDO_HDR_BITS > UDP_PSEUDO_HDR_BITS)
        ? TCP_PSEUDO_HDR_BITS
        : UDP_PSEUDO_HDR_BITS;


    // Pack parsed headers into packet wire byte order: byte 0 occupies bits [7:0].
    function automatic logic [IPV4_HDR_BITS-1:0] pack_ipv4_hdr_wire(input ipv4_hdr_t hdr);
        pack_ipv4_hdr_wire = '0;
        pack_ipv4_hdr_wire[8*0 +: 8] = {hdr.version, hdr.ihl};
        pack_ipv4_hdr_wire[8*1 +: 8] = {hdr.dscp, hdr.ecn};
        pack_ipv4_hdr_wire[8*2 +: 8] = hdr.total_length[15:8];
        pack_ipv4_hdr_wire[8*3 +: 8] = hdr.total_length[7:0];
        pack_ipv4_hdr_wire[8*4 +: 8] = hdr.identification[15:8];
        pack_ipv4_hdr_wire[8*5 +: 8] = hdr.identification[7:0];
        pack_ipv4_hdr_wire[8*6 +: 8] = {hdr.flags, hdr.fragment_offset[12:8]};
        pack_ipv4_hdr_wire[8*7 +: 8] = hdr.fragment_offset[7:0];
        pack_ipv4_hdr_wire[8*8 +: 8] = hdr.ttl;
        pack_ipv4_hdr_wire[8*9 +: 8] = hdr.protocol;
        pack_ipv4_hdr_wire[8*10 +: 8] = hdr.header_checksum[15:8];
        pack_ipv4_hdr_wire[8*11 +: 8] = hdr.header_checksum[7:0];
        pack_ipv4_hdr_wire[8*12 +: 8] = hdr.src_addr[31:24];
        pack_ipv4_hdr_wire[8*13 +: 8] = hdr.src_addr[23:16];
        pack_ipv4_hdr_wire[8*14 +: 8] = hdr.src_addr[15:8];
        pack_ipv4_hdr_wire[8*15 +: 8] = hdr.src_addr[7:0];
        pack_ipv4_hdr_wire[8*16 +: 8] = hdr.dst_addr[31:24];
        pack_ipv4_hdr_wire[8*17 +: 8] = hdr.dst_addr[23:16];
        pack_ipv4_hdr_wire[8*18 +: 8] = hdr.dst_addr[15:8];
        pack_ipv4_hdr_wire[8*19 +: 8] = hdr.dst_addr[7:0];
    endfunction

    function automatic logic [TCP_HDR_BITS-1:0] pack_tcp_hdr_wire(input tcp_hdr_t hdr);
        pack_tcp_hdr_wire = '0;
        pack_tcp_hdr_wire[8*0 +: 8] = hdr.src_port[15:8];
        pack_tcp_hdr_wire[8*1 +: 8] = hdr.src_port[7:0];
        pack_tcp_hdr_wire[8*2 +: 8] = hdr.dst_port[15:8];
        pack_tcp_hdr_wire[8*3 +: 8] = hdr.dst_port[7:0];
        pack_tcp_hdr_wire[8*4 +: 8] = hdr.seq_num[31:24];
        pack_tcp_hdr_wire[8*5 +: 8] = hdr.seq_num[23:16];
        pack_tcp_hdr_wire[8*6 +: 8] = hdr.seq_num[15:8];
        pack_tcp_hdr_wire[8*7 +: 8] = hdr.seq_num[7:0];
        pack_tcp_hdr_wire[8*8 +: 8] = hdr.ack_num[31:24];
        pack_tcp_hdr_wire[8*9 +: 8] = hdr.ack_num[23:16];
        pack_tcp_hdr_wire[8*10 +: 8] = hdr.ack_num[15:8];
        pack_tcp_hdr_wire[8*11 +: 8] = hdr.ack_num[7:0];
        pack_tcp_hdr_wire[8*12 +: 8] = {hdr.data_offset, hdr.reserved, hdr.ns};
        pack_tcp_hdr_wire[8*13 +: 8] = {hdr.cwr, hdr.ece, hdr.urg, hdr.ack, hdr.psh, hdr.rst, hdr.syn, hdr.fin};
        pack_tcp_hdr_wire[8*14 +: 8] = hdr.window[15:8];
        pack_tcp_hdr_wire[8*15 +: 8] = hdr.window[7:0];
        pack_tcp_hdr_wire[8*16 +: 8] = hdr.checksum[15:8];
        pack_tcp_hdr_wire[8*17 +: 8] = hdr.checksum[7:0];
        pack_tcp_hdr_wire[8*18 +: 8] = hdr.urgent_ptr[15:8];
        pack_tcp_hdr_wire[8*19 +: 8] = hdr.urgent_ptr[7:0];
    endfunction

    function automatic logic [UDP_HDR_BITS-1:0] pack_udp_hdr_wire(input udp_hdr_t hdr);
        pack_udp_hdr_wire = '0;
        pack_udp_hdr_wire[8*0 +: 8] = hdr.src_port[15:8];
        pack_udp_hdr_wire[8*1 +: 8] = hdr.src_port[7:0];
        pack_udp_hdr_wire[8*2 +: 8] = hdr.dst_port[15:8];
        pack_udp_hdr_wire[8*3 +: 8] = hdr.dst_port[7:0];
        pack_udp_hdr_wire[8*4 +: 8] = hdr.length[15:8];
        pack_udp_hdr_wire[8*5 +: 8] = hdr.length[7:0];
        pack_udp_hdr_wire[8*6 +: 8] = hdr.checksum[15:8];
        pack_udp_hdr_wire[8*7 +: 8] = hdr.checksum[7:0];
    endfunction


    function automatic logic [TCP_PSEUDO_HDR_BITS-1:0] pack_tcp_pseudo_hdr_wire(input tcp_pseudo_hdr_t hdr);
        pack_tcp_pseudo_hdr_wire = '0;
        pack_tcp_pseudo_hdr_wire[8*0 +: 8] = hdr.src_addr[31:24];
        pack_tcp_pseudo_hdr_wire[8*1 +: 8] = hdr.src_addr[23:16];
        pack_tcp_pseudo_hdr_wire[8*2 +: 8] = hdr.src_addr[15:8];
        pack_tcp_pseudo_hdr_wire[8*3 +: 8] = hdr.src_addr[7:0];
        pack_tcp_pseudo_hdr_wire[8*4 +: 8] = hdr.dst_addr[31:24];
        pack_tcp_pseudo_hdr_wire[8*5 +: 8] = hdr.dst_addr[23:16];
        pack_tcp_pseudo_hdr_wire[8*6 +: 8] = hdr.dst_addr[15:8];
        pack_tcp_pseudo_hdr_wire[8*7 +: 8] = hdr.dst_addr[7:0];
        pack_tcp_pseudo_hdr_wire[8*8 +: 8] = hdr.zeroes;
        pack_tcp_pseudo_hdr_wire[8*9 +: 8] = hdr.protocol;
        pack_tcp_pseudo_hdr_wire[8*10 +: 8] = hdr.length[15:8];
        pack_tcp_pseudo_hdr_wire[8*11 +: 8] = hdr.length[7:0];
        pack_tcp_pseudo_hdr_wire[8*12 +: 8] = hdr.src_port[15:8];
        pack_tcp_pseudo_hdr_wire[8*13 +: 8] = hdr.src_port[7:0];
        pack_tcp_pseudo_hdr_wire[8*14 +: 8] = hdr.dst_port[15:8];
        pack_tcp_pseudo_hdr_wire[8*15 +: 8] = hdr.dst_port[7:0];
        pack_tcp_pseudo_hdr_wire[8*16 +: 8] = hdr.seq_num[31:24];
        pack_tcp_pseudo_hdr_wire[8*17 +: 8] = hdr.seq_num[23:16];
        pack_tcp_pseudo_hdr_wire[8*18 +: 8] = hdr.seq_num[15:8];
        pack_tcp_pseudo_hdr_wire[8*19 +: 8] = hdr.seq_num[7:0];
        pack_tcp_pseudo_hdr_wire[8*20 +: 8] = hdr.ack_num[31:24];
        pack_tcp_pseudo_hdr_wire[8*21 +: 8] = hdr.ack_num[23:16];
        pack_tcp_pseudo_hdr_wire[8*22 +: 8] = hdr.ack_num[15:8];
        pack_tcp_pseudo_hdr_wire[8*23 +: 8] = hdr.ack_num[7:0];
        pack_tcp_pseudo_hdr_wire[8*24 +: 8] = {hdr.data_offset, hdr.reserved, hdr.ns};
        pack_tcp_pseudo_hdr_wire[8*25 +: 8] = {hdr.cwr, hdr.ece, hdr.urg, hdr.ack, hdr.psh, hdr.rst, hdr.syn, hdr.fin};
        pack_tcp_pseudo_hdr_wire[8*26 +: 8] = hdr.window[15:8];
        pack_tcp_pseudo_hdr_wire[8*27 +: 8] = hdr.window[7:0];
        pack_tcp_pseudo_hdr_wire[8*28 +: 8] = hdr.checksum[15:8];
        pack_tcp_pseudo_hdr_wire[8*29 +: 8] = hdr.checksum[7:0];
        pack_tcp_pseudo_hdr_wire[8*30 +: 8] = hdr.urgent_ptr[15:8];
        pack_tcp_pseudo_hdr_wire[8*31 +: 8] = hdr.urgent_ptr[7:0];
    endfunction

    function automatic logic [UDP_PSEUDO_HDR_BITS-1:0] pack_udp_pseudo_hdr_wire(input udp_pseudo_hdr_t hdr);
        pack_udp_pseudo_hdr_wire = '0;
        pack_udp_pseudo_hdr_wire[8*0 +: 8] = hdr.src_addr[31:24];
        pack_udp_pseudo_hdr_wire[8*1 +: 8] = hdr.src_addr[23:16];
        pack_udp_pseudo_hdr_wire[8*2 +: 8] = hdr.src_addr[15:8];
        pack_udp_pseudo_hdr_wire[8*3 +: 8] = hdr.src_addr[7:0];
        pack_udp_pseudo_hdr_wire[8*4 +: 8] = hdr.dst_addr[31:24];
        pack_udp_pseudo_hdr_wire[8*5 +: 8] = hdr.dst_addr[23:16];
        pack_udp_pseudo_hdr_wire[8*6 +: 8] = hdr.dst_addr[15:8];
        pack_udp_pseudo_hdr_wire[8*7 +: 8] = hdr.dst_addr[7:0];
        pack_udp_pseudo_hdr_wire[8*8 +: 8] = hdr.zero;
        pack_udp_pseudo_hdr_wire[8*9 +: 8] = hdr.protocol;
        pack_udp_pseudo_hdr_wire[8*10 +: 8] = hdr.pseudo_length[15:8];
        pack_udp_pseudo_hdr_wire[8*11 +: 8] = hdr.pseudo_length[7:0];
        pack_udp_pseudo_hdr_wire[8*12 +: 8] = hdr.src_port[15:8];
        pack_udp_pseudo_hdr_wire[8*13 +: 8] = hdr.src_port[7:0];
        pack_udp_pseudo_hdr_wire[8*14 +: 8] = hdr.dst_port[15:8];
        pack_udp_pseudo_hdr_wire[8*15 +: 8] = hdr.dst_port[7:0];
        pack_udp_pseudo_hdr_wire[8*16 +: 8] = hdr.udp_length[15:8];
        pack_udp_pseudo_hdr_wire[8*17 +: 8] = hdr.udp_length[7:0];
        pack_udp_pseudo_hdr_wire[8*18 +: 8] = hdr.checksum[15:8];
        pack_udp_pseudo_hdr_wire[8*19 +: 8] = hdr.checksum[7:0];
    endfunction

    // -------------------------------------------------------------------------
    // L4 protocol classification
    // -------------------------------------------------------------------------
    typedef enum logic [7:0] {
        L4_TCP     = 8'd6,
        L4_UDP     = 8'd17,
        L4_UNKNOWN = 8'd0
    } l4_proto_t;

    function automatic l4_proto_t ipv4_l4_proto(input ipv4_hdr_t hdr);
        case (hdr.protocol)
            8'd6:    return L4_TCP;
            8'd17:   return L4_UDP;
            default: return L4_UNKNOWN;
        endcase
    endfunction

endpackage

`endif
