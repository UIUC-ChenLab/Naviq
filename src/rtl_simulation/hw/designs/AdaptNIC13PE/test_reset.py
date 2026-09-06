#!/usr/bin/env python3
"""Verify XPM reset assertion and 2-/4-cycle release for both polarities."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class ResetModelTest(unittest.TestCase):
    def test_async_assert_and_synchronous_release(self):
        source = r'''
module tb;
    logic clk = 0;
    always #5 clk = ~clk;
    logic low_reset = 1, high_reset = 0;
    wire low2, low4, high2, high4, default_reset;
    xpm_cdc_async_rst dflt
        (.src_arst(low_reset), .dest_clk(clk), .dest_arst(default_reset));
    xpm_cdc_async_rst #(.DEST_SYNC_FF(2), .RST_ACTIVE_HIGH(0), .INIT_SYNC_FF(1))
        l2 (.src_arst(low_reset), .dest_clk(clk), .dest_arst(low2));
    xpm_cdc_async_rst #(.DEST_SYNC_FF(4), .RST_ACTIVE_HIGH(0), .INIT_SYNC_FF(0))
        l4 (.src_arst(low_reset), .dest_clk(clk), .dest_arst(low4));
    xpm_cdc_async_rst #(.DEST_SYNC_FF(2), .RST_ACTIVE_HIGH(1), .INIT_SYNC_FF(1))
        h2 (.src_arst(high_reset), .dest_clk(clk), .dest_arst(high2));
    xpm_cdc_async_rst #(.DEST_SYNC_FF(4), .RST_ACTIVE_HIGH(1), .INIT_SYNC_FF(0))
        h4 (.src_arst(high_reset), .dest_clk(clk), .dest_arst(high4));
    initial begin
        #1;
        assert (low2 && low4 && !high2 && !high4 && default_reset)
            else $fatal(1, "incorrect inactive power-up value/default polarity");
        for (int reset_number = 0; reset_number < 2; reset_number++) begin
            #1;
            low_reset = 0; high_reset = 1;
            #1;
            assert (!low2 && !low4 && high2 && high4 && !default_reset)
                else $fatal(1, "reset did not assert asynchronously");
            #1;
            low_reset = 1; high_reset = 0;
            for (int edge_number = 1; edge_number <= 4; edge_number++) begin
                @(posedge clk); #1;
                assert (low2 == (edge_number >= 2) && high2 == (edge_number < 2))
                    else $fatal(1, "incorrect two-cycle release");
                assert (low4 == (edge_number >= 4) && high4 == (edge_number < 4))
                    else $fatal(1, "incorrect four-cycle release");
            end
        end
        $display("PE13_XPM_RESET_PASS");
        $finish;
    end
endmodule
'''
        with tempfile.TemporaryDirectory(prefix="pe13-reset-") as temporary:
            temporary = Path(temporary)
            harness = temporary / "tb.sv"
            harness.write_text(source)
            binary = temporary / "reset_test"
            compile_run = subprocess.run([
                "verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                "--top-module", "tb", "--Mdir", str(temporary / "obj"),
                "-o", str(binary), str(HERE / "sim/xpm_cdc_async_rst.sv"), str(harness),
            ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                env=os.environ | {"CCACHE_DISABLE": "1"})
            self.assertEqual(compile_run.returncode, 0, compile_run.stdout)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("PE13_XPM_RESET_PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
