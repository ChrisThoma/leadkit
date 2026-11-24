"""A product pointed at a temporary leads folder, so tests never touch real TSVs."""
import shutil, tempfile
from datetime import date, timedelta
from pathlib import Path

from leadkit import product, reddit, tsv


class TempProduct:
    def __init__(self, name="knitwit"):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product(name)
        self.p.dir = self.tmp
        self.p.cfg.LEADS_DIR = "leads"
        (self.tmp / "leads").mkdir()

    def write(self, platform, rows, fields=reddit.FIELDS):
        path = self.p.reddit_tsv if platform == "Reddit" else self.p.threads_tsv
        tsv.write(path, fields, [dict.fromkeys(fields, "") | r for r in rows])

    def read(self, platform):
        return tsv.read(self.p.reddit_tsv if platform == "Reddit" else self.p.threads_tsv)[1]

    def close(self):
        shutil.rmtree(self.tmp)


def ago(days):
    return (date.today() - timedelta(days=days)).isoformat()
