`include "ifc_axis.sv"

// Shared by the local-offload fabric and the legacy top-level host path.
// TUSER[0] selects a physical NMU for the entire packet; a stalled selected
// lane never falls back to another lane. Lane 1 is drained when only lane 0
// exists, so an invalid selector cannot block later valid packets.
module host_h2c_lane_switch #(
    parameter int HOST_NOC_LANES = 2,
    parameter int HOST_TID_BASE = 26
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave s_axis,
    ifc_axis.master m_axis [2]
);
    ifc_axis #(.DATA_WIDTH(512), .TDEST_WIDTH(10), .TID_WIDTH(6), .TUSER_WIDTH(1))
        selected [2] (.axis_aclk(clk));
    axis_packet_demux #(
        .DATA_WIDTH(512), .TDEST_WIDTH(10), .TID_WIDTH(6),
        .TUSER_WIDTH(1), .NUM_MASTERS(2), .SELECT_WIDTH(1)
    ) u_packet_select (
        .clk(clk), .resetn(resetn), .select(s_axis.t.user[0]),
        .s_axis(s_axis), .m_axis(selected)
    );
    for (genvar lane = 0; lane < 2; lane++) begin : g_lane
        if (lane < HOST_NOC_LANES) begin : g_active
            always_comb begin
                m_axis[lane].t = selected[lane].t;
                m_axis[lane].t.id = 6'(HOST_TID_BASE + lane);
                m_axis[lane].t.user = '0;
            end
            assign m_axis[lane].tvalid = selected[lane].tvalid;
            assign selected[lane].tready = m_axis[lane].tready;
        end else begin : g_drop
            assign selected[lane].tready = 1'b1;
            assign m_axis[lane].t = '0;
            assign m_axis[lane].tvalid = 1'b0;
        end
    end
    initial begin
        if (HOST_NOC_LANES < 1 || HOST_NOC_LANES > 2)
            $fatal(1, "host_h2c_lane_switch: HOST_NOC_LANES must be 1 or 2");
        if (HOST_TID_BASE < 0 || HOST_TID_BASE + HOST_NOC_LANES > 64)
            $fatal(1, "host_h2c_lane_switch: physical NMU TIDs must fit six bits");
    end
endmodule

// Local host-facing USO/URO paths. USO retains its output NMU and URO retains
// its input NSU; neither of those NoC interfaces is part of this fabric.
module host_packet_fabric #(
    parameter int HOST_NOC_LANES = 2,
    parameter int USO_LOCAL_TDEST = 14,
    parameter int HOST_TID_BASE = 26,
    parameter int NUM_SOURCES = 32,
    parameter int MAX_PACKET_SIZE_BYTES = 2048
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave s_axis_h2c,
    ifc_axis.master m_axis_uso,
    ifc_axis.slave s_axis_uro,
    ifc_axis.master m_axis_noc_h2c [2],
    ifc_axis.slave s_axis_noc_c2h [2],
    ifc_axis.master m_axis_c2h
);
    localparam int DATA_WIDTH = 512;
    localparam int TDEST_WIDTH = 10;
    localparam int TID_WIDTH = 6;
    localparam int TUSER_WIDTH = 1;

    ifc_axis #(.DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH))
        h2c_selected [2] (.axis_aclk(clk)),
        return_registered [HOST_NOC_LANES] (.axis_aclk(clk)),
        c2h_frames [HOST_NOC_LANES + 1] (.axis_aclk(clk));

    // The alias is consumed locally. USO's own programmed egress table sets
    // the destination of its segmented output at its separate NMU.
    axis_packet_demux #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH), .NUM_MASTERS(2)
    ) u_h2c_select (
        .clk(clk), .resetn(resetn),
        .select(s_axis_h2c.t.dest == TDEST_WIDTH'(USO_LOCAL_TDEST)),
        .s_axis(s_axis_h2c), .m_axis(h2c_selected)
    );
    always_comb begin
        m_axis_uso.t = h2c_selected[1].t;
        m_axis_uso.t.id = TID_WIDTH'(HOST_TID_BASE);
        m_axis_uso.t.user = '0;
    end
    assign m_axis_uso.tvalid = h2c_selected[1].tvalid;
    assign h2c_selected[1].tready = m_axis_uso.tready;

    host_h2c_lane_switch #(
        .HOST_NOC_LANES(HOST_NOC_LANES), .HOST_TID_BASE(HOST_TID_BASE)
    ) u_h2c_lane_select (
        .clk(clk), .resetn(resetn),
        .s_axis(h2c_selected[0]), .m_axis(m_axis_noc_h2c)
    );
    for (genvar lane = 0; lane < 2; lane++) begin : g_host_lane
        if (lane < HOST_NOC_LANES) begin : g_active
            // Reconstruct independently at each NSU, using the original
            // physical producer TID. Do not packet-lock an interleaved input.
            axis_register_slice u_return_register (
                .clk(clk), .resetn(resetn),
                .s_axis(s_axis_noc_c2h[lane]), .m_axis(return_registered[lane])
            );
            axis_packet_rebuilder #(
                .DATA_WIDTH(DATA_WIDTH), .NUM_SOURCES(NUM_SOURCES),
                .MAX_PACKET_SIZE_BYTES(MAX_PACKET_SIZE_BYTES), .TID_WIDTH(TID_WIDTH)
            ) u_return_rebuilder (
                .clk(clk), .resetn(resetn),
                .s_axis(return_registered[lane]), .m_axis(c2h_frames[lane])
            );
        end else begin : g_unused
            assign s_axis_noc_c2h[lane].tready = 1'b0;
        end
    end

    // URO already reconstructs its own NSU input and emits complete frames.
    // Packet arbitration holds the selected producer through accepted TLAST,
    // including stalls, so neither bypass lane can splice into a URO frame.
    assign c2h_frames[HOST_NOC_LANES].t = s_axis_uro.t;
    assign c2h_frames[HOST_NOC_LANES].tvalid = s_axis_uro.tvalid;
    assign s_axis_uro.tready = c2h_frames[HOST_NOC_LANES].tready;
    axis_packet_arbiter #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH),
        .NUM_SLAVES(HOST_NOC_LANES + 1), .REGISTER_GRANT(1'b1)
    ) u_c2h_merge (
        .clk(clk), .resetn(resetn),
        .s_axis(c2h_frames), .m_axis(m_axis_c2h)
    );

    initial begin
        if (HOST_NOC_LANES < 1 || HOST_NOC_LANES > 2)
            $fatal(1, "host_packet_fabric: HOST_NOC_LANES must be 1 or 2");
        if (USO_LOCAL_TDEST < 0 || USO_LOCAL_TDEST >= 1024)
            $fatal(1, "host_packet_fabric: USO alias must be a 10-bit destination");
        if (HOST_TID_BASE < 0 || HOST_TID_BASE + HOST_NOC_LANES > NUM_SOURCES)
            $fatal(1, "host_packet_fabric: host TIDs must fit the source namespace");
        if ($bits(s_axis_h2c.t.data) != DATA_WIDTH ||
            $bits(s_axis_h2c.t.id) != TID_WIDTH ||
            $bits(s_axis_h2c.t.dest) != TDEST_WIDTH ||
            $bits(s_axis_h2c.t.user) != TUSER_WIDTH)
            $fatal(1, "host_packet_fabric: requires AXIS widths 512/6/10/1");
    end
endmodule
