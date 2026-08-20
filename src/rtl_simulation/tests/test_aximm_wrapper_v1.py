#!/usr/bin/env python3
"""Contract tests for the manifest-driven AXI-MM RTL wrapper V1."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RTL_SIMULATION = Path(__file__).resolve().parents[1]
GENERATOR = RTL_SIMULATION / "generate_gem5_aximm_node.py"
FIXTURE = RTL_SIMULATION / "hw" / "designs" / "AximmMemorySmoke"
INCLUDE = RTL_SIMULATION / "hw" / "include"


class AximmWrapperGeneratorTest(unittest.TestCase):
    def test_generator_emits_manifest_configured_wrapper(self):
        endpoint = {
            "id": "nsu_aximm_0",
            "instance_path": "u_nsu",
            "verilator_path": "FixtureTop__DOT__u_nsu",
            "module_type": "xpm_nsu_mm",
            "protocol": "aximm",
            "role": "nsu",
            "signal_prefix": "m_axi_",
        }
        plan = {
            "schema_version": 1,
            "design": "FixtureTop",
            "top_module": "FixtureTop",
            "gem5_wrapper": {
                "clock_signal": "rtl_clk",
                "reset_signal": "rtl_resetn",
                "data_width": 256,
                "id_width": 7,
                "addr_width": 40,
            },
            "nodes": [{"endpoint": endpoint}],
        }
        endpoint_map = {
            "schema_version": 1,
            "design": "FixtureTop",
            "top_module": "FixtureTop",
            "endpoints": [endpoint],
        }
        with tempfile.TemporaryDirectory(prefix="noc-aximm-generator-") as tmp:
            tmp_path = Path(tmp)
            endpoint_map_path = tmp_path / "endpoint_map.json"
            plan_path = tmp_path / "plan.json"
            output_dir = tmp_path / "generated"
            endpoint_map_path.write_text(json.dumps(endpoint_map), encoding="utf-8")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    str(endpoint_map_path),
                    str(plan_path),
                    "--class-name",
                    "FixtureRtlNode",
                    "--output-dir",
                    str(output_dir),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            header = (output_dir / "FixtureRtlNode.hh").read_text()
            simobject = (output_dir / "FixtureRtlNode.py").read_text()
            self.assertIn("Axi_FixtureTop__DOT__u_nsuTraits", header)
            self.assertIn("dut.rootp->rtl_clk", header)
            self.assertIn("dut.rootp->rtl_resetn", header)
            self.assertIn("Param.UInt32(256", simobject)
            self.assertIn("Param.UInt32(7", simobject)
            self.assertIn("Param.UInt32(40", simobject)

    def test_generator_rejects_unsupported_nmu_plan(self):
        endpoint = {
            "id": "nmu_aximm_0",
            "verilator_path": "FixtureTop__DOT__u_nmu",
            "module_type": "xpm_nmu_mm",
            "protocol": "aximm",
            "role": "nmu",
            "signal_prefix": "s_axi_",
        }
        plan = {
            "top_module": "FixtureTop",
            "gem5_wrapper": {
                "clock_signal": "clk",
                "reset_signal": "resetn",
                "data_width": 512,
                "id_width": 4,
                "addr_width": 32,
            },
            "nodes": [{"endpoint": endpoint}],
        }
        endpoint_map = {"top_module": "FixtureTop", "endpoints": [endpoint]}
        with tempfile.TemporaryDirectory(prefix="noc-aximm-generator-") as tmp:
            tmp_path = Path(tmp)
            endpoint_map_path = tmp_path / "endpoint_map.json"
            plan_path = tmp_path / "plan.json"
            endpoint_map_path.write_text(json.dumps(endpoint_map), encoding="utf-8")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    str(endpoint_map_path),
                    str(plan_path),
                    "--class-name",
                    "FixtureRtlNode",
                    "--output-dir",
                    str(tmp_path / "generated"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("xpm_nmu_mm", result.stderr)


@unittest.skipUnless(shutil.which("verilator"), "requires Verilator")
class AximmMemoryFixtureTest(unittest.TestCase):
    def test_partial_wstrb_readback(self):
        with tempfile.TemporaryDirectory(prefix="noc-aximm-fixture-") as tmp:
            build_dir = Path(tmp) / "build"
            compile_result = subprocess.run(
                [
                    "verilator",
                    "--binary",
                    "--timing",
                    "-Wno-fatal",
                    "--top-module",
                    "AximmMemorySmoke_tb",
                    "-I{}".format(INCLUDE),
                    str(FIXTURE / "AximmMemorySmoke_tb.sv"),
                    str(FIXTURE / "AximmMemorySmoke.sv"),
                    str(INCLUDE / "xpm_nsu_mm.sv"),
                    "--Mdir",
                    str(build_dir),
                ],
                text=True,
                capture_output=True,
                env={**os.environ, "CCACHE_DISABLE": "1"},
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                "stdout:\n{}\nstderr:\n{}".format(
                    compile_result.stdout, compile_result.stderr
                ),
            )
            run_result = subprocess.run(
                [str(build_dir / "VAximmMemorySmoke_tb")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(
                run_result.returncode,
                0,
                "stdout:\n{}\nstderr:\n{}".format(
                    run_result.stdout, run_result.stderr
                ),
            )
            self.assertIn("AXIMM_MEMORY_SMOKE_PASS", run_result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
