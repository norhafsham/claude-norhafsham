#!/usr/bin/env python3
"""Splice the TOB-STONFI-4 PoC into a checkout of ston-fi/dex-core-v2.

The PoC depends on the test harness defined inside the `describe` block of the
project's pool specs, so it cannot live as a standalone file. This copies
tests/ConstProduct.spec.ts to tests/TOB4Poc.spec.ts with the PoC appended after
the repo's own `should cross-swap on 2 routers` test.

    ./apply.py /path/to/dex-core-v2
    cd /path/to/dex-core-v2 && npx jest tests/TOB4Poc.spec.ts -t "POC TOB-STONFI-4"
"""

import re
import sys
from pathlib import Path

POC = Path(__file__).with_name("tob-stonfi-4.spec.ts")
HOST = "tests/ConstProduct.spec.ts"
OUT = "tests/TOB4Poc.spec.ts"


def poc_block() -> str:
    """The PoC file minus its leading /** ... */ explanatory header."""
    text = POC.read_text()
    end = text.index("*/") + 2
    return text[end:].strip("\n")


def find_insert_line(lines: list[str]) -> int:
    """Index just past the `should cross-swap on 2 routers` test's closing `});`."""
    start = next(
        (i for i, l in enumerate(lines) if "should cross-swap on 2 routers" in l), None
    )
    if start is None:
        raise SystemExit(
            f"anchor test not found in {HOST}; the upstream spec has changed — "
            "paste the PoC in by hand"
        )
    indent = re.match(r"\s*", lines[start]).group(0)
    closing = f"{indent}}});"
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip() == closing.rstrip():
            return i + 1
    raise SystemExit(f"could not find the end of the anchor test in {HOST}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} /path/to/dex-core-v2")
    repo = Path(sys.argv[1])
    host = repo / HOST
    if not host.is_file():
        raise SystemExit(f"{host} not found — is that a dex-core-v2 checkout?")

    lines = host.read_text().split("\n")
    at = find_insert_line(lines)
    merged = lines[:at] + ["", poc_block()] + lines[at:]
    (repo / OUT).write_text("\n".join(merged))

    print(f"wrote {repo / OUT} (PoC inserted after line {at})")
    print(f'next: cd {repo} && npx jest {OUT} -t "POC TOB-STONFI-4"')


if __name__ == "__main__":
    main()
