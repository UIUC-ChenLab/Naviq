`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 09/22/2025 08:45:51 PM
// Design Name: 
// Module Name: axis_endpoint
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////


module axis_endpoint #(
  parameter integer DATA_WIDTH  = 64,
  parameter integer KEEP_ENABLE = 1,                     // 1 to include TKEEP port
  parameter integer KEEP_WIDTH  = (DATA_WIDTH/8),
  parameter integer ID_WIDTH    = 0,                     // set to 0 if unused
  parameter integer DEST_WIDTH  = 0,                     // set to 0 if unused
  parameter integer USER_WIDTH  = 0                      // set to 0 if unused
)(
  input  wire                      ACLK,
  input  wire                      ARESETN,

  // AXI4-Stream Slave (sink)
  input  wire [DATA_WIDTH-1:0]     S_AXIS_TDATA,
  input  wire [KEEP_WIDTH-1:0]     S_AXIS_TKEEP,         // valid only if KEEP_ENABLE=1
  input  wire                      S_AXIS_TVALID,
  output wire                      S_AXIS_TREADY,
  input  wire                      S_AXIS_TLAST,
  input  wire [ID_WIDTH-1:0]       S_AXIS_TID,          // width may be 0 (tie off)
  input  wire [DEST_WIDTH-1:0]     S_AXIS_TDEST,        // width may be 0 (tie off)
  input  wire [USER_WIDTH-1:0]     S_AXIS_TUSER         // width may be 0 (tie off)
);

  // Always ready: no backpressure. Safe for test TGs and NoC egress to sink.
  assign S_AXIS_TREADY = 1'b1;

  // No storage/logic: intentionally ignore all inputs.
  // If your tools warn about unused signals, you can reference them in a dummy way:
  // wire _unused = &{1'b0, S_AXIS_TVALID, S_AXIS_TLAST,
  //   (KEEP_ENABLE ? ^S_AXIS_TKEEP : 1'b0),
  //   (^S_AXIS_TDATA),
  //   (ID_WIDTH   ? ^S_AXIS_TID   : 1'b0),
  //   (DEST_WIDTH ? ^S_AXIS_TDEST : 1'b0),
  //   (USER_WIDTH ? ^S_AXIS_TUSER : 1'b0),
  //   ACLK, ARESETN };

endmodule
