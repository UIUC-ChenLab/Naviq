`include "ifc_axil.sv"

module axil_dummy_okay_slave (
    input logic clk,
    input logic resetn,
    ifc_axil.slave ctrl_in
);

    logic aw_seen_r;
    logic w_seen_r;
    logic b_valid_r;
    logic r_valid_r;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            aw_seen_r <= 1'b0;
            w_seen_r  <= 1'b0;
            b_valid_r <= 1'b0;
            r_valid_r <= 1'b0;
        end else begin
            if (!b_valid_r) begin
                if (ctrl_in.aw_valid && ctrl_in.aw_ready) aw_seen_r <= 1'b1;
                if (ctrl_in.w_valid && ctrl_in.w_ready)   w_seen_r  <= 1'b1;

                if ((aw_seen_r || (ctrl_in.aw_valid && ctrl_in.aw_ready)) &&
                    (w_seen_r  || (ctrl_in.w_valid  && ctrl_in.w_ready))) begin
                    aw_seen_r <= 1'b0;
                    w_seen_r  <= 1'b0;
                    b_valid_r <= 1'b1;
                end
            end else if (ctrl_in.b_ready) begin
                b_valid_r <= 1'b0;
            end

            if (!r_valid_r) begin
                if (ctrl_in.ar_valid && ctrl_in.ar_ready) r_valid_r <= 1'b1;
            end else if (ctrl_in.r_ready) begin
                r_valid_r <= 1'b0;
            end
        end
    end

    assign ctrl_in.aw_ready = !b_valid_r && !aw_seen_r;
    assign ctrl_in.w_ready  = !b_valid_r && !w_seen_r;
    assign ctrl_in.ar_ready = !r_valid_r;

    assign ctrl_in.b.resp   = 2'b00;
    assign ctrl_in.b.user   = '0;
    assign ctrl_in.b_valid  = b_valid_r;

    assign ctrl_in.r.data   = '0;
    assign ctrl_in.r.resp   = 2'b00;
    assign ctrl_in.r.user   = '0;
    assign ctrl_in.r_valid  = r_valid_r;

endmodule
