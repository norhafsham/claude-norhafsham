"""Tests for apply.py, the TOB-STONFI-4 PoC splicer.

The splicer is the only delivery mechanism for the PoC, and the PoC is the evidence
for the one finding STON.fi declined to fix. A splice that lands in the wrong place
does not produce a wrong answer -- it produces a confusing TypeScript error that
looks like the PoC's fault. So most of these tests are about the splicer refusing
to guess.
"""

import re
from pathlib import Path

import pytest

POC_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = POC_DIR.parent.parent
POC_MARKER = "it('POC TOB-STONFI-4"

GOOD_HOST = """\
import { toNano } from '@ton/core';

describe('ConstProduct', () => {
    it('should swap', async () => {
        expect(1).toEqual(1);
    });

    it('should cross-swap on 2 routers', async () => {
        const x = [1, 2].map((n) => {
            return n;
        });
        expect(x).toBeDefined();
    });

    it('should provide liquidity', async () => {
        expect(2).toEqual(2);
    });
});
"""


def make_repo(tmp_path, host_text=GOOD_HOST, newline="\n"):
    repo = tmp_path / "dex-core-v2"
    (repo / "tests").mkdir(parents=True)
    host = repo / "tests" / "ConstProduct.spec.ts"
    with host.open("w", newline="") as fh:
        fh.write(host_text.replace("\n", newline))
    return repo


def line_index(text, needle):
    for i, line in enumerate(text.split("\n")):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found")


# --- the happy path -------------------------------------------------------------


def test_inserts_poc_after_the_anchor_test(apply_mod, tmp_path):
    repo = make_repo(tmp_path)
    apply_mod.main([str(repo)])

    out = (repo / "tests" / "TOB4Poc.spec.ts").read_text()
    assert POC_MARKER in out
    assert line_index(out, "should cross-swap on 2 routers") < line_index(out, POC_MARKER)
    assert line_index(out, POC_MARKER) < line_index(out, "should provide liquidity")


def test_poc_lands_inside_the_describe_block(apply_mod, tmp_path):
    """The regression that motivated the anchor rewrite.

    Spliced after the describe's closing brace, the PoC loses every harness symbol
    it depends on -- while the splicer still reports success.
    """
    repo = make_repo(tmp_path)
    apply_mod.main([str(repo)])

    out = (repo / "tests" / "TOB4Poc.spec.ts").read_text()
    lines = out.rstrip("\n").split("\n")
    describe_close = max(i for i, line in enumerate(lines) if line.rstrip() == "});")
    assert line_index(out, POC_MARKER) < describe_close


def test_host_file_is_left_untouched(apply_mod, tmp_path):
    repo = make_repo(tmp_path)
    before = (repo / "tests" / "ConstProduct.spec.ts").read_text()
    apply_mod.main([str(repo)])
    assert (repo / "tests" / "ConstProduct.spec.ts").read_text() == before


def test_output_preserves_everything_in_the_host(apply_mod, tmp_path):
    repo = make_repo(tmp_path)
    apply_mod.main([str(repo)])
    out = (repo / "tests" / "TOB4Poc.spec.ts").read_text()
    for line in GOOD_HOST.rstrip("\n").split("\n"):
        assert line in out


# --- anchors the splicer must refuse to guess at --------------------------------


@pytest.mark.parametrize(
    "name,host",
    [
        (
            # Matched the comment, derived indent "", then treated the describe's
            # own closing brace as the end of the "test" -- appending the PoC
            # outside the harness scope and exiting 0.
            "mentioned in a top-level comment",
            "// Covers the swaps, including 'should cross-swap on 2 routers'.\n"
            "describe('ConstProduct', () => {\n"
            "    it('should swap', async () => {\n"
            "        expect(1).toEqual(1);\n"
            "    });\n"
            "});\n",
        ),
        (
            "mentioned in a comment inside the describe",
            "describe('ConstProduct', () => {\n"
            "    // see 'should cross-swap on 2 routers' for the multi-hop case\n"
            "    it('should swap', async () => {\n"
            "        expect(1).toEqual(1);\n"
            "    });\n"
            "});\n",
        ),
        (
            "used as a describe title",
            "describe('should cross-swap on 2 routers', () => {\n"
            "    it('should swap', async () => {\n"
            "        expect(1).toEqual(1);\n"
            "    });\n"
            "});\n",
        ),
        (
            "inside a jsdoc block",
            "describe('ConstProduct', () => {\n"
            "    /**\n"
            "     * should cross-swap on 2 routers\n"
            "     */\n"
            "    it('should swap', async () => {\n"
            "        expect(1).toEqual(1);\n"
            "    });\n"
            "});\n",
        ),
    ],
)
def test_rejects_anchor_that_is_not_a_test_declaration(apply_mod, tmp_path, name, host):
    repo = make_repo(tmp_path, host)
    with pytest.raises(SystemExit) as exc:
        apply_mod.main([str(repo)])

    assert "not as an it(...) call" in str(exc.value), name
    assert not (repo / "tests" / "TOB4Poc.spec.ts").exists(), name


def test_rejects_missing_anchor(apply_mod, tmp_path):
    repo = make_repo(tmp_path, GOOD_HOST.replace("cross-swap on 2 routers", "cross swap"))
    with pytest.raises(SystemExit) as exc:
        apply_mod.main([str(repo)])

    assert "anchor test not found" in str(exc.value)
    assert "paste the PoC in by hand" in str(exc.value)


def test_rejects_ambiguous_anchor(apply_mod, tmp_path):
    host = GOOD_HOST.replace("it('should swap'", "it('should cross-swap on 2 routers'")
    repo = make_repo(tmp_path, host)
    with pytest.raises(SystemExit) as exc:
        apply_mod.main([str(repo)])

    assert "ambiguous" in str(exc.value)
    assert not (repo / "tests" / "TOB4Poc.spec.ts").exists()


def test_rejects_unterminated_anchor_test(apply_mod, tmp_path):
    host = (
        "describe('ConstProduct', () => {\n"
        "    it('should cross-swap on 2 routers', async () => {\n"
        "        expect(1).toEqual(1);\n"
    )
    repo = make_repo(tmp_path, host)
    with pytest.raises(SystemExit) as exc:
        apply_mod.main([str(repo)])

    assert "could not find the end of the anchor test" in str(exc.value)


def test_anchor_matches_modifiers_and_double_quotes(apply_mod, tmp_path):
    host = GOOD_HOST.replace(
        "it('should cross-swap on 2 routers'", 'it.only("should cross-swap on 2 routers"'
    )
    repo = make_repo(tmp_path, host)
    apply_mod.main([str(repo)])
    assert POC_MARKER in (repo / "tests" / "TOB4Poc.spec.ts").read_text()


# --- not clobbering things ------------------------------------------------------


def test_refuses_to_overwrite_existing_output(apply_mod, tmp_path):
    repo = make_repo(tmp_path)
    out = repo / "tests" / "TOB4Poc.spec.ts"
    out.write_text("// hand-edited PoC\n")

    with pytest.raises(SystemExit) as exc:
        apply_mod.main([str(repo)])

    assert "already exists" in str(exc.value)
    assert out.read_text() == "// hand-edited PoC\n"


def test_force_overwrites_existing_output(apply_mod, tmp_path):
    repo = make_repo(tmp_path)
    out = repo / "tests" / "TOB4Poc.spec.ts"
    out.write_text("// hand-edited PoC\n")

    apply_mod.main([str(repo), "--force"])
    assert POC_MARKER in out.read_text()


def test_rejects_directory_that_is_not_a_checkout(apply_mod, tmp_path):
    with pytest.raises(SystemExit) as exc:
        apply_mod.main([str(tmp_path)])
    assert "is that a dex-core-v2 checkout" in str(exc.value)


# --- formatting fidelity --------------------------------------------------------


def test_preserves_crlf_line_endings(apply_mod, tmp_path):
    repo = make_repo(tmp_path, newline="\r\n")
    apply_mod.main([str(repo)])

    raw = (repo / "tests" / "TOB4Poc.spec.ts").read_bytes()
    assert b"\r\n" in raw
    assert re.search(rb"[^\r]\n", raw) is None, "mixed line endings in output"


def test_preserves_lf_line_endings(apply_mod, tmp_path):
    repo = make_repo(tmp_path)
    apply_mod.main([str(repo)])
    assert b"\r" not in (repo / "tests" / "TOB4Poc.spec.ts").read_bytes()


def test_poc_block_strips_the_explanatory_header(apply_mod):
    block = apply_mod.poc_block()
    assert not block.lstrip().startswith("/**")
    assert "Observed output:" not in block
    assert block.lstrip().startswith("it('POC TOB-STONFI-4")


# --- the harness dependency list must not drift ---------------------------------
# harness.d.ts is the canonical list: it is what CI type-checks the PoC against.
# The prose in the PoC header and in the write-up has to agree with it.


def declared_harness_symbols():
    text = (POC_DIR / "harness.d.ts").read_text()
    borrowed = text.split("--- ambient globals")[0]
    return set(re.findall(r"declare (?:const|function) (\w+)", borrowed))


def test_harness_declarations_match_the_poc_header():
    header = (POC_DIR / "tob-stonfi-4.spec.ts").read_text()
    segment = header.split("Required identifiers:")[1].split("(declared in harness.d.ts")[0]
    listed = set(re.findall(r"[A-Za-z_]\w*", segment))
    assert listed == declared_harness_symbols()


def test_harness_declarations_match_the_writeup():
    md = (REPO_ROOT / "security" / "stonfi-dex-v2-fix-verification.md").read_text()
    segment = md.split("harness defined inside the `describe` block of the project's pool")[1]
    segment = segment.split("so it is spliced")[0]
    listed = set(re.findall(r"`(\w+)`", segment))
    assert listed == declared_harness_symbols()


def test_every_declared_symbol_is_actually_used_by_the_poc():
    body = (POC_DIR / "tob-stonfi-4.spec.ts").read_text().split("*/", 1)[1]
    used = set(re.findall(r"[A-Za-z_]\w*", body))
    unused = declared_harness_symbols() - used
    assert not unused, f"harness.d.ts declares unused symbols: {sorted(unused)}"
