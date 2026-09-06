`ifndef IFC_AXIMM_SV
`define IFC_AXIMM_SV
interface ifc_aximm #(
    parameter int ADDR_WIDTH   = 64,
    parameter int DATA_WIDTH   = 256,
    parameter int TDEST_WIDTH  = 12,
    parameter int TID_WIDTH    = 16,
    parameter int TUSER_WIDTH  = 16,
    // Optional sideband widths; when 0, the bus is 1 bit wide
    parameter int ID_WIDTH     = 0,
    parameter int AWUSER_WIDTH = TUSER_WIDTH,
    parameter int ARUSER_WIDTH = TUSER_WIDTH,
    parameter int WUSER_WIDTH  = TUSER_WIDTH,
    parameter int BUSER_WIDTH  = TUSER_WIDTH,
    parameter int RUSER_WIDTH  = TUSER_WIDTH
) (
    input logic aximm_aclk
);

    localparam int STRB_WIDTH = DATA_WIDTH / 8;

    // Effective widths: at least 1 bit when parameter is 0 (so bus is never zero-width)
    localparam int ID_W      = (ID_WIDTH > 0) ? ID_WIDTH : 1;
    localparam int AWUSER_W  = (AWUSER_WIDTH > 0) ? AWUSER_WIDTH : 1;
    localparam int ARUSER_W  = (ARUSER_WIDTH > 0) ? ARUSER_WIDTH : 1;
    localparam int WUSER_W   = (WUSER_WIDTH > 0) ? WUSER_WIDTH : 1;
    localparam int BUSER_W   = (BUSER_WIDTH > 0) ? BUSER_WIDTH : 1;
    localparam int RUSER_W   = (RUSER_WIDTH > 0) ? RUSER_WIDTH : 1;

    // -------------------------------------------------------------------------
    // Channel structs (payload only; valid/ready are separate)
    // -------------------------------------------------------------------------

    typedef struct packed {
        logic [ADDR_WIDTH-1:0]    addr;
        logic [7:0]               len;
        logic [2:0]               size;
        logic [1:0]               burst;
        logic [2:0]               prot;
        logic [3:0]               cache;
        logic [1:0]               lock;
        logic [3:0]               qos;
        logic [3:0]               region;
        logic [ID_W-1:0]          id;
        logic [AWUSER_W-1:0]      user;
    } aw_chan_t;

    typedef struct packed {
        logic [DATA_WIDTH-1:0]   data;
        logic [STRB_WIDTH-1:0]   strb;
        logic                    last;
        logic [WUSER_W-1:0]      user;
    } w_chan_t;

    typedef struct packed {
        logic [1:0]              resp;
        logic [ID_W-1:0]         id;
        logic [BUSER_W-1:0]      user;
    } b_chan_t;

    typedef struct packed {
        logic [ADDR_WIDTH-1:0]   addr;
        logic [7:0]              len;
        logic [2:0]              size;
        logic [1:0]              burst;
        logic [2:0]              prot;
        logic [3:0]              cache;
        logic [1:0]              lock;
        logic [3:0]              qos;
        logic [3:0]              region;
        logic [ID_W-1:0]         id;
        logic [ARUSER_W-1:0]     user;
    } ar_chan_t;

    typedef struct packed {
        logic [DATA_WIDTH-1:0]   data;
        logic [1:0]              resp;
        logic                    last;
        logic [ID_W-1:0]         id;
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
