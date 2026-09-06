`ifndef IFC_AXIS_SV
`define IFC_AXIS_SV
interface ifc_axis #(
    parameter int DATA_WIDTH = 512,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16,
    parameter int TUSER_WIDTH = 16
) (
    input logic axis_aclk
);

    localparam int KEEP_WIDTH = DATA_WIDTH / 8;

    // -------------------------------------------------------------------------
    // Channel struct (payload only; valid/ready are separate)
    // -------------------------------------------------------------------------

    typedef struct packed {
        logic [DATA_WIDTH-1:0]  data;
        logic [KEEP_WIDTH-1:0]  keep;
        logic [TID_WIDTH-1:0]   id;
        logic [TDEST_WIDTH-1:0] dest;
        logic [TUSER_WIDTH-1:0] user;
        logic                   last;
    } t_chan_t;

    // -------------------------------------------------------------------------
    // Channel payload
    // -------------------------------------------------------------------------

    t_chan_t t;

    // -------------------------------------------------------------------------
    // Valid/ready (direction depends on master vs slave; kept outside struct)
    // -------------------------------------------------------------------------

    logic tvalid;
    logic tready;

    // -------------------------------------------------------------------------
    // Modports
    // -------------------------------------------------------------------------

    modport master (
        output t,
        output tvalid,
        input  tready
    );

    modport slave (
        input  t,
        input  tvalid,
        output tready
    );

    modport monitor (
        input t,
        input tvalid,
        input tready
    );

endinterface
`endif

