`include "ifc_axil.sv"
`include "ifc_axis.sv"

module lookup_table #(
    parameter int TABLE_DEPTH       = 1024,
    parameter int TABLE_VALUE_WIDTH = 32,
    parameter int ENABLE_AXIL_READ  = 0,
    localparam int TABLE_ADDR_WIDTH = $clog2(TABLE_DEPTH)
) (
    input logic clk,
    input logic resetn,

    ifc_axil.slave  ctrl_in,
    ifc_axis.slave  s_axis_lookup,
    ifc_axis.master m_axis_value
);

    localparam logic [31:0] DEAD_BEEF = 32'hDEAD_BEEF;

    initial begin
        if (TABLE_DEPTH < 2 || ((TABLE_DEPTH & (TABLE_DEPTH - 1)) != 0)) begin
            $error("lookup_table: TABLE_DEPTH (%0d) must be a power of two and >= 2", TABLE_DEPTH);
            $finish;
        end
        if (TABLE_VALUE_WIDTH < 1 || TABLE_VALUE_WIDTH > 32) begin
            $error("lookup_table: TABLE_VALUE_WIDTH (%0d) must be in [1, 32]", TABLE_VALUE_WIDTH);
            $finish;
        end
        if ($bits(ctrl_in.w.data) != 32) begin
            $error("lookup_table: ctrl_in data width (%0d) must be 32", $bits(ctrl_in.w.data));
            $finish;
        end
        if ($bits(s_axis_lookup.t.data) < TABLE_ADDR_WIDTH) begin
            $error("lookup_table: s_axis_lookup.t.data width (%0d) must be at least TABLE_ADDR_WIDTH (%0d)",
                   $bits(s_axis_lookup.t.data), TABLE_ADDR_WIDTH);
            $finish;
        end
        if ($bits(m_axis_value.t.data) < TABLE_VALUE_WIDTH) begin
            $error("lookup_table: m_axis_value.t.data width (%0d) must be at least TABLE_VALUE_WIDTH (%0d)",
                   $bits(m_axis_value.t.data), TABLE_VALUE_WIDTH);
            $finish;
        end
    end

    // -------------------------------------------------------------------------
    // AXIL write path
    // -------------------------------------------------------------------------

    logic                         aw_buf_valid_r;
    logic [TABLE_ADDR_WIDTH-1:0]  aw_addr_r;
    logic                         w_buf_valid_r;
    logic [31:0]                  w_data_r;
    logic [3:0]                   w_strb_r;
    logic                         b_valid_r;
    logic [1:0]                   b_resp_r;

    wire write_ready = aw_buf_valid_r && w_buf_valid_r && !b_valid_r;
    wire full_strobe = (w_strb_r == 4'hF);

    wire                         bram_we     = write_ready && full_strobe;
    wire [TABLE_ADDR_WIDTH-1:0]  bram_addr_w = aw_addr_r;
    wire [TABLE_VALUE_WIDTH-1:0] bram_din_w  = w_data_r[TABLE_VALUE_WIDTH-1:0];

    assign ctrl_in.aw_ready = !aw_buf_valid_r && !b_valid_r;
    assign ctrl_in.w_ready  = !w_buf_valid_r && !b_valid_r;
    assign ctrl_in.b.resp   = b_resp_r;
    assign ctrl_in.b.user   = '0;
    assign ctrl_in.b_valid  = b_valid_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            aw_buf_valid_r <= 1'b0;
            aw_addr_r      <= '0;
            w_buf_valid_r  <= 1'b0;
            w_data_r       <= '0;
            w_strb_r       <= '0;
            b_valid_r      <= 1'b0;
            b_resp_r       <= 2'b00;
        end else begin
            if (!b_valid_r) begin
                if (!aw_buf_valid_r && ctrl_in.aw_valid && ctrl_in.aw_ready) begin
                    aw_buf_valid_r <= 1'b1;
                    aw_addr_r      <= ctrl_in.aw.addr[TABLE_ADDR_WIDTH+1:2];
                end

                if (!w_buf_valid_r && ctrl_in.w_valid && ctrl_in.w_ready) begin
                    w_buf_valid_r <= 1'b1;
                    w_data_r      <= ctrl_in.w.data;
                    w_strb_r      <= ctrl_in.w.strb;
                end

                if (write_ready) begin
                    aw_buf_valid_r <= 1'b0;
                    w_buf_valid_r  <= 1'b0;
                    b_valid_r      <= 1'b1;
                    b_resp_r       <= full_strobe ? 2'b00 : 2'b10;
                end
            end else if (ctrl_in.b_ready) begin
                b_valid_r <= 1'b0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // AXIS lookup path
    // -------------------------------------------------------------------------

    logic [TABLE_ADDR_WIDTH-1:0]  axis_addr;
    logic                         axis_rd_valid_r;
    logic [TABLE_VALUE_WIDTH-1:0] axis_dout;
    logic [1:0]                   axis_resp_count_r;
    logic [TABLE_VALUE_WIDTH-1:0] axis_resp_q0_r;
    logic [TABLE_VALUE_WIDTH-1:0] axis_resp_q1_r;

    wire axis_resp_pop  = (axis_resp_count_r != 2'd0) && m_axis_value.tready;
    wire axis_can_accept = (axis_resp_count_r + {1'b0, axis_rd_valid_r}) < 2'd2 || axis_resp_pop;
    wire axis_req_fire  = s_axis_lookup.tvalid && s_axis_lookup.tready;

    assign s_axis_lookup.tready = axis_can_accept;
    assign axis_addr = axis_req_fire ? s_axis_lookup.t.data[TABLE_ADDR_WIDTH-1:0] : '0;

    assign m_axis_value.t.keep  = '1;
    assign m_axis_value.t.id    = '0;
    assign m_axis_value.t.dest  = '0;
    assign m_axis_value.t.user  = '0;
    assign m_axis_value.t.last  = 1'b1;
    assign m_axis_value.tvalid  = (axis_resp_count_r != 2'd0);

    always_comb begin
        m_axis_value.t.data = '0;
        m_axis_value.t.data[TABLE_VALUE_WIDTH-1:0] = axis_resp_q0_r;
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            axis_rd_valid_r    <= 1'b0;
            axis_resp_count_r  <= 2'd0;
            axis_resp_q0_r     <= '0;
            axis_resp_q1_r     <= '0;
        end else begin
            unique case ({axis_resp_pop, axis_rd_valid_r})
                2'b00: begin
                    axis_resp_count_r <= axis_resp_count_r;
                end

                2'b01: begin
                    if (axis_resp_count_r == 2'd0) begin
                        axis_resp_q0_r    <= axis_dout;
                        axis_resp_count_r <= 2'd1;
                    end else begin
                        axis_resp_q1_r    <= axis_dout;
                        axis_resp_count_r <= 2'd2;
                    end
                end

                2'b10: begin
                    if (axis_resp_count_r == 2'd2) begin
                        axis_resp_q0_r <= axis_resp_q1_r;
                    end
                    axis_resp_count_r <= axis_resp_count_r - 2'd1;
                end

                2'b11: begin
                    if (axis_resp_count_r == 2'd1) begin
                        axis_resp_q0_r <= axis_dout;
                    end else begin
                        axis_resp_q0_r <= axis_resp_q1_r;
                        axis_resp_q1_r <= axis_dout;
                    end
                end
            endcase

            axis_rd_valid_r <= axis_req_fire;
        end
    end

    // -------------------------------------------------------------------------
    // AXIL read path
    // -------------------------------------------------------------------------

    typedef enum logic [1:0] {
        AXIL_RD_IDLE,
        AXIL_RD_WAIT_BRAM,
        AXIL_RD_CAPTURE
    } axil_rd_state_t;

    axil_rd_state_t                axil_rd_state_r;
    logic [TABLE_ADDR_WIDTH-1:0]   axil_rd_addr_r;
    logic                          r_valid_r;
    logic [31:0]                   r_data_r;
    logic [1:0]                    r_resp_r;
    logic [TABLE_VALUE_WIDTH-1:0]  axil_rd_dout;

    assign ctrl_in.ar_ready = (axil_rd_state_r == AXIL_RD_IDLE) && !r_valid_r;
    assign ctrl_in.r.data   = r_data_r;
    assign ctrl_in.r.resp   = r_resp_r;
    assign ctrl_in.r.user   = '0;
    assign ctrl_in.r_valid  = r_valid_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            axil_rd_state_r <= AXIL_RD_IDLE;
            axil_rd_addr_r  <= '0;
            r_valid_r       <= 1'b0;
            r_data_r        <= '0;
            r_resp_r        <= 2'b00;
        end else begin
            if (r_valid_r && ctrl_in.r_ready)
                r_valid_r <= 1'b0;

            unique case (axil_rd_state_r)
                AXIL_RD_IDLE: begin
                    if (ctrl_in.ar_valid && ctrl_in.ar_ready) begin
                        axil_rd_addr_r <= ctrl_in.ar.addr[TABLE_ADDR_WIDTH+1:2];
                        if (ENABLE_AXIL_READ != 0) begin
                            axil_rd_state_r <= AXIL_RD_WAIT_BRAM;
                        end else begin
                            r_valid_r <= 1'b1;
                            r_data_r  <= DEAD_BEEF;
                            r_resp_r  <= 2'b00;
                        end
                    end
                end

                AXIL_RD_WAIT_BRAM: begin
                    axil_rd_state_r <= AXIL_RD_CAPTURE;
                end

                AXIL_RD_CAPTURE: begin
                    r_valid_r       <= 1'b1;
                    r_data_r        <= '0;
                    r_data_r[TABLE_VALUE_WIDTH-1:0] <= axil_rd_dout;
                    r_resp_r        <= 2'b00;
                    axil_rd_state_r <= AXIL_RD_IDLE;
                end

                default: axil_rd_state_r <= AXIL_RD_IDLE;
            endcase
        end
    end

    // -------------------------------------------------------------------------
    // BRAM implementation selection
    // -------------------------------------------------------------------------

    generate
        if (ENABLE_AXIL_READ != 0) begin : gen_debug_read_bram
            bram_2r1w #(
                .BRAM_WIDTH(TABLE_VALUE_WIDTH),
                .BRAM_DEPTH(TABLE_DEPTH)
            ) u_table_bram (
                .clk     (clk),
                .we_w    (bram_we),
                .addr_w  (bram_addr_w),
                .din_w   (bram_din_w),
                .addr_r0 (axis_addr),
                .dout_r0 (axis_dout),
                .addr_r1 (axil_rd_addr_r),
                .dout_r1 (axil_rd_dout)
            );
        end else begin : gen_no_debug_read_bram
            simple_dual_port_bram #(
                .BRAM_WIDTH(TABLE_VALUE_WIDTH),
                .BRAM_DEPTH(TABLE_DEPTH)
            ) u_table_bram (
                .clk    (clk),
                .we_w   (bram_we),
                .addr_w (bram_addr_w),
                .din_w  (bram_din_w),
                .addr_r (axis_addr),
                .dout_r (axis_dout)
            );

            assign axil_rd_dout = '0;
        end
    endgenerate

endmodule
