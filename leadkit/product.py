"""Products: what each app looks for, loaded from products/<name>/config.py.

A config is plain data (subreddits, searches, score tables, paths) plus, rarely,
a hook function for something data can't say. Everything else is shared, so a
fix to the engine reaches every app at once.
"""
import importlib.util, os
from pathlib import Path

# The code lives here; your data (settings, products, leads, marketing logs) lives
# in DATA, so `git pull` on this repo never touches it. Set LEADKIT_DATA to move it.
HOME = Path(__file__).resolve().parents[1]
DATA = Path(os.path.expanduser(os.environ.get("LEADKIT_DATA") or "~/leadkit-data"))
PRODUCTS = DATA / "products"
SETTINGS = DATA / "settings.py"
SETTINGS_EXAMPLE = HOME / "settings.example.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Your accounts. Until `leads setup` copies the example into DATA, the example's
# placeholders stand in, so the commands still load.
settings = _load("leadkit_settings", SETTINGS if SETTINGS.exists() else SETTINGS_EXAMPLE)


class Product:
    def __init__(self, name):
        self.name = name
        self.dir = PRODUCTS / name
        if not (self.dir / "config.py").exists():
            raise SystemExit(f"no product {name!r}; have: {', '.join(names())}")
        self.cfg = _load(f"leadkit_product_{name}", self.dir / "config.py")

    def __repr__(self):
        return f"Product({self.name!r})"

    def get(self, key, default=None):
        return getattr(self.cfg, key, default)

    def need(self, key):
        if not hasattr(self.cfg, key):
            raise SystemExit(f"{self.name} has no {key} in products/{self.name}/config.py")
        return getattr(self.cfg, key)

    @property
    def title(self):
        return self.get("NAME", self.name)

    @property
    def repo(self):
        return Path(os.path.expanduser(self.need("REPO")))

    @property
    def leads(self):
        return self.dir / self.get("LEADS_DIR", "leads")

    @property
    def reddit_tsv(self):
        return self.leads / "reddit-leads.tsv"

    @property
    def threads_tsv(self):
        return self.leads / "threads-leads.tsv"

    @property
    def x_tsv(self):
        return self.leads / "x-leads.tsv"

    def tsv_for(self, platform):
        return {"Reddit": self.reddit_tsv, "Threads": self.threads_tsv, "X": self.x_tsv}[platform]

    def repo_path(self, rel):
        """A path in the app's own repo (store media, for instance)."""
        return self.repo / rel


def names():
    return sorted(p.parent.name for p in PRODUCTS.glob("*/config.py"))


def everything():
    return [Product(n) for n in names()]


def from_cwd(cwd=None):
    """The product whose repo (or product folder) holds the working directory."""
    here = Path(cwd or os.getcwd()).resolve()
    for p in everything():
        for root in (p.repo, p.dir):
            try:
                here.relative_to(root.resolve())
                return p
            except ValueError:
                continue
    return None


def pick(name=None):
    if name:
        return Product(name)
    p = from_cwd()
    if not p:
        raise SystemExit(f"run inside an app repo or pass --product ({', '.join(names())})")
    return p
