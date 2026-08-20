#!/usr/bin/env python3
"""End-to-end contract test for automatic XPM endpoint discovery."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RTL_SIMULATION = Path(__file__).resolve().parents[1]
MANIFEST = (
    RTL_SIMULATION
    / "hw"
    / "designs"
    / "EndpointDiscoverySmoke"
    / "EndpointDiscoverySmoke.rtl.json"
)


@unittest.skipUnless(shutil.which("verilator"), "requires Verilator")
class EndpointDiscoveryTest(unittest.TestCase):
    def test_fixture_generates_complete_endpoint_map_and_bindings(self):
        with tempfile.TemporaryDirectory(prefix="noc-rtl-discovery-") as tmp:
            build_dir = Path(tmp) / "build"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RTL_SIMULATION / "build_rtl_models.py"),
                    "--manifest",
                    str(MANIFEST),
                    "--build-dir",
                    str(build_dir),
                ],
                cwd=RTL_SIMULATION,
                text=True,
                capture_output=True,
                env={**os.environ, "CCACHE_DISABLE": "1"},
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )

            output_dir = build_dir / "EndpointDiscoverySmoke"
            endpoint_map = json.loads(
                (output_dir / "EndpointDiscoverySmoke_noc_endpoints.json").read_text()
            )
            self.assertEqual(endpoint_map["schema_version"], 1)
            self.assertEqual(endpoint_map["design"], "EndpointDiscoverySmoke")
            self.assertEqual(
                [endpoint["id"] for endpoint in endpoint_map["endpoints"]],
                ["nmu_aximm_0", "nsu_aximm_0", "nmu_axis_0", "nsu_axis_0"],
            )
            self.assertEqual(
                [
                    (endpoint["module_type"], endpoint["protocol"], endpoint["role"])
                    for endpoint in endpoint_map["endpoints"]
                ],
                [
                    ("xpm_nmu_mm", "aximm", "nmu"),
                    ("xpm_nsu_mm", "aximm", "nsu"),
                    ("xpm_nmu_strm", "axis", "nmu"),
                    ("xpm_nsu_strm", "axis", "nsu"),
                ],
            )

            gem5_plan = json.loads(
                (output_dir / "EndpointDiscoverySmoke_gem5_plan.json").read_text()
            )
            self.assertEqual(
                [node["wrapper_contract"] for node in gem5_plan["nodes"]],
                ["aximm_nmu", "aximm_nsu", "axis_nmu", "axis_nsu"],
            )

            mappings = (
                output_dir / "EndpointDiscoverySmoke_verilator_mappings.h"
            ).read_text()
            root_header = (
                output_dir / "EndpointDiscoverySmoke___024root.h"
            ).read_text()
            expected_signal_paths = (
                "u_nmu_mm__DOT__s_axi_awaddr",
                "u_nsu_mm__DOT__m_axi_awaddr",
                "u_nmu_axis__DOT__s_axis_tdata",
                "u_nsu_axis__DOT__m_axis_tdata",
            )
            for signal_path in expected_signal_paths:
                self.assertIn(signal_path, mappings)
                self.assertIn(signal_path, root_header)

    def test_axis_loopback_fixture_executes_a_complete_beat(self):
        design_dir = RTL_SIMULATION / "hw" / "designs" / "AxisLoopbackSmoke"
        include_dir = RTL_SIMULATION / "hw" / "include"
        with tempfile.TemporaryDirectory(prefix="noc-rtl-loopback-") as tmp:
            build_dir = Path(tmp) / "build"
            compile_result = subprocess.run(
                [
                    "verilator",
                    "--binary",
                    "--timing",
                    "-Wno-fatal",
                    "--top-module",
                    "AxisLoopbackSmoke_tb",
                    "-I{}".format(include_dir),
                    str(design_dir / "AxisLoopbackSmoke_tb.sv"),
                    str(design_dir / "AxisLoopbackSmoke.sv"),
                    str(include_dir / "xpm_nmu_strm.sv"),
                    str(include_dir / "xpm_nsu_strm.sv"),
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
                msg=(
                    "stdout:\n{}\nstderr:\n{}".format(
                        compile_result.stdout, compile_result.stderr
                    )
                ),
            )
            run_result = subprocess.run(
                [str(build_dir / "VAxisLoopbackSmoke_tb")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(
                run_result.returncode,
                0,
                msg=(
                    "stdout:\n{}\nstderr:\n{}".format(
                        run_result.stdout, run_result.stderr
                    )
                ),
            )
            self.assertIn("AXIS_LOOPBACK_PASS", run_result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
