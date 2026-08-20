"""Thresholded Naviq/gem5 latency accuracy checks against Vivado references."""

import csv
import os
from dataclasses import dataclass

PLAN_KEY = "name"


def _fail(message):
    raise AssertionError(message)


@dataclass(frozen=True)
class AccuracyMetric:
    name: str
    gem5_column: str
    vivado_column: str
    max_p95_abs_error_cycles: float
    max_abs_error_cycles: float


@dataclass(frozen=True)
class VivadoAccuracySpec:
    name: str
    reference_gem5_csv: str
    vivado_csv: str
    observed_env_var: str
    metrics: tuple[AccuracyMetric, ...]
    min_matched_rows: int = 1
    min_observed_coverage: float = 1.0


def _read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                _fail(f"{path} is missing a CSV header")
            return reader.fieldnames, list(reader)
    except OSError as exc:
        _fail(f"Could not read {path}: {exc}")


def _index_rows(path, rows):
    indexed = {}
    duplicates = []
    for row in rows:
        name = (row.get(PLAN_KEY) or "").strip()
        if not name:
            _fail(f"{path} has a row without '{PLAN_KEY}'")
        if name in indexed:
            duplicates.append(name)
        indexed[name] = row
    if duplicates:
        _fail(
            f"{path} has duplicate '{PLAN_KEY}' values: "
            + ", ".join(sorted(set(duplicates))[:10])
        )
    return indexed


def _float(path, name, column, value):
    try:
        return float(value)
    except (TypeError, ValueError):
        _fail(
            f"{path} row '{name}' column '{column}' is not numeric: {value!r}"
        )


def _percentile_95(values):
    ordered = sorted(values)
    return ordered[int(0.95 * (len(ordered) - 1))]


def _eligible_reference_names(gem5_rows, vivado_rows):
    gem5 = _index_rows("reference gem5 rows", gem5_rows)
    vivado = _index_rows("Vivado rows", vivado_rows)
    return {
        name
        for name in gem5.keys() & vivado.keys()
        if gem5[name].get("gem5_return_code") == "0"
        and vivado[name].get("test_status") == "TEST PASSED"
    }


def run_vivado_accuracy_check(spec, params):
    """Compare a full gem5 sweep against pinned Vivado latency references."""
    _, reference_rows = _read_csv(spec.reference_gem5_csv)
    vivado_header, vivado_rows = _read_csv(spec.vivado_csv)
    observed_csv = os.environ.get(
        spec.observed_env_var, spec.reference_gem5_csv
    )
    observed_header, observed_rows = _read_csv(observed_csv)

    expected_names = _eligible_reference_names(reference_rows, vivado_rows)
    if len(expected_names) < spec.min_matched_rows:
        _fail(
            f"{spec.name} has only {len(expected_names)} eligible rows; expected "
            f"at least {spec.min_matched_rows}"
        )

    required_gem5_columns = {
        "gem5_return_code",
        *(metric.gem5_column for metric in spec.metrics),
    }
    missing_gem5_columns = required_gem5_columns - set(observed_header)
    if missing_gem5_columns:
        _fail(
            f"{observed_csv} is missing gem5 metrics: "
            + ", ".join(sorted(missing_gem5_columns))
        )
    required_vivado_columns = {metric.vivado_column for metric in spec.metrics}
    missing_vivado_columns = required_vivado_columns - set(vivado_header)
    if missing_vivado_columns:
        _fail(
            f"{spec.vivado_csv} is missing Vivado metrics: "
            + ", ".join(sorted(missing_vivado_columns))
        )

    observed = _index_rows(observed_csv, observed_rows)
    vivado = _index_rows(spec.vivado_csv, vivado_rows)
    observed_passing_names = {
        name
        for name, row in observed.items()
        if row.get("gem5_return_code") == "0"
    }
    matched_names = expected_names & observed_passing_names
    coverage = len(matched_names) / len(expected_names)
    if coverage < spec.min_observed_coverage:
        missing = sorted(expected_names - observed_passing_names)
        _fail(
            f"{spec.name} observed coverage is {coverage:.1%}; required "
            f"{spec.min_observed_coverage:.1%}. First missing rows: "
            + ", ".join(missing[:10])
        )

    for metric in spec.metrics:
        errors = [
            abs(
                _float(
                    observed_csv,
                    name,
                    metric.gem5_column,
                    observed[name].get(metric.gem5_column),
                )
                - _float(
                    spec.vivado_csv,
                    name,
                    metric.vivado_column,
                    vivado[name].get(metric.vivado_column),
                )
            )
            for name in matched_names
        ]
        p95_error = _percentile_95(errors)
        max_error = max(errors)
        if p95_error > metric.max_p95_abs_error_cycles:
            _fail(
                f"{spec.name} {metric.name} p95 absolute error is "
                f"{p95_error:.3f} cycles; limit is "
                f"{metric.max_p95_abs_error_cycles:.3f}"
            )
        if max_error > metric.max_abs_error_cycles:
            _fail(
                f"{spec.name} {metric.name} maximum absolute error is "
                f"{max_error:.3f} cycles; limit is "
                f"{metric.max_abs_error_cycles:.3f}"
            )
        params.log.message(
            f"{spec.name} {metric.name}: rows={len(errors)}, "
            f"p95_abs_error_cycles={p95_error:.3f}, "
            f"max_abs_error_cycles={max_error:.3f}"
        )
