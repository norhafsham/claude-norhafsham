# Claude-Norhafsham

Security research notes and proof-of-concept artifacts.

- [`security/stonfi-dex-v2-fix-verification.md`](security/stonfi-dex-v2-fix-verification.md) —
  independent verification of the Trail of Bits STON.fi TON AMM DEX V2 findings.
- [`security/poc/`](security/poc/) — the TOB-STONFI-4 proof of concept, plus the
  splicer that inserts it into a `ston-fi/dex-core-v2` checkout.

Alongside the research, one vendored tool:

- [`tradingview-mcp/`](tradingview-mcp/) — a vendored copy of
  [`tradesdontlie/tradingview-mcp`](https://github.com/tradesdontlie/tradingview-mcp)
  at commit `c05b8f5`, MIT licensed. An MCP server exposing 84 tools that drive
  TradingView Desktop over the Chrome DevTools Protocol. It is a full checkout with
  upstream history removed, not a submodule, so changes here do not flow either way.

## Checks

CI (`.github/workflows/ci.yml`) runs all of these on every push and pull request.

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

# the vendored MCP server: lint plus the headless unit tests
npm ci --prefix tradingview-mcp
npm run lint --prefix tradingview-mcp
npm run test:unit --prefix tradingview-mcp
```

`test:unit` is the headless subset, and it is what CI runs. The suite `test:all`
additionally runs `tests/e2e.test.js`, which drives a live TradingView Desktop over
CDP on port 9222 and fails anywhere that is not a desktop with TradingView already
running — including CI and any container. Run `test:all` locally against a real
instance when changing anything that talks to the chart.

The PoC cannot be executed here — it is a fragment that borrows its harness from the
upstream spec it gets spliced into. `harness.d.ts` declares the identifiers that
harness must supply, so the fragment is at least parsed and type-checked on every
change instead of only when someone clones `dex-core-v2` and runs the full suite.
