import os
import re

from testlib.configuration import constants
from testlib.helper import joinpath

from gem5.verifier import Verifier

FAILURE_MARKERS = (
    "panic:",
    "fatal:",
    "m5.fatal",
)

TIMEOUT_CAUSE_SUBSTRINGS = (
    "simulate() limit reached",
    "tick exit reached",
    "maxtick",
    "max tick",
    "completed simcycles",
)

OUTSTANDING_AT_END_RE = re.compile(
    r"Monitor:\s*(\d+)\s+(read|write)\s+transactions?\s+still\s+"
    r"outstanding\s+at\s+end\b",
    re.IGNORECASE,
)


def _fail(message):
    raise AssertionError(message)


class NoCCompletionVerifier(Verifier):
    """Verify that a NoC smoke run made forward progress and completed."""

    def __init__(
        self,
        *,
        allow_smoke_skip=False,
        allow_outstanding_writes=False,
        min_reads=None,
        min_writes=None,
        min_packets=None,
    ):
        super().__init__()
        self.allow_smoke_skip = allow_smoke_skip
        self.allow_outstanding_writes = allow_outstanding_writes
        self.min_reads = min_reads
        self.min_writes = min_writes
        self.min_packets = min_packets

    def _read_output(self, tempdir):
        chunks = []
        missing = []
        for filename in (
            constants.gem5_simulation_stdout,
            constants.gem5_simulation_stderr,
        ):
            path = joinpath(tempdir, filename)
            if not os.path.exists(path):
                missing.append(path)
                continue
            with open(path, encoding="utf-8", errors="replace") as stream:
                chunks.append(stream.read())

        if missing and not chunks:
            _fail(
                "NoC completion verifier could not read gem5 output files: "
                + ", ".join(missing)
            )

        return "\n".join(chunks)

    @staticmethod
    def _parse_skip_reason(text):
        match = re.search(r"SMOKE_SKIP:\s*(.+)", text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _parse_exit_cause(text):
        match = re.search(r"Exiting @ tick \d+ because (.+)", text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _parse_completion_counts(text):
        reads = [
            int(value)
            for value in re.findall(r"Completed Reads:\s*(\d+)", text)
        ]
        writes = [
            int(value)
            for value in re.findall(r"Completed Writes:\s*(\d+)", text)
        ]
        packets = [
            int(value)
            for value in re.findall(r"Completed Packets:\s*(\d+)", text)
        ]
        packets += [
            int(value)
            for value in re.findall(
                r"packets_received[\"']?\s*[:=]\s*(\d+)", text
            )
        ]
        return reads, writes, packets

    @staticmethod
    def _parse_outstanding_at_end_counts(text):
        reads = 0
        writes = 0
        for count, kind in OUTSTANDING_AT_END_RE.findall(text):
            if kind.lower() == "read":
                reads += int(count)
            else:
                writes += int(count)
        return reads, writes

    @staticmethod
    def _contains_failure_markers(text):
        lowered = text.lower()
        return any(marker in lowered for marker in FAILURE_MARKERS)

    @staticmethod
    def _is_timeout_cause(cause):
        if cause is None:
            return False
        lowered = cause.lower()
        return any(token in lowered for token in TIMEOUT_CAUSE_SUBSTRINGS)

    @staticmethod
    def _has_completion_marker(text):
        lowered = text.lower()
        return (
            "completed" in lowered
            or "started dma" in lowered
            or "reads and writes completed" in lowered
        )

    def test(self, params):
        tempdir = params.fixtures[constants.tempdir_fixture_name].path
        text = self._read_output(tempdir)

        skip_reason = self._parse_skip_reason(text)
        if skip_reason:
            if self.allow_smoke_skip:
                params.log.message(
                    f"NoC smoke skipped by config: {skip_reason}"
                )
                return
            _fail(f"Unexpected NoC smoke skip: {skip_reason}")

        if self._contains_failure_markers(text):
            _fail("NoC smoke output contains panic/fatal marker")

        exit_cause = self._parse_exit_cause(text)
        if self._is_timeout_cause(exit_cause):
            _fail(f"NoC smoke reached timeout-like exit cause: {exit_cause}")

        outstanding_reads, outstanding_writes = (
            self._parse_outstanding_at_end_counts(text)
        )
        if outstanding_reads or (
            outstanding_writes and not self.allow_outstanding_writes
        ):
            _fail(
                "NoC smoke ended with outstanding transactions: "
                f"{outstanding_reads} reads, {outstanding_writes} writes"
            )

        if outstanding_writes:
            params.log.message(
                "NoC smoke reported "
                f"{outstanding_writes} outstanding write(s); allowed by "
                "the AXIS stream-completion policy."
            )

        completed_reads, completed_writes, completed_packets = (
            self._parse_completion_counts(text)
        )
        total_reads = sum(completed_reads)
        total_writes = sum(completed_writes)
        total_packets = sum(completed_packets)

        if (completed_reads or completed_writes or completed_packets) and (
            total_reads + total_writes + total_packets == 0
        ):
            _fail(
                "NoC smoke completion counters were present but all were zero"
            )

        if self.min_reads is not None and total_reads < self.min_reads:
            _fail(
                f"NoC smoke completed {total_reads} reads, expected at least "
                f"{self.min_reads}"
            )

        if self.min_writes is not None and total_writes < self.min_writes:
            _fail(
                f"NoC smoke completed {total_writes} writes, expected at least "
                f"{self.min_writes}"
            )

        if self.min_packets is not None and total_packets < self.min_packets:
            _fail(
                f"NoC smoke completed {total_packets} packets, expected at least "
                f"{self.min_packets}"
            )

        if completed_reads or completed_writes or completed_packets:
            return

        if self._has_completion_marker(text):
            return

        _fail("NoC smoke output has no completion evidence")
