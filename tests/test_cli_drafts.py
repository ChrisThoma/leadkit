import sys, unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import cli, drafts  # noqa: E402
from helpers import TempProduct  # noqa: E402


class DraftsOpenTest(unittest.TestCase):
    """A draft over the length limit is reported before the page opens, so fixing it
    doesn't mean closing that page and opening a second tab."""

    def setUp(self):
        self.t = TempProduct()
        self.serve = mock.patch.object(drafts, "serve").start()
        mock.patch.object(cli.product, "pick", return_value=self.t.p).start()

    def tearDown(self):
        mock.patch.stopall()
        self.t.close()

    def run_drafts(self, *extra):
        out = StringIO()
        with redirect_stdout(out):
            try:
                cli.main(["drafts", *extra])
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def test_a_threads_reply_over_the_limit_keeps_the_page_closed(self):
        self.t.write("Threads", [{"url": "https://t/long", "author": "a", "reply": "x" * 514, "status": "draft"}])
        code, out = self.run_drafts()
        self.serve.assert_not_called()
        self.assertTrue(code)
        self.assertIn("https://t/long", out)
        self.assertIn("514 characters", out)

    def test_replies_that_fit_open_the_page(self):
        self.t.write("Threads", [{"url": "https://t/ok", "author": "a", "reply": "x" * 500, "status": "draft"}])
        self.t.write("Reddit", [{"url": "https://r/long", "author": "b", "reply": "x" * 900, "status": "draft"}])
        self.run_drafts()
        self.serve.assert_called_once()

    def test_no_open_still_writes_the_file_and_lists_the_problem(self):
        self.t.write("Threads", [{"url": "https://t/long", "author": "a", "reply": "x" * 514, "status": "draft"}])
        with mock.patch.object(drafts, "write_file") as wf:
            code, out = self.run_drafts("--no-open")
        wf.assert_called_once()
        self.assertIn("https://t/long", out)


if __name__ == "__main__":
    unittest.main()
