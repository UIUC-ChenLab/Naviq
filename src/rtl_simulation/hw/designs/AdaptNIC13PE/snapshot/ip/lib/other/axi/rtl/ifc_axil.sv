`ifndef IFC_AXIL_SV
`define IFC_AXIL_SV
interface ifc_axil #(
    parameter int ADDR_WIDTH   = 32,
    parameter int DATA_WIDTH   = 32,
    parameter int TUSER_WIDTH  = 1,
    // Optional sideband widths; when 0, the bus is 1 bit wide
    parameter int AWUSER_WIDTH = TUSER_WIDTH,
    parameter int WUSER_WIDTH  = TUSER_WIDTH,
    parameter int BUSER_WIDTH  = TUSER_WIDTH,
    parameter int ARUSER_WIDTH = TUSER_WIDTH,
    parameter int RUSER_WIDTH  = TUSER_WIDTH
) (
    input logic axil_aclk
);

    localparam int STRB_WIDTH = DATA_WIDTH / 8;

    localparam int AWUSER_W = (AWUSER_WIDTH > 0) ? AWUSER_WIDTH : 1;
    localparam int WUSER_W  = (WUSER_WIDTH > 0) ? WUSER_WIDTH : 1;
    localparam int BUSER_W  = (BUSER_WIDTH > 0) ? BUSER_WIDTH : 1;
    localparam int ARUSER_W = (ARUSER_WIDTH > 0) ? ARUSER_WIDTH : 1;
    localparam int RUSER_W  = (RUSER_WIDTH > 0) ? RUSER_WIDTH : 1;

    // -------------------------------------------------------------------------
    // Channel structs (payload only; valid/ready are separate)
    // AXI4-Lite: no burst/ID/cache/qos/region/lock; single beat per transaction (no last).
    // -------------------------------------------------------------------------

    typedef struct packed {
        logic [ADDR_WIDTH-1:0]   addr;
        logic [2:0]              prot;
        logic [AWUSER_W-1:0]     user;
    } aw_chan_t;

    typedef struct packed {
        logic [DATA_WIDTH-1:0]   data;
        logic [STRB_WIDTH-1:0]   strb;
        logic [WUSER_W-1:0]      user;
    } w_chan_t;

    typedef struct packed {
        logic [1:0]              resp;
        logic [BUSER_W-1:0]      user;
    } b_chan_t;

    typedef struct packed {
        logic [ADDR_WIDTH-1:0]   addr;
        logic [2:0]              prot;
        logic [ARUSER_W-1:0]     user;
    } ar_chan_t;

    typedef struct packed {
        logic [DATA_WIDTH-1:0]   data;
        logic [1:0]              resp;
        logic [RUSER_W-1:0]      user;
    } r_chan_t;

    // -------------------------------------------------------------------------
    // Channel payloads
    // -------------------------------------------------------------------------

    aw_chan_t aw;
    w_chan_t  w;
    b_chan_t  b;
    ar_chan_t ar;
    r_chan_t  r;

    // -------------------------------------------------------------------------
    // Valid/ready (direction depends on master vs slave; kept outside structs)
    // -------------------------------------------------------------------------

    logic aw_valid;
    logic aw_ready;
    logic w_valid;
    logic w_ready;
    logic b_valid;
    logic b_ready;
    logic ar_valid;
    logic ar_ready;
    logic r_valid;
    logic r_ready;

    // -------------------------------------------------------------------------
    // Modports
    // -------------------------------------------------------------------------

    modport master (
        output aw,
        output aw_valid,
        input  aw_ready,

        output w,
        output w_valid,
        input  w_ready,

        input  b,
        input  b_valid,
        output b_ready,

        output ar,
        output ar_valid,
        input  ar_ready,

        input  r,
        input  r_valid,
        output r_ready
    );

    modport slave (
        input  aw,
        input  aw_valid,
        output aw_ready,

        input  w,
        input  w_valid,
        output w_ready,

        output b,
        output b_valid,
        input  b_ready,

        input  ar,
        input  ar_valid,
        output ar_ready,

        output r,
        output r_valid,
        input  r_ready
    );

    modport monitor (
        input aw,
        input aw_valid,
        input aw_ready,

        input w,
        input w_valid,
        input w_ready,

        input b,
        input b_valid,
        input b_ready,

        input ar,
        input ar_valid,
        input ar_ready,

        input r,
        input r_valid,
        input r_ready
    );

endinterface
`endif
