import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


EVALUATION_EXPERIMENTS_ROOT = Path(__file__).resolve().parent
NOC_TESTING_ROOT = EVALUATION_EXPERIMENTS_ROOT.parents[1]
REPO_ROOT = NOC_TESTING_ROOT.parent
if str(NOC_TESTING_ROOT) not in sys.path:
    sys.path.insert(0, str(NOC_TESTING_ROOT))
if str(EVALUATION_EXPERIMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_EXPERIMENTS_ROOT))

import run_experiment1 as exp1
import noc_sweep


class Experiment1HelperTests(unittest.TestCase):
    def test_parse_gem5_output_preserves_zero_completion_source_ids(self):
        text = """
>>>>>> AXI Node ID: 0 Stats >>>>>>
  Completed Writes: 0
  Total Write Bytes: 0
***************************************************
  Completed Reads: 0
  Total Read Bytes: 0
>>>>>> AXI Node ID: 1 Stats >>>>>>
  Completed Writes: 64
  Total Write Bytes: 34816
  Min Write Latency = 214.00 axi cycles (214000 ticks)
  Max Write Latency = 287.00 axi cycles (287000 ticks)
  Avg Write Latency = 232.83 axi cycles (232828.12 ticks)
  P50 Write Latency = 234.00 axi cycles
  P95 Write Latency = 260.00 axi cycles
  P99 Write Latency = 287.00 axi cycles
  P99.9 Write Latency = 287.00 axi cycles
  Achieved Write BW = 405.332092 MB/s
***************************************************
  Completed Reads: 64
  Total Read Bytes: 34816
  Min Read Latency = 207.00 axi cycles (207000 ticks)
  Max Read Latency = 242.00 axi cycles (242000 ticks)
  Avg Read Latency = 209.41 axi cycles (209406.25 ticks)
  P50 Read Latency = 208.00 axi cycles
  P95 Read Latency = 217.00 axi cycles
  P99 Read Latency = 242.00 axi cycles
  P99.9 Read Latency = 242.00 axi cycles
  Achieved Read BW = 405.516213 MB/s
>>>>>> AXI Node ID: 2 Stats >>>>>>
  Completed Writes: 41
  Total Write Bytes: 22304
  Min Write Latency = 241.00 axi cycles (241000 ticks)
  Max Write Latency = 300.00 axi cycles (300000 ticks)
  Avg Write Latency = 258.68 axi cycles (258682.93 ticks)
  P50 Write Latency = 254.00 axi cycles
  P95 Write Latency = 288.00 axi cycles
  P99 Write Latency = 300.00 axi cycles
  P99.9 Write Latency = 300.00 axi cycles
  Achieved Write BW = 408.012439 MB/s
***************************************************
  Completed Reads: 41
  Total Read Bytes: 22304
  Min Read Latency = 223.00 axi cycles (223000 ticks)
  Max Read Latency = 269.00 axi cycles (269000 ticks)
  Avg Read Latency = 241.10 axi cycles (241097.56 ticks)
  P50 Read Latency = 243.00 axi cycles
  P95 Read Latency = 264.00 axi cycles
  P99 Read Latency = 269.00 axi cycles
  P99.9 Read Latency = 269.00 axi cycles
  Achieved Read BW = 408.400930 MB/s
>>>>>> AXI Node ID: 3 Stats >>>>>>
  Completed Writes: 16
  Total Write Bytes: 8704
  Min Write Latency = 286.00 axi cycles (286000 ticks)
  Max Write Latency = 362.00 axi cycles (362000 ticks)
  Avg Write Latency = 304.25 axi cycles (304250.00 ticks)
  P50 Write Latency = 301.00 axi cycles
  P95 Write Latency = 362.00 axi cycles
  P99 Write Latency = 362.00 axi cycles
  P99.9 Write Latency = 362.00 axi cycles
  Achieved Write BW = 420.280058 MB/s
***************************************************
  Completed Reads: 16
  Total Read Bytes: 8704
  Min Read Latency = 252.00 axi cycles (252000 ticks)
  Max Read Latency = 334.00 axi cycles (334000 ticks)
  Avg Read Latency = 296.37 axi cycles (296375.00 ticks)
  P50 Read Latency = 306.00 axi cycles
  P95 Read Latency = 334.00 axi cycles
  P99 Read Latency = 334.00 axi cycles
  P99.9 Read Latency = 334.00 axi cycles
  Achieved Read BW = 420.828700 MB/s
=== Fairness Summary (across AXIMM NMUs) ===
  Write BW   JFI = 0.9997  CV = 0.0161  Max/Min = 1.04
  Read BW    JFI = 0.9997  CV = 0.0161  Max/Min = 1.04
  Write Lat  JFI = 0.9796  CV = 0.1444  Max/Min = 1.42
  Read Lat   JFI = 0.9796  CV = 0.1444  Max/Min = 1.42
"""
        rows = noc_sweep.parse_gem5_output(text)
        self.assertEqual([row["src_id"] for row in rows], [0, 1, 2, 3])
        self.assertNotIn("gem5_achieved_read_bw_MBps", rows[0])
        self.assertEqual(rows[1]["gem5_p99_read_lat_cycles"], 242.0)
        self.assertEqual(rows[2]["gem5_p99_write_lat_cycles"], 300.0)
        self.assertEqual(rows[3]["gem5_p99_read_lat_cycles"], 334.0)

    def test_distributed_bram_ranges_are_non_overlapping(self):
        conn_path = (
            REPO_ROOT
            / "noc_testing"
            / "topology_jsons"
            / "multi_endpoint"
            / "4nmu_to_4nsu_distributed_aximm.conn.json"
        )
        data = json.loads(conn_path.read_text())
        ranges = []
        for component_name in ("bram_0", "bram_1", "bram_2", "bram_3"):
            port = data["components"][component_name]["ports"]["s_axi"]
            start = int(port["base_address"], 16)
            size = int(port["size"], 16)
            ranges.append((start, start + size))
        self.assertEqual(len({rng[0] for rng in ranges}), 4)
        for i, (start_i, end_i) in enumerate(ranges):
            for j, (start_j, end_j) in enumerate(ranges):
                if i == j:
                    continue
                self.assertTrue(end_i <= start_j or end_j <= start_i)

    def test_distributed_topology_validation_passes(self):
        meta = exp1.validate_case_topology(exp1.CASE_BY_NAME["exp1_4to4_compact"])
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 4)
        self.assertEqual(meta["num_flows"], 4)

    def test_existing_all_to_all_fails_distributed_validation(self):
        bad_case = exp1.CaseSpec(
            "bad_4to4",
            "topology_jsons/multi_endpoint/4nmu_to_4nsu_all_to_all_aximm.conn.json",
            "topology_jsons/multi_endpoint/4nmu_to_4nsu_all_to_all_compact.place.json",
            "distributed",
        )
        with self.assertRaises(SystemExit):
            exp1.validate_case_topology(bad_case)

    def test_incast_validation_passes(self):
        meta = exp1.validate_case_topology(exp1.CASE_BY_NAME["exp1_4to1_far"])
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 1)
        self.assertEqual(meta["num_flows"], 4)

    def test_baseline_case_maps_to_expected_row_index(self):
        self.assertEqual(exp1._baseline_row_index("exp1_4to1_far"), 4)

    def test_hotspot_profile_mapping(self):
        self.assertEqual(
            exp1._hotspot_mode(exp1.HOTSPOT_PROFILE_NONE, "exp1_4to4_compact"),
            "off",
        )
        self.assertEqual(
            exp1._hotspot_mode(exp1.HOTSPOT_PROFILE_ALL, "exp1_4to1_compact"),
            "both",
        )
        self.assertEqual(
            exp1._hotspot_mode(exp1.HOTSPOT_PROFILE_RECOMMENDED, "exp1_4to1_compact"),
            "off",
        )
        self.assertEqual(
            exp1._hotspot_mode(exp1.HOTSPOT_PROFILE_RECOMMENDED, "exp1_4to1_far"),
            "both",
        )

    def test_plan_only_writes_expected_plan_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir) / "artifacts"
            rc = exp1.main(
                [
                    "--mode",
                    "plan-only",
                    "--run-tag",
                    "unit_test_run",
                    "--artifact-root",
                    str(artifact_root),
                ]
            )
            self.assertEqual(rc, 0)

            run_root = artifact_root / "unit_test_run"
            plan_path = run_root / "plan" / exp1.PLAN_FILENAME
            manifest_path = run_root / "manifest.json"

            self.assertTrue(plan_path.exists())
            self.assertTrue(manifest_path.exists())

            with plan_path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([row["name"] for row in rows], [case.case_name for case in exp1.CASE_SPECS])
            self.assertEqual(rows[0]["name"], "exp1_4to4_compact")
            self.assertEqual(rows[3]["name"], "exp1_4to1_far")

            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["baseline_case"], "exp1_4to4_compact")
            self.assertEqual(manifest["baseline_plan_row_index"], 1)
            self.assertEqual(manifest["selected_cases"], [case.case_name for case in exp1.CASE_SPECS])


if __name__ == "__main__":
    unittest.main()
