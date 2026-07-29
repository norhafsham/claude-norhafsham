/**
 * Ambient declarations for `tob-stonfi-4.spec.ts`.
 *
 * The PoC is a fragment: it is spliced into tests/ConstProduct.spec.ts and borrows
 * that file's imports and its `describe`-scoped helpers. Nothing in this repository
 * can run it, so without these stubs the PoC is never parsed by any tool and a typo
 * in it surfaces only after a ~6 minute upstream test run.
 *
 * These are deliberately loose about TON's own types -- `Address`, `Cell` and the
 * sandbox contract wrappers are modelled as opaque. What they pin down precisely is
 * the set of identifiers the host spec must provide, and the shape of the option
 * bags the PoC passes. That is what actually rots when upstream moves.
 *
 * Shapes verified against ston-fi/dex-core-v2 @ af0a955 (v2.2.0).
 * Keep the identifier list here in sync with the header of tob-stonfi-4.spec.ts and
 * the harness paragraph of ../stonfi-dex-v2-fix-verification.md -- tests/test_apply.py
 * fails if they drift apart.
 */

/** An opaque TON value (Address, Cell, contract wrapper, ...). */
type Opaque = unknown;

// --- borrowed from the host spec's imports -------------------------------------

declare function toNano(value: number | string): bigint;

// --- borrowed from the host spec's `describe` scope -----------------------------

/** Seconds in an hour; used to build the swap deadline. */
declare const HOUR_IN_SECONDS: number;

/** The sandbox blockchain the host spec sets up in `beforeEach`. */
declare const bc: Opaque;

/** Blockchain timestamp captured at setup; swap deadlines are relative to it. */
declare const initTimestamp: number;

declare const deployer: {
  address: Opaque;
  getSender(): Opaque;
};

interface SetupDexResult {
  router: { address: Opaque };
  token1: Opaque;
  token2: Opaque;
}

declare function setupDex(opts: {
  createPool: {
    amount1: bigint;
    amount2: bigint;
    name1?: string;
    name2?: string;
  };
  routerId?: number;
}): Promise<SetupDexResult>;

interface JettonWallet {
  address: Opaque;
  sendTransfer(
    via: Opaque,
    opts: {
      value: bigint;
      jettonAmount: bigint;
      toAddress: Opaque;
      responseAddress: Opaque;
      fwdAmount: bigint;
      fwdPayload: Opaque;
    },
  ): Promise<{ events: Opaque[] }>;
}

declare function getWalletContract(
  blockchain: Opaque,
  token: Opaque,
  owner: Opaque,
): Promise<JettonWallet>;

declare function getWalletBalance(wallet: JettonWallet): Promise<bigint>;

declare function swapPayload(opts: {
  otherTokenWallet: Opaque;
  receiver: Opaque;
  minOut: bigint;
  refundAddress: Opaque;
  deadline: number;
  /** Forward TON attached to this hop. The knob TOB-STONFI-4 turns. */
  fwdGas?: bigint;
  customPayload?: Opaque;
}): Opaque;

declare function expectNotBounced(events: Opaque[]): void;

// --- ambient globals the fragment uses ------------------------------------------
// Declared here rather than pulled in via @types/jest and @types/node, so that
// type-checking the PoC needs no dependency beyond typescript itself.

interface Matchers {
  toEqual(expected: unknown): void;
  toBeGreaterThan(expected: bigint | number): void;
}
declare function expect(actual: unknown): Matchers;
declare function it(name: string, fn: () => Promise<void> | void): void;
declare const console: { log(...args: unknown[]): void };
