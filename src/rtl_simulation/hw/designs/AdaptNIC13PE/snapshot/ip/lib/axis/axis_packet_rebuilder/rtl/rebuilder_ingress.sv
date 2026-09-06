module rebuilder_ingress #(
    parameter int DATA_WIDTH            = 512,
    parameter int NUM_SOURCES           = 16,
    parameter int MAX_PACKET_SIZE_BYTES = 1500,
    parameter int TID_WIDTH             = (NUM_SOURCES <= 1) ? 1 : $clog2(NUM_SOURCES),
    localparam int KEEP_WIDTH           = DATA_WIDTH / 8,
    localparam int BEATS_PER_SOURCE     = (MAX_PACKET_SIZE_BYTES + KEEP_WIDTH - 1) / KEEP_WIDTH,
    localparam int POINTER_WIDTH        = (BEATS_PER_SOURCE <= 1) ? 1 : $clog2(BEATS_PER_SOURCE),
    localparam int PACKET_COUNT_WIDTH   = (BEATS_PER_SOURCE <= 1) ? 1 : $clog2(BEATS_PER_SOURCE + 1),
    localparam int URAM_DEPTH           = NUM_SOURCES * BEATS_PER_SOURCE,
    localparam int URAM_ADDR_WIDTH      = (URAM_DEPTH <= 1) ? 1 : $clog2(URAM_DEPTH),
    localparam int URAM_WIDTH           = DATA_WIDTH + KEEP_WIDTH
) (
    input logic clk,
    input logic resetn,

    input  logic [DATA_WIDTH-1:0]   s_tdata,
    input  logic [KEEP_WIDTH-1:0]   s_tkeep,
    input  logic [TID_WIDTH-1:0]    s_tid,
    input  logic                    s_tlast,
    input  logic                    s_tvalid,
    output logic                    s_tready,

    input logic                     retire_valid,
    input logic [TID_WIDTH-1:0]     retire_source,

    output logic                    uram_we,
    output logic [URAM_ADDR_WIDTH-1:0] uram_addr,
    output logic [URAM_WIDTH-1:0]   uram_data,

    output logic [NUM_SOURCES-1:0] completed,
    output logic [PACKET_COUNT_WIDTH-1:0] packet_lengths [NUM_SOURCES]
);

    logic [POINTER_WIDTH-1:0] tail_ptr [NUM_SOURCES];
    logic [PACKET_COUNT_WIDTH-1:0] packet_count [NUM_SOURCES];

    logic source_valid;
    logic input_fire;
    int unsigned source_index;

    always_comb begin
        source_index = int'(s_tid);
        source_valid = (source_index < NUM_SOURCES);
        s_tready = source_valid && !completed[source_index] &&
            (packet_count[source_index] < PACKET_COUNT_WIDTH'(BEATS_PER_SOURCE));
        input_fire = s_tvalid && s_tready;

        uram_we = input_fire;
        uram_addr = '0;
        if (source_valid) begin
            uram_addr = URAM_ADDR_WIDTH'(
                (source_index * BEATS_PER_SOURCE) + int'(tail_ptr[source_index])
            );
        end
        uram_data = {s_tkeep, s_tdata};
    end

    function automatic logic [POINTER_WIDTH-1:0] next_pointer(
        input logic [POINTER_WIDTH-1:0] pointer
    );
        if (pointer == POINTER_WIDTH'(BEATS_PER_SOURCE - 1))
            return '0;
        return pointer + 1'b1;
    endfunction

    always_ff @(posedge clk) begin
        if (!resetn) begin
            completed <= '0;
            for (int source = 0; source < NUM_SOURCES; source++) begin
                tail_ptr[source] <= '0;
                packet_count[source] <= '0;
                packet_lengths[source] <= '0;
            end
        end else begin
            if (retire_valid && (int'(retire_source) < NUM_SOURCES)) begin
                completed[int'(retire_source)] <= 1'b0;
                packet_count[int'(retire_source)] <= '0;
                packet_lengths[int'(retire_source)] <= '0;
            end

            if (input_fire) begin
                tail_ptr[source_index] <= next_pointer(tail_ptr[source_index]);
                packet_count[source_index] <= packet_count[source_index] + 1'b1;

                if (s_tlast) begin
                    completed[source_index] <= 1'b1;
                    packet_lengths[source_index] <= packet_count[source_index] + 1'b1;
                end
            end
        end
    end

endmodule
