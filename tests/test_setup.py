"""setup's checks, without touching ~/.local/bin, launchd or the real products.

    bin/test
"""
import plistlib, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso, product, reddit, setup  # noqa: E402


class LinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "leads"
        self.src.write_text("#!/bin/sh\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_states(self):
        dest = self.tmp / "bin" / "leads"
        self.assertEqual(setup.link_state(self.src, dest), "missing")
        setup.make_link(self.src, dest)
        self.assertEqual(setup.link_state(self.src, dest), "ok")
        other = self.tmp / "other"
        other.write_text("")
        dest.unlink()
        dest.symlink_to(other)
        self.assertEqual(setup.link_state(self.src, dest), "other")


class DailyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.plist = self.tmp / "job.plist"
        self.python = sys.executable

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_states(self):
        self.assertEqual(setup.daily_state(self.plist, product.HOME, self.python), ("missing", None))
        self.plist.write_bytes(aso.plist(8, 30, product.HOME, self.python, self.tmp / "log"))
        self.assertEqual(setup.daily_state(self.plist, product.HOME, self.python), ("ok", "08:30"))
        self.plist.write_bytes(aso.plist(8, 30, self.tmp / "old-checkout", self.python, self.tmp / "log"))
        self.assertEqual(setup.daily_state(self.plist, product.HOME, self.python)[0], "stale")
        self.plist.write_bytes(aso.plist(8, 30, product.HOME, str(self.tmp / "gone/python3"), self.tmp / "log"))
        self.assertEqual(setup.daily_state(self.plist, product.HOME, self.python)[0], "stale")


class NewProductTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.was = product.PRODUCTS
        product.PRODUCTS = self.tmp / "products"
        self.repo = self.tmp / "coin-app"
        self.repo.mkdir()

    def tearDown(self):
        product.PRODUCTS = self.was
        shutil.rmtree(self.tmp)

    def test_scaffold_loads_and_scores(self):
        setup.scaffold("coin", "Coin Flip", str(self.repo), None)
        p = product.Product("coin")
        self.assertEqual(p.title, "Coin Flip")
        self.assertTrue(p.leads.is_dir())
        self.assertTrue((p.dir / "cases.py").exists())
        self.assertEqual(reddit.score(p, "anything at all")[0], 0)
        self.assertIsNone(p.get("APP_STORE_ID"))
        self.assertEqual(p.get("THREADS_SEARCHES"), {"keywords": [("coin flip", "&filter=recent", False)]})

    def test_scaffold_with_an_app_store_id(self):
        setup.scaffold("coin", "Coin Flip", str(self.repo), 123456)
        self.assertEqual(product.Product("coin").get("APP_STORE_ID"), 123456)
        text = "\n".join(s.text for s in setup.product_steps(product.Product("coin")))
        self.assertIn("until ASO_KEYWORDS", text)

    def test_scaffold_refuses_an_existing_product(self):
        setup.scaffold("coin", "Coin Flip", str(self.repo), None)
        with self.assertRaises(SystemExit):
            setup.scaffold("coin", "Coin Flip", str(self.repo), None)

    def test_a_new_product_says_what_it_still_needs(self):
        setup.scaffold("coin", "Coin Flip", str(self.repo), None)
        text = "\n".join(s.text for s in setup.product_steps(product.Product("coin")))
        self.assertIn("SUBREDDITS", text)
        self.assertIn("aso is off", text)

    def test_a_missing_leads_folder_can_be_made(self):
        setup.scaffold("coin", "Coin Flip", str(self.repo), None)
        p = product.Product("coin")
        p.leads.rmdir()
        fixes = [s for s in setup.product_steps(p) if s.fix]
        self.assertEqual(len(fixes), 1)
        fixes[0].fix()
        self.assertTrue(p.leads.is_dir())

    def test_aso_on_points_at_the_next_aso_step(self):
        setup.scaffold("coin", "Coin Flip", str(self.repo), 123456)
        p = product.Product("coin")
        p.cfg.ASO_KEYWORDS = ["coin flipper"]
        text = "\n".join(s.text for s in setup.product_steps(p))
        self.assertIn("aso check -p coin", text)
        self.assertIn("aso locales -p coin", text)


if __name__ == "__main__":
    unittest.main()
