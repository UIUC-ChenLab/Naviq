`ifndef AXIS_HIERARCHICAL_PACKET_ARBITER_SV
`define AXIS_HIERARCHICAL_PACKET_ARBITER_SV

`include "ifc_axis.sv"
`include "axis_packet_arbiter.sv"

// Pipelined tree of packet-level round-robin arbiters.
//
// Every tree node arbitrates at most BRANCH_FACTOR streams.  A registered,
// ready-isolating AXIS boundary follows every node, so neither selection nor
// backpressure propagates through more than one level per cycle.  Selection at
// every node remains locked through the accepted tlast beat.
module axis_hierarchical_packet_arbiter #(
    parameter int DATA_WIDTH      = 512,
    parameter int TDEST_WIDTH     = 12,
    parameter int TID_WIDTH       = 16,
    parameter int TUSER_WIDTH     = 16,
    parameter int NUM_SLAVES      = 1,
    parameter int TREE_DEPTH      = 1,
    parameter int BRANCH_FACTOR   = 4,
    parameter int PIPELINE_STAGES = 2
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis [NUM_SLAVES],
    ifc_axis.master m_axis,

    output logic pending
);

    function automatic integer tree_capacity(input integer depth);
        integer result;
        result = 1;
        for (integer level = 0; level < depth; level++)
            result *= BRANCH_FACTOR;
        return result;
    endfunction

    localparam int CAPACITY = tree_capacity(TREE_DEPTH);

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH)
    ) node_input [BRANCH_FACTOR] (clk);

    ifc_axis #(
        .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH)
    ) node_output (clk);

    logic child_pending [BRANCH_FACTOR];

    if (TREE_DEPTH == 1) begin : g_leaf
        for (genvar lane = 0; lane < BRANCH_FACTOR; lane++) begin : g_lane
            if (lane < NUM_SLAVES) begin : g_connected
                assign node_input[lane].t = s_axis[lane].t;
                assign node_input[lane].tvalid = s_axis[lane].tvalid;
                assign s_axis[lane].tready = node_input[lane].tready;
                assign child_pending[lane] = s_axis[lane].tvalid;
            end else begin : g_padding
                assign node_input[lane].t = '0;
                assign node_input[lane].tvalid = 1'b0;
                assign child_pending[lane] = 1'b0;
            end
        end
    end else begin : g_branch
        localparam int CHILD_CAPACITY = tree_capacity(TREE_DEPTH - 1);
        localparam int ACTIVE_BRANCHES =
            (NUM_SLAVES + CHILD_CAPACITY - 1) / CHILD_CAPACITY;

        for (genvar branch = 0; branch < BRANCH_FACTOR; branch++) begin : g_child
            if (branch < ACTIVE_BRANCHES) begin : g_active
                localparam int CHILD_BASE = branch * CHILD_CAPACITY;
                localparam int CHILD_REMAINING = NUM_SLAVES - CHILD_BASE;
                localparam int CHILD_SLAVES =
                    (CHILD_REMAINING < CHILD_CAPACITY)
                    ? CHILD_REMAINING : CHILD_CAPACITY;

                ifc_axis #(
                    .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
                    .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH)
                ) child_input [CHILD_SLAVES] (clk);

                for (genvar lane = 0; lane < CHILD_SLAVES; lane++) begin : g_lane
                    assign child_input[lane].t = s_axis[CHILD_BASE + lane].t;
                    assign child_input[lane].tvalid =
                        s_axis[CHILD_BASE + lane].tvalid;
                    assign s_axis[CHILD_BASE + lane].tready =
                        child_input[lane].tready;
                end

                axis_hierarchical_packet_arbiter #(
                    .DATA_WIDTH(DATA_WIDTH),
                    .TDEST_WIDTH(TDEST_WIDTH),
                    .TID_WIDTH(TID_WIDTH),
                    .TUSER_WIDTH(TUSER_WIDTH),
                    .NUM_SLAVES(CHILD_SLAVES),
                    .TREE_DEPTH(TREE_DEPTH - 1),
                    .BRANCH_FACTOR(BRANCH_FACTOR),
                    .PIPELINE_STAGES(PIPELINE_STAGES)
                ) u_child (
                    .clk(clk), .resetn(resetn),
                    .s_axis(child_input), .m_axis(node_input[branch]),
                    .pending(child_pending[branch])
                );
            end else begin : g_padding
                assign node_input[branch].t = '0;
                assign node_input[branch].tvalid = 1'b0;
                assign child_pending[branch] = 1'b0;
            end
        end
    end

    axis_packet_arbiter #(
        .DATA_WIDTH(DATA_WIDTH),
        .TDEST_WIDTH(TDEST_WIDTH),
        .TID_WIDTH(TID_WIDTH),
        .TUSER_WIDTH(TUSER_WIDTH),
        .NUM_SLAVES(BRANCH_FACTOR),
        .SELECT_WIDTH((BRANCH_FACTOR <= 1) ? 1 : $clog2(BRANCH_FACTOR)),
        .REGISTER_GRANT(1'b1)
    ) u_level_arbiter (
        .clk(clk), .resetn(resetn),
        .s_axis(node_input), .m_axis(node_output)
    );

    axis_register_slice #(
        .MODE("ISOLATE"),
        .NUM_STAGES(PIPELINE_STAGES)
    ) u_level_pipeline (
        .clk(clk), .resetn(resetn),
        .s_axis(node_output), .m_axis(m_axis)
    );

    always_comb begin
        pending = node_output.tvalid || m_axis.tvalid;
        for (int branch = 0; branch < BRANCH_FACTOR; branch++)
            pending |= child_pending[branch];
    end

    initial begin
        if (NUM_SLAVES < 1) begin
            $error("axis_hierarchical_packet_arbiter: NUM_SLAVES must be >= 1");
            $finish;
        end
        if (TREE_DEPTH < 1) begin
            $error("axis_hierarchical_packet_arbiter: TREE_DEPTH must be >= 1");
            $finish;
        end
        if (BRANCH_FACTOR < 2) begin
            $error("axis_hierarchical_packet_arbiter: BRANCH_FACTOR must be >= 2");
            $finish;
        end
        if (NUM_SLAVES > CAPACITY) begin
            $error("axis_hierarchical_packet_arbiter: depth %0d and branch factor %0d provide %0d leaves for %0d inputs",
                   TREE_DEPTH, BRANCH_FACTOR, CAPACITY, NUM_SLAVES);
            $finish;
        end
        if (PIPELINE_STAGES < 2) begin
            $error("axis_hierarchical_packet_arbiter: PIPELINE_STAGES must be >= 2");
            $finish;
        end
    end

endmodule

`endif
