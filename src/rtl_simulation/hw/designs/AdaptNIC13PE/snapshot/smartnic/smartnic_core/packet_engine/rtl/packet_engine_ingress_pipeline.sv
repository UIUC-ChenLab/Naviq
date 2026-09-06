`include "ifc_axis.sv"

module packet_engine_ingress_pipeline #(
    parameter int NUM_INPUTS             = 1,
    parameter bit REBUILD_PACKETS        = (NUM_INPUTS > 1),
    parameter int DATA_WIDTH             = 512,
    parameter int NUM_SOURCES            = 16,
    parameter int MAX_PACKET_SIZE_BYTES  = 1500,
    parameter int STEERING_MODE          = 0,
    parameter int STEERING_HEADER_BYTES  = 2
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis [NUM_INPUTS],
    ifc_axis.master m_axis
);
    localparam int TDEST_WIDTH = 10;
    localparam int TID_WIDTH = 6;
    localparam int TUSER_WIDTH = 1;
    localparam int HEADER_WIDTH = 8 * STEERING_HEADER_BYTES;
    localparam int ARBITER_SELECT_WIDTH =
        (NUM_INPUTS <= 1) ? 1 : $clog2(NUM_INPUTS);

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (TDEST_WIDTH),
        .TID_WIDTH   (TID_WIDTH),
        .TUSER_WIDTH (TUSER_WIDTH)
    ) u_merged_axis (.axis_aclk(clk)), u_rebuilt_axis (.axis_aclk(clk));

    generate
        if (REBUILD_PACKETS) begin : g_rebuilder
            ifc_axis #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
                .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH)
            ) u_input_packets [NUM_INPUTS] (.axis_aclk(clk));

            // Each NSU preserves its source streams. Rebuild at that boundary
            // before joining destinations: sequential packets from one NMU
            // can reach different NSUs independently and retain the same TID.
            // The visible TID remains unchanged; no lane bits are encoded.
            for (genvar input_lane = 0; input_lane < NUM_INPUTS; input_lane++) begin : g_input
                axis_packet_rebuilder #(
                    .DATA_WIDTH(DATA_WIDTH), .NUM_SOURCES(NUM_SOURCES),
                    .MAX_PACKET_SIZE_BYTES(MAX_PACKET_SIZE_BYTES),
                    .TID_WIDTH(TID_WIDTH)
                ) u_rebuilder (
                    .clk(clk), .resetn(resetn),
                    .s_axis(s_axis[input_lane]),
                    .m_axis(u_input_packets[input_lane])
                );
            end

            if (NUM_INPUTS == 2) begin : g_packet_arbiter
                axis_packet_arbiter #(
                    .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
                    .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH),
                    .NUM_SLAVES(NUM_INPUTS), .SELECT_WIDTH(ARBITER_SELECT_WIDTH),
                    .REGISTER_GRANT(1'b1)
                ) u_arbiter (
                    .clk(clk), .resetn(resetn),
                    .s_axis(u_input_packets), .m_axis(u_merged_axis)
                );

                // Break the arbitration path before the offload. This elastic
                // register accepts and forwards one beat on every cycle.
                assign u_merged_axis.tready = !u_rebuilt_axis.tvalid ||
                    u_rebuilt_axis.tready;
                always_ff @(posedge clk) begin
                    if (!resetn) begin
                        u_rebuilt_axis.tvalid <= 1'b0;
                    end else if (u_merged_axis.tready) begin
                        u_rebuilt_axis.tvalid <= u_merged_axis.tvalid;
                        if (u_merged_axis.tvalid)
                            u_rebuilt_axis.t <= u_merged_axis.t;
                    end
                end
            end else begin : g_single_input
                assign u_rebuilt_axis.t = u_input_packets[0].t;
                assign u_rebuilt_axis.tvalid = u_input_packets[0].tvalid;
                assign u_input_packets[0].tready = u_rebuilt_axis.tready;
            end
        end else begin : g_rebuilder_bypass
            // Legacy raw-beat behavior remains available for callers whose
            // downstream logic explicitly accepts interleaved packets.
            if (NUM_INPUTS == 2) begin : g_arbiter
                axis_beat_arbiter #(
                    .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(TDEST_WIDTH),
                    .TID_WIDTH(TID_WIDTH), .TUSER_WIDTH(TUSER_WIDTH),
                    .NUM_SLAVES(NUM_INPUTS), .SELECT_WIDTH(ARBITER_SELECT_WIDTH),
                    .REGISTER_GRANT(1'b0)
                ) u_arbiter (
                    .clk(clk), .resetn(resetn),
                    .s_axis(s_axis), .m_axis(u_rebuilt_axis)
                );
            end else begin : g_single_input
                assign u_rebuilt_axis.t = s_axis[0].t;
                assign u_rebuilt_axis.tvalid = s_axis[0].tvalid;
                assign s_axis[0].tready = u_rebuilt_axis.tready;
            end
        end
    endgenerate

    generate
        if (STEERING_MODE == 0) begin : g_hash_steering
            assign m_axis.t.data = u_rebuilt_axis.t.data;
            assign m_axis.t.keep = u_rebuilt_axis.t.keep;
            assign m_axis.t.id = u_rebuilt_axis.t.id[0];
            assign m_axis.t.dest = u_rebuilt_axis.t.dest[0];
            assign m_axis.t.user = u_rebuilt_axis.t.user[0];
            assign m_axis.t.last = u_rebuilt_axis.t.last;
            assign m_axis.tvalid = u_rebuilt_axis.tvalid;
            assign u_rebuilt_axis.tready = m_axis.tready;
        end else begin : g_header_steering
            ifc_axis #(
                .DATA_WIDTH(DATA_WIDTH), .TDEST_WIDTH(1),
                .TID_WIDTH(1), .TUSER_WIDTH(1)
            ) u_strip_input (.axis_aclk(clk)), u_stripped_axis (.axis_aclk(clk));
            ifc_axis #(
                .DATA_WIDTH(16), .TDEST_WIDTH(1),
                .TID_WIDTH(1), .TUSER_WIDTH(1)
            ) u_remove_axis (.axis_aclk(clk));

            logic input_in_packet_r;
            logic output_in_packet_r;
            logic [HEADER_WIDTH-1:0] output_header_r;
            logic header_push_valid;
            logic header_push_ready;
            logic [HEADER_WIDTH-1:0] header_pop_data;
            logic header_pop_valid;
            logic header_pop_ready;
            logic input_fire;
            logic output_fire;
            logic packet_has_payload;

            assign packet_has_payload = !u_rebuilt_axis.t.last ||
                (|(u_rebuilt_axis.t.keep >> STEERING_HEADER_BYTES));
            assign u_remove_axis.t = '{
                data: 16'(STEERING_HEADER_BYTES), keep: '1,
                id: '0, dest: '0, user: '0, last: 1'b1
            };
            assign u_remove_axis.tvalid = !input_in_packet_r;

            assign u_strip_input.t.data = u_rebuilt_axis.t.data;
            assign u_strip_input.t.keep = u_rebuilt_axis.t.keep;
            assign u_strip_input.t.id = '0;
            assign u_strip_input.t.dest = '0;
            assign u_strip_input.t.user = '0;
            assign u_strip_input.t.last = u_rebuilt_axis.t.last;
            assign u_strip_input.tvalid = u_rebuilt_axis.tvalid &&
                (input_in_packet_r || !packet_has_payload || header_push_ready);
            assign u_rebuilt_axis.tready = u_strip_input.tready &&
                (input_in_packet_r || !packet_has_payload || header_push_ready);
            assign input_fire = u_rebuilt_axis.tvalid && u_rebuilt_axis.tready;
            assign header_push_valid = input_fire && !input_in_packet_r &&
                packet_has_payload;

            sync_ff_fifo #(
                .DEPTH(16), .T(logic [HEADER_WIDTH-1:0]),
                .MODE("FULL_CAPACITY")
            ) u_header_fifo (
                .clk(clk), .resetn(resetn),
                .push_valid(header_push_valid),
                .push_data(u_rebuilt_axis.t.data[HEADER_WIDTH-1:0]),
                .push_ready(header_push_ready),
                .pop_valid(header_pop_valid), .pop_data(header_pop_data),
                .pop_ready(header_pop_ready)
            );

            axis_strip_repack #(
                .DATA_WIDTH(DATA_WIDTH), .STRIP_WIDTH(16)
            ) u_strip_repack (
                .clk(clk), .resetn(resetn),
                .s_axis(u_strip_input.slave),
                .s_axis_remove(u_remove_axis.slave), .m_axis(u_stripped_axis.master)
            );

            // axis_strip_repack scrubs sideband. Reapply the captured prefix to
            // every payload beat presented to the offload.
            assign m_axis.t.data = u_stripped_axis.t.data;
            assign m_axis.t.keep = u_stripped_axis.t.keep;
            assign m_axis.t.id = '0;
            assign m_axis.t.dest = '0;
            assign m_axis.t.user = output_in_packet_r ? output_header_r : header_pop_data;
            assign m_axis.t.last = u_stripped_axis.t.last;
            assign m_axis.tvalid = u_stripped_axis.tvalid &&
                (output_in_packet_r || header_pop_valid);
            assign u_stripped_axis.tready = m_axis.tready &&
                (output_in_packet_r || header_pop_valid);
            assign output_fire = m_axis.tvalid && m_axis.tready;
            assign header_pop_ready = output_fire && !output_in_packet_r;

            always_ff @(posedge clk) begin
                if (!resetn) begin
                    input_in_packet_r <= 1'b0;
                    output_in_packet_r <= 1'b0;
                    output_header_r <= '0;
                end else begin
                    if (input_fire)
                        input_in_packet_r <= !u_rebuilt_axis.t.last;
                    if (output_fire) begin
                        if (!output_in_packet_r) begin
                            output_header_r <= header_pop_data;
                            output_in_packet_r <= !m_axis.t.last;
                        end else if (m_axis.t.last) begin
                            output_in_packet_r <= 1'b0;
                        end
                    end
                end
            end
        end
    endgenerate

    initial begin
        if (NUM_INPUTS < 1 || NUM_INPUTS > 2) begin
            $error("packet_engine_ingress_pipeline: NUM_INPUTS must be 1 or 2");
            $finish;
        end
        if (DATA_WIDTH < 8 || (DATA_WIDTH % 8) != 0) begin
            $error("packet_engine_ingress_pipeline: input data width must be byte aligned");
            $finish;
        end
        if ($bits(s_axis[0].t.data) != DATA_WIDTH ||
            $bits(s_axis[0].t.dest) != TDEST_WIDTH ||
            $bits(s_axis[0].t.id) != TID_WIDTH ||
            $bits(s_axis[0].t.user) != TUSER_WIDTH) begin
            $error("packet_engine_ingress_pipeline: input does not use packet-engine AXIS widths");
            $finish;
        end
        if ($bits(m_axis.t.data) != DATA_WIDTH || $bits(m_axis.t.dest) != 1 ||
            $bits(m_axis.t.id) != 1 ||
            $bits(m_axis.t.user) != ((STEERING_MODE == 1) ? HEADER_WIDTH : 1)) begin
            $error("packet_engine_ingress_pipeline: output sideband width does not match steering mode");
            $finish;
        end
        if (STEERING_MODE < 0 || STEERING_MODE > 1) begin
            $error("packet_engine_ingress_pipeline: STEERING_MODE must be 0 or 1");
            $finish;
        end
        if (STEERING_HEADER_BYTES < 1 || STEERING_HEADER_BYTES > DATA_WIDTH / 8) begin
            $error("packet_engine_ingress_pipeline: STEERING_HEADER_BYTES must fit one data beat");
            $finish;
        end
        if (NUM_SOURCES < 1 || MAX_PACKET_SIZE_BYTES < 1) begin
            $error("packet_engine_ingress_pipeline: source and packet limits must be positive");
            $finish;
        end
    end

endmodule
