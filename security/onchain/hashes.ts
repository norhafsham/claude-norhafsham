/**
 * Build-side half of the on-chain verification: compiles every pool-type variant
 * and records the code-cell hash of each contract.
 *
 * Copy into a dex-core-v2 checkout as helpers/hashes.ts and run:
 *     npx ts-node helpers/hashes.ts
 * It writes build/local_hashes.json, which security/onchain/verify.py reads.
 *
 * The hash recorded here is Cell.hash() of the compiled code — the same value
 * that appears inside the library reference cell of a deployed router.
 */
import 'dotenv/config';
import * as fs from 'fs';
import { Cell } from '@ton/core';
import { compileX } from "../libs/";
import { POOL_TYPES, preprocBuildContractsLocal } from "./helpers";

const NAMES = ['Router', 'Pool', 'LPAccount', 'LPWallet', 'Vault'] as const;

function hashOf(name: string): string {
    const j = JSON.parse(fs.readFileSync(`build/${name}.compiled.json`, 'utf8'));
    return Cell.fromBase64(j.base64).hash().toString('base64');
}

(async () => {
    const out: Record<string, Record<string, string>> = {};
    for (const tp of POOL_TYPES) {
        // null defaults reproduce the values the repo ships: lp fee 20, protocol fee 10, unlocked
        preprocBuildContractsLocal({
            dexType: tp, defaultProtocolFee: null, defaultIsLocked: null, defaultLPFee: null,
        });
        out[tp] = {};
        for (const n of NAMES) {
            await compileX(n, { cells: true, base64: true });
            out[tp][n] = hashOf(n);
        }
        console.log(tp, JSON.stringify(out[tp]));
    }
    fs.writeFileSync('build/local_hashes.json', JSON.stringify(out, null, 1));
    console.log('wrote build/local_hashes.json');
})();
