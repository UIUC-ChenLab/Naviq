import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
for path in (
    ROOT / "ext",
    ROOT / "tests",
    Path(__file__).resolve().parent,
):
    sys.path.insert(0, str(path))

from noc_verifier import NoCCompletionVerifier
from testlib.configuration import constants


class NoCCompletionVerifierTest(unittest.TestCase):
    def _run_verifier(self, simout, simerr="", verifier=None):
        with tempfile.TemporaryDirectory() as tempdir:
            Path(tempdir, constants.gem5_simulation_stdout).write_text(
                simout, encoding="utf-8"
            )
            Path(tempdir, constants.gem5_simulation_stderr).write_text(
                simerr, encoding="utf-8"
            )
            params = SimpleNamespace(
                fixtures={
                    constants.tempdir_fixture_name: SimpleNamespace(
                        path=tempdir
                    )
                },
                log=SimpleNamespace(message=lambda message: None),
            )
            (verifier or NoCCompletionVerifier()).test(params)

    def test_fails_on_outstanding_reads_at_end(self):
        with self.assertRaisesRegex(
            AssertionError, "outstanding transactions: 3 reads, 0 writes"
        ):
            self._run_verifier(
                """
                Completed Reads: 12
                Monitor: 3 read transactions still outstanding at end.
                """
            )

    def test_fails_on_outstanding_writes_at_end(self):
        with self.assertRaisesRegex(
            AssertionError, "outstanding transactions: 0 reads, 2 writes"
        ):
            self._run_verifier(
                """
                Completed Writes: 8
                Monitor: 2 write transactions still outstanding at end.
                """
            )

    def test_allows_clean_completion_counts(self):
        self._run_verifier(
            """
            Completed Reads: 4
            Completed Writes: 5
            """
        )

    def test_allows_outstanding_writes_only_when_requested(self):
        self._run_verifier(
            """
            Completed Writes: 8
            Monitor: 2 write transactions still outstanding at end.
            """,
            verifier=NoCCompletionVerifier(allow_outstanding_writes=True),
        )

    def test_does_not_allow_outstanding_reads_when_writes_are_allowed(self):
        with self.assertRaisesRegex(
            AssertionError, "outstanding transactions: 1 reads, 2 writes"
        ):
            self._run_verifier(
                """
                Completed Writes: 8
                Monitor: 1 read transaction still outstanding at end.
                Monitor: 2 write transactions still outstanding at end.
                """,
                verifier=NoCCompletionVerifier(allow_outstanding_writes=True),
            )

    def test_failure_marker_reports_intended_error(self):
        with self.assertRaisesRegex(AssertionError, "panic/fatal marker"):
            self._run_verifier("panic: synthetic NoC failure")

    def test_timeout_like_exit_cause_fails(self):
        with self.assertRaisesRegex(AssertionError, "timeout-like exit cause"):
            self._run_verifier(
                "Exiting @ tick 1000 because simulate() limit reached"
            )

    def test_zero_completion_counters_fail(self):
        with self.assertRaisesRegex(AssertionError, "all were zero"):
            self._run_verifier(
                """
                Completed Reads: 0
                Completed Writes: 0
                """
            )

    def test_missing_completion_evidence_fails(self):
        with self.assertRaisesRegex(AssertionError, "no completion evidence"):
            self._run_verifier("Exiting @ tick 10 because m5_exit instruction")

    def test_unexpected_smoke_skip_fails(self):
        with self.assertRaisesRegex(AssertionError, "smoke skip"):
            self._run_verifier("SMOKE_SKIP: missing external RTL")

    def test_allowed_smoke_skip_passes(self):
        self._run_verifier(
            "SMOKE_SKIP: missing external RTL",
            verifier=NoCCompletionVerifier(allow_smoke_skip=True),
        )


if __name__ == "__main__":
    unittest.main()
