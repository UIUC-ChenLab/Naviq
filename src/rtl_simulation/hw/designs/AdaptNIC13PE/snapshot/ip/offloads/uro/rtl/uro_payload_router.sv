`include "ifc_axis.sv"

// Hierarchical, packet-locked payload demultiplexer.
//
// The queue ID travels in t.user.  Every level first captures the stream in a
// ready-isolating relay queue and then decodes only that level's queue-ID bits.
// Consequently, leaf FIFO readiness cannot propagate combinationally through
// the hierarchy to the source.
module uro_payload_router #(
    parameter int DATA_WIDTH      = 512,
    parameter int TDEST_WIDTH     = 1,
    parameter int TID_WIDTH       = 1,
    parameter int NUM_QUEUES      = 32,
    parameter int TREE_DEPTH      = 2,
    parameter int ROUTE_WIDTH     =
        (NUM_QUEUES <= 1) ? 1 : $clog2(NUM_QUEUES),
    parameter int ISOLATE_STAGES  = 2
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.master m_axis [NUM_QUEUES]
);
    localparam int LOCAL_ROUTE_WIDTH =
        (NUM_QUEUES <= 1) ? 1 : $clog2(NUM_QUEUES);
    localparam int LEVEL_SELECT_WIDTH =
        (LOCAL_ROUTE_WIDTH + TREE_DEPTH - 1) / TREE_DEPTH;
    localparam int CHILD_ROUTE_WIDTH =
        LOCAL_ROUTE_WIDTH - LEVEL_SELECT_WIDTH;
    localparam int NUM_BRANCHES = 1 << LEVEL_SELECT_WIDTH;

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH),
        .TUSER_WIDTH(ROUTE_WIDTH)
    ) level_input (clk);

    // This buffer is the timing boundary for the current routing level.
    axis_register_slice #(
        .MODE("ISOLATE"),
        .NUM_STAGES(ISOLATE_STAGES)
    ) u_level_input_pipeline (
        .clk(clk),
        .resetn(resetn),
        .s_axis(s_axis),
        .m_axis(level_input)
    );

    if (TREE_DEPTH == 1) begin : g_leaf
        axis_packet_demux #(
            .DATA_WIDTH(DATA_WIDTH),
            .TDEST_WIDTH(TDEST_WIDTH),
            .TID_WIDTH(TID_WIDTH),
            .TUSER_WIDTH(ROUTE_WIDTH),
            .NUM_MASTERS(NUM_QUEUES),
            .SELECT_WIDTH(LOCAL_ROUTE_WIDTH),
            .BROADCAST_DATA(1'b1)
        ) u_leaf_demux (
            .clk(clk),
            .resetn(resetn),
            .select(level_input.t.user[LOCAL_ROUTE_WIDTH-1:0]),
            .s_axis(level_input),
            .m_axis(m_axis)
        );
    end else begin : g_branch
        localparam int CHILD_QUEUES = 1 << CHILD_ROUTE_WIDTH;

        ifc_axis #(
            .DATA_WIDTH(DATA_WIDTH),
            .TDEST_WIDTH(TDEST_WIDTH),
            .TID_WIDTH(TID_WIDTH),
            .TUSER_WIDTH(ROUTE_WIDTH)
        ) branch_axis [NUM_BRANCHES] (clk);

        axis_packet_demux #(
            .DATA_WIDTH(DATA_WIDTH),
            .TDEST_WIDTH(TDEST_WIDTH),
            .TID_WIDTH(TID_WIDTH),
            .TUSER_WIDTH(ROUTE_WIDTH),
            .NUM_MASTERS(NUM_BRANCHES),
            .SELECT_WIDTH(LEVEL_SELECT_WIDTH),
            .BROADCAST_DATA(1'b1)
        ) u_branch_demux (
            .clk(clk),
            .resetn(resetn),
            .select(level_input.t.user[
                CHILD_ROUTE_WIDTH +: LEVEL_SELECT_WIDTH
            ]),
            .s_axis(level_input),
            .m_axis(branch_axis)
        );

        for (genvar branch = 0; branch < NUM_BRANCHES; branch++) begin : g_child
            localparam int CHILD_BASE = branch * CHILD_QUEUES;

            ifc_axis #(
                .DATA_WIDTH(DATA_WIDTH),
                .TDEST_WIDTH(TDEST_WIDTH),
                .TID_WIDTH(TID_WIDTH),
                .TUSER_WIDTH(ROUTE_WIDTH)
            ) child_axis [CHILD_QUEUES] (clk);

            uro_payload_router #(
                .DATA_WIDTH(DATA_WIDTH),
                .TDEST_WIDTH(TDEST_WIDTH),
                .TID_WIDTH(TID_WIDTH),
                .NUM_QUEUES(CHILD_QUEUES),
                .TREE_DEPTH(TREE_DEPTH - 1),
                .ROUTE_WIDTH(ROUTE_WIDTH),
                .ISOLATE_STAGES(ISOLATE_STAGES)
            ) u_child (
                .clk(clk),
                .resetn(resetn),
                .s_axis(branch_axis[branch]),
                .m_axis(child_axis)
            );

            for (genvar lane = 0; lane < CHILD_QUEUES; lane++) begin : g_lane
                assign m_axis[CHILD_BASE + lane].t = child_axis[lane].t;
                assign m_axis[CHILD_BASE + lane].tvalid =
                    child_axis[lane].tvalid;
                assign child_axis[lane].tready =
                    m_axis[CHILD_BASE + lane].tready;
            end
        end
    end

    initial begin
        if (NUM_QUEUES < 2 ||
            ((NUM_QUEUES & (NUM_QUEUES - 1)) != 0)) begin
            $error("uro_payload_router: NUM_QUEUES must be a power of two >= 2");
            $finish;
        end
        if (TREE_DEPTH < 1 || TREE_DEPTH > LOCAL_ROUTE_WIDTH) begin
            $error("uro_payload_router: TREE_DEPTH must be in [1, %0d]",
                   LOCAL_ROUTE_WIDTH);
            $finish;
        end
        if (ROUTE_WIDTH < LOCAL_ROUTE_WIDTH) begin
            $error("uro_payload_router: ROUTE_WIDTH is too small");
            $finish;
        end
        if (ISOLATE_STAGES < 2) begin
            $error("uro_payload_router: ISOLATE_STAGES must be >= 2");
            $finish;
        end
    end
endmodule
