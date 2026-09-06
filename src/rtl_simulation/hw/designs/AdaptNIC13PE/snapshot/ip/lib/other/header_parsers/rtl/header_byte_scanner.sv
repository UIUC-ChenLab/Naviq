`include "ifc_axis.sv"

module header_byte_scanner #(
    parameter int DATA_WIDTH = 512,
    parameter int HDR_BYTES  = 20
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis_header
);

    localparam int KEEP_WIDTH   = DATA_WIDTH / 8;
    localparam int HDR_DATA_W   = HDR_BYTES * 8;
    localparam int OUT_DATA_W   = (HDR_BYTES + 1) * 8;
    localparam int BEAT_COUNT_W = $clog2(DATA_WIDTH);

    typedef enum logic {COLLECT, DRAIN} state_t;

    initial begin
        if (DATA_WIDTH < 256 || DATA_WIDTH % 8 != 0)
            $error("header_byte_scanner: DATA_WIDTH must be byte-aligned and at least 256 bits");
        if (HDR_BYTES < 1)
            $error("header_byte_scanner: HDR_BYTES must be positive");
        if (HDR_BYTES > KEEP_WIDTH)
            $error("header_byte_scanner: header must fit in one input beat");
    end

    state_t state_r;
    logic out_valid_r;
    logic [OUT_DATA_W-1:0] out_data_r;

    logic advance;
    logic scan_fire;
    logic header_short_c;

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_count_in (.axis_aclk(clk)), u_scan_data_in (.axis_aclk(clk)),
      u_scan_data (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(BEAT_COUNT_W), .TDEST_WIDTH(1), .TID_WIDTH(1), .TUSER_WIDTH(1)
    ) u_beat_size (.axis_aclk(clk));

    always_comb begin
        u_count_in.t = '0;
        u_count_in.t.data = s_axis.t.data;
        u_count_in.t.keep = s_axis.t.keep;
        u_count_in.t.last = s_axis.t.last;
        u_count_in.tvalid = s_axis.tvalid && u_scan_data_in.tready;

        u_scan_data_in.t = '0;
        u_scan_data_in.t.data = s_axis.t.data;
        u_scan_data_in.t.keep = s_axis.t.keep;
        u_scan_data_in.t.last = s_axis.t.last;
        u_scan_data_in.tvalid = s_axis.tvalid && u_count_in.tready;

        s_axis.tready = u_count_in.tready && u_scan_data_in.tready;
    end

    axis_count_beat_size #(
        .DATA_WIDTH(DATA_WIDTH)
    ) u_count_beat_size (
        .clk(clk), .resetn(resetn), .s_axis(u_count_in), .m_axis(u_beat_size)
    );

    axis_register_slice #(
        .MODE("STANDARD"), .NUM_STAGES(3)
    ) u_scan_data_pipeline (
        .clk(clk), .resetn(resetn), .s_axis(u_scan_data_in), .m_axis(u_scan_data)
    );

    assign advance = !out_valid_r || m_axis_header.tready;
    assign scan_fire = u_scan_data.tvalid && u_beat_size.tvalid && advance;
    assign u_scan_data.tready = u_beat_size.tvalid && advance;
    assign u_beat_size.tready = u_scan_data.tvalid && advance;
    assign header_short_c = int'(u_beat_size.t.data) < HDR_BYTES;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            state_r <= COLLECT;
            out_valid_r <= 1'b0;
            out_data_r <= '0;
        end else if (advance) begin
            out_valid_r <= 1'b0;

            if (scan_fire) begin
                if (state_r == COLLECT) begin
                    out_data_r <= '0;
                    out_data_r[HDR_DATA_W-1:0] <= u_scan_data.t.data[HDR_DATA_W-1:0];
                    out_data_r[HDR_DATA_W] <= header_short_c;
                    out_valid_r <= 1'b1;

                    if (!u_scan_data.t.last)
                        state_r <= DRAIN;
                end else if (u_scan_data.t.last) begin
                    state_r <= COLLECT;
                end
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (resetn && u_scan_data.tvalid && u_beat_size.tvalid) begin
            assert (u_scan_data.t.last == u_beat_size.t.last)
                else $error("header_byte_scanner: beat data and byte count are misaligned");
        end

        if (resetn && s_axis.tvalid && s_axis.tready) begin
            if (!s_axis.t.last)
                assert (s_axis.t.keep == '1)
                    else $error("header_byte_scanner: non-final beat must be dense");
            else begin
                assert (s_axis.t.keep != '0)
                    else $error("header_byte_scanner: empty final beat is unsupported");
                assert ((s_axis.t.keep & (s_axis.t.keep + 1'b1)) == '0)
                    else $error("header_byte_scanner: final tkeep must be lower-contiguous");
            end
        end
    end
`endif

    always_comb begin
        m_axis_header.t = '0;
        m_axis_header.t.data = out_data_r;
        m_axis_header.t.keep = '1;
        m_axis_header.t.id = '0;
        m_axis_header.t.dest = '0;
        m_axis_header.t.user = '0;
        m_axis_header.t.last = 1'b1;
        m_axis_header.tvalid = out_valid_r;
    end

endmodule
