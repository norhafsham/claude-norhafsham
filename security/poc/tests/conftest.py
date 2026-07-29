"""Make `apply.py` importable; it is a script, not a package member."""

import importlib.util
import sys
from pathlib import Path

import pytest

POC_DIR = Path(__file__).resolve().parent.parent


def _load_apply():
    spec = importlib.util.spec_from_file_location("apply", POC_DIR / "apply.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["apply"] = module
    spec.loader.exec_module(module)
    return module


apply = _load_apply()


@pytest.fixture
def apply_mod():
    return apply
