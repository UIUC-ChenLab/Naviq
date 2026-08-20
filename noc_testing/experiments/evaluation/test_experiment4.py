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

import run_experiment4 as exp4


class Experiment4HelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validations = {
            case.case_name: exp4.validate_route_artifacts(
                case,
                exp4.validate_case_topology(case),
            )
            for case in exp4.CASE_SPECS
            if case.enabled_by_default
        }

    def test_single_target_topology_validation_passes(self):
        case = exp4.CASE_BY_NAME["exp4_near_single_target"]
        meta = exp4.validate_case_topology(case)
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 1)
        self.assertEqual(meta["num_flows"], 4)
        self.assertEqual(meta["attachment_mode"], "single_target")

    def test_distributed_target_topology_validation_passes(self):
        case = exp4.CASE_BY_NAME["exp4_near_distributed_targets"]
        meta = exp4.validate_case_topology(case)
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 4)
        self.assertEqual(meta["num_flows"], 4)
        self.assertEqual(meta["attachment_mode"], "distributed_targets")

    def test_default_baseline_and_traffic_mode_are_expected(self):
        args = exp4.parse_args([])
        self.assertEqual(args.baseline_case, "exp4_near_single_target")
        self.assertEqual(args.traffic_mode, "mixed_rw")

    def test_joined_rows_include_attachment_and_route_columns(self):
        joined = exp4._join_summary_rows(
            [{"name": "exp4_near_single_target", "worst_p99_cycles": "100"}],
            self.validations,
            "mixed_rw",
        )
        row = joined[0]
        for column in (
            "subexperiment",
            "target_class",
            "attachment_mode",
            "source_placement_class",
            "source_count",
            "traffic_mode",
            "avg_hop_count",
            "max_hop_count",
            "max_flows_on_any_resource",
            "average_pairwise_route_overlap",
            "top_shared_resource_id",
            "route_overlap_score",
            "memory_path_hotspot_status",
        ):
            self.assertIn(column, row)
        self.assertEqual(row["memory_path_hotspot_status"], exp4.MEMORY_PATH_HOTSPOT_STATUS)

    def test_same_placement_pairwise_deltas_only_populate_for_distributed_rows(self):
        rows = [
            {
                "name": "exp4_near_single_target",
                "worst_p99_cycles": 100,
                "mean_bw_MBps": 400,
                "hotspot_top1_share": 0.5,
                "route_overlap_score": 0.8,
                "avg_hop_count": 14.5,
                "hotspot_primary_location": "A",
            },
            {
                "name": "exp4_near_distributed_targets",
                "worst_p99_cycles": 80,
                "mean_bw_MBps": 420,
                "hotspot_top1_share": 0.2,
                "route_overlap_score": 0.0,
                "avg_hop_count": 9.0,
                "hotspot_primary_location": "B",
            },
        ]
        exp4._apply_same_placement_pairwise_deltas(rows)
        self.assertEqual(rows[0]["same_placement_single_case"], "")
        self.assertEqual(rows[0]["delta_worst_p99_vs_same_placement_single"], "")
        self.assertEqual(rows[1]["same_placement_single_case"], "exp4_near_single_target")
        self.assertEqual(rows[1]["delta_worst_p99_vs_same_placement_single"], -20)
        self.assertEqual(rows[1]["delta_route_overlap_vs_same_placement_single"], -0.8)
        self.assertTrue(rows[1]["primary_hotspot_changed_vs_same_placement_single"])

    def test_plan_only_writes_expected_plan_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir) / "artifacts"
            rc = exp4.main(
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
            plan_path = run_root / "plan" / exp4.PLAN_FILENAME
            manifest_path = run_root / "manifest.json"
            self.assertTrue(plan_path.exists())
            self.assertTrue(manifest_path.exists())

            with plan_path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(
                [row["name"] for row in rows],
                [case.case_name for case in exp4.CASE_SPECS if case.enabled_by_default],
            )

            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["baseline_case"], "exp4_near_single_target")
            self.assertEqual(manifest["baseline_plan_row_index"], 1)
            self.assertEqual(manifest["traffic_mode"], "mixed_rw")
            self.assertEqual(manifest["selected_cases"], exp4.OFFICIAL_CASES)


if __name__ == "__main__":
    unittest.main()
