import os, sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import looking  # noqa: E402
from helpers import TempProduct  # noqa: E402


class LookingTest(unittest.TestCase):
    """What the drafts page's "still looking" line reads, so a slow source doesn't
    hold the page back without a word."""

    def setUp(self):
        self.t = TempProduct()

    def tearDown(self):
        self.t.close()

    def test_nothing_looking_by_default(self):
        self.assertEqual(looking.current([self.t.p]), [])

    def test_a_running_process_is_looking_until_it_stops(self):
        looking.start(self.t.p, "reddit", "Reddit watcher", pid=os.getpid())
        self.assertEqual(looking.current([self.t.p]), ["Reddit watcher"])
        looking.stop(self.t.p, "reddit")
        self.assertEqual(looking.current([self.t.p]), [])

    def test_a_dead_process_is_not_looking(self):
        looking.start(self.t.p, "reddit", "Reddit watcher", pid=2 ** 22 + 7)
        self.assertEqual(looking.current([self.t.p]), [])

    def test_a_session_note_expires(self):
        looking.start(self.t.p, "session", "Reading r/knitting threads", ttl=0.2)
        self.assertEqual(looking.current([self.t.p]), ["Reading r/knitting threads"])
        time.sleep(0.3)
        self.assertEqual(looking.current([self.t.p]), [])

    def test_a_second_note_replaces_the_first(self):
        looking.start(self.t.p, "session", "Triage")
        looking.start(self.t.p, "session", "Drafting replies")
        self.assertEqual(looking.current([self.t.p]), ["Drafting replies"])

    def test_a_broken_file_is_nothing_looking(self):
        looking.path(self.t.p).write_text("{not json")
        self.assertEqual(looking.current([self.t.p]), [])

    def test_titles_name_the_app_when_the_page_has_several(self):
        looking.start(self.t.p, "reddit", "Reddit watcher", pid=os.getpid())
        self.assertEqual(looking.current([self.t.p, self.t.p], titled=True),
                         [f"{self.t.p.title}: Reddit watcher"] * 2)


class LookingCliTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from leadkit import cli
        self.t = TempProduct()
        self.cli = cli
        self.pick = mock.patch.object(cli.product, "pick", return_value=self.t.p)
        self.pick.start()

    def tearDown(self):
        self.pick.stop()
        self.t.close()

    def test_say_then_done(self):
        self.cli.main(["looking", "Reading r/knitting threads"])
        self.assertEqual(looking.current([self.t.p]), ["Reading r/knitting threads"])
        self.cli.main(["looking", "--done"])
        self.assertEqual(looking.current([self.t.p]), [])

    def test_the_watcher_is_looking_while_it_runs_and_not_after(self):
        from unittest import mock
        seen = []
        with mock.patch.object(self.cli.reddit, "watch", lambda p, **k: seen.append(looking.current([p]))):
            self.cli.main(["reddit"])
        self.assertEqual(seen, [["Reddit watcher"]])
        self.assertEqual(looking.current([self.t.p]), [])


if __name__ == "__main__":
    unittest.main()
