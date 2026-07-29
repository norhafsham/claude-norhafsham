#!/usr/bin/env python3
"""Compare STON.fi's deployed v2.2 routers against a local build of dex-core-v2.

Deployed routers do not store their code inline. Each account's code is a 46-byte
*library reference cell* -- an exotic cell (d1 bit 0x08) of type 0x02 whose payload
is the 32-byte hash of the real code in the masterchain library collection. So the
`code_hash` an explorer or API reports is the hash of the wrapper, not of the code:
comparing it against a local build always mismatches. The value to compare is the
library hash carried inside that cell.

    BoC layout of a deployed router's code cell (46 bytes)
    ┌────────────┬──────────┬──────┬────┬──────┬──────┬────────────────────────┐
    │ b5ee9c72   │ 01010101 │ 0023 │ 00 │ d108 │ d242 │ 02 + 32-byte lib hash  │
    │ magic      │ flags    │ len  │    │ exotic, 33B  │ type 0x02 = library   │
    └────────────┴──────────┴──────┴────┴──────┴──────┴────────────────────────┘

The same applies to the pool, lp_wallet, lp_account and vault code the router keeps
in its storage, which is what it stamps into every pool it deploys. Those live in
the `_static` ref of the router's data cell (see contracts/router/storage.fc) and are
library cells too, so both halves of the deployment are checked here.

Usage:
    ./hashes.ts must have been run in the checkout first (see that file).
    ./verify.py /path/to/dex-core-v2
"""

import base64
import collections
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import boc

ROUTERS_API = "https://api.ston.fi/v1/routers"
TONCENTER = "https://toncenter.com/api/v3/accountStates"
TARGET_VERSION = (2, 2)

# Order of the code refs inside the router's `_static` cell, per router/storage.fc.
# Names match the keys hashes.ts writes into build/local_hashes.json.
STATIC_CODE_ORDER = ["LPWallet", "Pool", "LPAccount", "Vault"]

# api.ston.fi router_type -> dex-core-v2 POOL_TYPES name
TYPE_MAP = {
    "ConstantProduct": "constant_product",
    "StableSwap": "stableswap",
    "WeightedConstProduct": "weighted_const_product",
    "WeightedStableSwap": "weighted_stableswap",
    "ConstantSum": "constant_sum",
}


def fetch(url: str) -> dict:
    """GET via curl -- honours the environment's proxy config where urllib does not."""
    r = subprocess.run(
        ["curl", "-sS", "--max-time", "60", "-H", "accept: application/json", url],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise SystemExit(f"curl failed for {url}: {r.stderr.strip()}")
    return json.loads(r.stdout)


def fetch_states(addresses: list[str], attempts: int = 4) -> tuple[dict, dict]:
    """One batch, retried with backoff until every address comes back with its code.

    toncenter throttles unauthenticated callers by silently returning a short
    account list. Treating a missing entry as 'no code' would mislabel a healthy
    router, so an incomplete batch is retried and then raised.
    """
    q = "&".join("address=" + urllib.parse.quote(a) for a in addresses)
    for attempt in range(attempts):
        d = fetch(f"{TONCENTER}?{q}&include_boc=true")
        states = {st["address"]: st for st in d.get("accounts", [])}
        book = d.get("address_book", {})
        raw_of = {v["user_friendly"]: k for k, v in book.items()}
        missing = [
            a
            for a in addresses
            if not all(
                (states.get(raw_of.get(a, ""), {}) or {}).get(k) for k in ("code_boc", "data_boc")
            )
        ]
        if not missing:
            return states, book
        time.sleep(2**attempt)
    raise SystemExit(
        f"toncenter returned incomplete state for {len(missing)} address(es) after "
        f"{attempts} attempts (e.g. {missing[0]}). Rerun, or set a TONCENTER API key — "
        f"do not read a missing response as a code difference."
    )


def library_hash(code_b64: str) -> str | None:
    """The 32-byte library hash inside a code cell, or None if the code is inline."""
    return boc.from_base64(code_b64).library_hash()


def storage_code_hashes(data_b64: str) -> dict[str, str | None]:
    """Library hashes of the four contract codes the router stamps into its pools.

    Router data is `is_locked:bool admin:MsgAddress temp_upgrade:^Cell _static:^Cell
    upgrade_pool_code:^Cell`, and `_static` holds the code refs in STATIC_CODE_ORDER.
    """
    static = boc.from_base64(data_b64).refs[1]
    return {
        name: cell.library_hash() for name, cell in zip(STATIC_CODE_ORDER, static.refs, strict=True)
    }


def deployed_routers() -> list[dict]:
    d = fetch(ROUTERS_API)
    rs = d.get("router_list", d if isinstance(d, list) else [])
    return [r for r in rs if (r["major_version"], r["minor_version"]) == TARGET_VERSION]


def account_states(addresses: list[str], batch: int = 4) -> dict:
    """address (user-friendly) -> account state, every one carrying its code."""
    states, book = {}, {}
    for i in range(0, len(addresses), batch):
        s, b = fetch_states(addresses[i : i + batch])
        states.update(s)
        book.update(b)
    raw_of = {v["user_friendly"]: k for k, v in book.items()}
    return {a: states.get(raw_of.get(a), {}) for a in addresses}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} /path/to/dex-core-v2")
    hashes_file = Path(sys.argv[1]) / "build" / "local_hashes.json"
    if not hashes_file.is_file():
        raise SystemExit(f"{hashes_file} not found — run helpers/hashes.ts in the checkout first")
    local = json.loads(hashes_file.read_text())
    want = {base64.b64decode(v["Router"]).hex(): k for k, v in local.items()}

    routers = deployed_routers()
    states = account_states([r["address"] for r in routers])

    rows = []
    for r in routers:
        st = states[r["address"]]
        rows.append(
            {
                "address": r["address"],
                "type": r["router_type"],
                "creation_enabled": r["pool_creation_enabled"],
                "lib_hash": library_hash(st["code_boc"]),
                "storage": storage_code_hashes(st["data_boc"]),
            }
        )

    print("local Router code-cell hashes:")
    for name, h in local.items():
        print(f"  {name:22} {base64.b64decode(h['Router']).hex()}")
    print()

    grouped = collections.defaultdict(list)
    for x in rows:
        grouped[(x["type"], x["lib_hash"])].append(x)

    match = differ = 0
    for (rtype, lib), group in sorted(grouped.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        ok = want.get(lib) == TYPE_MAP.get(rtype)
        match, differ = (match + len(group), differ) if ok else (match, differ + len(group))
        live = sum(1 for g in group if g["creation_enabled"])
        label = "MATCH  " if ok else "differs"
        short = (lib or "inline code")[:16]
        print(
            f"{label}  {rtype:22} x{len(group):<3} {short}…  "
            f"({live} accepting new pools)  {group[0]['address']}"
        )

    total = match + differ
    live_ok = sum(
        1
        for x in rows
        if x["creation_enabled"] and want.get(x["lib_hash"]) == TYPE_MAP.get(x["type"])
    )
    live_all = sum(1 for x in rows if x["creation_enabled"])
    print(
        f"\n{match}/{total} deployed v{TARGET_VERSION[0]}.{TARGET_VERSION[1]} routers "
        f"run exactly this source; {differ} differ."
    )
    print(f"{live_ok}/{live_all} routers still accepting new pools run exactly this source.")

    # --- the code each router stamps into the pools it deploys ---
    print("\npool / lp_wallet / lp_account / vault code held in router storage:")
    buckets = collections.defaultdict(list)
    for x in rows:
        expected = local.get(TYPE_MAP.get(x["type"]), {})
        verdict = tuple(
            (name, x["storage"][name] == base64.b64decode(expected[name]).hex())
            if name in expected
            else (name, False)
            for name in STATIC_CODE_ORDER
        )
        router_ok = want.get(x["lib_hash"]) == TYPE_MAP.get(x["type"])
        buckets[(x["type"], router_ok, verdict)].append(x)

    for (rtype, router_ok, verdict), group in sorted(
        buckets.items(), key=lambda kv: (kv[0][0], -len(kv[1]))
    ):
        good = [n for n, ok in verdict if ok]
        bad = [n for n, ok in verdict if not ok]
        state = "all 4 match" if not bad else f"matches {good or '-'}, differs {bad}"
        print(
            f"  {rtype:22} x{len(group):<3} router {'matches' if router_ok else 'differs':7}  "
            f"→ {state}"
        )

    full = sum(
        1
        for x in rows
        if want.get(x["lib_hash"]) == TYPE_MAP.get(x["type"])
        and all(
            x["storage"][n] == base64.b64decode(local[TYPE_MAP[x["type"]]][n]).hex()
            for n in STATIC_CODE_ORDER
        )
    )
    print(f"\n{full}/{total} routers match this source on the router *and* all four stamped codes.")


if __name__ == "__main__":
    main()
