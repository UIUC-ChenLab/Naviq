`include "ifc_axis.sv"

module axis_serializer #(
    parameter int INPUT_DATA_WIDTH = 512,
    parameter int OUTPUT_DATA_WIDTH = 128
) (
    input logic clk,
    input logic resetn,
    ifc_axis.slave s_axis,
    ifc_axis.master m_axis
);
    localparam int INPUT_BYTES = INPUT_DATA_WIDTH/8;
    localparam int OUTPUT_BYTES = OUTPUT_DATA_WIDTH/8;
    localparam int NUM_QUEUES = INPUT_DATA_WIDTH/OUTPUT_DATA_WIDTH;
    localparam int QUEUE_IDX_WIDTH = $clog2(NUM_QUEUES);

    ifc_axis #(.DATA_WIDTH(OUTPUT_DATA_WIDTH),.TDEST_WIDTH(1),.TID_WIDTH(1),.TUSER_WIDTH(1))
        queue_in[NUM_QUEUES](clk),queue_out[NUM_QUEUES](clk);
    logic [NUM_QUEUES-1:0] slice_active;
    logic [NUM_QUEUES-1:0] queue_input_ready,queue_output_valid,queue_output_ready;
    logic [NUM_QUEUES-1:0][OUTPUT_DATA_WIDTH-1:0] queue_output_data;
    logic [NUM_QUEUES-1:0][OUTPUT_BYTES-1:0] queue_output_keep;
    logic [NUM_QUEUES-1:0] queue_output_last;
    logic [QUEUE_IDX_WIDTH-1:0] queue_idx_r;
    wire output_fire=m_axis.tvalid&&m_axis.tready;

    always_comb begin
        for(int i=0;i<NUM_QUEUES;i++)
            slice_active[i]=s_axis.t.keep[i*OUTPUT_BYTES];
    end
    wire all_active_ready=&(~slice_active|queue_input_ready);
    assign s_axis.tready=all_active_ready;

    for(genvar i=0;i<NUM_QUEUES;i++) begin : g_queue
        always_comb begin
            queue_in[i].t='0;
            queue_in[i].t.data=s_axis.t.data[i*OUTPUT_DATA_WIDTH +:OUTPUT_DATA_WIDTH];
            queue_in[i].t.keep=s_axis.t.keep[i*OUTPUT_BYTES +:OUTPUT_BYTES];
            if (i == NUM_QUEUES-1)
                queue_in[i].t.last=s_axis.t.last&&slice_active[i];
            else
                queue_in[i].t.last=s_axis.t.last&&slice_active[i]&&!slice_active[i+1];
        end
        assign queue_in[i].tvalid=s_axis.tvalid&&all_active_ready&&slice_active[i];
        assign queue_input_ready[i]=queue_in[i].tready;
        assign queue_output_data[i]=queue_out[i].t.data;
        assign queue_output_keep[i]=queue_out[i].t.keep;
        assign queue_output_last[i]=queue_out[i].t.last;
        assign queue_output_valid[i]=queue_out[i].tvalid;
        assign queue_out[i].tready=queue_output_ready[i];
        axis_fifo #(.DEPTH(4),.USE_BRAM(1'b0),.MODE("CONSERVATIVE")) u_fifo(
            .clk(clk),.resetn(resetn),.s_axis(queue_in[i]),.m_axis(queue_out[i]));
    end

    always_comb begin
        m_axis.t='0;
        m_axis.t.data=queue_output_data[queue_idx_r];
        m_axis.t.keep=queue_output_keep[queue_idx_r];
        m_axis.t.last=queue_output_last[queue_idx_r];
        m_axis.tvalid=queue_output_valid[queue_idx_r];
        queue_output_ready='0;
        queue_output_ready[queue_idx_r]=m_axis.tready;
    end

    always_ff @(posedge clk) begin
        if(!resetn) queue_idx_r<='0;
        else if(output_fire) begin
            if(m_axis.t.last||queue_idx_r==QUEUE_IDX_WIDTH'(NUM_QUEUES-1)) queue_idx_r<='0;
            else queue_idx_r<=queue_idx_r+1'b1;
        end
    end

    initial begin
        if(INPUT_DATA_WIDTH<=OUTPUT_DATA_WIDTH) $error("axis_serializer: input width must exceed output width");
        if((INPUT_DATA_WIDTH%8)!=0||(OUTPUT_DATA_WIDTH%8)!=0) $error("axis_serializer: widths must be byte aligned");
        if((INPUT_DATA_WIDTH&(INPUT_DATA_WIDTH-1))!=0||(OUTPUT_DATA_WIDTH&(OUTPUT_DATA_WIDTH-1))!=0)
            $error("axis_serializer: widths must be powers of two");
    end
endmodule
