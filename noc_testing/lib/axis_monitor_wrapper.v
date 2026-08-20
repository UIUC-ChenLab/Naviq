`timescale 1ns/1ps
`default_nettype none

// Pure-Verilog wrapper with AXIS monitor bus interfaces (spyglass in BD).
// Instantiates the SystemVerilog axis_path_monitor for latency/bandwidth stats.
//
// Notes:
// - Mixed HDL (this .v + axis_path_monitor.sv) is fine in Vivado.
// - Keep as a passive observer; no backpressure generated here.
// - You can set DONT_TOUCH on the BD cell too if you like.
(* DONT_TOUCH = "true", keep_hierarchy = "yes" *)
module axis_monitor_wrapper #(
  parameter integer TDATA_WIDTH    = 512,
  parameter integer LAT_FIFO_DEPTH = 512,  
  parameter integer SRC_ID          = 0 
)(
  // Clock and reset
  (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ACLK CLK" *)
  (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME ACLK, ASSOCIATED_RESET aresetn, ASSOCIATED_BUSIF MON_AXIS_IN:MON_AXIS_OUT" *)
  input  wire                           aclk,

  (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 ARESETN RST" *)
  (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME ARESETN, POLARITY ACTIVE_LOW" *)
  input  wire                           aresetn,

  // ===== Ingress monitor (before NoC) =====
  (* X_INTERFACE_MODE = "monitor" *)
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_IN TDATA" *)
  input  wire [TDATA_WIDTH-1:0]         mon_in_tdata,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_IN TVALID" *)
  input  wire                           mon_in_tvalid,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_IN TREADY" *)
  input  wire                           mon_in_tready,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_IN TLAST" *)
  input  wire                           mon_in_tlast,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_IN TKEEP" *)
  input  wire [(TDATA_WIDTH/8)-1:0]     mon_in_tkeep,

  // ===== Egress monitor (after NoC) =====
  (* X_INTERFACE_MODE = "monitor" *)
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_OUT TDATA" *)
  input  wire [TDATA_WIDTH-1:0]         mon_out_tdata,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_OUT TVALID" *)
  input  wire                           mon_out_tvalid,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_OUT TREADY" *)
  input  wire                           mon_out_tready,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_OUT TLAST" *)
  input  wire                           mon_out_tlast,
  (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 MON_AXIS_OUT TKEEP" *)
  input  wire [(TDATA_WIDTH/8)-1:0]     mon_out_tkeep

);

  // Instantiate the passive path monitor (SystemVerilog module)
  axis_monitor #(
    .TDATA_WIDTH    (TDATA_WIDTH),
    .LAT_FIFO_DEPTH (LAT_FIFO_DEPTH),
    .SRC_ID         (SRC_ID)
  ) axis_mon (
    .aclk           (aclk),
    .aresetn        (aresetn),

    .in_tdata       (mon_in_tdata),
    .in_tvalid      (mon_in_tvalid),
    .in_tready      (mon_in_tready),
    .in_tlast       (mon_in_tlast),
    .in_tkeep       (mon_in_tkeep),

    .out_tdata      (mon_out_tdata),
    .out_tvalid     (mon_out_tvalid),
    .out_tready     (mon_out_tready),
    .out_tlast      (mon_out_tlast),
    .out_tkeep      (mon_out_tkeep)

  );

endmodule

`default_nettype wire