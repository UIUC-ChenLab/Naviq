import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NOC_TESTING_ROOT = REPO_ROOT / "noc_testing"
if str(NOC_TESTING_ROOT) not in sys.path:
    sys.path.insert(0, str(NOC_TESTING_ROOT))

import topology_recommender as recommender


def _base_context():
    return {
        "name": "case",
        "overlap_class": "",
        "measured_metrics": {
            "worst_p99_cycles": 100.0,
            "mean_bw_MBps": 400.0,
            "min_jfi": 0.99,
            "hotspot_top1_share": 0.05,
        },
        "route_metadata": {
            "avg_hop_count": 10.0,
            "max_hop_count": 12.0,
            "route_overlap_score": 0.01,
            "num_sources": 1,
            "num_destinations": 1,
            "num_flows": 1,
        },
        "endpoint_metrics": {},
        "hotspot_locations": {},
        "connection_metadata": {
            "protocols": ["aximm"],
            "target_fan_in": {},
            "max_target_fan_in": 1,
            "memory_targets": [],
            "has_streaming_protocol": False,
        },
        "placement_metadata": {"placements": {}},
        "lower_overlap_peer": {},
        "population_thresholds": {
            "route_overlap_median": 0.01,
            "route_overlap_p75": 0.02,
            "avg_hop_median": 10.0,
            "avg_hop_p75": 20.0,
            "worst_p99_median": 100.0,
            "worst_p99_p75": 150.0,
        },
    }


def _classes(context):
    return [item.classification for item in recommender.diagnose_config(context)]


class TopologyRecommenderDiagnosisTests(unittest.TestCase):
    def test_route_overlap_bottleneck(self):
        ctx = _base_context()
        ctx["overlap_class"] = "high_overlap"
        ctx["measured_metrics"]["worst_p99_cycles"] = 220.0
        ctx["measured_metrics"]["hotspot_top1_share"] = 0.22
        ctx["route_metadata"].update(
            {
                "route_overlap_score": 0.20,
                "average_pairwise_route_overlap": 0.05,
                "fraction_of_route_resources_shared_by_2_or_more_flows": 0.30,
                "max_flows_on_any_resource": 3,
                "top_shared_resource_id": "NOC_NPS_SHARED",
            }
        )
        self.assertIn("route_overlap_bottleneck", _classes(ctx))

    def test_path_length_bottleneck(self):
        ctx = _base_context()
        ctx["measured_metrics"]["worst_p99_cycles"] = 180.0
        ctx["route_metadata"].update({"avg_hop_count": 34.0, "max_hop_count": 40.0})
        self.assertIn("path_length_bottleneck", _classes(ctx))

    def test_destination_convergence_bottleneck(self):
        ctx = _base_context()
        ctx["measured_metrics"].update(
            {"worst_p99_cycles": 190.0, "hotspot_top1_share": 0.20}
        )
        ctx["route_metadata"].update(
            {"num_sources": 4, "num_destinations": 1, "num_flows": 4}
        )
        ctx["connection_metadata"]["max_target_fan_in"] = 4
        self.assertIn("destination_convergence_bottleneck", _classes(ctx))

    def test_incast_destination_convergence_outranks_route_overlap(self):
        ctx = _base_context()
        ctx["overlap_class"] = "high_overlap"
        ctx["measured_metrics"].update(
            {"worst_p99_cycles": 240.0, "hotspot_top1_share": 0.25}
        )
        ctx["route_metadata"].update(
            {
                "num_sources": 4,
                "num_destinations": 1,
                "num_flows": 4,
                "route_overlap_score": 1.2,
                "average_pairwise_route_overlap": 0.3,
                "fraction_of_route_resources_shared_by_2_or_more_flows": 0.9,
                "max_flows_on_any_resource": 4,
                "top_shared_resource_id": "NOC_NPS_SHARED",
            }
        )
        ctx["connection_metadata"]["max_target_fan_in"] = 4
        diagnoses = recommender.diagnose_config(ctx)
        self.assertEqual(
            diagnoses[0].classification, "destination_convergence_bottleneck"
        )
        self.assertIn("route_overlap_bottleneck", [d.classification for d in diagnoses])

    def test_paired_route_overlap_requires_measured_degradation_for_strong(self):
        ctx = _base_context()
        ctx["overlap_class"] = "high_overlap"
        ctx["measured_metrics"].update(
            {
                "worst_p99_cycles": 180.0,
                "hotspot_top1_share": 0.20,
                "mean_bw_MBps": 390.0,
            }
        )
        ctx["route_metadata"].update(
            {
                "avg_hop_count": 20.0,
                "route_overlap_score": 0.20,
                "average_pairwise_route_overlap": 0.06,
                "fraction_of_route_resources_shared_by_2_or_more_flows": 0.25,
                "top_shared_resource_id": "NOC_NPS_SHARED",
            }
        )
        ctx["lower_overlap_peer"] = {
            "name": "case_low_overlap",
            "route_overlap_score": 0.05,
            "avg_hop_count": 19.0,
            "worst_p99_cycles": 160.0,
            "hotspot_top1_share": 0.12,
            "mean_bw_MBps": 400.0,
        }
        diagnosis = next(
            item
            for item in recommender.diagnose_config(ctx)
            if item.classification == "route_overlap_bottleneck"
        )
        self.assertEqual(diagnosis.confidence, "strong")

    def test_endpoint_imbalance_bottleneck(self):
        ctx = _base_context()
        ctx["measured_metrics"].update(
            {
                "endpoint_latency_imbalance_ratio": 1.8,
                "endpoint_bw_imbalance_ratio": 1.4,
                "min_jfi": 0.88,
            }
        )
        ctx["endpoint_metrics"]["worst_p99_endpoint"] = "src_3"
        self.assertIn("endpoint_imbalance_bottleneck", _classes(ctx))

    def test_endpoint_imbalance_flat_bandwidth_is_latency_driven(self):
        ctx = _base_context()
        ctx["measured_metrics"].update(
            {
                "endpoint_latency_imbalance_ratio": 1.5,
                "endpoint_bw_imbalance_ratio": 1.001,
                "min_jfi": 0.99,
            }
        )
        ctx["endpoint_metrics"]["worst_p99_endpoint"] = "src_3"
        diagnosis = next(
            item
            for item in recommender.diagnose_config(ctx)
            if item.classification == "endpoint_imbalance_bottleneck"
        )
        self.assertEqual(diagnosis.confidence, "moderate")
        self.assertIn("latency-driven", diagnosis.recommended_action)
        self.assertIn("Investigate endpoint remapping", diagnosis.recommended_action)

    def test_memory_path_contention(self):
        ctx = _base_context()
        ctx["name"] = "hbm_case"
        ctx["measured_metrics"].update(
            {"worst_p99_cycles": 220.0, "hotspot_top1_share": 0.18}
        )
        ctx["route_metadata"].update(
            {"num_sources": 8, "num_destinations": 2, "num_flows": 8}
        )
        ctx["connection_metadata"].update(
            {
                "max_target_fan_in": 4,
                "memory_targets": ["hbm0_port0.s_axi", "hbm1_port0.s_axi"],
            }
        )
        self.assertIn("memory_path_contention", _classes(ctx))

    def test_streaming_datapath_backpressure(self):
        ctx = _base_context()
        ctx["connection_metadata"].update(
            {"protocols": ["axis"], "has_streaming_protocol": True}
        )
        ctx["measured_metrics"].update(
            {
                "queue_peak_depth": 8.0,
                "credit_share_margin": 0.20,
                "queue_data_vc_share": 0.75,
            }
        )
        self.assertIn("streaming_datapath_backpressure", _classes(ctx))

    def test_inconclusive_when_no_signal_is_strong_enough(self):
        ctx = _base_context()
        self.assertEqual(_classes(ctx), ["inconclusive"])


class TopologyRecommenderOutputTests(unittest.TestCase):
    def test_build_evidence_and_deterministic_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            conn = root / "case.conn.json"
            place = root / "case.place.json"
            summary = root / "summary.csv"
            conn.write_text(
                json.dumps(
                    {
                        "kind": "naviq.connections",
                        "components": {
                            "tg0": {
                                "node_type": "AxiRandomTrafficGenerator",
                                "ports": {
                                    "m_axi": {
                                        "role": "master",
                                        "protocol": "aximm",
                                    }
                                },
                            },
                            "bram0": {
                                "node_type": "BramEndpoint",
                                "ports": {
                                    "s_axi": {
                                        "role": "slave",
                                        "protocol": "aximm",
                                    }
                                },
                            },
                        },
                        "connections": [{"from": "tg0.m_axi", "to": "bram0.s_axi"}],
                    }
                )
            )
            place.write_text(
                json.dumps(
                    {
                        "kind": "naviq.placement",
                        "placements": {
                            "tg0.m_axi": "NOC_NMU512_X0Y0",
                            "bram0.s_axi": "NOC_NSU512_X0Y2",
                        },
                    }
                )
            )
            with summary.open("w", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "name",
                        "connection_json",
                        "placement_json",
                        "worst_p99_cycles",
                        "mean_bw_MBps",
                        "min_jfi",
                        "avg_hop_count",
                        "max_hop_count",
                        "route_overlap_score",
                        "num_sources",
                        "num_destinations",
                        "num_flows",
                        "hotspot_top1_share",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "name": "balanced",
                        "connection_json": str(conn),
                        "placement_json": str(place),
                        "worst_p99_cycles": "100",
                        "mean_bw_MBps": "400",
                        "min_jfi": "1.0",
                        "avg_hop_count": "4",
                        "max_hop_count": "5",
                        "route_overlap_score": "0.01",
                        "num_sources": "1",
                        "num_destinations": "1",
                        "num_flows": "1",
                        "hotspot_top1_share": "0.02",
                    }
                )

            evidence = recommender.build_evidence_bundle(summary_csv=summary)
            markdown = recommender.render_deterministic_markdown(evidence)
            self.assertEqual(
                evidence["configs"][0]["deterministic_diagnoses"][0][
                    "classification"
                ],
                "inconclusive",
            )
            self.assertEqual(evidence["configs"][0]["primary_diagnosis"], "inconclusive")
            self.assertIn("recommendation_confidence", evidence["configs"][0])
            self.assertIn("# Automated NoC Recommendation Report", markdown)
            self.assertIn("## Pairwise Route-Overlap Comparisons", markdown)
            self.assertIn("## Follow-Up Experiments", markdown)


if __name__ == "__main__":
    unittest.main()
