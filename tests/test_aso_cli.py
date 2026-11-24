"""The daily check committing its own ranks."""
import shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso_cli  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class CommitRanksTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        self.ranks = self.repo / "products" / "app" / "aso" / "ranks.tsv"
        self.ranks.parent.mkdir(parents=True)
        self.ranks.write_text("date\tkeyword\n")
        self.other = self.repo / "notes.md"
        self.other.write_text("a\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "start")

    def tearDown(self):
        shutil.rmtree(self.repo)

    def test_commits_only_the_ranks_files(self):
        self.ranks.write_text("date\tkeyword\n2026-11-04\tknitwit\n")
        self.other.write_text("someone else's edit\n")
        git(self.repo, "add", "notes.md")
        aso_cli.commit_ranks(self.repo, [self.ranks], "2026-11-04")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s").strip(), "aso: daily ranks 2026-11-04")
        self.assertEqual(git(self.repo, "show", "--name-only", "--format=", "HEAD").split(),
                         ["products/app/aso/ranks.tsv"])
        self.assertIn("notes.md", git(self.repo, "diff", "--cached", "--name-only"))

    def test_other_jobs_name_their_own_commit(self):
        self.ranks.write_text("changed\n")
        aso_cli.commit_ranks(self.repo, [self.ranks], "2026-11-17", message="threads: daily insights 2026-11-17")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s").strip(), "threads: daily insights 2026-11-17")

    def test_a_new_file_is_committed_too(self):
        new = self.repo / "threads-insights.tsv"
        new.write_text("date\tviews\n")
        aso_cli.commit_ranks(self.repo, [new], "2026-11-16", message="threads: daily insights 2026-11-16")
        self.assertEqual(git(self.repo, "show", "--name-only", "--format=", "HEAD").split(), ["threads-insights.tsv"])

    def test_nothing_to_commit_is_quiet(self):
        aso_cli.commit_ranks(self.repo, [self.ranks], "2026-11-04")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s").strip(), "start")


if __name__ == "__main__":
    unittest.main()
