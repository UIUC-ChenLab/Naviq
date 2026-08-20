import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from testlib.configuration import constants


@dataclass(frozen=True)
class KnownBugSpec:
    bug_id: str
    name: str
    smoke_path: str
    smoke_args: Tuple[str, ...]
    expected_markers: Tuple[str, ...]
    expected_returncode: Optional[int] = None


def _fail(message):
    raise AssertionError(message)


def _runner_path():
    return Path(__file__).resolve().parent / "run_noc_smoke.py"


def _read_output(tempdir):
    chunks = []
    for filename in (
        constants.gem5_simulation_stdout,
        constants.gem5_simulation_stderr,
    ):
        path = Path(tempdir) / filename
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def run_known_bug_check(spec, params):
    fixtures = params.fixtures
    tempdir = fixtures[constants.tempdir_fixture_name].path
    gem5 = fixtures[constants.gem5_binary_fixture_name].path

    command = [
        gem5,
        "-d",
        tempdir,
        "-re",
        "--silent-redirect",
        str(_runner_path()),
        spec.smoke_path,
        *spec.smoke_args,
    ]

    params.log.message(
        "Running known NoC bug reproducer "
        f"{spec.bug_id}: {' '.join(command)}"
    )
    result = subprocess.run(command)
    text = _read_output(tempdir)

    if spec.expected_returncode is not None:
        if result.returncode != spec.expected_returncode:
            _fail(
                f"{spec.bug_id} expected return code "
                f"{spec.expected_returncode}, observed {result.returncode}"
            )

    missing = [marker for marker in spec.expected_markers if marker not in text]
    if missing:
        _fail(
            f"{spec.bug_id} did not reproduce expected known-bug markers: "
            + ", ".join(missing)
        )

    params.log.message(
        f"Known NoC bug reproduced as expected: {spec.bug_id} ({spec.name})"
    )
