"""Battery cell should-cost tracker: chemistry -> bill of materials -> monthly cost from market prices."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "assumptions"


def load(name):
    return yaml.safe_load((ASSUMPTIONS / f"{name}.yaml").read_text())
