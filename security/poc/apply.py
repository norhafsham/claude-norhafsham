#!/usr/bin/env python3
"""Splice the TOB-STONFI-4 PoC into a checkout of ston-fi/dex-core-v2.

The PoC depends on the test harness defined inside the `describe` block of the
project's pool specs, so it cannot live as a standalone file. This copies
tests/ConstProduct.spec.ts to tests/TOB4Poc.spec.ts with the PoC appended after
the repo's own `should cross-swap on 2 routers` test.

    ./apply.py /path/to/dex-core-v2
    cd /path/to/dex-core-v2 && npx jest tests/TOB4Poc.spec.ts -t "POC TOB-STONFI-4"

Verified against dex-core-v2 @ af0a955. The anchor test must still exist, and must
still be a single `it(...)` call; if upstream has moved on, this exits with a
message rather than guessing.
"""

import argparse
import re
import sys
from pathlib import Path

POC = Path(__file__).with_name("tob-stonfi-4.spec.ts")
HOST = "tests/ConstProduct.spec.ts"
OUT = "tests/TOB4Poc.spec.ts"
ANCHOR = "should cross-swap on 2 routers"

# The anchor has to be the test declaration itself. Matching the bare string
# anywhere would also match a comment or a `describe` title, and the indentation
# of such a line sends the closing-brace search off to the end of an unrelated
# block -- which used to splice the PoC outside the `describe` silently.
TEST_CALL_RE = re.compile(r"^\s*(?:it|test)(?:\.\w+)*\s*\(")
COMMENT_RE = re.compile(r"^\s*(?://|/\*|\*)")


def poc_block() -> str:
    """The PoC file minus its leading /** ... */ explanatory header."""
    text = POC.read_text()
    marker = text.find("*/")
    if marker == -1:
        raise SystemExit(f"{POC} has no /** ... */ header to strip")
    return text[marker + 2 :].strip("\n")


def find_anchor_line(lines: list[str]) -> int:
    """Index of the `it('...should cross-swap on 2 routers...')` declaration."""
    hits = [
        i
        for i, line in enumerate(lines)
        if ANCHOR in line and TEST_CALL_RE.match(line) and not COMMENT_RE.match(line)
    ]
    if len(hits) == 1:
        return hits[0]

    if not hits:
        mentions = [i + 1 for i, line in enumerate(lines) if ANCHOR in line]
        detail = (
            f"; {ANCHOR!r} appears on line(s) {mentions} but not as an it(...) call"
            if mentions
            else ""
        )
        raise SystemExit(
            f"anchor test not found in {HOST}{detail} -- the upstream spec has "
            "changed; paste the PoC in by hand"
        )

    raise SystemExit(
        f"anchor test is ambiguous in {HOST}: {len(hits)} it(...) calls match "
        f"{ANCHOR!r} on lines {[i + 1 for i in hits]} -- paste the PoC in by hand"
    )


def find_insert_line(lines: list[str]) -> int:
    """Index just past the anchor test's closing `});`."""
    start = find_anchor_line(lines)
    indent = re.match(r"\s*", lines[start]).group(0)
    closing = f"{indent}}});".rstrip()
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip() == closing:
            return i + 1
    raise SystemExit(
        f"could not find the end of the anchor test in {HOST} (no {closing!r} "
        f"after line {start + 1})"
    )


def splice(text: str, block: str) -> str:
    """Insert `block` after the anchor test, preserving the host's line endings."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split("\n")
    at = find_insert_line(lines)
    inserted = ["", block] if newline == "\n" else ["\r", block.replace("\n", "\r\n") + "\r"]
    return "\n".join(lines[:at] + inserted + lines[at:])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", type=Path, help="path to a dex-core-v2 checkout")
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"overwrite an existing {OUT} (refuses by default)",
    )
    args = parser.parse_args(argv)

    host = args.repo / HOST
    out = args.repo / OUT
    if not host.is_file():
        raise SystemExit(f"{host} not found -- is that a dex-core-v2 checkout?")
    if out.exists() and not args.force:
        raise SystemExit(f"{out} already exists; pass --force to overwrite it")

    with host.open(newline="") as fh:
        text = fh.read()
    merged = splice(text, poc_block())
    with out.open("w", newline="") as fh:
        fh.write(merged)

    print(f"wrote {out}")
    print(f'next: cd {args.repo} && npx jest {OUT} -t "POC TOB-STONFI-4"')


if __name__ == "__main__":
    main(sys.argv[1:])
