# Does the deployed STON.fi DEX match the audited source?

Follow-up to [`stonfi-dex-v2-fix-verification.md`](./stonfi-dex-v2-fix-verification.md), which
verified the five Trail of Bits findings against `ston-fi/dex-core-v2` @ `af0a955` (v2.2.0) and
listed this as an open item: *"Whether the deployed mainnet contracts match this v2.2 source."*

Checked: 2026-07-29. Result reproduced twice, identical both times.

## Answer

**17 of the 32 deployed v2.2 routers run byte-for-byte the audited source — and that includes
all 16 routers still accepting new pools.** The remaining 15 differ, and all 15 have pool
creation disabled.

So the fixes verified in source, including the `original_caller` fix for the High-severity
finding, are the code actually executing on every v2.2 router that STON.fi is still
provisioning pools on.

## The trap: deployed code is a library reference, not code

A deployed router does not store its code inline. Its `code` is a 46-byte **exotic library
reference cell** whose payload is the 32-byte hash of the real code, which lives in the
masterchain library collection:

```
BoC layout of a deployed router's code cell (46 bytes)
┌──────────┬──────────┬──────┬────┬──────┬──────┬───────────────────────────┐
│ b5ee9c72 │ 01010101 │ 0023 │ 00 │ 08   │ 42   │ 02 + 32-byte library hash │
│ magic    │ flags    │ len  │    │ d1   │ d2   │ 0x02 = library cell       │
└──────────┴──────────┴──────┴────┴──────┴──────┴───────────────────────────┘
              d1 & 0x08 = exotic          d2 = 66 → 33 bytes of data
```

This matters because **the `code_hash` reported by explorers and APIs is the hash of that
wrapper, not of the code**. Comparing it against a local build mismatches 100% of the time and
looks like evidence the deployment diverged. The value to compare is the library hash carried
*inside* the cell, against `Cell.hash()` of the locally compiled code.

I hit this myself: the first comparison showed zero matches across all 32 routers before the
46-byte code cells gave the mechanic away.

## Method

1. Enumerate deployed routers from STON.fi's own registry, `https://api.ston.fi/v1/routers`,
   filtered to `major_version 2, minor_version 2` — 32 routers, across four pool types
   (23 ConstantProduct, 3 StableSwap, 2 WeightedConstProduct, 4 WeightedStableSwap).
2. Fetch each account's code BoC from `toncenter.com/api/v3/accountStates`, confirm it is an
   exotic library cell, and extract the library hash. All 32 are library cells.
3. Build every pool-type variant locally from `af0a955` and record `Cell.hash()` of each
   compiled contract — `security/onchain/hashes.ts`.
4. Compare — `security/onchain/verify.py`.

The build is deterministic given the toolchain: FunC **0.4.4** (funcfiftlib `ffe0a1c6`,
2024-03-27), which is what the repo's pinned `@ton-community/func-js@0.7.0` ships. Preprocessor
defaults are the repo's own (lp fee 20, protocol fee 10, unlocked).

Local Router code-cell hashes at `af0a955`:

| Pool type | Router code hash |
|---|---|
| `constant_product` | `848d1da9f94d125219685290a670a23573a3ff671dfe3c04b7aa8832c6a4f5cc` |
| `stableswap` | `389f3e494d5c9657c39b1d835d68e330f3c2be7c501dfdbd4762fd0a2a44829e` |
| `weighted_const_product` | `45e94dc8bfbfb33e3d28dd20a4998a2816872530b1c8f98d8895b7dc6ca066b3` |
| `weighted_stableswap` | `0d000208481f77a49ba3d55e09f1ee71e2df4531d9ae7929abcdeadb1c1ccccd` |
| `constant_sum` | `cca1d42db68cc5175f73daa7524c6f6e71d530fdd8acfbd4dc7121e7c0c999d4` |

## Results

| Type | Count | Library hash | Accepting new pools | Verdict |
|---|---|---|---|---|
| ConstantProduct | **17** | `848d1da9f94d1252…` | **16** | **matches `constant_product` exactly** |
| ConstantProduct | 1 each ×6 | 6 distinct hashes | 0 | differs |
| StableSwap | 3 | `aef0febd0a029f7d…` | 0 | differs |
| WeightedConstProduct | 2 | `f13d4058e67f82ed…` | 0 | differs |
| WeightedStableSwap | 4 | `57de63d28e4d3608…` | 0 | differs |

`constant_sum` has no deployed v2.2 routers.

The split lines up exactly with operational status: every router still taking new pools is on
the audited code, and every router that is not matches nothing in this source tree.

## What this does **not** establish

- **Why the other 15 differ.** They could be earlier v2.2.x point builds, a different compiler
  version, or genuinely different source. I did not investigate, and nothing here should be read
  as a claim that they are unsafe — only that they are not this source tree. They hold real
  liquidity even with pool creation disabled, so their code is worth pinning down separately.
- **Pool, lp_account, lp_wallet, and vault code.** Those are separate library cells held in
  router storage and were not compared. A matching router is not by itself proof that the pools
  it spawns run audited code. This is the obvious next check, and the local hashes for all four
  are already recorded by `hashes.ts`.
- **Anything about v2.1 or v1.** 19 older routers are live and out of scope here.

## Reproducing

```sh
git clone https://github.com/ston-fi/dex-core-v2 && cd dex-core-v2
git checkout af0a955
npm install --legacy-peer-deps
cp /path/to/security/onchain/hashes.ts helpers/hashes.ts
npx ts-node helpers/hashes.ts          # writes build/local_hashes.json
/path/to/security/onchain/verify.py .  # fetches mainnet state and compares
```

`verify.py` retries throttled toncenter batches and aborts rather than reporting a missing
response as a code difference — an unauthenticated batch that silently returns a short account
list would otherwise mislabel healthy routers. An earlier revision of the script had that bug
and under-reported the matches as 11/32.

## Appendix — the 17 routers running the audited source

| Address | Accepting new pools |
|---|---|
| `EQAJG5pyZPWEiQiMVJdf7bDRgRLzg6QR57qKeRsOrMO-ncZN` | no |
| `EQDh5oHPvfRwPu2bORBGCoLEO4WQZKL4fk5DD1gydeNG9oEH` | yes |
| `EQCiypoBWNIEPlarBp04UePyEj5zH0ZDHxuRNqJ1WQx3FCY-` | yes |
| `EQBigMnbY4NU1uwdvzertV5mv_yI7282R-ffW7XZFWPEVRDG` | yes |
| `EQDx--jUU9PUtHltPYZX7wdzIi0SPY3KZ8nvOs0iZvQJd6Ql` | yes |
| `EQAQYbnb1EGK0Wb8mk3vEW4vbHTyv7cOcfJlPWQ87_6_qfzR` | yes |
| `EQDAPye7HAPAAl4WXpz5jOCdhf2H9h9QkkzRQ-6K5usiuQeC` | yes |
| `EQByADL5Ra2dldrMSBctgfSm2X2W1P61NVW2RYDb8eJNJGx6` | yes |
| `EQCDT9dCT52pdfsLNW0e6qP5T3cgq7M4Ug72zkGYgP17tsWD` | yes |
| `EQAyD7O8CvVdR8AEJcr96fHI1ifFq21S8QMt1czi5IfJPyfA` | yes |
| `EQADEFMTMnC-gu5v2U0ZY8AYaGhAOk9TcECg1TOquAW3r-IE` | yes |
| `EQBCtlN7Zy96qx-3yH0Yi4V0SNtQ-8RbhYaNs65MC4Hwfq31` | yes |
| `EQCx0HDJ_DxLxDSQyfsEqHI8Rs65nygvdmeD9Ra7rY15OWN8` | yes |
| `EQCS4UEa5UaJLzOyyKieqQOQ2P9M-7kXpkO5HnP3Bv250cN3` | yes |
| `EQBQ_UBQvR9ryUjKDwijtoiyyga2Wl-yJm6Y8gl0k-HDh_5x` | yes |
| `EQDQ6j53q21HuZtw6oclm7z4LU2cG6S2OKvpSSMH548d7kJT` | yes |
| `EQAiv3IuxYA6ZGEunOgZSTuMBzbpjwRbWw09-WsE-iqKKMrK` | yes |
