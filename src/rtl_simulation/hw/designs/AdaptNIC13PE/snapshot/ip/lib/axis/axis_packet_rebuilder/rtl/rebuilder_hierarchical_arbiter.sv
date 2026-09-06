module rebuilder_hierarchical_arbiter #(
    parameter int NUM_SOURCES = 16,
    parameter int DATA_WIDTH  = 16,
    localparam int SOURCE_WIDTH = (NUM_SOURCES <= 1) ? 1 : $clog2(NUM_SOURCES)
) (
    input logic clk,
    input logic resetn,

    input logic [NUM_SOURCES-1:0] request_valid,
    input logic [DATA_WIDTH-1:0] request_data [NUM_SOURCES],

    output logic reserve_valid,
    output logic [SOURCE_WIDTH-1:0] reserve_source,

    output logic m_valid,
    input logic m_ready,
    output logic [SOURCE_WIDTH-1:0] m_source,
    output logic [DATA_WIDTH-1:0] m_data
);
    localparam int NUM_GROUPS = (NUM_SOURCES > 16) ? 8 : 4;
    localparam int GROUP_SIZE = 4;
    localparam int GROUP_WIDTH = $clog2(NUM_GROUPS);
    localparam int LOCAL_WIDTH = 2;

    logic [LOCAL_WIDTH-1:0] leaf_ptr [NUM_GROUPS];
    logic [NUM_GROUPS-1:0] leaf_valid;
    logic [SOURCE_WIDTH-1:0] leaf_source [NUM_GROUPS];
    logic [DATA_WIDTH-1:0] leaf_data [NUM_GROUPS];

    logic [GROUP_WIDTH-1:0] root_ptr;
    logic root_valid_r;
    logic [SOURCE_WIDTH-1:0] root_source_r;
    logic [DATA_WIDTH-1:0] root_data_r;

    logic [NUM_GROUPS-1:0] leaf_consume;
    logic [NUM_GROUPS-1:0] leaf_refill_valid;
    logic [SOURCE_WIDTH-1:0] leaf_refill_source [NUM_GROUPS];
    logic [DATA_WIDTH-1:0] leaf_refill_data [NUM_GROUPS];
    logic [GROUP_WIDTH-1:0] selected_group;
    logic root_selection_valid;
    logic root_slot_ready;
    logic [NUM_GROUPS*GROUP_SIZE-1:0] padded_request_valid;
    logic [DATA_WIDTH-1:0] padded_request_data [NUM_GROUPS*GROUP_SIZE];

    function automatic logic [LOCAL_WIDTH-1:0] next_leaf(
        input logic [LOCAL_WIDTH-1:0] current
    );
        return current + 1'b1;
    endfunction

    function automatic logic [GROUP_WIDTH-1:0] next_group(
        input logic [GROUP_WIDTH-1:0] current
    );
        return current + 1'b1;
    endfunction

    always_comb begin
        padded_request_valid = '0;
        for (int source = 0; source < NUM_GROUPS * GROUP_SIZE; source++)
            padded_request_data[source] = '0;
        for (int source = 0; source < NUM_SOURCES; source++) begin
            padded_request_valid[source] = request_valid[source];
            padded_request_data[source] = request_data[source];
        end
    end

    // Four sources per registered leaf; the root grows from four to eight
    // leaves for 17..32 source contexts without adding a pipeline stage.
    always_comb begin
        root_selection_valid = |leaf_valid;
        selected_group = root_ptr;
        // Reverse priority order makes the first eligible rotation win. The
        // width cast wraps at the power-of-two group count, with no divider.
        for (int offset = NUM_GROUPS - 1; offset >= 0; offset--) begin
            if (leaf_valid[GROUP_WIDTH'(int'(root_ptr) + offset)])
                selected_group = GROUP_WIDTH'(int'(root_ptr) + offset);
        end
    end

    assign root_slot_ready = !root_valid_r || m_ready;
    assign reserve_valid = root_slot_ready && root_selection_valid;
    assign reserve_source = root_selection_valid
        ? leaf_source[selected_group] : '0;

    always_comb begin
        leaf_consume = '0;
        if (reserve_valid)
            leaf_consume[selected_group] = 1'b1;
    end

    for (genvar group = 0; group < NUM_GROUPS; group++) begin : g_leaf_select
        localparam int BASE = group * GROUP_SIZE;
        logic [GROUP_SIZE-1:0] eligible;
        logic [LOCAL_WIDTH-1:0] search_ptr;
        logic [LOCAL_WIDTH-1:0] selected_local;
        logic selection_valid;

        always_comb begin
            eligible = padded_request_valid[BASE +: GROUP_SIZE];
            // Only the selected leaf can consume a descriptor.  Use its
            // already-local source index for the duplicate mask instead of
            // decoding the root's global source back into every leaf.  This
            // keeps one leaf's valid bit out of the other leaves' refill
            // timing cones.
            if (leaf_consume[group])
                eligible[LOCAL_WIDTH'(leaf_source[group])] = 1'b0;

            search_ptr = leaf_consume[group]
                ? next_leaf(LOCAL_WIDTH'(leaf_source[group]))
                : leaf_ptr[group];
            selection_valid = |eligible;
            selected_local = search_ptr;
            unique case (search_ptr)
                2'd0: begin
                    if      (eligible[0]) selected_local = 2'd0;
                    else if (eligible[1]) selected_local = 2'd1;
                    else if (eligible[2]) selected_local = 2'd2;
                    else                 selected_local = 2'd3;
                end
                2'd1: begin
                    if      (eligible[1]) selected_local = 2'd1;
                    else if (eligible[2]) selected_local = 2'd2;
                    else if (eligible[3]) selected_local = 2'd3;
                    else                 selected_local = 2'd0;
                end
                2'd2: begin
                    if      (eligible[2]) selected_local = 2'd2;
                    else if (eligible[3]) selected_local = 2'd3;
                    else if (eligible[0]) selected_local = 2'd0;
                    else                 selected_local = 2'd1;
                end
                default: begin
                    if      (eligible[3]) selected_local = 2'd3;
                    else if (eligible[0]) selected_local = 2'd0;
                    else if (eligible[1]) selected_local = 2'd1;
                    else                 selected_local = 2'd2;
                end
            endcase

            leaf_refill_valid[group] =
                (!leaf_valid[group] || leaf_consume[group]) && selection_valid;
            leaf_refill_source[group] = SOURCE_WIDTH'(BASE) |
                SOURCE_WIDTH'(selected_local);
            unique case (selected_local)
                2'd0: leaf_refill_data[group] = padded_request_data[BASE + 0];
                2'd1: leaf_refill_data[group] = padded_request_data[BASE + 1];
                2'd2: leaf_refill_data[group] = padded_request_data[BASE + 2];
                default: leaf_refill_data[group] = padded_request_data[BASE + 3];
            endcase
        end
    end

    assign m_valid = root_valid_r;
    assign m_source = root_source_r;
    assign m_data = root_data_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            leaf_valid <= '0;
            root_valid_r <= 1'b0;
            root_source_r <= '0;
            root_data_r <= '0;
            root_ptr <= '0;
            for (int group = 0; group < NUM_GROUPS; group++) begin
                leaf_ptr[group] <= '0;
                leaf_source[group] <= '0;
                leaf_data[group] <= '0;
            end
        end else begin
            for (int group = 0; group < NUM_GROUPS; group++) begin
                if (!leaf_valid[group] || leaf_consume[group]) begin
                    leaf_valid[group] <= leaf_refill_valid[group];
                    if (leaf_refill_valid[group]) begin
                        leaf_source[group] <= leaf_refill_source[group];
                        leaf_data[group] <= leaf_refill_data[group];
                    end
                end
                if (leaf_consume[group])
                    leaf_ptr[group] <= next_leaf(LOCAL_WIDTH'(leaf_source[group]));
            end

            if (reserve_valid) begin
                root_valid_r <= 1'b1;
                root_source_r <= leaf_source[selected_group];
                root_data_r <= leaf_data[selected_group];
                root_ptr <= next_group(selected_group);
            end else if (m_ready) begin
                root_valid_r <= 1'b0;
            end
        end
    end

    initial begin
        if (NUM_SOURCES < 1 || NUM_SOURCES > 32) begin
            $error("rebuilder_hierarchical_arbiter: NUM_SOURCES must be from 1 through 32");
            $finish;
        end
        if (DATA_WIDTH < 1) begin
            $error("rebuilder_hierarchical_arbiter: DATA_WIDTH must be positive");
            $finish;
        end
    end
endmodule
