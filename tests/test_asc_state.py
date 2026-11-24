"""aso export --asc stops when App Store Connect won't take new languages on the version.

A version already submitted for review takes no new localizations: exporting dozens of
languages to it would only collect one refusal per creation.
"""
import json, subprocess, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import asc_state  # noqa: E402


def runner(versions, code=0):
    body = json.dumps({"data": [{"attributes": {"versionString": v, "platform": "IOS",
                                                 "appVersionState": s, "appStoreState": s}}
                                for v, s in versions]})
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, code, body if code == 0 else "", "boom" if code else "")
    return run


class VersionProblemTest(unittest.TestCase):
    def test_submitted_version_is_a_problem(self):
        msg = asc_state.version_problem(1, "1.0.1", run=runner([("1.0.1", "WAITING_FOR_REVIEW")]))
        self.assertIn("WAITING_FOR_REVIEW", msg)

    def test_editable_version_passes(self):
        for state in ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED"):
            self.assertIsNone(asc_state.version_problem(1, "1.0.2", run=runner([("1.0.2", state)])))

    def test_missing_version_is_a_problem(self):
        msg = asc_state.version_problem(1, "1.0.2", run=runner([("1.0.1", "WAITING_FOR_REVIEW")]))
        self.assertIn("no 1.0.2", msg)

    def test_asc_failure_is_reported_not_raised(self):
        msg = asc_state.version_problem(1, "1.0.2", run=runner([], code=1))
        self.assertIn("couldn't read", msg)


if __name__ == "__main__":
    unittest.main()
