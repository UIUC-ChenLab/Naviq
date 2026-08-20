import argparse
import sys
from dataclasses import dataclass

from generic_v2_smoke_common import (
    build_aximm_param_overrides,
    build_axis_source_param_overrides,
    run_v2_smoke,
)


@dataclass(frozen=True)
class MatrixCase:
    label: str
    noc_topology: str
    connections_json: str
    placement_json: str
    default_args: tuple
    param_overrides: tuple


def _with_seed(component_ids, seed_base):
    params = []
    for offset, component_id in enumerate(component_ids):
        params.append(f"{component_id}.seed={seed_base + offset}")
    return params


def _axis_sink_overrides(
    component_ids, *, expected_packets, data_width_bits=512, ready_percent=100
):
    params = []
    for component_id in component_ids:
        params.extend(
            [
                f"{component_id}.expected_packets={expected_packets}",
                f"{component_id}.data_width={data_width_bits}",
                f"{component_id}.ready_percent={ready_percent}",
            ]
        )
    return params


def _axis_fifo_overrides(
    *,
    packets,
    packet_size_bytes,
    data_width_bits=512,
    fifo_depth=4,
    ready_percent=100,
):
    return build_axis_source_param_overrides(
        ["axis_tg_0"],
        packets=packets,
        packet_size_bytes=packet_size_bytes,
        data_width_bits=data_width_bits,
    ) + [
        f"axis_tg_0.seed=2101",
        f"axis_fifo.expected_packets={packets}",
        f"axis_fifo.fifo_depth={fifo_depth}",
        f"axis_fifo.data_width={data_width_bits}",
        f"axis_fifo.ready_percent={ready_percent}",
        f"axis_end_0.expected_packets={packets}",
        f"axis_end_0.data_width={data_width_bits}",
        f"axis_end_0.ready_percent={ready_percent}",
    ]


def _axis_2to2_overrides(
    *,
    packets,
    packet_size_bytes,
    data_width_bits,
    seed_base,
    ready_percent=100,
):
    components = ["tg_0", "tg_1"]
    return build_axis_source_param_overrides(
        components,
        packets=packets,
        packet_size_bytes=packet_size_bytes,
        data_width_bits=data_width_bits,
        seed_base=seed_base,
    ) + _axis_sink_overrides(
        ["bram_0", "bram_1"],
        expected_packets=packets,
        data_width_bits=data_width_bits,
        ready_percent=ready_percent,
    )


def _aximm_2to2_overrides(
    *,
    transactions,
    beat_size,
    transaction_size,
    mode,
    max_outstanding,
    seed_base,
    nsu_selection="INTERLEAVE",
):
    components = ["first_dummy", "tg_1"]
    return (
        build_aximm_param_overrides(
            components,
            num_transactions=transactions,
            beat_size_bytes=beat_size,
            transaction_size_bytes=transaction_size,
            bandwidth_MBps=1200,
            read_write_mode=mode,
            max_outstanding_writes=max_outstanding,
            align_addresses=False,
            address_increment_bytes=transaction_size,
        )
        + _with_seed(components, seed_base)
        + [
            f"{component}.nsu_selection={nsu_selection}"
            for component in components
        ]
        + [
            f"{component}.awid_distribution=INCREMENT"
            for component in components
        ]
        + [
            f"{component}.arid_distribution=INCREMENT"
            for component in components
        ]
        + [f"{component}.max_awid=3" for component in components]
        + [f"{component}.max_arid=3" for component in components]
    )


BASE_ARGS = (
    "--sim-cycles",
    "500000",
    "--abs-max-tick",
    "5000000000",
)


CASES = {
    "aximm-write-16b-unaligned": MatrixCase(
        label="deep AXIMM 16B unaligned write",
        noc_topology="src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm",
        connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.conn.json",
        placement_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.place.json",
        default_args=BASE_ARGS,
        param_overrides=tuple(
            _aximm_2to2_overrides(
                transactions=4,
                beat_size=16,
                transaction_size=16,
                mode="WRITE_ONLY",
                max_outstanding=1,
                seed_base=1101,
            )
        ),
    ),
    "aximm-write-64b-multi-id-rotate": MatrixCase(
        label="deep AXIMM 64B multi-id rotating write",
        noc_topology="src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm",
        connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.conn.json",
        placement_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.place.json",
        default_args=(
            "--sim-cycles",
            "2000000",
            "--abs-max-tick",
            "10000000000",
        ),
        param_overrides=tuple(
            _aximm_2to2_overrides(
                transactions=8,
                beat_size=64,
                transaction_size=64,
                mode="WRITE_ONLY",
                max_outstanding=4,
                seed_base=1201,
                nsu_selection="ROTATE",
            )
        ),
    ),
    "aximm-sequential-64b-2to2": MatrixCase(
        label="deep AXIMM 64B sequential readback 2-to-2",
        noc_topology="src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm",
        connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.conn.json",
        placement_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.place.json",
        default_args=(
            "--sim-cycles",
            "1000000",
            "--abs-max-tick",
            "5000000000",
        ),
        param_overrides=tuple(
            _aximm_2to2_overrides(
                transactions=1,
                beat_size=64,
                transaction_size=64,
                mode="SEQUENTIAL",
                max_outstanding=4,
                seed_base=1251,
            )
        ),
    ),
    "aximm-incast-64b-stress": MatrixCase(
        label="deep AXIMM 4 NMU to 1 NSU incast stress",
        noc_topology="src/noc/testing/fixtures/topologies/1to4_aximm/1to4_aximm",
        connections_json="noc_testing/topology_jsons/multi_endpoint/1to4_aximm.conn.json",
        placement_json="noc_testing/topology_jsons/multi_endpoint/1to4_aximm.place.json",
        default_args=(
            "--sim-cycles",
            "2000000",
            "--abs-max-tick",
            "10000000000",
        ),
        param_overrides=tuple(
            build_aximm_param_overrides(
                ["tg_0", "tg_1", "tg_2", "tg_3"],
                num_transactions=16,
                beat_size_bytes=64,
                transaction_size_bytes=64,
                bandwidth_MBps=1600,
                read_write_mode="INTERLEAVED",
                max_outstanding_writes=8,
                align_addresses=False,
            )
            + _with_seed(["tg_0", "tg_1", "tg_2", "tg_3"], 1301)
        ),
    ),
    "axis-fifo-64b-baseline": MatrixCase(
        label="deep AXIS FIFO 64B baseline",
        noc_topology="src/noc/testing/fixtures/topologies/axis_fifo/axis_fifo",
        connections_json="noc_testing/topology_jsons/axis/axis_fifo_topo.conn.json",
        placement_json="noc_testing/topology_jsons/axis/axis_fifo_placement.place.json",
        default_args=BASE_ARGS,
        param_overrides=tuple(
            _axis_fifo_overrides(
                packets=8,
                packet_size_bytes=64,
                fifo_depth=2,
            )
        ),
    ),
    "axis-2to2-64b-128w-backpressure": MatrixCase(
        label="deep AXIS 64B 128-bit width conversion with backpressure",
        noc_topology="src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis",
        connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.conn.json",
        placement_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.place.json",
        default_args=BASE_ARGS,
        param_overrides=tuple(
            _axis_2to2_overrides(
                packets=8,
                packet_size_bytes=64,
                data_width_bits=128,
                seed_base=3201,
                ready_percent=60,
            )
        ),
    ),
    "axis-2to2-65b-128w-backpressure": MatrixCase(
        label="deep AXIS 65B 128-bit width conversion with backpressure",
        noc_topology="src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis",
        connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.conn.json",
        placement_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.place.json",
        default_args=BASE_ARGS,
        param_overrides=tuple(
            _axis_2to2_overrides(
                packets=8,
                packet_size_bytes=65,
                data_width_bits=128,
                seed_base=2201,
                ready_percent=60,
            )
        ),
    ),
    "axis-2to2-1500b-stress": MatrixCase(
        label="deep AXIS 2-to-2 MTU-like stress",
        noc_topology="src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis",
        connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.conn.json",
        placement_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.place.json",
        default_args=(
            "--sim-cycles",
            "2000000",
            "--abs-max-tick",
            "10000000000",
        ),
        param_overrides=tuple(
            build_axis_source_param_overrides(
                ["tg_0", "tg_1"],
                packets=16,
                packet_size_bytes=1500,
                data_width_bits=512,
            )
            + _with_seed(["tg_0", "tg_1"], 2301)
            + _axis_sink_overrides(
                ["bram_0", "bram_1"],
                expected_packets=16,
                data_width_bits=512,
                ready_percent=75,
            )
        ),
    ),
}


def _parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=sorted(CASES))
    args, remaining = parser.parse_known_args(argv)
    return args, remaining


args, remaining = _parse_args(sys.argv[1:])
sys.argv = [sys.argv[0], *remaining]
case = CASES[args.case]

run_v2_smoke(
    label=case.label,
    noc_topology=case.noc_topology,
    connections_json=case.connections_json,
    placement_json=case.placement_json,
    default_args=case.default_args,
    param_overrides=case.param_overrides,
)
