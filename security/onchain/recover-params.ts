/**
 * Recover the compile-time constants a deployed STON.fi router was built with.
 *
 * Copy into a dex-core-v2 checkout as helpers/recover-params.ts and run:
 *     npx ts-node helpers/recover-params.ts
 *
 * Why this works. `pool/pools/<type>/state_init.fc` bakes three preprocessor values
 * into `_pool_idata()` -- defaultIsLocked, defaultLPFee, defaultProtocolFee -- and
 * `common/common.fc` includes that file into the *router*. So two routers built from
 * identical source with different fee defaults get different code hashes, and the
 * router's `get_pool_address` getter returns an address derived from those constants.
 *
 * Asking the deployed router what address it computes *now*, then searching locally
 * for the constants that reproduce it, recovers the values. Note that existing pools
 * are no use for this: routers can upgrade `pool_code`, so a pool deployed long ago
 * need not be reproducible from the router's current code. The getter avoids that.
 *
 * Fee values are bounded by params::max_fee (100 = 1%), so the search space is small.
 */
import { Address, beginCell, Cell, contractAddress } from '@ton/core';

const ROUTERS_API = 'https://api.ston.fi/v1/routers';
const TONCENTER = 'https://toncenter.com/api/v3';
const MAX_FEE = 300; // params::max_fee is 100; searching wider costs little

// Two arbitrary wallet addresses -- any pair works, the getter is pure.
const T0 = new Address(0, Buffer.alloc(32, 0x11));
const T1 = new Address(0, Buffer.alloc(32, 0x22));

const TYPE_MAP: Record<string, string> = {
    ConstantProduct: 'constant_product',
    StableSwap: 'stableswap',
    WeightedConstProduct: 'weighted_const_product',
    WeightedStableSwap: 'weighted_stableswap',
    ConstantSum: 'constant_sum',
};

// Trailing storage fields after the two fee uint16s, per state_init.fc of each type.
const TAIL: Record<string, (b: any) => any> = {
    constant_product: (b) => b,
    constant_sum: (b) => b,
    weighted_stableswap: (b) => b,
    stableswap: (b) => b.storeUint(1, 32), // storage::amp = 1
    weighted_const_product: (b) => b.storeUint(0, 64), // storage::w0 = 0
};

function poolIdata(
    type: string, locked: number, lp: number, pf: number, inner: Cell, feeAddr: Address | null,
): Cell {
    let b = beginCell()
        .storeUint(locked, 1)
        .storeCoins(0).storeCoins(0).storeCoins(0).storeCoins(0).storeCoins(0);
    if (feeAddr) b.storeAddress(feeAddr); else b.storeUint(0, 2);
    b = TAIL[type](b.storeUint(lp, 16).storeUint(pf, 16));
    if (type === 'weighted_stableswap') {
        // storage::amp / rate / w0 / rate_setter_address sit in their own ref
        b = b.storeRef(beginCell()
            .storeUint(1000000000000000000n, 128)
            .storeUint(0, 128)
            .storeUint(0, 128)
            .storeUint(0, 2)
            .endCell());
    }
    return b.storeRef(inner).endCell();
}

async function post(path: string, body: unknown, attempts = 4): Promise<any> {
    for (let i = 0; i < attempts; i++) {
        const r = await fetch(`${TONCENTER}/${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json().catch(() => null);
        if (d && d.exit_code === 0) return d;
        await new Promise((res) => setTimeout(res, 2 ** i * 1000));
    }
    return null;
}

async function accountState(address: string): Promise<any> {
    const r = await fetch(`${TONCENTER}/accountStates?address=${encodeURIComponent(address)}&include_boc=true`);
    const d = await r.json();
    return d.accounts?.[0];
}

/** Protocol-fee address most of a router's pools use, if it isn't addr_none. */
async function bakedFeeAddress(router: string, pools: any[]): Promise<string | null> {
    const seen = new Map<string, number>();
    for (const p of pools) {
        if (p.router_address !== router || !p.protocol_fee_address) continue;
        seen.set(p.protocol_fee_address, (seen.get(p.protocol_fee_address) ?? 0) + 1);
    }
    const best = [...seen.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    if (!best) return null;
    return Address.parse(best).hash.every((x) => x === 0) ? null : best;
}

(async () => {
    const routers: any[] = await fetch(ROUTERS_API).then((r) => r.json())
        .then((d) => d.router_list ?? d)
        .then((rs: any[]) => rs.filter((r) => r.major_version === 2 && r.minor_version === 2));
    const pools: any[] = await fetch('https://api.ston.fi/v1/pools').then((r) => r.json())
        .then((d) => d.pool_list ?? d);

    const argAddr = beginCell().storeAddress(T0).endCell().toBoc().toString('base64');
    const argAddr2 = beginCell().storeAddress(T1).endCell().toBoc().toString('base64');

    for (const r of routers) {
        const type = TYPE_MAP[r.router_type];
        const st = await accountState(r.address);
        const answer = await post('runGetMethod', {
            address: r.address,
            method: 'get_pool_address',
            stack: [{ type: 'slice', value: argAddr }, { type: 'slice', value: argAddr2 }],
        });
        if (!st || !answer) { console.log(`${r.address}  getter unavailable`); continue; }

        const target = Cell.fromBase64(answer.stack[0].value).beginParse().loadAddress()!;
        const stat = Cell.fromBase64(st.data_boc).refs[1];
        const [lpWallet, poolCode, lpAccount] = [stat.refs[0], stat.refs[1], stat.refs[2]];

        const feeAddr = await bakedFeeAddress(r.address, pools);
        const feeCandidates: (Address | null)[] = feeAddr ? [null, Address.parse(feeAddr)] : [null];

        let hit: string | null = null;
        outer:
        for (const [a, b] of [[T0, T1], [T1, T0]]) {
            const inner = beginCell()
                .storeAddress(Address.parse(r.address))
                .storeAddress(a).storeAddress(b)
                .storeRef(lpWallet).storeRef(lpAccount)
                .endCell();
            for (const fa of feeCandidates)
                for (let locked = 0; locked <= 1; locked++)
                    for (let lp = 0; lp <= MAX_FEE; lp++)
                        for (let pf = 0; pf <= MAX_FEE; pf++) {
                            const data = poolIdata(type, locked, lp, pf, inner, fa);
                            if (contractAddress(0, { code: poolCode, data }).equals(target)) {
                                hit = `lp_fee=${lp} protocol_fee=${pf} is_locked=${locked}`
                                    + (fa ? ' protocol_fee_address=baked-in' : '');
                                break outer;
                            }
                        }
        }
        console.log(`${type.padEnd(23)} ${r.address}  ${hit ?? 'NO MATCH'}`);
    }
})();
