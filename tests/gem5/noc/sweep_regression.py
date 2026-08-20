import csv
import os
from dataclasses import dataclass

from testlib import test_util


PLAN_KEY = "name"
DEFAULT_METRIC_COLUMNS = (
    "gem5_min_write_lat_cycles",
    "gem5_avg_write_lat_cycles",
    "gem5_max_write_lat_cycles",
    "gem5_p50_write_lat_cycles",
    "gem5_p95_write_lat_cycles",
    "gem5_p99_write_lat_cycles",
    "gem5_p999_write_lat_cycles",
    "gem5_achieved_write_bw_MBps",
    "gem5_min_read_lat_cycles",
    "gem5_avg_read_lat_cycles",
    "gem5_max_read_lat_cycles",
    "gem5_p50_read_lat_cycles",
    "gem5_p95_read_lat_cycles",
    "gem5_p99_read_lat_cycles",
    "gem5_p999_read_lat_cycles",
    "gem5_achieved_read_bw_MBps",
)


@dataclass(frozen=True)
class SweepRegressionSpec:
    name: str
    plan_csv: str
    trusted_csv: str
    observed_env_var: str
    metric_columns: tuple[str, ...] = DEFAULT_METRIC_COLUMNS


def _read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                test_util.fail(f"{path} is missing a CSV header")
            rows = list(reader)
            return reader.fieldnames, rows
    except OSError as exc:
        test_util.fail(f"Could not read {path}: {exc}")


def _index_rows(path, rows):
    indexed = {}
    duplicates = []
    for row in rows:
        key = (row.get(PLAN_KEY) or "").strip()
        if not key:
            test_util.fail(f"{path} has a row without a '{PLAN_KEY}' value")
        if key in indexed:
            duplicates.append(key)
        indexed[key] = row
    if duplicates:
        test_util.fail(
            f"{path} has duplicate '{PLAN_KEY}' values: "
            + ", ".join(sorted(set(duplicates))[:10])
        )
    return indexed


def _parse_float(path, row_name, column, value):
    try:
        return float(value)
    except (TypeError, ValueError):
        test_util.fail(
            f"{path} row '{row_name}' column '{column}' is not numeric: {value!r}"
        )


def _warn(params, message):
    warning = f"WARNING: {message}"
    print(warning)
    params.log.message(warning)


def run_sweep_regression_check(spec, params):
    _, plan_rows = _read_csv(spec.plan_csv)
    trusted_header, trusted_rows = _read_csv(spec.trusted_csv)
    observed_csv = os.environ.get(spec.observed_env_var, spec.trusted_csv)
    observed_header, observed_rows = _read_csv(observed_csv)

    if PLAN_KEY not in trusted_header:
        test_util.fail(f"{spec.trusted_csv} is missing required column '{PLAN_KEY}'")
    if PLAN_KEY not in observed_header:
        test_util.fail(f"{observed_csv} is missing required column '{PLAN_KEY}'")

    missing_trusted_columns = [
        column for column in spec.metric_columns if column not in trusted_header
    ]
    if missing_trusted_columns:
        test_util.fail(
            f"{spec.trusted_csv} is missing metric columns: "
            + ", ".join(missing_trusted_columns)
        )

    missing_observed_columns = [
        column for column in spec.metric_columns if column not in observed_header
    ]
    if missing_observed_columns:
        test_util.fail(
            f"{observed_csv} is missing metric columns: "
            + ", ".join(missing_observed_columns)
        )

    trusted_by_name = _index_rows(spec.trusted_csv, trusted_rows)
    observed_by_name = _index_rows(observed_csv, observed_rows)
    plan_names = [(row.get(PLAN_KEY) or "").strip() for row in plan_rows]
    missing_plan_names = [name for name in plan_names if not name]
    if missing_plan_names:
        test_util.fail(f"{spec.plan_csv} has rows without a '{PLAN_KEY}' value")

    missing_trusted = [name for name in plan_names if name not in trusted_by_name]
    if missing_trusted:
        test_util.fail(
            f"{spec.name} trusted results do not cover plan rows: "
            + ", ".join(missing_trusted[:10])
        )

    missing_observed = [name for name in plan_names if name not in observed_by_name]
    if missing_observed:
        _warn(
            params,
            f"{spec.name} observed results do not cover {len(missing_observed)} "
            f"plan rows; first missing: {', '.join(missing_observed[:10])}",
        )

    compared = 0
    drift_count = 0
    drift_examples = []
    for name in plan_names:
        if name not in observed_by_name:
            continue
        trusted = trusted_by_name[name]
        observed = observed_by_name[name]
        for column in spec.metric_columns:
            expected = _parse_float(spec.trusted_csv, name, column, trusted.get(column))
            actual = _parse_float(observed_csv, name, column, observed.get(column))
            compared += 1
            if actual != expected:
                drift_count += 1
                if len(drift_examples) < 12:
                    drift_examples.append(
                        f"{name}.{column}: expected {expected}, observed {actual}"
                    )

    extra_observed = sorted(set(observed_by_name) - set(plan_names))
    if extra_observed:
        _warn(
            params,
            f"{spec.name} observed results include {len(extra_observed)} rows not "
            f"in the plan; first extra: {', '.join(extra_observed[:10])}",
        )

    if drift_count:
        _warn(
            params,
            f"{spec.name} detected {drift_count} latency/bandwidth metric drifts "
            f"across {compared} comparisons. Examples: "
            + "; ".join(drift_examples),
        )

    params.log.message(
        f"{spec.name}: checked {len(plan_names)} plan rows, "
        f"{len(trusted_rows)} trusted rows, {len(observed_rows)} observed rows, "
        f"{compared} metric comparisons"
    )
