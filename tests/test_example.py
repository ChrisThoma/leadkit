"""The example product in examples/ loads and its cases score as they say."""
import importlib.util, unittest
from pathlib import Path

from leadkit import product, reddit

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "products" / "proofer"


class ExampleProductTest(unittest.TestCase):
    def setUp(self):
        self.p = product.Product.__new__(product.Product)
        self.p.name, self.p.dir = "proofer", EXAMPLE
        self.p.cfg = product._load("leadkit_example_proofer", EXAMPLE / "config.py")
        spec = importlib.util.spec_from_file_location("cases_proofer", EXAMPLE / "cases.py")
        self.cases = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cases)

    def test_leads_clear_the_bar(self):
        for title in self.cases.LEADS:
            with self.subTest(title=title):
                self.assertGreaterEqual(reddit.score(self.p, title)[0], self.p.cfg.MIN_SCORE)

    def test_not_leads_stay_under_it(self):
        for title in self.cases.NOT_LEADS:
            with self.subTest(title=title):
                self.assertLess(reddit.score(self.p, title)[0], self.p.cfg.MIN_SCORE)


if __name__ == "__main__":
    unittest.main()
