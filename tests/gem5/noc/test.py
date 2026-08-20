import os
import sys

from testlib import *

THIS_DIR = os.path.dirname(__file__)
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from fixture_regression import (
    TopologyFixtureSpec,
    run_topology_fixture_check,
)
from known_bug import (
    KnownBugSpec,
    run_known_bug_check,
)
from noc_verifier import NoCCompletionVerifier
from sweep_regression import (
    SweepRegressionSpec,
    run_sweep_regression_check,
)
from vivado_accuracy_regression import (
    AccuracyMetric,
    VivadoAccuracySpec,
    run_vivado_accuracy_check,
)


class NoCCpuPrereqFixture(Fixture):
    def __init__(self):
        super().__init__(name="noc-cpu-prerequisites")
        self.required_paths = (
            joinpath(
                config.base_dir,
                "tests",
                "test-progs",
                "hello",
                "bin",
                "x86",
                "linux",
                "hello",
            ),
            joinpath(
                config.base_dir,
                "src",
                "noc",
                "cpu",
                "programs",
                "cpu_ddr_memory_x86",
            ),
            joinpath(
                config.base_dir,
                "src",
                "noc",
                "cpu",
                "programs",
                "cpu_ddr_walk_x86",
            ),
            joinpath(
                config.base_dir,
                "src",
                "noc",
                "cpu",
                "programs",
                "ddr_dma_control_x86",
            ),
        )

    def setup(self, testitem):
        missing = [
            path for path in self.required_paths if not os.path.exists(path)
        ]
        if missing:
            self.name = "noc-cpu-prerequisites missing " + ", ".join(missing)
            self.skip(testitem)


def _runner_path():
    return joinpath(
        config.base_dir, "tests", "gem5", "noc", "run_noc_smoke.py"
    )


def _test_name(smoke_path):
    return "noc-" + os.path.splitext(os.path.basename(smoke_path))[0]


def _register_noc_smoke(
    smoke_path,
    *,
    length,
    valid_isas,
    tags,
    fixtures=(),
    allow_smoke_skip=False,
    smoke_args=(),
    name=None,
    min_reads=None,
    min_writes=None,
    min_packets=None,
    allow_outstanding_writes=False,
):
    verifier = NoCCompletionVerifier(
        allow_smoke_skip=allow_smoke_skip,
        allow_outstanding_writes=allow_outstanding_writes,
        min_reads=min_reads,
        min_writes=min_writes,
        min_packets=min_packets,
    )
    suites = gem5_verify_config(
        name=name or _test_name(smoke_path),
        config=_runner_path(),
        config_args=[smoke_path, *smoke_args],
        verifiers=(verifier,),
        fixtures=fixtures,
        valid_isas=valid_isas,
        valid_variants=(constants.opt_tag,),
        valid_hosts=(constants.host_x86_64_tag,),
        length=length,
    )
    for suite in suites:
        suite.tags.update({"noc", *tags})


QUICK_GENERIC_SMOKES = (
    {
        "path": "src/noc/testing/generic/aximm_handshake_stress_smoke.py",
        "tags": {"noc-aximm", "noc-stress", "noc-axi-handshake-stress"},
        "min_writes": 8,
    },
    {
        "path": "src/noc/testing/generic/aximm_1_to_1_close_smoke.py",
        "tags": {"noc-aximm"},
        "min_writes": 1,
    },
    {
        "path": "src/noc/testing/generic/aximm_2_to_2_smoke.py",
        "tags": {"noc-aximm"},
        "min_writes": 16,
    },
    {
        "path": "src/noc/testing/generic/aximm_1_to_4_smoke.py",
        "tags": {"noc-aximm"},
        "min_writes": 32,
    },
    {
        "path": "src/noc/testing/generic/axis_2_to_2_smoke.py",
        "tags": {"noc-axis"},
        "min_writes": 16,
        "allow_outstanding_writes": True,
    },
    {
        "path": "src/noc/testing/generic/axis_1_to_4_smoke.py",
        "tags": {"noc-axis"},
        "min_writes": 32,
        "allow_outstanding_writes": True,
    },
    {
        "path": "src/noc/testing/generic/axis_fifo_smoke.py",
        "tags": {"noc-axis"},
        "min_writes": 8,
        "allow_outstanding_writes": True,
    },
)

LONG_GENERIC_SMOKES = (
    {
        "path": "src/noc/testing/generic/aximm_1_to_1_close_long_smoke.py",
        "tags": {"noc-aximm"},
        "min_writes": 1,
    },
    {
        "path": "src/noc/testing/generic/axis_2_to_2_long_smoke.py",
        "tags": {"noc-axis"},
        "min_writes": 32,
        "allow_outstanding_writes": True,
    },
)

DDR_SMOKES = (
    "src/noc/testing/ddr/ddr_direct_interleaved_smoke.py",
    "src/noc/testing/ddr/ddr_direct_contention_smoke.py",
    "src/noc/testing/ddr/ddr_dma_axis_sink_smoke.py",
)

DDR_EXTERNAL_RTL_SMOKES = (
    "src/noc/testing/ddr/ddr_dma_ppe_base_axis_sink_smoke.py",
)

HBM_SMOKES = (
    "src/noc/testing/hbm/hbm_shared_controller_smoke.py",
    "src/noc/testing/hbm/hbm_shared_controller_contention_smoke.py",
    "src/noc/testing/hbm/hbm_single_port_smoke.py",
    "src/noc/testing/hbm/hbm_single_port_read_only_smoke.py",
    "src/noc/testing/hbm/hbm_single_port_unaligned_smoke.py",
    "src/noc/testing/hbm/hbm_multi_hbm_multi_nmu_smoke.py",
    "src/noc/testing/hbm/hbm_mixed_bram_hbm_smoke.py",
    "src/noc/testing/hbm/hbm_32tg_16mc_uncapped_bandwidth_smoke.py",
)

CPU_SMOKES = (
    "src/noc/testing/ddr/cpu_ddr_hello_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_memory_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_walk_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_dma_axis_sink_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_dma_ppe_base_axis_sink_smoke.py",
)

DEEP_MATRIX_SMOKE = "src/noc/testing/generic/deep_matrix_smoke.py"

DEEP_MATRIX_CASES = (
    {
        "case": "aximm-write-16b-unaligned",
        "length": constants.quick_tag,
        "tags": {"noc-generic", "noc-nmu", "noc-nsu", "noc-aximm"},
        "min_writes": 8,
    },
    {
        "case": "aximm-write-64b-multi-id-rotate",
        "length": constants.long_tag,
        "tags": {
            "noc-generic",
            "noc-nmu",
            "noc-nsu",
            "noc-aximm",
            "noc-stress",
        },
        "min_writes": 16,
    },
    {
        "case": "aximm-sequential-64b-2to2",
        "length": constants.quick_tag,
        "tags": {"noc-generic", "noc-nmu", "noc-nsu", "noc-aximm"},
        "min_reads": 2,
        "min_writes": 2,
    },
    {
        "case": "aximm-incast-64b-stress",
        "length": constants.long_tag,
        "tags": {
            "noc-generic",
            "noc-nmu",
            "noc-nsu",
            "noc-aximm",
            "noc-stress",
            "noc-nightly",
        },
        "min_reads": 1,
        "min_writes": 1,
    },
    {
        "case": "axis-fifo-64b-baseline",
        "length": constants.quick_tag,
        "tags": {"noc-generic", "noc-nmu", "noc-nsu", "noc-axis"},
        "min_writes": 8,
        "allow_outstanding_writes": True,
    },
    {
        "case": "axis-2to2-64b-128w-backpressure",
        "length": constants.quick_tag,
        "tags": {"noc-generic", "noc-nmu", "noc-nsu", "noc-axis"},
        "min_writes": 16,
        "allow_outstanding_writes": True,
    },
    {
        "case": "axis-2to2-65b-128w-backpressure",
        "length": constants.quick_tag,
        "tags": {"noc-generic", "noc-nmu", "noc-nsu", "noc-axis"},
        "min_writes": 16,
        "allow_outstanding_writes": True,
    },
    {
        "case": "axis-2to2-1500b-stress",
        "length": constants.long_tag,
        "tags": {
            "noc-generic",
            "noc-nmu",
            "noc-nsu",
            "noc-axis",
            "noc-stress",
            "noc-nightly",
        },
    },
)

AXIS_FIFO_BOUNDARY_REGRESSIONS = (
    {
        "name": "noc-axis-fifo-15b-clean-completion",
        "packet_size": 15,
    },
    {
        "name": "noc-axis-fifo-17b-clean-completion",
        "packet_size": 17,
    },
)

AXIMM_MULTI_ID_REGRESSIONS = (
    {
        "name": "noc-aximm-interleaved-multi-id-readback",
        "smoke_args": (
            "--case",
            "aximm-write-64b-multi-id-rotate",
            "--param",
            "first_dummy.read_write_mode=INTERLEAVED",
            "--param",
            "tg_1.read_write_mode=INTERLEAVED",
        ),
    },
)


def _register_sweep_regression(spec, tags):
    TestSuite(
        name="noc-" + spec.name,
        tests=(
            TestFunction(
                lambda params, sweep_spec=spec: run_sweep_regression_check(
                    sweep_spec, params
                ),
                name="noc-" + spec.name + "-check",
            ),
        ),
        tags={
            "noc",
            "noc-sweep",
            constants.long_tag,
            constants.null_tag,
            constants.opt_tag,
            constants.host_x86_64_tag,
            *tags,
        },
    )


TRUSTED_RESULTS_DIR = joinpath(
    config.base_dir, "tests", "gem5", "noc", "trusted_results"
)

TOPOLOGY_FIXTURE_DIR = joinpath(
    config.base_dir, "src", "noc", "testing", "fixtures", "topologies"
)

TOPOLOGY_FIXTURES = (
    TopologyFixtureSpec(
        name="aximm-2to2",
        connections_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "2to2_aximm.conn.json",
        ),
        placement_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "2to2_aximm.place.json",
        ),
        nts=joinpath(TOPOLOGY_FIXTURE_DIR, "2to2_aximm", "2to2_aximm.nts"),
        ncr=joinpath(TOPOLOGY_FIXTURE_DIR, "2to2_aximm", "2to2_aximm.ncr"),
    ),
    TopologyFixtureSpec(
        name="aximm-1to4",
        connections_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "1to4_aximm.conn.json",
        ),
        placement_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "1to4_aximm.place.json",
        ),
        nts=joinpath(TOPOLOGY_FIXTURE_DIR, "1to4_aximm", "1to4_aximm.nts"),
        ncr=joinpath(TOPOLOGY_FIXTURE_DIR, "1to4_aximm", "1to4_aximm.ncr"),
    ),
    TopologyFixtureSpec(
        name="axis-2to2",
        connections_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "2to2_axis.conn.json",
        ),
        placement_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "2to2_axis.place.json",
        ),
        nts=joinpath(TOPOLOGY_FIXTURE_DIR, "2to2_axis", "2to2_axis.nts"),
        ncr=joinpath(TOPOLOGY_FIXTURE_DIR, "2to2_axis", "2to2_axis.ncr"),
    ),
    TopologyFixtureSpec(
        name="axis-1to4",
        connections_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "1to4_axis.conn.json",
        ),
        placement_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "multi_endpoint",
            "1to4_axis.place.json",
        ),
        nts=joinpath(TOPOLOGY_FIXTURE_DIR, "1to4_axis", "1to4_axis.nts"),
        ncr=joinpath(TOPOLOGY_FIXTURE_DIR, "1to4_axis", "1to4_axis.ncr"),
    ),
    TopologyFixtureSpec(
        name="axis-fifo",
        connections_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "axis",
            "axis_fifo_topo.conn.json",
        ),
        placement_json=joinpath(
            config.base_dir,
            "noc_testing",
            "topology_jsons",
            "axis",
            "axis_fifo_placement.place.json",
        ),
        nts=joinpath(TOPOLOGY_FIXTURE_DIR, "axis_fifo", "axis_fifo.nts"),
        ncr=joinpath(TOPOLOGY_FIXTURE_DIR, "axis_fifo", "axis_fifo.ncr"),
    ),
)

VIVADO_ACCURACY_REGRESSIONS = (
    VivadoAccuracySpec(
        name="sizing-latency-accuracy",
        reference_gem5_csv=joinpath(
            TRUSTED_RESULTS_DIR, "latency_comp_sizes_gem5.csv"
        ),
        vivado_csv=joinpath(
            TRUSTED_RESULTS_DIR, "latency_comp_sizes_vivado.csv"
        ),
        observed_env_var="NOC_VIVADO_ACCURACY_OBSERVED_CSV",
        min_matched_rows=1200,
        metrics=(
            AccuracyMetric(
                "write-average-latency",
                "gem5_avg_write_lat_cycles",
                "write_latency_avg",
                max_p95_abs_error_cycles=6.0,
                max_abs_error_cycles=12.0,
            ),
            AccuracyMetric(
                "write-maximum-latency",
                "gem5_max_write_lat_cycles",
                "write_latency_max",
                max_p95_abs_error_cycles=4.0,
                max_abs_error_cycles=6.0,
            ),
            AccuracyMetric(
                "read-average-latency",
                "gem5_avg_read_lat_cycles",
                "read_latency_avg",
                max_p95_abs_error_cycles=6.5,
                max_abs_error_cycles=16.0,
            ),
            AccuracyMetric(
                "read-maximum-latency",
                "gem5_max_read_lat_cycles",
                "read_latency_max",
                max_p95_abs_error_cycles=4.0,
                max_abs_error_cycles=6.0,
            ),
        ),
    ),
)


def _register_static_check(name, tags, function):
    TestSuite(
        name="noc-" + name,
        tests=(TestFunction(function, name="noc-" + name + "-check"),),
        tags={
            "noc",
            constants.quick_tag,
            constants.null_tag,
            constants.opt_tag,
            constants.host_x86_64_tag,
            *tags,
        },
    )


SWEEP_REGRESSIONS = (
    SweepRegressionSpec(
        name="sizing-sweep-regression",
        plan_csv=joinpath(
            config.base_dir,
            "noc_testing",
            "sweep_plans",
            "sizing",
            "noc_plan_all_sizes_v2.csv",
        ),
        trusted_csv=joinpath(
            TRUSTED_RESULTS_DIR, "latency_comp_sizes_gem5.csv"
        ),
        observed_env_var="NOC_SWEEP_OBSERVED_SIZING_CSV",
    ),
    SweepRegressionSpec(
        name="placement-route-ladder-regression",
        plan_csv=joinpath(
            config.base_dir,
            "noc_testing",
            "sweep_plans",
            "placement",
            "placement_plan_aximm_bram_route_ladder_bw300_no_ncr_nts.csv",
        ),
        trusted_csv=joinpath(
            TRUSTED_RESULTS_DIR, "placement_route_ladder_gem5.csv"
        ),
        observed_env_var="NOC_SWEEP_OBSERVED_PLACEMENT_CSV",
    ),
)

KNOWN_BUGS = ()


def _known_bug_list_only(params, spec):
    raise Exception(
        "Known-bug suite registered for listing only. "
        "Use NOC_RUN_KNOWN_BUGS=1 to execute " + spec.bug_id + "."
    )


def _register_known_bug(spec, *, run_reproducer):
    safe_name = spec.name.replace("_", "-")
    if run_reproducer:
        test_function = TestFunction(
            lambda params, known_bug_spec=spec: run_known_bug_check(
                known_bug_spec, params
            ),
            name="noc-known-bug-" + safe_name + "-xfail",
        )
        fixtures = (
            Gem5Fixture(constants.null_tag, constants.opt_tag),
            TempdirFixture(),
        )
    else:
        test_function = TestFunction(
            lambda params, known_bug_spec=spec: _known_bug_list_only(
                params, known_bug_spec
            ),
            name="noc-known-bug-" + safe_name + "-list-only",
        )
        fixtures = ()

    TestSuite(
        name="noc-known-bug-" + safe_name,
        tests=(test_function,),
        fixtures=fixtures,
        tags={
            "noc",
            "noc-known-bug",
            "noc-xfail",
            spec.bug_id.lower(),
            constants.null_tag,
            constants.opt_tag,
            constants.host_x86_64_tag,
        },
    )


for smoke in QUICK_GENERIC_SMOKES:
    _register_noc_smoke(
        smoke["path"],
        length=constants.quick_tag,
        valid_isas=(constants.null_tag,),
        tags={"noc-generic", *smoke["tags"]},
        min_writes=smoke.get("min_writes"),
        allow_outstanding_writes=smoke.get("allow_outstanding_writes", False),
    )

for smoke in LONG_GENERIC_SMOKES:
    _register_noc_smoke(
        smoke["path"],
        length=constants.long_tag,
        valid_isas=(constants.null_tag,),
        tags={"noc-generic", *smoke["tags"]},
        min_writes=smoke.get("min_writes"),
        allow_outstanding_writes=smoke.get("allow_outstanding_writes", False),
    )

for case in DEEP_MATRIX_CASES:
    _register_noc_smoke(
        DEEP_MATRIX_SMOKE,
        length=case["length"],
        valid_isas=(constants.null_tag,),
        tags=case["tags"],
        smoke_args=("--case", case["case"]),
        name="noc-deep-" + case["case"].replace("_", "-"),
        min_reads=case.get("min_reads"),
        min_writes=case.get("min_writes"),
        min_packets=case.get("min_packets"),
        allow_outstanding_writes=case.get("allow_outstanding_writes", False),
    )

for regression in AXIS_FIFO_BOUNDARY_REGRESSIONS:
    packet_size = regression["packet_size"]
    _register_noc_smoke(
        "src/noc/testing/generic/axis_fifo_smoke.py",
        length=constants.quick_tag,
        valid_isas=(constants.null_tag,),
        tags={"noc-generic", "noc-nmu", "noc-nsu", "noc-axis"},
        name=regression["name"],
        min_writes=16,
        smoke_args=(
            "--sim-cycles",
            "500000",
            "--abs-max-tick",
            "5000000000",
            "--param",
            f"axis_tg_0.min_packet_size_bytes={packet_size}",
            "--param",
            f"axis_tg_0.max_packet_size_bytes={packet_size}",
            "--param",
            "axis_tg_0.packet_size_distribution=FIXED",
            "--param",
            "axis_tg_0.max_packets=8",
            "--param",
            "axis_fifo.expected_packets=8",
            "--param",
            "axis_fifo.fifo_depth=2",
            "--param",
            "axis_end_0.expected_packets=8",
        ),
    )

for regression in AXIMM_MULTI_ID_REGRESSIONS:
    _register_noc_smoke(
        DEEP_MATRIX_SMOKE,
        length=constants.quick_tag,
        valid_isas=(constants.null_tag,),
        tags={
            "noc-generic",
            "noc-nmu",
            "noc-nsu",
            "noc-aximm",
            "noc-aximm-multi-id",
        },
        name=regression["name"],
        min_reads=16,
        min_writes=16,
        smoke_args=regression["smoke_args"],
    )

for smoke in DDR_SMOKES:
    _register_noc_smoke(
        smoke,
        length=constants.long_tag,
        valid_isas=(constants.null_tag,),
        tags={"noc-ddr"},
    )

for smoke in DDR_EXTERNAL_RTL_SMOKES:
    _register_noc_smoke(
        smoke,
        length=constants.long_tag,
        valid_isas=(constants.null_tag,),
        tags={"noc-ddr", "external-rtl"},
        allow_smoke_skip=True,
    )

for smoke in HBM_SMOKES:
    _register_noc_smoke(
        smoke,
        length=constants.long_tag,
        valid_isas=(constants.null_tag,),
        tags={"noc-hbm"},
    )

cpu_prereqs = NoCCpuPrereqFixture()
for smoke in CPU_SMOKES:
    _register_noc_smoke(
        smoke,
        length=constants.long_tag,
        valid_isas=(constants.x86_tag,),
        tags={"noc-cpu", "noc-ddr"},
        fixtures=(cpu_prereqs,),
    )

_register_sweep_regression(SWEEP_REGRESSIONS[0], {"noc-sizing"})
_register_sweep_regression(SWEEP_REGRESSIONS[1], {"noc-placement"})

_register_static_check(
    "topology-fixtures",
    {"noc-fixture"},
    lambda params: run_topology_fixture_check(TOPOLOGY_FIXTURES, params),
)

for accuracy_regression in VIVADO_ACCURACY_REGRESSIONS:
    _register_static_check(
        "vivado-" + accuracy_regression.name,
        {"noc-accuracy", "noc-vivado"},
        lambda params, spec=accuracy_regression: run_vivado_accuracy_check(
            spec, params
        ),
    )

if os.environ.get("NOC_REGISTER_KNOWN_BUGS") == "1":
    for known_bug in KNOWN_BUGS:
        _register_known_bug(known_bug, run_reproducer=False)
elif os.environ.get("NOC_RUN_KNOWN_BUGS") == "1":
    for known_bug in KNOWN_BUGS:
        _register_known_bug(known_bug, run_reproducer=True)
