`include "ifc_axis.sv"

module uram_egress #(
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
    localparam int URAM_WIDTH           = DATA_WIDTH + KEEP_WIDTH,
    localparam int SOURCE_WIDTH         = (NUM_SOURCES <= 1) ? 1 : $clog2(NUM_SOURCES)
) (
    input logic clk,
    input logic resetn,

    input logic [NUM_SOURCES-1:0] completed,
    input logic [PACKET_COUNT_WIDTH-1:0] packet_lengths [NUM_SOURCES],

    output logic [URAM_ADDR_WIDTH-1:0] uram_read_address,
    input  logic [URAM_WIDTH-1:0]      uram_read_data,

    output logic                   retire_valid,
    output logic [TID_WIDTH-1:0]   retire_source,

    ifc_axis.master m_axis
);

    localparam int FIFO_DEPTH = 4;
    localparam int SAFE_RESERVATIONS = FIFO_DEPTH - 1;
    localparam int RESERVATION_WIDTH = $clog2(FIFO_DEPTH + 1);
    localparam int TDEST_WIDTH = $bits(m_axis.t.dest);
    localparam int TUSER_WIDTH = $bits(m_axis.t.user);
    localparam int DESCRIPTOR_WIDTH = PACKET_COUNT_WIDTH + POINTER_WIDTH;

    logic [POINTER_WIDTH-1:0] head_ptr [NUM_SOURCES];
    logic [NUM_SOURCES-1:0] scheduled;

    logic active;
    logic [SOURCE_WIDTH-1:0] active_source;
    logic [PACKET_COUNT_WIDTH-1:0] active_remaining;
    logic [POINTER_WIDTH-1:0] active_read_ptr;

    logic [NUM_SOURCES-1:0] descriptor_valid;
    logic [DESCRIPTOR_WIDTH-1:0] descriptor_data [NUM_SOURCES];
    logic descriptor_reserve_valid;
    logic [SOURCE_WIDTH-1:0] descriptor_reserve_source;
    logic selected_valid;
    logic selected_ready;
    logic [SOURCE_WIDTH-1:0] selected_source;
    logic [DESCRIPTOR_WIDTH-1:0] selected_descriptor;
    logic [PACKET_COUNT_WIDTH-1:0] selected_length;
    logic [POINTER_WIDTH-1:0] selected_head_ptr;
    logic issue_valid;
    logic issue_last;
    logic output_fire;
    logic [RESERVATION_WIDTH-1:0] reservation_count;

    logic response_valid_d0;
    logic response_valid_d1;
    logic [TID_WIDTH-1:0] response_source_d0;
    logic [TID_WIDTH-1:0] response_source_d1;
    logic response_last_d0;
    logic response_last_d1;

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) fifo_axis (.axis_aclk(clk));

    always_comb begin
        for (int source = 0; source < NUM_SOURCES; source++) begin
            descriptor_valid[source] = completed[source] && !scheduled[source];
            descriptor_data[source] = {
                packet_lengths[source], head_ptr[source]
            };
        end
    end

    rebuilder_hierarchical_arbiter #(
        .NUM_SOURCES (NUM_SOURCES),
        .DATA_WIDTH  (DESCRIPTOR_WIDTH)
    ) u_descriptor_arbiter (
        .clk            (clk),
        .resetn         (resetn),
        .request_valid  (descriptor_valid),
        .request_data   (descriptor_data),
        .reserve_valid  (descriptor_reserve_valid),
        .reserve_source (descriptor_reserve_source),
        .m_valid        (selected_valid),
        .m_ready        (selected_ready),
        .m_source       (selected_source),
        .m_data         (selected_descriptor)
    );

    assign selected_length = selected_descriptor[
        DESCRIPTOR_WIDTH-1 -: PACKET_COUNT_WIDTH
    ];
    assign selected_head_ptr = selected_descriptor[POINTER_WIDTH-1:0];

    assign output_fire = m_axis.tvalid && m_axis.tready;

    always_comb begin
        logic credit_available;
        logic [SOURCE_WIDTH-1:0] issue_source;
        logic [POINTER_WIDTH-1:0] issue_read_ptr;

        credit_available = (reservation_count < RESERVATION_WIDTH'(SAFE_RESERVATIONS)) ||
                           output_fire;
        selected_ready = !active && credit_available;
        issue_source = active ? active_source : selected_source;
        issue_read_ptr = active ? active_read_ptr : selected_head_ptr;
        issue_valid = credit_available && (active || selected_valid);
        issue_last = active
            ? (active_remaining == PACKET_COUNT_WIDTH'(1))
            : (selected_length == PACKET_COUNT_WIDTH'(1));

        uram_read_address = '0;
        if (issue_valid) begin
            uram_read_address = URAM_ADDR_WIDTH'(
                (int'(issue_source) * BEATS_PER_SOURCE) + int'(issue_read_ptr)
            );
        end
    end

    always_comb begin
        fifo_axis.t.data = uram_read_data[DATA_WIDTH-1:0];
        fifo_axis.t.keep = uram_read_data[URAM_WIDTH-1:DATA_WIDTH];
        fifo_axis.t.id = response_source_d1;
        fifo_axis.t.dest = '0;
        fifo_axis.t.user = '0;
        fifo_axis.t.last = response_last_d1;
        fifo_axis.tvalid = response_valid_d1;
    end

    assign retire_valid = output_fire && m_axis.t.last;
    assign retire_source = m_axis.t.id;

    function automatic logic [POINTER_WIDTH-1:0] next_pointer(
        input logic [POINTER_WIDTH-1:0] pointer
    );
        if (pointer == POINTER_WIDTH'(BEATS_PER_SOURCE - 1))
            return '0;
        return pointer + 1'b1;
    endfunction

    always_ff @(posedge clk) begin
        if (!resetn) begin
            scheduled <= '0;
            active <= 1'b0;
            active_source <= '0;
            active_remaining <= '0;
            active_read_ptr <= '0;
            reservation_count <= '0;
            response_valid_d0 <= 1'b0;
            response_valid_d1 <= 1'b0;
            response_source_d0 <= '0;
            response_source_d1 <= '0;
            response_last_d0 <= 1'b0;
            response_last_d1 <= 1'b0;
            for (int source = 0; source < NUM_SOURCES; source++) begin
                head_ptr[source] <= '0;
            end
        end else begin
            response_valid_d0 <= issue_valid;
            response_valid_d1 <= response_valid_d0;
            response_source_d1 <= response_source_d0;
            response_last_d1 <= response_last_d0;

            if (descriptor_reserve_valid)
                scheduled[descriptor_reserve_source] <= 1'b1;

            if (issue_valid) begin
                logic [SOURCE_WIDTH-1:0] issued_source;
                logic [POINTER_WIDTH-1:0] issued_read_ptr;
                issued_source = active ? active_source : selected_source;
                issued_read_ptr = active ? active_read_ptr : selected_head_ptr;

                response_source_d0 <= TID_WIDTH'(issued_source);
                response_last_d0 <= issue_last;
                head_ptr[issued_source] <= next_pointer(issued_read_ptr);

                if (!active) begin
                    if (selected_length > PACKET_COUNT_WIDTH'(1)) begin
                        active <= 1'b1;
                        active_source <= issued_source;
                        active_remaining <= selected_length - 1'b1;
                        active_read_ptr <= next_pointer(issued_read_ptr);
                    end else begin
                        active <= 1'b0;
                    end
                end else if (active_remaining == PACKET_COUNT_WIDTH'(1)) begin
                    active <= 1'b0;
                    active_remaining <= '0;
                end else begin
                    active_remaining <= active_remaining - 1'b1;
                    active_read_ptr <= next_pointer(active_read_ptr);
                end
            end

            if (retire_valid && (int'(retire_source) < NUM_SOURCES)) begin
                scheduled[int'(retire_source)] <= 1'b0;
            end

            case ({issue_valid, output_fire})
                2'b10: reservation_count <= reservation_count + 1'b1;
                2'b01: reservation_count <= reservation_count - 1'b1;
                default:;
            endcase

            if (response_valid_d1) begin
                assert (fifo_axis.tready)
                    else $error("uram_egress: fixed-latency URAM response overran output FIFO");
            end
        end
    end

    axis_fifo #(
        .DEPTH            (FIFO_DEPTH),
        .USE_BRAM         (1'b0),
        .EXTRA_OUTPUT_REG (1'b1),
        .MODE             ("CONSERVATIVE")
    ) u_output_fifo (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (fifo_axis.slave),
        .m_axis (m_axis)
    );

endmodule
