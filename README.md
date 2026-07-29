# Claude-Norhafsham

Security research notes and proof-of-concept artifacts.

- [`security/stonfi-dex-v2-fix-verification.md`](security/stonfi-dex-v2-fix-verification.md) —
  independent verification of the Trail of Bits STON.fi TON AMM DEX V2 findings.
- [`security/poc/`](security/poc/) — the TOB-STONFI-4 proof of concept, plus the
  splicer that inserts it into a `ston-fi/dex-core-v2` checkout.

## Checks

CI (`.github/workflows/ci.yml`) runs both of these on every push and pull request.

```sh
# apply.py: lint, format, unit tests
pip install pytest ruff
ruff check . && ruff format --check . && pytest

# the PoC fragment: type-checked against security/poc/harness.d.ts
npm ci --prefix security/poc
npm run typecheck --prefix security/poc

# contract tests against the pinned ston-fi/dex-core-v2 revision (needs network;
# deselected by default). Fails if upstream drifts from what the write-up verified.
pytest -m network
```

The PoC cannot be executed here — it is a fragment that borrows its harness from the
upstream spec it gets spliced into. `harness.d.ts` declares the identifiers that
harness must supply, so the fragment is at least parsed and type-checked on every
change instead of only when someone clones `dex-core-v2` and runs the full suite.
