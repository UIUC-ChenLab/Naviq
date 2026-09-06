`include "ifc_axil.sv"

module axil_crossbar #(
    parameter int ADDR_WIDTH  = 32,
    parameter int DATA_WIDTH  = 32,
    parameter int TUSER_WIDTH = 16,
    parameter int NUM_SLAVES  = 1,
    parameter logic [NUM_SLAVES-1:0][ADDR_WIDTH-1:0] SLAVE_BASE_ADDR = '0,
    parameter logic [NUM_SLAVES-1:0][ADDR_WIDTH-1:0] SLAVE_ADDR_SIZE = '0
) (
    input logic clk,
    input logic resetn,

    ifc_axil.slave  s_axil,
    ifc_axil.master m_axil [NUM_SLAVES]
);

    localparam int STRB_WIDTH = DATA_WIDTH / 8;
    localparam int SEL_WIDTH  = (NUM_SLAVES <= 1) ? 1 : $clog2(NUM_SLAVES);
    localparam int AWUSER_W   = (TUSER_WIDTH > 0) ? TUSER_WIDTH : 1;
    localparam int WUSER_W    = (TUSER_WIDTH > 0) ? TUSER_WIDTH : 1;
    localparam int ARUSER_W   = (TUSER_WIDTH > 0) ? TUSER_WIDTH : 1;

    typedef struct packed {
        logic [ADDR_WIDTH-1:0] addr;
        logic [2:0]            prot;
        logic [AWUSER_W-1:0]   user;
    } aw_chan_t;

    typedef struct packed {
        logic [DATA_WIDTH-1:0] data;
        logic [STRB_WIDTH-1:0] strb;
        logic [WUSER_W-1:0]    user;
    } w_chan_t;

    typedef struct packed {
        logic [ADDR_WIDTH-1:0] addr;
        logic [2:0]            prot;
        logic [ARUSER_W-1:0]   user;
    } ar_chan_t;

    typedef struct packed {
        logic [1:0]            resp;
        logic [TUSER_WIDTH-1:0] user;
    } b_chan_t;

    typedef struct packed {
        logic [DATA_WIDTH-1:0] data;
        logic [1:0]            resp;
        logic [TUSER_WIDTH-1:0] user;
    } r_chan_t;

    typedef enum logic [1:0] {
        ST_IDLE          = 2'd0,
        ST_WRITE_COLLECT = 2'd1,
        ST_WRITE_FORWARD = 2'd2,
        ST_READ_FORWARD  = 2'd3
    } state_t;

    state_t state_r;

    aw_chan_t aw_buf_r;
    aw_chan_t aw_capture_c;
    w_chan_t  w_buf_r;
    ar_chan_t ar_buf_r;

    logic aw_buf_valid_r;
    logic w_buf_valid_r;
    logic ar_buf_valid_r;

    logic [SEL_WIDTH-1:0] write_sel_r;
    logic                 write_sel_valid_r;
    logic                 write_decode_hit_r;
    logic                 write_aw_sent_r;
    logic                 write_w_sent_r;

    logic [SEL_WIDTH-1:0] read_sel_r;
    logic                 read_decode_hit_r;
    logic                 read_ar_sent_r;

    logic aw_decode_hit_c;
    logic [SEL_WIDTH-1:0] aw_decode_sel_c;
    logic ar_decode_hit_c;
    logic [SEL_WIDTH-1:0] ar_decode_sel_c;

    aw_chan_t m_aw_c [NUM_SLAVES];
    logic     m_aw_valid_c [NUM_SLAVES];
    logic     m_aw_ready_s [NUM_SLAVES];

    w_chan_t  m_w_c [NUM_SLAVES];
    logic     m_w_valid_c [NUM_SLAVES];
    logic     m_w_ready_s [NUM_SLAVES];

    b_chan_t  m_b_s [NUM_SLAVES];
    logic     m_b_valid_s [NUM_SLAVES];
    logic     m_b_ready_c [NUM_SLAVES];

    ar_chan_t m_ar_c [NUM_SLAVES];
    logic     m_ar_valid_c [NUM_SLAVES];
    logic     m_ar_ready_s [NUM_SLAVES];

    r_chan_t  m_r_s [NUM_SLAVES];
    logic     m_r_valid_s [NUM_SLAVES];
    logic     m_r_ready_c [NUM_SLAVES];

    logic aw_fire_c;
    logic w_fire_c;
    logic ar_fire_c;
    logic b_fire_c;
    logic r_fire_c;

    function automatic logic [ADDR_WIDTH:0] extend_addr(input logic [ADDR_WIDTH-1:0] addr);
        extend_addr = {1'b0, addr};
    endfunction

    function automatic logic is_power_of_two(input logic [ADDR_WIDTH-1:0] value);
        is_power_of_two = (value != '0) && ((value & (value - 1'b1)) == '0);
    endfunction

    function automatic logic decode_addr_hit(
        input logic [ADDR_WIDTH-1:0] addr,
        output logic [SEL_WIDTH-1:0] sel
    );
        logic hit;

        hit = 1'b0;
        sel = '0;

        for (int i = 0; i < NUM_SLAVES; i++) begin
            logic [ADDR_WIDTH:0] base_ext;
            logic [ADDR_WIDTH:0] size_ext;
            logic [ADDR_WIDTH:0] end_ext;
            logic [ADDR_WIDTH:0] addr_ext;

            base_ext = extend_addr(SLAVE_BASE_ADDR[i]);
            size_ext = extend_addr(SLAVE_ADDR_SIZE[i]);
            end_ext  = base_ext + size_ext;
            addr_ext = extend_addr(addr);

            if ((addr_ext >= base_ext) && (addr_ext < end_ext)) begin
                hit = 1'b1;
                sel = SEL_WIDTH'(i);
            end
        end

        return hit;
    endfunction

    always_comb begin
        aw_decode_hit_c = decode_addr_hit(s_axil.aw.addr, aw_decode_sel_c);
        ar_decode_hit_c = decode_addr_hit(s_axil.ar.addr, ar_decode_sel_c);

        aw_capture_c = s_axil.aw;
        if (aw_decode_hit_c)
            aw_capture_c.addr = s_axil.aw.addr - SLAVE_BASE_ADDR[aw_decode_sel_c];
    end

    for (genvar i = 0; i < NUM_SLAVES; i++) begin : g_if_map
        assign m_axil[i].aw       = m_aw_c[i];
        assign m_axil[i].aw_valid = m_aw_valid_c[i];
        assign m_aw_ready_s[i]    = m_axil[i].aw_ready;

        assign m_axil[i].w        = m_w_c[i];
        assign m_axil[i].w_valid  = m_w_valid_c[i];
        assign m_w_ready_s[i]     = m_axil[i].w_ready;

        assign m_b_s[i].resp      = m_axil[i].b.resp;
        assign m_b_s[i].user      = m_axil[i].b.user;
        assign m_b_valid_s[i]     = m_axil[i].b_valid;
        assign m_axil[i].b_ready  = m_b_ready_c[i];

        assign m_axil[i].ar       = m_ar_c[i];
        assign m_axil[i].ar_valid = m_ar_valid_c[i];
        assign m_ar_ready_s[i]    = m_axil[i].ar_ready;

        assign m_r_s[i].data      = m_axil[i].r.data;
        assign m_r_s[i].resp      = m_axil[i].r.resp;
        assign m_r_s[i].user      = m_axil[i].r.user;
        assign m_r_valid_s[i]     = m_axil[i].r_valid;
        assign m_axil[i].r_ready  = m_r_ready_c[i];
    end

    always_comb begin
        s_axil.aw_ready = 1'b0;
        s_axil.w_ready  = 1'b0;
        s_axil.b_valid  = 1'b0;
        s_axil.b.resp   = 2'b00;
        s_axil.b.user   = '0;
        s_axil.ar_ready = 1'b0;
        s_axil.r_valid  = 1'b0;
        s_axil.r.data   = '0;
        s_axil.r.resp   = 2'b00;
        s_axil.r.user   = '0;

        for (int i = 0; i < NUM_SLAVES; i++) begin
            m_aw_c[i]      = '0;
            m_aw_valid_c[i] = 1'b0;
            m_w_c[i]       = '0;
            m_w_valid_c[i]  = 1'b0;
            m_b_ready_c[i]  = 1'b0;
            m_ar_c[i]      = '0;
            m_ar_valid_c[i] = 1'b0;
            m_r_ready_c[i]  = 1'b0;
        end

        unique case (state_r)
            ST_IDLE: begin
                if (s_axil.aw_valid || s_axil.w_valid) begin
                    s_axil.aw_ready = 1'b1;
                    s_axil.w_ready  = 1'b1;
                end else begin
                    s_axil.ar_ready = 1'b1;
                end
            end

            ST_WRITE_COLLECT: begin
                s_axil.aw_ready = !aw_buf_valid_r;
                s_axil.w_ready  = !w_buf_valid_r;
            end

            ST_WRITE_FORWARD: begin
                if (!write_decode_hit_r) begin
                    s_axil.b_valid = 1'b1;
                    s_axil.b.resp  = 2'b10;
                end else begin
                    m_aw_c[write_sel_r]          = aw_buf_r;
                    m_aw_valid_c[write_sel_r]    = !write_aw_sent_r;
                    m_w_c[write_sel_r]           = w_buf_r;
                    m_w_valid_c[write_sel_r]     = !write_w_sent_r;

                    if (write_aw_sent_r && write_w_sent_r) begin
                        s_axil.b_valid            = m_b_valid_s[write_sel_r];
                        s_axil.b.resp             = m_b_s[write_sel_r].resp;
                        s_axil.b.user             = m_b_s[write_sel_r].user;
                        m_b_ready_c[write_sel_r]  = s_axil.b_ready;
                    end
                end
            end

            ST_READ_FORWARD: begin
                if (!read_decode_hit_r) begin
                    s_axil.r_valid = 1'b1;
                    s_axil.r.data  = '0;
                    s_axil.r.resp  = 2'b10;
                end else begin
                    m_ar_c[read_sel_r]        = ar_buf_r;
                    m_ar_c[read_sel_r].addr   = ar_buf_r.addr - SLAVE_BASE_ADDR[read_sel_r];
                    m_ar_valid_c[read_sel_r]  = !read_ar_sent_r;

                    if (read_ar_sent_r) begin
                        s_axil.r_valid           = m_r_valid_s[read_sel_r];
                        s_axil.r.data            = m_r_s[read_sel_r].data;
                        s_axil.r.resp            = m_r_s[read_sel_r].resp;
                        s_axil.r.user            = m_r_s[read_sel_r].user;
                        m_r_ready_c[read_sel_r]  = s_axil.r_ready;
                    end
                end
            end

            default: begin
            end
        endcase
    end

    assign aw_fire_c = s_axil.aw_valid && s_axil.aw_ready;
    assign w_fire_c  = s_axil.w_valid && s_axil.w_ready;
    assign ar_fire_c = s_axil.ar_valid && s_axil.ar_ready;
    assign b_fire_c  = s_axil.b_valid && s_axil.b_ready;
    assign r_fire_c  = s_axil.r_valid && s_axil.r_ready;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            state_r            <= ST_IDLE;
            aw_buf_r           <= '0;
            w_buf_r            <= '0;
            ar_buf_r           <= '0;
            aw_buf_valid_r     <= 1'b0;
            w_buf_valid_r      <= 1'b0;
            ar_buf_valid_r     <= 1'b0;
            write_sel_r        <= '0;
            write_sel_valid_r  <= 1'b0;
            write_decode_hit_r <= 1'b0;
            write_aw_sent_r    <= 1'b0;
            write_w_sent_r     <= 1'b0;
            read_sel_r         <= '0;
            read_decode_hit_r  <= 1'b0;
            read_ar_sent_r     <= 1'b0;
        end else begin
            unique case (state_r)
                ST_IDLE: begin
                    if (aw_fire_c || w_fire_c) begin
                        if (aw_fire_c) begin
                            aw_buf_r           <= aw_capture_c;
                            aw_buf_valid_r     <= 1'b1;
                            write_sel_r        <= aw_decode_sel_c;
                            write_sel_valid_r  <= 1'b1;
                            write_decode_hit_r <= aw_decode_hit_c;
                        end else begin
                            aw_buf_valid_r     <= 1'b0;
                            write_sel_r        <= '0;
                            write_sel_valid_r  <= 1'b0;
                            write_decode_hit_r <= 1'b0;
                        end

                        if (w_fire_c) begin
                            w_buf_r       <= s_axil.w;
                            w_buf_valid_r <= 1'b1;
                        end else begin
                            w_buf_valid_r <= 1'b0;
                        end

                        ar_buf_valid_r  <= 1'b0;
                        read_ar_sent_r  <= 1'b0;
                        write_aw_sent_r <= 1'b0;
                        write_w_sent_r  <= 1'b0;

                        if ((aw_fire_c || aw_buf_valid_r) && (w_fire_c || w_buf_valid_r))
                            state_r <= ST_WRITE_FORWARD;
                        else
                            state_r <= ST_WRITE_COLLECT;
                    end else if (ar_fire_c) begin
                        ar_buf_r          <= s_axil.ar;
                        ar_buf_valid_r    <= 1'b1;
                        read_sel_r        <= ar_decode_sel_c;
                        read_decode_hit_r <= ar_decode_hit_c;
                        read_ar_sent_r    <= 1'b0;

                        aw_buf_valid_r     <= 1'b0;
                        w_buf_valid_r      <= 1'b0;
                        write_sel_valid_r  <= 1'b0;
                        write_decode_hit_r <= 1'b0;
                        write_aw_sent_r    <= 1'b0;
                        write_w_sent_r     <= 1'b0;

                        state_r <= ST_READ_FORWARD;
                    end
                end

                ST_WRITE_COLLECT: begin
                    if (aw_fire_c) begin
                        aw_buf_r           <= aw_capture_c;
                        aw_buf_valid_r     <= 1'b1;
                        write_sel_r        <= aw_decode_sel_c;
                        write_sel_valid_r  <= 1'b1;
                        write_decode_hit_r <= aw_decode_hit_c;
                    end

                    if (w_fire_c) begin
                        w_buf_r       <= s_axil.w;
                        w_buf_valid_r <= 1'b1;
                    end

                    if ((aw_buf_valid_r || aw_fire_c) && (w_buf_valid_r || w_fire_c)) begin
                        write_aw_sent_r <= 1'b0;
                        write_w_sent_r  <= 1'b0;
                        state_r         <= ST_WRITE_FORWARD;
                    end
                end

                ST_WRITE_FORWARD: begin
                    if (write_decode_hit_r) begin
                        if (!write_aw_sent_r && m_aw_valid_c[write_sel_r] && m_aw_ready_s[write_sel_r])
                            write_aw_sent_r <= 1'b1;
                        if (!write_w_sent_r && m_w_valid_c[write_sel_r] && m_w_ready_s[write_sel_r])
                            write_w_sent_r <= 1'b1;
                    end

                    if (b_fire_c) begin
                        state_r            <= ST_IDLE;
                        aw_buf_valid_r     <= 1'b0;
                        w_buf_valid_r      <= 1'b0;
                        write_sel_valid_r  <= 1'b0;
                        write_decode_hit_r <= 1'b0;
                        write_aw_sent_r    <= 1'b0;
                        write_w_sent_r     <= 1'b0;
                    end
                end

                ST_READ_FORWARD: begin
                    if (read_decode_hit_r) begin
                        if (!read_ar_sent_r && m_ar_valid_c[read_sel_r] && m_ar_ready_s[read_sel_r])
                            read_ar_sent_r <= 1'b1;
                    end

                    if (r_fire_c) begin
                        state_r           <= ST_IDLE;
                        ar_buf_valid_r    <= 1'b0;
                        read_decode_hit_r <= 1'b0;
                        read_ar_sent_r    <= 1'b0;
                    end
                end

                default: begin
                    state_r <= ST_IDLE;
                end
            endcase
        end
    end

    initial begin
        if (DATA_WIDTH != 32) begin
            $error("axil_crossbar: DATA_WIDTH must be 32, got %0d", DATA_WIDTH);
            $finish;
        end

        if (NUM_SLAVES < 1) begin
            $error("axil_crossbar: NUM_SLAVES must be >= 1, got %0d", NUM_SLAVES);
            $finish;
        end

        for (int i = 0; i < NUM_SLAVES; i++) begin
            logic [ADDR_WIDTH:0] base_i;
            logic [ADDR_WIDTH:0] size_i;
            logic [ADDR_WIDTH:0] end_i;

            base_i = extend_addr(SLAVE_BASE_ADDR[i]);
            size_i = extend_addr(SLAVE_ADDR_SIZE[i]);
            end_i  = base_i + size_i;

            if (!is_power_of_two(SLAVE_ADDR_SIZE[i])) begin
                $error("axil_crossbar: SLAVE_ADDR_SIZE[%0d] (%0h) must be a non-zero power of 2",
                       i, SLAVE_ADDR_SIZE[i]);
                $finish;
            end

            if ((SLAVE_BASE_ADDR[i] & (SLAVE_ADDR_SIZE[i] - 1'b1)) != '0) begin
                $error("axil_crossbar: SLAVE_BASE_ADDR[%0d] (%0h) must be aligned to size %0h",
                       i, SLAVE_BASE_ADDR[i], SLAVE_ADDR_SIZE[i]);
                $finish;
            end

            if (end_i > ({{ADDR_WIDTH{1'b0}}, 1'b1} << ADDR_WIDTH)) begin
                $error("axil_crossbar: aperture %0d overflows ADDR_WIDTH space (base=%0h size=%0h)",
                       i, SLAVE_BASE_ADDR[i], SLAVE_ADDR_SIZE[i]);
                $finish;
            end

            for (int j = i + 1; j < NUM_SLAVES; j++) begin
                logic [ADDR_WIDTH:0] base_j;
                logic [ADDR_WIDTH:0] size_j;
                logic [ADDR_WIDTH:0] end_j;

                base_j = extend_addr(SLAVE_BASE_ADDR[j]);
                size_j = extend_addr(SLAVE_ADDR_SIZE[j]);
                end_j  = base_j + size_j;

                if ((base_i < end_j) && (base_j < end_i)) begin
                    $error("axil_crossbar: apertures %0d and %0d overlap", i, j);
                    $finish;
                end
            end
        end
    end

endmodule
