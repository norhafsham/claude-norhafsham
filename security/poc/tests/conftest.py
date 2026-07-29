"""Shared fixtures. `apply.py` is a script, not a package member, so it is loaded by path."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

POC_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = POC_DIR.parent.parent


def _load_apply():
    spec = importlib.util.spec_from_file_location("apply", POC_DIR / "apply.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["apply"] = module
    spec.loader.exec_module(module)
    return module


apply = _load_apply()


def declared_harness_symbols() -> set[str]:
    """The identifiers harness.d.ts says the host spec must provide.

    This is the canonical list: it is what CI type-checks the PoC against. The
    trailing `--- ambient globals` section declares jest/console stubs, which the
    host spec does not supply, so it is excluded.
    """
    text = (POC_DIR / "harness.d.ts").read_text()
    borrowed = text.split("--- ambient globals")[0]
    return set(re.findall(r"declare (?:const|function) (\w+)", borrowed))


@pytest.fixture
def apply_mod():
    return apply


@pytest.fixture
def harness_symbols():
    return declared_harness_symbols()
