`ifndef AXIS_BEAT_ARBITER_SV
`define AXIS_BEAT_ARBITER_SV

`include "ifc_axis.sv"
`include "axi_struct_macros.svh"
`include "axis_beat_mux.sv"

// Beat-level round-robin AXI Stream arbiter. The grant advances after every
// accepted beat; tlast has no effect on arbitration.
module axis_beat_arbiter #(
    parameter int DATA_WIDTH     = 512,
    parameter int TDEST_WIDTH    = 12,
    parameter int TID_WIDTH      = 16,
    parameter int TUSER_WIDTH    = 16,
    parameter int NUM_SLAVES     = 1,
    parameter int SELECT_WIDTH   = (NUM_SLAVES <= 1) ? 1 : $clog2(NUM_SLAVES),
    parameter bit REGISTER_GRANT = 1'b0
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave  s_axis [NUM_SLAVES],
    ifc_axis.master m_axis
);
    `AXIS_T_CHAN_T(m_axis, t_chan_t);
    localparam int SEL_WIDTH = (NUM_SLAVES <= 1) ? 1 : $clog2(NUM_SLAVES);

    logic [SEL_WIDTH-1:0] last_grant_r, grant_sel_r;
    logic last_grant_valid_r, grant_pending_r;
    logic s_valid [NUM_SLAVES];
    logic any_valid_c, grant_valid_c, m_fire_c;
    logic [SEL_WIDTH-1:0] grant_sel_c;
    logic [SELECT_WIDTH-1:0] mux_select_c;
    logic mux_grant_valid_c;

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH)
    ) mux_s_axis [NUM_SLAVES] (.axis_aclk(clk));
    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH)
    ) mux_m_axis (.axis_aclk(clk));

    function automatic logic [SEL_WIDTH-1:0] lowest_valid(
        input logic valid [NUM_SLAVES]
    );
        logic found;
        lowest_valid = '0;
        found = 1'b0;
        for (int i = 0; i < NUM_SLAVES; i++) begin
            if (!found && valid[i]) begin
                lowest_valid = SEL_WIDTH'(i);
                found = 1'b1;
            end
        end
    endfunction

    function automatic logic [SEL_WIDTH-1:0] next_valid_after(
        input logic [SEL_WIDTH-1:0] last,
        input logic valid [NUM_SLAVES]
    );
        int candidate;
        logic found;
        next_valid_after = '0;
        found = 1'b0;
        for (int offset = 1; offset <= NUM_SLAVES; offset++) begin
            candidate = int'(last) + offset;
            if (candidate >= NUM_SLAVES)
                candidate -= NUM_SLAVES;
            if (!found && valid[candidate]) begin
                next_valid_after = SEL_WIDTH'(candidate);
                found = 1'b1;
            end
        end
    endfunction

    always_comb begin
        any_valid_c = 1'b0;
        for (int i = 0; i < NUM_SLAVES; i++)
            any_valid_c |= s_valid[i];
    end

    assign grant_valid_c = any_valid_c;
    assign grant_sel_c = last_grant_valid_r ? next_valid_after(last_grant_r, s_valid)
                                            : lowest_valid(s_valid);
    assign mux_select_c = (REGISTER_GRANT || grant_pending_r)
        ? SELECT_WIDTH'(grant_sel_r) : SELECT_WIDTH'(grant_sel_c);
    assign mux_grant_valid_c = REGISTER_GRANT ? grant_pending_r
        : (grant_pending_r || grant_valid_c);
    assign m_fire_c = m_axis.tvalid && m_axis.tready;

    for (genvar i = 0; i < NUM_SLAVES; i++) begin : g_inputs
        assign s_valid[i] = s_axis[i].tvalid;
        assign mux_s_axis[i].t = s_axis[i].t;
        assign mux_s_axis[i].tvalid =
            mux_grant_valid_c && (mux_select_c == SELECT_WIDTH'(i)) && s_axis[i].tvalid;
        assign s_axis[i].tready =
            mux_grant_valid_c && (mux_select_c == SELECT_WIDTH'(i))
                ? mux_s_axis[i].tready : 1'b0;
    end

    assign m_axis.t = mux_grant_valid_c ? mux_m_axis.t : t_chan_t'('0);
    assign m_axis.tvalid = mux_grant_valid_c && mux_m_axis.tvalid;
    assign mux_m_axis.tready = mux_grant_valid_c && m_axis.tready;

    axis_beat_mux #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH),
        .NUM_SLAVES(NUM_SLAVES), .SELECT_WIDTH(SELECT_WIDTH)
    ) u_mux (
        .clk(clk), .resetn(resetn), .select(mux_select_c),
        .s_axis(mux_s_axis), .m_axis(mux_m_axis.master)
    );

    always_ff @(posedge clk) begin
        if (!resetn) begin
            last_grant_r <= '0;
            last_grant_valid_r <= 1'b0;
            grant_sel_r <= '0;
            grant_pending_r <= 1'b0;
        end else begin
            if (!grant_valid_c && !grant_pending_r)
                last_grant_valid_r <= 1'b0;
            if (REGISTER_GRANT && !grant_pending_r && grant_valid_c) begin
                grant_sel_r <= grant_sel_c;
                grant_pending_r <= 1'b1;
            end
            // A combinational grant may be replaced only after acceptance.
            // Hold the selected source while stalled, including the first
            // beat, without adding a cycle on the always-ready path.
            if (!REGISTER_GRANT && !grant_pending_r &&
                m_axis.tvalid && !m_axis.tready) begin
                grant_sel_r <= SEL_WIDTH'(mux_select_c);
                grant_pending_r <= 1'b1;
            end
            if (m_fire_c) begin
                last_grant_r <= SEL_WIDTH'(mux_select_c);
                last_grant_valid_r <= 1'b1;
                grant_pending_r <= 1'b0;
            end
        end
    end

    initial begin
        if (NUM_SLAVES < 1) begin
            $error("axis_beat_arbiter: NUM_SLAVES must be >= 1");
            $finish;
        end
        if (DATA_WIDTH % 8 != 0) begin
            $error("axis_beat_arbiter: DATA_WIDTH must be byte-aligned");
            $finish;
        end
        if (SELECT_WIDTH < SEL_WIDTH) begin
            $error("axis_beat_arbiter: SELECT_WIDTH is too small");
            $finish;
        end
    end
endmodule
`endif
