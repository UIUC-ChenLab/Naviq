module xpm_nmu_mm #(
    parameter int DATA_WIDTH = 512,
    parameter int ADDR_WIDTH = 32,
    parameter int ID_WIDTH = 4,
    parameter int AW_USER_WIDTH = 0,
    parameter int W_USER_WIDTH = 0,
    parameter int B_USER_WIDTH = 0,
    parameter int AR_USER_WIDTH = 0,
    parameter int R_USER_WIDTH = 0
) (
    input logic s_axi_aclk /* verilator public_flat */,
    input logic [ADDR_WIDTH-1:0] s_axi_awaddr /* verilator public_flat */,
    input logic [7:0] s_axi_awlen /* verilator public_flat */,
    input logic [2:0] s_axi_awsize /* verilator public_flat */,
    input logic [1:0] s_axi_awburst /* verilator public_flat */,
    input logic [2:0] s_axi_awprot /* verilator public_flat */,
    input logic [3:0] s_axi_awcache /* verilator public_flat */,
    input logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] s_axi_awid /* verilator public_flat */,
    input logic [1:0] s_axi_awlock /* verilator public_flat */,
    input logic [3:0] s_axi_awqos /* verilator public_flat */,
    input logic [3:0] s_axi_awregion /* verilator public_flat */,
    input logic [(AW_USER_WIDTH > 0 ? AW_USER_WIDTH : 1)-1:0] s_axi_awuser /* verilator public_flat */,
    input logic s_axi_awvalid /* verilator public_flat */,
    output logic s_axi_awready /* verilator public_flat */,

    // Write Data Channel
    input logic [DATA_WIDTH-1:0] s_axi_wdata /* verilator public_flat */,
    input logic [DATA_WIDTH/8-1:0] s_axi_wstrb /* verilator public_flat */,
    input logic [(W_USER_WIDTH > 0 ? W_USER_WIDTH : 1)-1:0] s_axi_wuser /* verilator public_flat */,
    input logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] s_axi_wid /* verilator public_flat */,
    input logic s_axi_wlast /* verilator public_flat */,
    input logic s_axi_wvalid /* verilator public_flat */,
    output logic s_axi_wready /* verilator public_flat */,

    // Write Response Channel
    output logic [1:0] s_axi_bresp /* verilator public_flat */,
    output logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] s_axi_bid /* verilator public_flat */,
    output logic [(B_USER_WIDTH > 0 ? B_USER_WIDTH : 1)-1:0] s_axi_buser /* verilator public_flat */,
    output logic s_axi_bvalid /* verilator public_flat */,
    input logic s_axi_bready /* verilator public_flat */,

    // Read Address Channel
    input logic [ADDR_WIDTH-1:0] s_axi_araddr /* verilator public_flat */,
    input logic [7:0] s_axi_arlen /* verilator public_flat */,
    input logic [2:0] s_axi_arsize /* verilator public_flat */,
    input logic [1:0] s_axi_arburst /* verilator public_flat */,
    input logic [2:0] s_axi_arprot /* verilator public_flat */,
    input logic [3:0] s_axi_arcache /* verilator public_flat */,
    input logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] s_axi_arid /* verilator public_flat */,
    input logic [1:0] s_axi_arlock /* verilator public_flat */,
    input logic [3:0] s_axi_arqos /* verilator public_flat */,
    input logic [3:0] s_axi_arregion /* verilator public_flat */,
    input logic [(AR_USER_WIDTH > 0 ? AR_USER_WIDTH : 1)-1:0] s_axi_aruser /* verilator public_flat */,
    input logic s_axi_arvalid /* verilator public_flat */,
    output logic s_axi_arready /* verilator public_flat */,

    // Read Data Channel
    output logic [DATA_WIDTH-1:0] s_axi_rdata /* verilator public_flat */,
    output logic [1:0] s_axi_rresp /* verilator public_flat */,
    output logic [(ID_WIDTH > 0 ? ID_WIDTH : 1)-1:0] s_axi_rid /* verilator public_flat */,
    output logic [(R_USER_WIDTH > 0 ? R_USER_WIDTH : 1)-1:0] s_axi_ruser /* verilator public_flat */,
    output logic s_axi_rlast /* verilator public_flat */,
    output logic s_axi_rvalid /* verilator public_flat */,
    input logic s_axi_rready /* verilator public_flat */
);

endmodule
