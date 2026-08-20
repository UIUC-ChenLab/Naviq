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

import run_experiment3 as exp3


class Experiment3HelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.validations = exp3._build_validations(
            workload_case="exp1_4to1_far",
            artifact_root=Path(cls._tmpdir.name) / "artifacts",
            command_log=[],
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_incast_workload_validation_passes(self):
        case = exp3._runtime_cases("exp1_4to1_far")[0]
        meta = exp3.validate_case_topology(case)
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 1)
        self.assertEqual(meta["num_flows"], 4)

    def test_experiment2_reverse_workload_validation_passes(self):
        case = exp3._runtime_cases("exp2_reverse")[0]
        meta = exp3.validate_case_topology(case)
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 4)
        self.assertEqual(meta["num_flows"], 4)

    def test_default_workload_is_expected(self):
        args = exp3.parse_args([])
        self.assertEqual(args.workload_case, "exp1_4to1_far")

    def test_default_strategy_selection_is_expected(self):
        args = exp3.parse_args([])
        self.assertEqual(
            exp3._strategy_list_from_args(args),
            ["exp3_shortest", "exp3_high_overlap", "exp3_path_diverse"],
        )

    def test_generated_router_names_are_recorded(self):
        self.assertEqual(self.validations["exp3_shortest"]["router_name"], "shortest_path")
        self.assertEqual(self.validations["exp3_bad_path"]["router_name"], "bad_path")
        self.assertEqual(self.validations["exp3_high_overlap"]["router_name"], "high_overlap")
        self.assertEqual(self.validations["exp3_path_diverse"]["router_name"], "low_overlap")

    def test_strategy_validation_passes_for_default_workload(self):
        results = exp3._strategy_validation_results(
            self.validations,
            selected_strategies=["exp3_shortest", "exp3_high_overlap", "exp3_path_diverse"],
            min_bad_overlap_ratio=1.25,
            min_diverse_overlap_reduction_ratio=1.25,
            max_diverse_hop_increase=2.0,
            allow_validation_failures=False,
        )
        self.assertTrue(results["exp3_high_overlap"]["passes"])
        self.assertTrue(results["exp3_path_diverse"]["passes"])
        self.assertEqual(results["exp3_path_diverse"]["candidate_strength"], "strong")

    def test_joined_rows_include_route_columns(self):
        joined = exp3._join_summary_rows(
            [{"name": "exp3_shortest", "worst_p99_cycles": "100"}],
            self.validations,
            {
                "exp3_shortest": {"passes": True},
                "exp3_bad_path": {"passes": True},
                "exp3_high_overlap": {"passes": True},
                "exp3_path_diverse": {"passes": True, "candidate_strength": "strong"},
            },
        )
        row = joined[0]
        for column in (
            "workload_case",
            "strategy_class",
            "route_origin",
            "router_name",
            "avg_hop_count",
            "max_hop_count",
            "max_flows_on_any_resource",
            "average_pairwise_route_overlap",
            "top_shared_resource_id",
            "route_overlap_score",
        ):
            self.assertIn(column, row)

    def test_apply_shortest_deltas_handles_zero_hop_delta(self):
        rows = [
            {
                "name": "exp3_shortest",
                "avg_hop_count": 10,
                "route_overlap_score": 2,
                "worst_p99_cycles": 100,
                "min_jfi": 0.5,
                "hotspot_top1_share": 0.3,
                "mean_bw_MBps": 400,
                "hotspot_primary_location": "A",
            },
            {
                "name": "exp3_path_diverse",
                "avg_hop_count": 10,
                "route_overlap_score": 1,
                "worst_p99_cycles": 80,
                "min_jfi": 0.6,
                "hotspot_top1_share": 0.2,
                "mean_bw_MBps": 410,
                "hotspot_primary_location": "B",
            },
        ]
        exp3._apply_shortest_deltas(rows, "exp3_shortest")
        self.assertEqual(rows[1]["p99_improvement_per_added_hop"], "")
        self.assertNotEqual(rows[1]["p99_improvement_per_overlap_reduction"], "")

    def test_overlap_reduction_metric_blank_when_overlap_not_reduced(self):
        rows = [
            {
                "name": "exp3_shortest",
                "avg_hop_count": 10,
                "route_overlap_score": 2,
                "worst_p99_cycles": 100,
                "min_jfi": 0.5,
                "hotspot_top1_share": 0.3,
                "mean_bw_MBps": 400,
                "hotspot_primary_location": "A",
            },
            {
                "name": "exp3_high_overlap",
                "avg_hop_count": 11,
                "route_overlap_score": 3,
                "worst_p99_cycles": 120,
                "min_jfi": 0.4,
                "hotspot_top1_share": 0.4,
                "mean_bw_MBps": 390,
                "hotspot_primary_location": "A",
            },
        ]
        exp3._apply_shortest_deltas(rows, "exp3_shortest")
        self.assertEqual(rows[1]["p99_improvement_per_overlap_reduction"], "")

    def test_plan_only_writes_expected_plan_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir) / "artifacts"
            rc = exp3.main(
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
            plan_path = run_root / "plan" / exp3.PLAN_FILENAME
            manifest_path = run_root / "manifest.json"
            self.assertTrue(plan_path.exists())
            self.assertTrue(manifest_path.exists())

            with plan_path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(
                [row["name"] for row in rows],
                [strategy.case_name for strategy in exp3.STRATEGY_SPECS],
            )

            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["workload_case"], "exp1_4to1_far")
            self.assertEqual(manifest["baseline_strategy"], "exp3_shortest")
            self.assertEqual(manifest["baseline_plan_row_index"], 1)
            self.assertEqual(
                manifest["selected_strategies"],
                ["exp3_shortest", "exp3_high_overlap", "exp3_path_diverse"],
            )


if __name__ == "__main__":
    unittest.main()
