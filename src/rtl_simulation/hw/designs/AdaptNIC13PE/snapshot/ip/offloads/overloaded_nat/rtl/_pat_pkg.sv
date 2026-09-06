`ifndef PAT_PKG_DEFINED
`define PAT_PKG_DEFINED

package pat_pkg;

    // -------------------------------------------------------------------------
    // Table sizing (overridable at top-level via localparam before import)
    // -------------------------------------------------------------------------
    parameter int NUM_ENTRIES   = 1024;
    parameter int ENTRY_ID_W    = $clog2(NUM_ENTRIES);          // 10
    parameter int HASH_BUCKETS  = NUM_ENTRIES * 2;              // 2048
    parameter int BUCKET_IDX_W  = $clog2(HASH_BUCKETS);         // 11
    parameter int MAX_PROBE     = 4;

    // -------------------------------------------------------------------------
    // Forward key: {protocol, private_src_ip, private_src_port,
    //               remote_dst_ip, remote_dst_port}
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic [7:0]  protocol;
        logic [31:0] src_ip;
        logic [15:0] src_port;
        logic [31:0] dst_ip;
        logic [15:0] dst_port;
    } fwd_key_t;  // 104 bits

    localparam int FWD_KEY_BITS = $bits(fwd_key_t);

    // -------------------------------------------------------------------------
    // Reverse key uses the same canonical 5-tuple layout as the forward key:
    // {protocol, src_ip, src_port, dst_ip, dst_port}
    //
    // For RX lookups this is the packet's public-facing tuple:
    // {protocol, remote_ip, remote_port, public_ip, public_port}.
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic [7:0]  protocol;
        logic [31:0] src_ip;
        logic [15:0] src_port;
        logic [31:0] dst_ip;
        logic [15:0] dst_port;
    } rev_key_t;  // 104 bits

    localparam int REV_KEY_BITS = $bits(rev_key_t);

    // -------------------------------------------------------------------------
    // Hash-table bucket entries (stored in BRAM)
    // Forward bucket: valid + full key + entry_id  (for exact-match verify)
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic                    valid;
        fwd_key_t                key;
        logic [ENTRY_ID_W-1:0]  entry_id;
    } fwd_bucket_t;

    localparam int FWD_BUCKET_BITS = $bits(fwd_bucket_t);  // 1+104+10 = 115

    typedef struct packed {
        logic                    valid;
        rev_key_t                key;
        logic [ENTRY_ID_W-1:0]  entry_id;
    } rev_bucket_t;

    localparam int REV_BUCKET_BITS = $bits(rev_bucket_t);

    // -------------------------------------------------------------------------
    // Entry metadata (indexed by entry_id, stored in separate BRAM)
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic        valid;
        logic [7:0]  protocol;
        logic [31:0] private_ip;
        logic [15:0] private_port;
        logic [31:0] remote_ip;
        logic [15:0] remote_port;
        logic [15:0] last_used;     // 16-bit wrapping timestamp
    } entry_meta_t;

    localparam int ENTRY_META_BITS = $bits(entry_meta_t);  // 121

    // -------------------------------------------------------------------------
    // Pipeline metadata passed alongside buffered packet
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic        valid;         // is a valid IPv4 TCP/UDP packet
        logic        is_outbound;   // direction (1 = outbound, 0 = inbound)
        logic [7:0]  protocol;
        logic [31:0] src_ip;
        logic [15:0] src_port;
        logic [31:0] dst_ip;
        logic [15:0] dst_port;
    } pkt_meta_t;

    localparam int PKT_META_BITS = $bits(pkt_meta_t);  // 106

    // -------------------------------------------------------------------------
    // Lookup result passed from hash table to rewrite stage
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic                    hit;
        logic                    miss;
        logic                    bypass;       // not a valid PAT packet
        logic [ENTRY_ID_W-1:0]  entry_id;
    } lookup_result_t;

    // -------------------------------------------------------------------------
    // Reclaim command (used by aging / eviction policy → core)
    // -------------------------------------------------------------------------
    typedef struct packed {
        logic [ENTRY_ID_W-1:0] entry_id;
    } reclaim_cmd_t;

endpackage

`endif
