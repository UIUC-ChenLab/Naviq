import unittest
from pathlib import Path
import sys

import networkx as nx

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from routing import HighOverlapRouter, LowOverlapRouter


class DummyGraph:
    def __init__(self):
        self.flow_graph = nx.DiGraph()


class OverlapRouterTests(unittest.TestCase):
    def _diamond_graph(self) -> DummyGraph:
        graph = DummyGraph()
        graph.flow_graph.add_edges_from(
            [
                ("A", "B"),
                ("B", "D"),
                ("A", "C"),
                ("C", "D"),
            ]
        )
        return graph

    def test_low_overlap_avoids_used_route(self):
        graph = self._diamond_graph()
        router = LowOverlapRouter()

        first = router.find_routes(graph, "A", "D", protocol="axis")["WRITE"]
        second = router.find_routes(graph, "A", "D", protocol="axis")["WRITE"]

        self.assertEqual(first, ["A", "B", "D"])
        self.assertEqual(second, ["A", "C", "D"])

    def test_high_overlap_reuses_used_route(self):
        graph = self._diamond_graph()
        router = HighOverlapRouter()

        first = router.find_routes(graph, "A", "D", protocol="axis")["WRITE"]
        second = router.find_routes(graph, "A", "D", protocol="axis")["WRITE"]

        self.assertEqual(first, ["A", "B", "D"])
        self.assertEqual(second, ["A", "B", "D"])


if __name__ == "__main__":
    unittest.main()
