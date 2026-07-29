"""Contract tests against the pinned upstream spec the PoC is spliced into.

Everything in the PoC's environment -- the anchor test's name, the harness symbols,
the file path -- is an assumption about ston-fi/dex-core-v2 that lives in prose
today. When upstream changes, the current failure mode is that the next person to
try to reproduce the finding gets a confusing error, months later.

These tests fetch the pinned revision and check those assumptions directly, so drift
shows up as a red build. They are marked `network` and deselected by default; CI runs
them in a dedicated job (see .github/workflows/ci.yml).

A hash mismatch is not automatically a bug -- it means the verification write-up was
done against a file that no longer matches, and the finding needs re-checking against
whatever upstream looks like now.
"""

import hashlib
import re
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.network

UPSTREAM = "ston-fi/dex-core-v2"
COMMIT = "af0a955cc835af9697cd383e201fefcbe1a6a87e"
HOST_PATH = "tests/ConstProduct.spec.ts"
RAW = f"https://raw.githubusercontent.com/{UPSTREAM}/{COMMIT}/{HOST_PATH}"

# sha256 of tests/ConstProduct.spec.ts @ af0a955, the revision the write-up and the
# PoC's recorded balances were produced against.
EXPECTED_SHA256 = "e4d2cfca2942b77c4619c48e68e9e731f51550153496faaa980381fa6bcf5d97"

# The write-up calls this out as the coverage gap that would have caught TOB-STONFI-4:
# the cross-router helper threads a mid-hop forward-gas parameter that no test sets.
FWD_GAS_KNOB = "fwdGas2"


@pytest.fixture(scope="module")
def host_spec():
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(RAW, timeout=60) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            last = exc
    pytest.skip(f"could not fetch {RAW}: {last}")


def test_pinned_host_spec_is_unchanged(host_spec):
    actual = hashlib.sha256(host_spec.encode("utf-8")).hexdigest()
    assert actual == EXPECTED_SHA256, (
        f"{HOST_PATH} at {COMMIT[:7]} no longer hashes to the pinned value. "
        "Re-verify the finding and the PoC's recorded balances against the new content."
    )


def test_anchor_resolves_to_exactly_one_test(apply_mod, host_spec):
    lines = host_spec.split("\n")
    index = apply_mod.find_anchor_line(lines)
    assert apply_mod.TEST_CALL_RE.match(lines[index])
    assert apply_mod.ANCHOR in lines[index]


def test_anchor_is_not_confused_by_the_neighbouring_refund_tests(apply_mod, host_spec):
    """Upstream has `should refund cross-swap on 2 routers (in)` and `(mid)` nearby.

    They share most of the anchor string; the splicer must not match them.
    """
    mentions = [line for line in host_spec.split("\n") if "cross-swap on 2 routers" in line]
    exact = [line for line in mentions if apply_mod.ANCHOR in line]
    assert len(mentions) > len(exact), "expected the refund variants to exist upstream"
    assert len(exact) == 1


def test_host_spec_provides_every_harness_symbol(harness_symbols, host_spec):
    """Each identifier harness.d.ts declares must be reachable in the splice target.

    They arrive three different ways -- module-scope const, import, describe-scope
    binding -- so this only checks the name is bound somewhere in the file.
    """
    missing = [
        symbol
        for symbol in sorted(harness_symbols)
        if not re.search(rf"\b{re.escape(symbol)}\b", host_spec)
    ]
    assert not missing, f"{HOST_PATH} no longer provides: {missing}"


def test_apply_splices_cleanly_into_the_real_spec(apply_mod, tmp_path):
    """End-to-end against upstream's actual 2000-line spec, not a fixture."""
    repo = tmp_path / "dex-core-v2"
    (repo / "tests").mkdir(parents=True)
    with urllib.request.urlopen(RAW, timeout=60) as response:
        (repo / HOST_PATH).write_bytes(response.read())

    apply_mod.main([str(repo)])

    out = (repo / "tests" / "TOB4Poc.spec.ts").read_text().split("\n")
    poc = next(i for i, line in enumerate(out) if "POC TOB-STONFI-4" in line)
    describe_close = max(i for i, line in enumerate(out) if line.rstrip() == "});")
    assert poc < describe_close, "PoC landed outside the describe block"


def test_forward_gas_knob_is_still_never_exercised(host_spec):
    """The gap that lets TOB-STONFI-4 sit uncovered upstream.

    `fwdGas2` exists on the cross-router helper and is threaded into the mid-hop
    payload, but no test ever passes it -- so every cross-router test runs the 1 TON
    default and the lossy path is never taken. If this starts failing, upstream has
    added coverage and the write-up's claim needs updating.
    """
    uses = [line.strip() for line in host_spec.split("\n") if FWD_GAS_KNOB in line]
    assert len(uses) == 2, f"expected only a declaration and a use, got {uses}"
    assert any(u.startswith(f"{FWD_GAS_KNOB}?:") for u in uses), "declaration gone"
    assert any(f"params.{FWD_GAS_KNOB} ??" in u for u in uses), "no longer threaded"
