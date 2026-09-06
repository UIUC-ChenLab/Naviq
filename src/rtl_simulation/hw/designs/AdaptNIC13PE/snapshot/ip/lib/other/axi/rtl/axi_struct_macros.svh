// AXI channel struct macros: field layout matches ifc_axis / ifc_aximm / ifc_axil.
// - *_STRUCT macros: define a struct type from explicit width parameters and NAME.
// - *_T(PORT, NAME) macros: define a struct type with widths taken from PORT via $bits().
//
// Usage (axis, from port):
//   `include "axi_struct_macros.svh"
//   `AXIS_T_CHAN_T(s_axis, t_chan_t);
//
// Usage (axis, from widths):
//   `AXIS_T_CHAN_STRUCT(DATA_W, KEEP_W, TID_W, TDEST_W, TUSER_W, t_chan_t);
//
// Usage (aximm, from port): `AXIMM_AW_CHAN_T(s_aximm, aw_chan_t); etc.
// Usage (aximm, from widths): `AXIMM_AW_CHAN_STRUCT(ADDR_W, ID_W, AWUSER_W, aw_chan_t); etc.
//
// Usage (axil, from port): `AXIL_AW_CHAN_T(s_axil, aw_chan_t); etc.
// Usage (axil, from widths): `AXIL_AW_CHAN_STRUCT(ADDR_W, AWUSER_W, aw_chan_t); etc.
//
// Usage (axil <-> aximm, single-beat / register-style traffic):
//   `AXIL_MASTER_TO_AXIMM_SLAVE(axil_if, aximm_if)   // axil.master -> aximm.slave
//   `AXIMM_MASTER_TO_AXIL_SLAVE(aximm_if, axil_if)   // aximm.master -> axil.slave
//   Assumes DATA_WIDTH/8 is a power of two; `AXIL_PAD_ASSIGN` uses IEEE 1800 width rules.

`ifndef AXI_STRUCT_MACROS_SVH
`define AXI_STRUCT_MACROS_SVH

// -----------------------------------------------------------------------------
// Axis: struct from fields in ifc_axis (t_chan_t)
// -----------------------------------------------------------------------------
// (DATA_W, KEEP_W, TID_W, TDEST_W, TUSER_W, NAME)
`define AXIS_T_CHAN_STRUCT(DATA_W, KEEP_W, TID_W, TDEST_W, TUSER_W, NAME) \
    typedef struct packed { \
        logic [DATA_W-1:0]   data; \
        logic [KEEP_W-1:0]   keep; \
        logic [TID_W-1:0]    id; \
        logic [TDEST_W-1:0]  dest; \
        logic [TUSER_W-1:0]  user; \
        logic                last; \
    } NAME

// (PORT, NAME) = axis port and desired struct typedef name
`define AXIS_T_CHAN_T(PORT, NAME) \
    `AXIS_T_CHAN_STRUCT($bits(PORT.t.data), $bits(PORT.t.keep), $bits(PORT.t.id), $bits(PORT.t.dest), $bits(PORT.t.user), NAME)

// -----------------------------------------------------------------------------
// AXIMM: structs from fields in ifc_aximm (aw_chan_t, w_chan_t, b_chan_t, ar_chan_t, r_chan_t)
// -----------------------------------------------------------------------------
// (ADDR_W, ID_W, AWUSER_W, NAME)
`define AXIMM_AW_CHAN_STRUCT(ADDR_W, ID_W, AWUSER_W, NAME) \
    typedef struct packed { \
        logic [ADDR_W-1:0]   addr; \
        logic [7:0]         len; \
        logic [2:0]         size; \
        logic [1:0]         burst; \
        logic [2:0]         prot; \
        logic [3:0]         cache; \
        logic [1:0]         lock; \
        logic [3:0]         qos; \
        logic [3:0]         region; \
        logic [ID_W-1:0]     id; \
        logic [AWUSER_W-1:0] user; \
    } NAME

`define AXIMM_AW_CHAN_T(PORT, NAME) \
    `AXIMM_AW_CHAN_STRUCT($bits(PORT.aw.addr), $bits(PORT.aw.id), $bits(PORT.aw.user), NAME)

// (DATA_W, STRB_W, WUSER_W, NAME)
`define AXIMM_W_CHAN_STRUCT(DATA_W, STRB_W, WUSER_W, NAME) \
    typedef struct packed { \
        logic [DATA_W-1:0]   data; \
        logic [STRB_W-1:0]   strb; \
        logic                last; \
        logic [WUSER_W-1:0]  user; \
    } NAME

`define AXIMM_W_CHAN_T(PORT, NAME) \
    `AXIMM_W_CHAN_STRUCT($bits(PORT.w.data), $bits(PORT.w.strb), $bits(PORT.w.user), NAME)

// (ID_W, BUSER_W, NAME)
`define AXIMM_B_CHAN_STRUCT(ID_W, BUSER_W, NAME) \
    typedef struct packed { \
        logic [1:0]          resp; \
        logic [ID_W-1:0]     id; \
        logic [BUSER_W-1:0]  user; \
    } NAME

`define AXIMM_B_CHAN_T(PORT, NAME) \
    `AXIMM_B_CHAN_STRUCT($bits(PORT.b.id), $bits(PORT.b.user), NAME)

// (ADDR_W, ID_W, ARUSER_W, NAME)
`define AXIMM_AR_CHAN_STRUCT(ADDR_W, ID_W, ARUSER_W, NAME) \
    typedef struct packed { \
        logic [ADDR_W-1:0]   addr; \
        logic [7:0]         len; \
        logic [2:0]         size; \
        logic [1:0]         burst; \
        logic [2:0]         prot; \
        logic [3:0]         cache; \
        logic [1:0]         lock; \
        logic [3:0]         qos; \
        logic [3:0]         region; \
        logic [ID_W-1:0]     id; \
        logic [ARUSER_W-1:0] user; \
    } NAME

`define AXIMM_AR_CHAN_T(PORT, NAME) \
    `AXIMM_AR_CHAN_STRUCT($bits(PORT.ar.addr), $bits(PORT.ar.id), $bits(PORT.ar.user), NAME)

// (DATA_W, ID_W, RUSER_W, NAME)
`define AXIMM_R_CHAN_STRUCT(DATA_W, ID_W, RUSER_W, NAME) \
    typedef struct packed { \
        logic [DATA_W-1:0]   data; \
        logic [1:0]          resp; \
        logic                last; \
        logic [ID_W-1:0]     id; \
        logic [RUSER_W-1:0]  user; \
    } NAME

`define AXIMM_R_CHAN_T(PORT, NAME) \
    `AXIMM_R_CHAN_STRUCT($bits(PORT.r.data), $bits(PORT.r.id), $bits(PORT.r.user), NAME)

// -----------------------------------------------------------------------------
// AXIL: structs from fields in ifc_axil (aw_chan_t, w_chan_t, b_chan_t, ar_chan_t, r_chan_t)
// -----------------------------------------------------------------------------
// (ADDR_W, AWUSER_W, NAME)
`define AXIL_AW_CHAN_STRUCT(ADDR_W, AWUSER_W, NAME) \
    typedef struct packed { \
        logic [ADDR_W-1:0]   addr; \
        logic [2:0]          prot; \
        logic [AWUSER_W-1:0] user; \
    } NAME

`define AXIL_AW_CHAN_T(PORT, NAME) \
    `AXIL_AW_CHAN_STRUCT($bits(PORT.aw.addr), $bits(PORT.aw.user), NAME)

// (DATA_W, STRB_W, WUSER_W, NAME)
`define AXIL_W_CHAN_STRUCT(DATA_W, STRB_W, WUSER_W, NAME) \
    typedef struct packed { \
        logic [DATA_W-1:0]   data; \
        logic [STRB_W-1:0]   strb; \
        logic [WUSER_W-1:0]  user; \
    } NAME

`define AXIL_W_CHAN_T(PORT, NAME) \
    `AXIL_W_CHAN_STRUCT($bits(PORT.w.data), $bits(PORT.w.strb), $bits(PORT.w.user), NAME)

// (BUSER_W, NAME)
`define AXIL_B_CHAN_STRUCT(BUSER_W, NAME) \
    typedef struct packed { \
        logic [1:0]          resp; \
        logic [BUSER_W-1:0]  user; \
    } NAME

`define AXIL_B_CHAN_T(PORT, NAME) \
    `AXIL_B_CHAN_STRUCT($bits(PORT.b.user), NAME)

// (ADDR_W, ARUSER_W, NAME)
`define AXIL_AR_CHAN_STRUCT(ADDR_W, ARUSER_W, NAME) \
    typedef struct packed { \
        logic [ADDR_W-1:0]   addr; \
        logic [2:0]          prot; \
        logic [ARUSER_W-1:0] user; \
    } NAME

`define AXIL_AR_CHAN_T(PORT, NAME) \
    `AXIL_AR_CHAN_STRUCT($bits(PORT.ar.addr), $bits(PORT.ar.user), NAME)

// (DATA_W, RUSER_W, NAME)
`define AXIL_R_CHAN_STRUCT(DATA_W, RUSER_W, NAME) \
    typedef struct packed { \
        logic [DATA_W-1:0]   data; \
        logic [1:0]          resp; \
        logic [RUSER_W-1:0]  user; \
    } NAME

`define AXIL_R_CHAN_T(PORT, NAME) \
    `AXIL_R_CHAN_STRUCT($bits(PORT.r.data), $bits(PORT.r.user), NAME)

// -----------------------------------------------------------------------------
// AXIL <-> AXIMM: width resize via assign; single-beat AXIMM side
// -----------------------------------------------------------------------------
// Width resize: widening zero-pads, narrowing keeps low bits (IEEE 1800 assignment rules).
`define AXIL_PAD_ASSIGN(dst, src) assign dst = src;

// axil: master modport; aximm: slave modport. Drives INCR burst, len=0, w.last=1, id=0, etc.
`define AXIL_MASTER_TO_AXIMM_SLAVE(axil, aximm) \
    `AXIL_PAD_ASSIGN(aximm.aw.addr, axil.aw.addr) \
    assign aximm.aw.prot = axil.aw.prot; \
    `AXIL_PAD_ASSIGN(aximm.aw.user, axil.aw.user) \
    assign aximm.aw.len = 8'h0; \
    assign aximm.aw.size = 3'($clog2($bits(aximm.w.data) / 8)); \
    assign aximm.aw.burst = 2'b01; \
    assign aximm.aw.cache = 4'b0; \
    assign aximm.aw.lock = 2'b0; \
    assign aximm.aw.qos = 4'b0; \
    assign aximm.aw.region = 4'b0; \
    assign aximm.aw.id = '0; \
    assign aximm.aw_valid = axil.aw_valid; \
    assign axil.aw_ready = aximm.aw_ready; \
    `AXIL_PAD_ASSIGN(aximm.w.data, axil.w.data) \
    `AXIL_PAD_ASSIGN(aximm.w.strb, axil.w.strb) \
    assign aximm.w.last = 1'b1; \
    `AXIL_PAD_ASSIGN(aximm.w.user, axil.w.user) \
    assign aximm.w_valid = axil.w_valid; \
    assign axil.w_ready = aximm.w_ready; \
    `AXIL_PAD_ASSIGN(axil.b.resp, aximm.b.resp) \
    `AXIL_PAD_ASSIGN(axil.b.user, aximm.b.user) \
    assign axil.b_valid = aximm.b_valid; \
    assign aximm.b_ready = axil.b_ready; \
    `AXIL_PAD_ASSIGN(aximm.ar.addr, axil.ar.addr) \
    assign aximm.ar.prot = axil.ar.prot; \
    `AXIL_PAD_ASSIGN(aximm.ar.user, axil.ar.user) \
    assign aximm.ar.len = 8'h0; \
    assign aximm.ar.size = 3'($clog2($bits(aximm.r.data) / 8)); \
    assign aximm.ar.burst = 2'b01; \
    assign aximm.ar.cache = 4'b0; \
    assign aximm.ar.lock = 2'b0; \
    assign aximm.ar.qos = 4'b0; \
    assign aximm.ar.region = 4'b0; \
    assign aximm.ar.id = '0; \
    assign aximm.ar_valid = axil.ar_valid; \
    assign axil.ar_ready = aximm.ar_ready; \
    `AXIL_PAD_ASSIGN(axil.r.data, aximm.r.data) \
    `AXIL_PAD_ASSIGN(axil.r.resp, aximm.r.resp) \
    `AXIL_PAD_ASSIGN(axil.r.user, aximm.r.user) \
    assign axil.r_valid = aximm.r_valid; \
    assign aximm.r_ready = axil.r_ready;

// aximm: master modport; axil: slave modport. Lite side has no burst/id/last; master must honor single beat.
`define AXIMM_MASTER_TO_AXIL_SLAVE(aximm, axil) \
    `AXIL_PAD_ASSIGN(axil.aw.addr, aximm.aw.addr) \
    assign axil.aw.prot = aximm.aw.prot; \
    `AXIL_PAD_ASSIGN(axil.aw.user, aximm.aw.user) \
    assign axil.aw_valid = aximm.aw_valid; \
    assign aximm.aw_ready = axil.aw_ready; \
    `AXIL_PAD_ASSIGN(axil.w.data, aximm.w.data) \
    `AXIL_PAD_ASSIGN(axil.w.strb, aximm.w.strb) \
    `AXIL_PAD_ASSIGN(axil.w.user, aximm.w.user) \
    assign axil.w_valid = aximm.w_valid; \
    assign aximm.w_ready = axil.w_ready; \
    `AXIL_PAD_ASSIGN(aximm.b.resp, axil.b.resp) \
    `AXIL_PAD_ASSIGN(aximm.b.user, axil.b.user) \
    assign aximm.b_valid = axil.b_valid; \
    assign axil.b_ready = aximm.b_ready; \
    `AXIL_PAD_ASSIGN(axil.ar.addr, aximm.ar.addr) \
    assign axil.ar.prot = aximm.ar.prot; \
    `AXIL_PAD_ASSIGN(axil.ar.user, aximm.ar.user) \
    assign axil.ar_valid = aximm.ar_valid; \
    assign aximm.ar_ready = axil.ar_ready; \
    `AXIL_PAD_ASSIGN(aximm.r.data, axil.r.data) \
    `AXIL_PAD_ASSIGN(aximm.r.resp, axil.r.resp) \
    `AXIL_PAD_ASSIGN(aximm.r.user, axil.r.user) \
    assign aximm.r_valid = axil.r_valid; \
    assign axil.r_ready = aximm.r_ready;

`endif
