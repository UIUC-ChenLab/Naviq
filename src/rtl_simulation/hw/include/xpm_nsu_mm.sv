// Simulation-only marker for a NoC slave unit (NSU).  An NSU presents an
// AXI master interface to RTL: it issues AW/W/AR requests and consumes B/R
// responses.  Keeping these directions accurate is required for the
// Verilated public-flat signals to propagate into a wrapped RTL endpoint.
module xpm_nsu_mm #(
    parameter int DATA_WIDTH = 512,
    parameter int ADDR_WIDTH = 32,
    parameter int ID_WIDTH = 4,
    parameter int AW_USER_WIDTH = 0,
    parameter int W_USER_WIDTH = 0,
    parameter int B_USER_WIDTH = 0,
    parameter int AR_USER_WIDTH = 0,
    parameter int R_USER_WIDTH = 0
) (
    input logic m_axi_aclk /* verilator public_flat */,
    output logic [ADDR_WIDTH-1:0] m_axi_awaddr /* verilator public_flat */,
    output logic [7:0] m_axi_awlen /* verilator public_flat */,
    output logic [2:0] m_axi_awsize /* verilator public_flat */,
    output logic [1:0] m_axi_awburst /* verilator public_flat */,
    output logic [2:0] m_axi_awprot /* verilator public_flat */,
    output logic [3:0] m_axi_awcache /* verilator public_flat */,
    output logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] m_axi_awid /* verilator public_flat */,
    output logic [1:0] m_axi_awlock /* verilator public_flat */,
    output logic [3:0] m_axi_awqos /* verilator public_flat */,
    output logic [3:0] m_axi_awregion /* verilator public_flat */,
    output logic [(AW_USER_WIDTH > 0 ? AW_USER_WIDTH : 1)-1:0] m_axi_awuser /* verilator public_flat */,
    output logic m_axi_awvalid /* verilator public_flat */,
    input logic m_axi_awready /* verilator public_flat */,

    // Write Data Channel
    output logic [DATA_WIDTH-1:0] m_axi_wdata /* verilator public_flat */,
    output logic [DATA_WIDTH/8-1:0] m_axi_wstrb /* verilator public_flat */,
    output logic [(W_USER_WIDTH > 0 ? W_USER_WIDTH : 1)-1:0] m_axi_wuser /* verilator public_flat */,
    output logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] m_axi_wid /* verilator public_flat */,
    output logic m_axi_wlast /* verilator public_flat */,
    output logic m_axi_wvalid /* verilator public_flat */,
    input logic m_axi_wready /* verilator public_flat */,

    // Write Response Channel
    input logic [1:0] m_axi_bresp /* verilator public_flat */,
    input logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] m_axi_bid /* verilator public_flat */,
    input logic [(B_USER_WIDTH > 0 ? B_USER_WIDTH : 1)-1:0] m_axi_buser /* verilator public_flat */,
    input logic m_axi_bvalid /* verilator public_flat */,
    output logic m_axi_bready /* verilator public_flat */,

    // Read Address Channel
    output logic [ADDR_WIDTH-1:0] m_axi_araddr /* verilator public_flat */,
    output logic [7:0] m_axi_arlen /* verilator public_flat */,
    output logic [2:0] m_axi_arsize /* verilator public_flat */,
    output logic [1:0] m_axi_arburst /* verilator public_flat */,
    output logic [2:0] m_axi_arprot /* verilator public_flat */,
    output logic [3:0] m_axi_arcache /* verilator public_flat */,
    output logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] m_axi_arid /* verilator public_flat */,
    output logic [1:0] m_axi_arlock /* verilator public_flat */,
    output logic [3:0] m_axi_arqos /* verilator public_flat */,
    output logic [3:0] m_axi_arregion /* verilator public_flat */,
    output logic [(AR_USER_WIDTH > 0 ? AR_USER_WIDTH : 1)-1:0] m_axi_aruser /* verilator public_flat */,
    output logic m_axi_arvalid /* verilator public_flat */,
    input logic m_axi_arready /* verilator public_flat */,

    // Read Data Channel
    input logic [DATA_WIDTH-1:0] m_axi_rdata /* verilator public_flat */,
    input logic [1:0] m_axi_rresp /* verilator public_flat */,
    input logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] m_axi_rid /* verilator public_flat */,
    input logic [(R_USER_WIDTH > 0 ? R_USER_WIDTH : 1)-1:0] m_axi_ruser /* verilator public_flat */,
    input logic m_axi_rlast /* verilator public_flat */,
    input logic m_axi_rvalid /* verilator public_flat */,
    output logic m_axi_rready /* verilator public_flat */
);


endmodule
