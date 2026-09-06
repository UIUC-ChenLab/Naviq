// Strip first N valid bytes per packet, then repack the remaining byte fragments.
//
// The strip-only front end is implemented by axis_strip_bytes. The fragment
// packer then combines lower-contiguous stripped fragments into full-width beats.

`include "ifc_axis.sv"

module axis_strip_repack #(
    parameter int DATA_WIDTH = 512,
    parameter int STRIP_WIDTH = 10,
    parameter int FRAGMENT_PACKER_PAGE_COUNT = 8
) (
    input logic clk,
    input logic resetn,

    ifc_axis.slave  s_axis,
    ifc_axis.slave  s_axis_remove,
    ifc_axis.master m_axis
);

    initial begin
        if ($bits(s_axis_remove.t.data) != STRIP_WIDTH)
            $error("axis_strip_repack: s_axis_remove DATA_WIDTH must equal STRIP_WIDTH (%0d)", STRIP_WIDTH);
        if (STRIP_WIDTH > DATA_WIDTH)
            $error("axis_strip_repack: STRIP_WIDTH (%0d) must be <= DATA_WIDTH (%0d)",
                   STRIP_WIDTH, DATA_WIDTH);
    end

    ifc_axis #(
        .DATA_WIDTH  (DATA_WIDTH),
        .TDEST_WIDTH (1),
        .TID_WIDTH   (1),
        .TUSER_WIDTH (1)
    ) u_strip_to_packer (clk);

    axis_strip_bytes #(
        .DATA_WIDTH  (DATA_WIDTH),
        .STRIP_WIDTH (STRIP_WIDTH)
    ) u_strip_bytes (
        .clk           (clk),
        .resetn        (resetn),
        .s_axis        (s_axis),
        .s_axis_remove (s_axis_remove),
        .m_axis        (u_strip_to_packer.master)
    );

    axis_fragment_packer #(
        .DATA_WIDTH  (DATA_WIDTH),
        .PAGE_COUNT  (FRAGMENT_PACKER_PAGE_COUNT),
        .FIFO_MODE   ("CONSERVATIVE")
    ) u_fragment_packer (
        .clk    (clk),
        .resetn (resetn),
        .s_axis (u_strip_to_packer.slave),
        .m_axis (m_axis)
    );

endmodule
