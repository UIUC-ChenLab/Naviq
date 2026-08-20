module AxisFifo #(
    parameter int FIFO_DEPTH = 1024,
    parameter int DATA_WIDTH = 256,
    parameter int TDEST_WIDTH = 12,
    parameter int TID_WIDTH = 16,
    parameter int REGISTERED_READ = 0  // 0 = combinational read, 1 = registered read
) (
    input logic axis_aclk,
    input logic axis_aresetn
);

    localparam int KEEP_WIDTH = DATA_WIDTH/8;
    localparam int ADDR_WIDTH = $clog2(FIFO_DEPTH);

    // Input stream interface (from xpm_nsu_strm)
    logic [DATA_WIDTH-1:0] s_axis_tdata;
    logic [KEEP_WIDTH-1:0] s_axis_tkeep;
    logic [TID_WIDTH-1:0] s_axis_tid;
    logic [TDEST_WIDTH-1:0] s_axis_tdest;
    logic s_axis_tlast;
    logic s_axis_tvalid;
    logic s_axis_tready;

    // Output stream interface (to xpm_nmu_strm)
    logic [DATA_WIDTH-1:0] m_axis_tdata;
    logic [KEEP_WIDTH-1:0] m_axis_tkeep;
    logic [TID_WIDTH-1:0] m_axis_tid;
    logic [TDEST_WIDTH-1:0] m_axis_tdest;
    logic m_axis_tlast;
    logic m_axis_tvalid;
    logic m_axis_tready;

    // Define AXIS data struct (without tuser since strm modules don't support it)
    typedef struct packed {
        logic [DATA_WIDTH-1:0] tdata;
        logic [KEEP_WIDTH-1:0] tkeep;
        logic [TID_WIDTH-1:0] tid;
        logic [TDEST_WIDTH-1:0] tdest;
        logic tlast;
    } axis_data_t;

    // Instantiate xpm_nsu_strm (input)
    xpm_nsu_strm #(
        .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH)
    ) u_xpm_nsu_strm (
        .m_axis_aclk(axis_aclk),
        .m_axis_tdata(s_axis_tdata),
        .m_axis_tkeep(s_axis_tkeep),
        .m_axis_tid(s_axis_tid),
        .m_axis_tdest(s_axis_tdest),
        .m_axis_tlast(s_axis_tlast),
        .m_axis_tvalid(s_axis_tvalid),
        .m_axis_tready(s_axis_tready)
    );

    // Internal signals for FIFO
    logic [DATA_WIDTH-1:0] fifo_s_axis_tdata;
    logic [KEEP_WIDTH-1:0] fifo_s_axis_tkeep;
    logic [TID_WIDTH-1:0] fifo_s_axis_tid;
    logic [TDEST_WIDTH-1:0] fifo_s_axis_tdest;
    logic fifo_s_axis_tlast;
    logic fifo_s_axis_tvalid;
    logic fifo_s_axis_tready;

    logic [DATA_WIDTH-1:0] fifo_m_axis_tdata;
    logic [KEEP_WIDTH-1:0] fifo_m_axis_tkeep;
    logic [TID_WIDTH-1:0] fifo_m_axis_tid;
    logic [TDEST_WIDTH-1:0] fifo_m_axis_tdest;
    logic fifo_m_axis_tlast;
    logic fifo_m_axis_tvalid;
    logic fifo_m_axis_tready;

    // Connect input ports through xpm_nsu_strm to FIFO input
    // (xpm_nmu_strm is currently empty, so signals pass through directly)
    assign fifo_s_axis_tdata = s_axis_tdata;
    assign fifo_s_axis_tkeep = s_axis_tkeep;
    assign fifo_s_axis_tid = s_axis_tid;
    assign fifo_s_axis_tdest = s_axis_tdest;
    assign fifo_s_axis_tlast = s_axis_tlast;
    assign fifo_s_axis_tvalid = s_axis_tvalid;
    assign s_axis_tready = fifo_s_axis_tready;

    // FIFO memory array using struct
    axis_data_t fifo [FIFO_DEPTH-1:0];

    // Write and read pointers (one extra bit for full/empty detection)
    logic [ADDR_WIDTH:0] wr_ptr, rd_ptr;
    logic [ADDR_WIDTH-1:0] wr_addr, rd_addr;

    // Control signals
    logic fifo_full, fifo_empty;
    logic wr_en, rd_en;

    // Extract addresses from pointers
    assign wr_addr = wr_ptr[ADDR_WIDTH-1:0];
    assign rd_addr = rd_ptr[ADDR_WIDTH-1:0];

    // Full: pointers match but MSB differs
    // Empty: pointers match exactly
    assign fifo_full = (wr_addr == rd_addr) && (wr_ptr[ADDR_WIDTH] != rd_ptr[ADDR_WIDTH]);
    assign fifo_empty = (wr_ptr == rd_ptr);

    // Write enable
    assign wr_en = fifo_s_axis_tvalid && fifo_s_axis_tready;
    assign fifo_s_axis_tready = !fifo_full;

    // Registered read path signals
    axis_data_t read_data_reg;
    logic read_valid_reg;

    // Write data to FIFO
    always_ff @(posedge axis_aclk) begin
        if (!axis_aresetn) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
        end else begin
            // Write pointer update
            if (wr_en) begin
                fifo[wr_addr].tdata <= fifo_s_axis_tdata;
                fifo[wr_addr].tkeep <= fifo_s_axis_tkeep;
                fifo[wr_addr].tid <= fifo_s_axis_tid;
                fifo[wr_addr].tdest <= fifo_s_axis_tdest;
                fifo[wr_addr].tlast <= fifo_s_axis_tlast;
                wr_ptr <= wr_ptr + 1'b1;
            end

            // Read pointer update
            if (rd_en) begin
                rd_ptr <= rd_ptr + 1'b1;
            end
        end
    end

    // Generate block for combinational vs registered read path
    generate
        if (REGISTERED_READ == 0) begin: l_comb_read
            // Combinational read path (zero latency)
            assign fifo_m_axis_tvalid = !fifo_empty;
            assign rd_en = fifo_m_axis_tvalid && fifo_m_axis_tready;

            assign fifo_m_axis_tdata = fifo[rd_addr].tdata;
            assign fifo_m_axis_tkeep = fifo[rd_addr].tkeep;
            assign fifo_m_axis_tid = fifo[rd_addr].tid;
            assign fifo_m_axis_tdest = fifo[rd_addr].tdest;
            assign fifo_m_axis_tlast = fifo[rd_addr].tlast;
        end else begin: l_reg_read
            // Registered read path (one cycle latency, better timing)
            // Read data from FIFO and register it
            always_ff @(posedge axis_aclk) begin
                if (!axis_aresetn) begin
                    read_data_reg <= '0;
                    read_valid_reg <= 1'b0;
                end else begin
                    // Update read register when data is consumed or FIFO becomes non-empty
                    if (!read_valid_reg || (read_valid_reg && fifo_m_axis_tready)) begin
                        read_data_reg <= fifo[rd_addr];
                        read_valid_reg <= !fifo_empty;
                    end
                end
            end

            // Read enable: advance pointer when registered data is consumed
            assign rd_en = read_valid_reg && fifo_m_axis_tready;

            // Output registered data
            assign fifo_m_axis_tvalid = read_valid_reg;
            assign fifo_m_axis_tdata = read_data_reg.tdata;
            assign fifo_m_axis_tkeep = read_data_reg.tkeep;
            assign fifo_m_axis_tid = read_data_reg.tid;
            assign fifo_m_axis_tdest = read_data_reg.tdest;
            assign fifo_m_axis_tlast = read_data_reg.tlast;
        end
    endgenerate

    // Connect FIFO output through xpm_nsu_strm to output ports
    // (xpm_nsu_strm is currently empty, so signals pass through directly)
    assign m_axis_tdata = fifo_m_axis_tdata;
    assign m_axis_tkeep = fifo_m_axis_tkeep;
    assign m_axis_tid = fifo_m_axis_tid;
    assign m_axis_tdest = fifo_m_axis_tdest;
    assign m_axis_tlast = fifo_m_axis_tlast;
    assign m_axis_tvalid = fifo_m_axis_tvalid;
    assign fifo_m_axis_tready = m_axis_tready;

    // Instantiate xpm_nsu_strm (output)
    xpm_nmu_strm #(
        .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH)
    ) u_xpm_nmu_strm (
        .s_axis_aclk(axis_aclk),
        .s_axis_tdata(m_axis_tdata),
        .s_axis_tkeep(m_axis_tkeep),
        .s_axis_tid(m_axis_tid),
        .s_axis_tdest(m_axis_tdest),
        .s_axis_tlast(m_axis_tlast),
        .s_axis_tvalid(m_axis_tvalid),
        .s_axis_tready(m_axis_tready)
    );

endmodule
