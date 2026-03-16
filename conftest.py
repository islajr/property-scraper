"""
Root conftest.py — makes the project root importable when running pytest
from any working directory.

Without this, `from scraper.models import ...` fails because pytest's test
discovery doesn't automatically add the project root to sys.path.
"""
import sys
from pathlib import Path

# Insert the project root at the front of sys.path so that `scraper` and
# `config` are importable regardless of where pytest is invoked from.
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))