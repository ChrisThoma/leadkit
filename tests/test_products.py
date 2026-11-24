"""Every product's examples against its own score tables.

Each product keeps its cases in products/<name>/cases.py, so a change to the
shared engine is checked against every app, not just the one being worked on.

    bin/test
"""
import importlib.util, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import product, reddit  # noqa: E402


def cases(p):
    path = p.dir / "cases.py"
    spec = importlib.util.spec_from_file_location(f"cases_{p.name}", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class ProductCases(unittest.TestCase):
    def test_every_product_has_cases(self):
        for p in product.everything():
            with self.subTest(product=p.name):
                self.assertTrue((p.dir / "cases.py").exists())

    def test_leads_clear_the_bar(self):
        for p in product.everything():
            for title in cases(p).LEADS:
                with self.subTest(product=p.name, title=title):
                    self.assertGreaterEqual(reddit.score(p, title)[0], p.cfg.MIN_SCORE)

    def test_not_leads_stay_under_it(self):
        for p in product.everything():
            for title in cases(p).NOT_LEADS:
                with self.subTest(product=p.name, title=title):
                    self.assertLess(reddit.score(p, title)[0], p.cfg.MIN_SCORE)

    def test_excluded_subs(self):
        for p in product.everything():
            c = cases(p)
            for sub in getattr(c, "EXCLUDED", []):
                with self.subTest(product=p.name, sub=sub):
                    self.assertFalse(reddit.allowed(p, sub))
            for sub in getattr(c, "ALLOWED", []):
                self.assertTrue(reddit.allowed(p, sub))
