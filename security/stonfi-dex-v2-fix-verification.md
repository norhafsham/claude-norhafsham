# STON.fi TON AMM DEX V2 — independent verification of the Trail of Bits findings

Source report: *STON.fi TON AMM DEX V2 Review — Security Assessment*, Trail of Bits,
January 9, 2025 (public). Five findings (TOB-STONFI-1…5) plus an Appendix E fix review
claiming four resolved and one unresolved.

Verified: 2026-07-28.

## Scope and method

| | |
|---|---|
| Target | `github.com/ston-fi/dex-core-v2` @ `af0a955cc835af9697cd383e201fefcbe1a6a87e` ("bump v2.2", `package.json` version `2.2.0`) |
| Dependency | `@ston-fi/funcbox` pinned to `0.1.4`; verified against `github.com/ston-fi/funcbox` @ `af37d2c` ("bump 0.1.4") |
| Static | Full read of the router / pool / lp_account message paths and the pool math for each finding |
| Dynamic | `npm install --legacy-peer-deps` → `npm run build` (all FunC contracts compile) → `npx jest`: **158/158 tests pass across 9 suites** (~346 s). Plus one purpose-written proof-of-concept for TOB-STONFI-4 (below) |

**Limitation — no before/after diff is possible.** The public repository's history is squashed
to two commits, both titled "bump v2.2". The commits the report audited (`bb62e6b`, `b2c7e8c`,
`5a529a1`) and the "PR 1" that Appendix E credits for the fixes are not present in the public
repo (only `refs/pull/3` exists). Everything below therefore verifies **that the fixed behaviour
is present in the shipped v2.2 code**, not that a particular PR introduced it. Claims about
*how* a fix was landed are taken from the report and not independently confirmed.

## Verdicts

| ID | Finding | Severity | ToB fix status | Verdict here | Evidence |
|----|---------|----------|----------------|--------------|----------|
| 1 | Attacker steals jettons from a user's `lp_account` | High | Resolved | **Confirmed fixed** (belt and braces) | `contracts/common/op.fc:10`, `contracts/common/contracts.fc:146`, `contracts/pool/msgs/router.fc:139`, `contracts/router/msgs/pool.fc:8,55`, `contracts/router/dex.fc:44,46` |
| 2 | Protocol fees withdrawable by liquidity providers | Medium | Resolved | **Confirmed fixed** | `contracts/pool/msgs/lp_account.fc:57-61`, `contracts/pool/msgs/protocolfee.fc:57-58` |
| 3 | `math::int::sqrt` returns a result for negative input | Low | Resolved | **Confirmed fixed** (in both places) | `contracts/pool/pools/constant_product/math.fc:2`; funcbox `af37d2c:contracts/math/int/int.fc:8` |
| 4 | Cross-router swaps can lock jettons in the second router | Medium | Unresolved | **Confirmed still exploitable — reproduced** | `contracts/router/msgs/pool.fc:46,62-67`; PoC below |
| 5 | Weighted-stableswap convergence threshold too large | Informational | Resolved | **Confirmed fixed** | `contracts/pool/pools/weighted_stableswap/math.fc:1` |

Bottom line: the four fixes the report calls resolved are genuinely present in the shipped
code. The one the client declined to fix is still present and reproduces on the first attempt
using the project's own test harness.

---

## TOB-STONFI-1 — jetton theft from a victim's `lp_account` (High) — Confirmed fixed

**Claim.** `pay_to` now carries an `original_caller` field, used as the `_caller` argument to
`route_dex_messages`; `op::cross_provide_lp` was removed.

**What the code shows.** Both halves are real, and either alone would close the attack.

The `pay_to` schema now carries a third address:

```
const op::pay_to = "pay_to query_id:uint64 to_address:MsgAddress excesses_address:MsgAddress
                    original_caller:MsgAddress exit_code:uint32 ..." ;; common/op.fc:10
```

The pool always populates it from `from_user_address` — the value the router passed in the
`op::swap` body, which originates from the jetton `transfer_notification`'s `from_address`
(`router/msgs/jetton.fc:7,28` → `dex.fc:88` → `pool::$route`). It is not user-supplied
payload data. All three `router::pay_to` call sites in the pool's swap handler
(`pool/msgs/router.fc:59,139,161` — parse-failure refund, success, and swap-failure refund)
pass `from_user_address` as `_original_caller`. The user-controlled `to_address` remains a
separate, later field, so the two can no longer be conflated.

The router loads it back in the same order the builder writes it and forwards *that* value:

```
slice owner            = in_msg_body~load_msg_addr();
slice excesses_address = in_msg_body~load_msg_addr();
slice original_caller  = in_msg_body~load_msg_addr();   ;; router/msgs/pool.fc:8
...
route_dex_messages(sent_jetton_address, gas, swap_amount, original_caller, custom_payload);
                                                          ;; router/msgs/pool.fc:55
```

`op::cross_provide_lp` no longer exists anywhere in `contracts/` — the opcode is gone from
`common/op.fc` and there is no handler for it. Two independent gates now block the original
attack shape: the continuation branch is entered only when the forwarded opcode is
`op::cross_swap` (`router/msgs/pool.fc:46`), and `route_dex_messages` maps `cross_swap` → `swap`
and rejects anything that is not `swap` or `provide_lp` (`dex.fc:44,46`). A liquidity-provision
continuation cannot be reached from a `pay_to` at all.

**Residual risk.** None found for this issue. The remaining `cross_swap` continuation carries
the true initiator, so caller confusion cannot be reintroduced through it.

## TOB-STONFI-2 — protocol fees withdrawable by LPs (Medium) — Confirmed fixed

**Claim.** The `cb_add_liquidity` handler now subtracts the protocol fee from the token amounts
before adding them to the reserves.

**What the code shows.** Exactly that, in the non-empty-pool branch:

```
storage::collected_token0_protocol_fee += new_collected_protocol_fees0;
storage::collected_token1_protocol_fee += new_collected_protocol_fees1;

storage::reserve0 += (tot_am0 - new_collected_protocol_fees0);
storage::reserve1 += (tot_am1 - new_collected_protocol_fees1);   ;; pool/msgs/lp_account.fc:57-61
```

No double-count: `pool::get_lp_provide_out` (e.g.
`pool/pools/constant_product/pool.fc:25-52`) computes the LP fee and the protocol fee from the
imbalance, returns only the protocol fee to the caller, and the LP fee correctly stays inside
the reserves for the benefit of LPs. On the withdrawal side, `op::collect_fees` pays out the
accumulated `collected_token*_protocol_fee` and zeroes both counters in the same transaction
(`pool/msgs/protocolfee.fc:22-58`), so `reserves + collected fees` stays within the router's
actual jetton balance. The empty-pool branch takes no protocol fee at all and needs no change.

**Residual observations (not this finding).** Two pre-existing quirks are worth knowing about:

- `collect_fees` requires *both* sides to be non-zero:
  `throw_unless(error::zero_output, (collected_token0_protocol_fee > 0) & (collected_token1_protocol_fee > 0))`
  (`protocolfee.fc:5`). A pool that has only ever accrued a one-sided fee cannot collect until
  the other side accrues. Availability nuisance, not a loss of funds.
- `get_lp_provide_out` is called inside `try { } catch(_, _) { }` with the results left at their
  zero initialisers on a math error (`lp_account.fc:52-55`). A silent failure mints zero
  liquidity; the subsequent `liquidity < min_lp_out` check refunds, so this is safe today, but
  it is fragile if the guard is ever relaxed.

## TOB-STONFI-3 — `sqrt` of a negative input (Low) — Confirmed fixed

**Claim.** funcbox `95a60be` makes `math::int::sqrt` throw on negatives; separately the DEX
moved to its own OpenZeppelin-derived implementation in
`pools/constant_product/math.fc`.

**What the code shows.** Both are true, and the pinned dependency really contains the fix.

The in-repo implementation guards on the first line:

```
int oz_sqrt(int x) impure inline {
    throw_if(math::error::invalid_input, x < 0);      ;; constant_product/math.fc:2
```

It is the only square root used by the contracts (single call site,
`norm_invariant`, `math.fc:48`); no `math::int::sqrt` call sites remain in `contracts/`. Both
deltas from OpenZeppelin v5.1.0 that the report calls out are present and behave as described:
`repeat(7)` Newton iterations rather than six (`math.fc:38`), and the extra `r1 = x / r` /
`min(r, r1)` step (`math.fc:42-44`), which can only round the result down to the true integer
square root.

On the dependency: funcbox commit `95a60be` is tagged "bump 0.1.3"; `package.json` pins
`@ston-fi/funcbox` `0.1.4` (`af37d2c`), i.e. one release *after* the fix. Reading
`af37d2c:contracts/math/int/int.fc` confirms the `throw_if(math::error::invalid_input, x < 0)`
guard is in the pinned version, and funcbox's own `int_test.fc` asserts the throw.

## TOB-STONFI-4 — jettons locked in the second router (Medium) — Confirmed still exploitable

**Client's position, quoted in Appendix E.** *"We have decided not to address this issue as it
was deemed irrelevant following our internal review. Setting `fwd_amount` to 0 is necessary to
prevent jettons from becoming stuck in the router due to failed gas checks. Potential fixes
could introduce unpredictable behavior in the contract."*

**What the code shows.** The vulnerable path is unchanged, and the client's rebuttal does not
hold for the cross-router case. In `router/msgs/pool.fc`, the routing branch is entered *only*
when the forwarded opcode is `op::cross_swap` (line 46) — that is the same-router, cross-pool
case, where the router does the next hop itself. A cross-*router* swap cannot use that opcode:
the payload has to be a plain `op::swap` body that the *second* router will parse, so it falls
through to the `else` branch, where:

```
int gas_available = ctx.at(MSG_VALUE) - (used_gas + storage_fee::router);
if (fwd_ton_amount > 0) & (
    (gas_available - (gas::jetton_wallet::est_transfer + (ctx.at(FWD_FEE) * 2))) - fwd_ton_amount <= 0
) {
    ;; do not send transfer_notification, if gas is too low
    fwd_ton_amount = 0;                                   ;; router/msgs/pool.fc:62-67
}
```

The jettons are then transferred to `owner` (the second router) with the custom payload
attached but `fwd_ton_amount = 0`, so the receiving jetton wallet sends no
`transfer_notification`. The second router never learns it holds them, and nothing in the
router accepts a bare balance — the tokens are stranded. Neither of the report's short-term
recommendations is implemented: there is no fallback to the refund/excesses address in this
branch, and the up-front gas check in `route_dex_messages`
(`dex.fc:56-64`) budgets for the hop's own fees but never reads the user-specified
`fwd_ton_amount` out of the nested `custom_payload`.

**Reproduced.** Using the project's own harness, a cross-router swap that requests a mid-hop
`fwd_ton_amount` larger than what remains at payout time strands the intermediate jettons:

```
TOB-4 router2 mid-jetton balance: 1000000000000n -> 1001992015968n   (+1.992 Token2, stranded)
TOB-4 user  final-jetton balance:   96000000000000n -> 96000000000000n   (unchanged — leg 2 never ran)
```

The transaction does not bounce and no refund is issued; the user simply loses the swap output.
The identical flow with a sane `fwdGas` succeeds (the repo's own `should cross-swap on 2 routers`
test), so the only difference is the forward-gas amount.

The PoC is `security/poc/tob-stonfi-4.spec.ts`. It depends on the harness defined inside the
`describe` block of the project's pool specs (`setupDex`, `bc`, `deployer`, `initTimestamp`,
`getWalletContract`, `swapPayload`), so it is spliced into a copy of
`tests/ConstProduct.spec.ts` by `security/poc/apply.py` rather than run on its own.

**Assessment.** The severity rating (Medium, Low difficulty) still fits: no attacker is needed —
a user or an integrating front-end that quotes a forward-gas value too optimistically burns the
swap output. It is a user-error amplifier rather than a theft primitive, which is presumably
why the client discounted it, but "irrelevant" overstates the case: the failure is silent, has
no refund path, and the loss is permanent. The client's stated reason (zeroing `fwd_amount`
prevents jettons sticking in the router) argues against removing the zeroing, but the report's
recommendation #1 — refund to the caller/refund address when the forward amount cannot be
honoured — is compatible with keeping it, and is not implemented.

## TOB-STONFI-5 — convergence threshold (Informational) — Confirmed fixed

```
const int __EPSILON = 1000000000000000000000000; ;; 0.001
const int __MAX_ITERATIONS = 255;                ;; weighted_stableswap/math.fc:1-2
```

The threshold is 10²⁴ = 0.001 TON in 18-decimal fixed point, down from 10²⁷ (1 TON) — a
1000× tightening, exactly as Appendix E states. Used at both Newton loops (`math.fc:58,81`).
`__MAX_ITERATIONS` was left at 255, which is ample headroom for a quadratically converging
Newton iteration, so the tighter threshold does not convert precision loss into
`error::not_converge` throws in practice; the whole weighted-stableswap suite passes.

---

## Codebase-maturity claims, re-checked

| Report's rating | Still accurate at v2.2? |
|---|---|
| Auditing — **Weak** | **Yes.** There is still no log/event emission anywhere in `contracts/`; nothing for off-chain monitoring to consume. |
| Testing and Verification — **Moderate** ("no visible integrations of tests with CI/CD") | **Yes.** No `.github/` directory exists — still no CI. The suite itself is substantial (9 specs, ~11k lines, 158 tests, all passing) and includes happy-path cross-router coverage. |
| Arithmetic — **Moderate** | Improved for the specific issue: `oz_sqrt` now validates its domain. The fixed-point/regular-notation mixing the report flagged is unchanged. |
| Access Controls / Decentralization — **Moderate** | Not re-assessed; nothing in scope here changes the single-admin, no-timelock-on-config posture. |
| Transaction Ordering — *Further investigation required* | Still unexamined, by ToB and here. |

**Test-coverage gap worth flagging.** The cross-router helper in all five pool specs declares a
`fwdGas2` parameter and threads it into the mid-hop payload
(e.g. `tests/ConstProduct.spec.ts:178,902`), but **no test ever passes it** — every cross-router
test uses the 1 TON default. The one knob that would exercise TOB-STONFI-4 exists and is never
turned. Adding a case that asserts the current (lossy) behaviour would at least make the
accepted risk visible in the suite.

## Open items the public repo cannot settle

- Whether the fixes landed via the "PR 1" Appendix E cites, and whether anything else changed
  alongside them — the squashed history hides it.
- Whether the deployed mainnet contracts match this v2.2 source. Not checked; verifying that
  requires comparing on-chain code hashes against a local build.
- The Funcbox library beyond `math::int::sqrt` — out of scope for ToB too, per their coverage
  limitations, and out of scope here.

## Reproducing this

```sh
git clone https://github.com/ston-fi/dex-core-v2 && cd dex-core-v2
git checkout af0a955
npm install --legacy-peer-deps
npm run build        # compiles every pool variant
npx jest             # 158/158 pass, ~6 min

# then the TOB-STONFI-4 proof of concept:
/path/to/security/poc/apply.py .            # writes tests/TOB4Poc.spec.ts
npx jest tests/TOB4Poc.spec.ts -t "POC TOB-STONFI-4"
```
