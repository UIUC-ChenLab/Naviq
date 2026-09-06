// Behavioral model of XPM_CDC_ASYNC_RST for the copied PE reset wrappers.
// This models reset assertion and destination-clock release only; it does not
// model analog metastability. The production wrapper still instantiates XPM.
module xpm_cdc_async_rst #(
    parameter integer DEST_SYNC_FF = 4,
    parameter integer INIT_SYNC_FF = 0,
    parameter integer RST_ACTIVE_HIGH = 0
) (
    input logic src_arst,
    input logic dest_clk,
    output wire dest_arst
);
    // Match the vendor model's inactive power-up value for either polarity.
    // INIT_SYNC_FF controls simulation initialization plumbing, not polarity.
    logic [DEST_SYNC_FF-1:0] sync_ff = (RST_ACTIVE_HIGH == 1) ? '0 : '1;
    if (RST_ACTIVE_HIGH == 1) begin : g_active_high
        always @(posedge dest_clk or posedge src_arst) begin
            if (src_arst) sync_ff <= '1;
            else sync_ff <= {sync_ff[DEST_SYNC_FF-2:0], 1'b0};
        end
    end else begin : g_active_low
        always @(posedge dest_clk or negedge src_arst) begin
            if (!src_arst) sync_ff <= '0;
            else sync_ff <= {sync_ff[DEST_SYNC_FF-2:0], 1'b1};
        end
    end
    assign dest_arst = sync_ff[DEST_SYNC_FF-1];
    initial begin
        if (DEST_SYNC_FF < 2 || DEST_SYNC_FF > 10)
            $fatal(1, "xpm_cdc_async_rst: DEST_SYNC_FF must be 2..10");
        if ((INIT_SYNC_FF != 0 && INIT_SYNC_FF != 1) ||
            (RST_ACTIVE_HIGH != 0 && RST_ACTIVE_HIGH != 1))
            $fatal(1, "xpm_cdc_async_rst: invalid boolean parameter");
    end
endmodule
