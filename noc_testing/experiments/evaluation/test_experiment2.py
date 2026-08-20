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

import route_metrics
import run_experiment2 as exp2


class RouteMetricsTests(unittest.TestCase):
    def test_route_metrics_ignore_control_nets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ncr_path = Path(tmpdir) / "sample.ncr"
            ncr_path.write_text(
                json.dumps(
                    {
                        "Paths": [
                            {
                                "Nets": [
                                    {
                                        "CommType": "READ",
                                        "Connections": [
                                            "SRC0",
                                            "resp",
                                            "R_DATA_A",
                                            "in0",
                                            "DST0",
                                            "resp_in",
                                        ],
                                    },
                                    {
                                        "CommType": "WRITE",
                                        "Connections": [
                                            "SRC0",
                                            "req_out",
                                            "R_DATA_B",
                                            "in0",
                                            "DST0",
                                            "req",
                                        ],
                                    },
                                    {
                                        "CommType": "READ_REQ",
                                        "Connections": [
                                            "SRC0",
                                            "req_out",
                                            "R_CTRL_SHARED",
                                            "in0",
                                            "DST0",
                                            "req",
                                        ],
                                    },
                                ]
                            },
                            {
                                "Nets": [
                                    {
                                        "CommType": "READ",
                                        "Connections": [
                                            "SRC1",
                                            "resp",
                                            "R_DATA_C",
                                            "in0",
                                            "DST1",
                                            "resp_in",
                                        ],
                                    },
                                    {
                                        "CommType": "WRITE_RESP",
                                        "Connections": [
                                            "SRC1",
                                            "resp",
                                            "R_CTRL_SHARED",
                                            "in0",
                                            "DST1",
                                            "resp_in",
                                        ],
                                    },
                                ]
                            },
                        ]
                    }
                )
            )
            metrics = route_metrics.compute_route_metrics(ncr_path)
            self.assertEqual(metrics["num_data_nets"], 3)
            self.assertEqual(metrics["avg_hop_count"], 2.0)
            self.assertEqual(metrics["max_flows_on_any_resource"], 1)
            self.assertNotEqual(metrics["top_shared_resource_id"], "R_CTRL_SHARED")


class Experiment2HelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.validations = exp2._build_validations(
            artifact_root=Path(cls._tmpdir.name) / "artifacts",
            command_log=[],
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_shift_topology_validation_passes(self):
        meta = exp2.validate_case_topology(exp2.CASE_BY_NAME["shift_low_overlap"])
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 4)
        self.assertEqual(meta["num_flows"], 4)

    def test_existing_all_to_all_fails_4x4_validation(self):
        bad_case = exp2.CaseSpec(
            "bad_all_to_all",
            "shift",
            "low_overlap",
            "4x4",
            "topology_jsons/multi_endpoint/4nmu_to_4nsu_all_to_all_aximm.conn.json",
            "topology_jsons/multi_endpoint/exp2_shift.place.json",
            "low_overlap",
        )
        with self.assertRaises(SystemExit):
            exp2.validate_case_topology(bad_case)

    def test_hotspot_validation_passes(self):
        meta = exp2.validate_case_topology(exp2.CASE_BY_NAME["hotspot_high_overlap"])
        self.assertEqual(meta["num_sources"], 4)
        self.assertEqual(meta["num_destinations"], 1)
        self.assertEqual(meta["num_flows"], 4)

    def test_shift_pair_uses_router_generated_overlap_separation(self):
        result = exp2._pair_validation_result(
            family="shift",
            low_case=self.validations["shift_low_overlap"],
            high_case=self.validations["shift_high_overlap"],
            hop_tolerance=1.0,
            min_overlap_ratio=1.5,
        )
        self.assertGreater(result["route_overlap_score_high"], result["route_overlap_score_low"])
        self.assertGreaterEqual(result["measured_overlap_ratio"], 1.5)

    def test_reverse_and_tornado_pairs_pass_validation(self):
        for family in ("reverse", "tornado"):
            result = exp2._pair_validation_result(
                family=family,
                low_case=self.validations[f"{family}_low_overlap"],
                high_case=self.validations[f"{family}_high_overlap"],
                hop_tolerance=1.0,
                min_overlap_ratio=1.5,
            )
            self.assertTrue(result["passes"], family)

    def test_constrained_high_overlap_cases_record_their_route_policy(self):
        self.assertEqual(
            self.validations["shift_high_overlap"]["router_max_extra_hops"], 3
        )
        self.assertEqual(
            self.validations["reverse_high_overlap"]["router_max_extra_hops"], 1
        )

    def test_pair_validation_can_fail_with_stricter_threshold(self):
        result = exp2._pair_validation_result(
            family="shift",
            low_case=self.validations["shift_low_overlap"],
            high_case=self.validations["shift_high_overlap"],
            hop_tolerance=0.5,
            min_overlap_ratio=10.0,
        )
        self.assertFalse(result["passes"])
        self.assertFalse(result["passes_hop_match"] and result["passes_overlap_separation"])

    def test_baseline_case_maps_to_expected_row_index(self):
        self.assertEqual(exp2._baseline_row_index("shift_low_overlap"), 1)

    def test_low_and_high_overlap_cases_share_one_placement_per_family(self):
        self.assertEqual(
            exp2.CASE_BY_NAME["shift_low_overlap"].placement_json,
            exp2.CASE_BY_NAME["shift_high_overlap"].placement_json,
        )
        self.assertEqual(
            exp2.CASE_BY_NAME["reverse_low_overlap"].placement_json,
            exp2.CASE_BY_NAME["reverse_high_overlap"].placement_json,
        )
        self.assertEqual(
            exp2.CASE_BY_NAME["tornado_low_overlap"].placement_json,
            exp2.CASE_BY_NAME["tornado_high_overlap"].placement_json,
        )
        self.assertEqual(
            exp2.CASE_BY_NAME["hotspot_low_overlap"].placement_json,
            exp2.CASE_BY_NAME["hotspot_high_overlap"].placement_json,
        )

    def test_join_summary_rows_include_route_columns(self):
        joined = exp2._join_summary_rows(
            [{"name": "shift_low_overlap", "worst_p99_cycles": "100"}],
            self.validations,
        )
        row = joined[0]
        for column in (
            "pattern_family",
            "overlap_class",
            "avg_hop_count",
            "max_hop_count",
            "max_flows_on_any_resource",
            "average_pairwise_route_overlap",
            "top_shared_resource_id",
            "route_overlap_score",
        ):
            self.assertIn(column, row)

    def test_plan_only_writes_expected_plan_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir) / "artifacts"
            rc = exp2.main(
                [
                    "--mode",
                    "plan-only",
                    "--run-tag",
                    "unit_test_run",
                    "--artifact-root",
                    str(artifact_root),
                    "--allow-validation-failures",
                ]
            )
            self.assertEqual(rc, 0)

            run_root = artifact_root / "unit_test_run"
            plan_path = run_root / "plan" / exp2.PLAN_FILENAME
            manifest_path = run_root / "manifest.json"

            self.assertTrue(plan_path.exists())
            self.assertTrue(manifest_path.exists())

            with plan_path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([row["name"] for row in rows], [case.case_name for case in exp2.CASE_SPECS])
            self.assertEqual(rows[0]["name"], "shift_low_overlap")
            self.assertEqual(rows[-1]["name"], "hotspot_high_overlap")

            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["baseline_case"], "shift_low_overlap")
            self.assertEqual(manifest["baseline_plan_row_index"], 1)
            self.assertEqual(manifest["selected_cases"], [case.case_name for case in exp2.CASE_SPECS])
            self.assertIn("shift", manifest["pair_validation"])
            self.assertIn("hotspot", manifest["pair_validation"])


if __name__ == "__main__":
    unittest.main()
