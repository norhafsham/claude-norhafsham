/**
 * PoC for TOB-STONFI-4 — "Risk of locking jettons in the router contract with
 * cross-router swaps" (Trail of Bits, STON.fi TON AMM DEX V2, Medium, Unresolved).
 *
 * Verified against ston-fi/dex-core-v2 @ af0a955 (v2.2.0).
 *
 * A cross-router swap whose mid-hop fwd_ton_amount exceeds the gas still available
 * when router1 pays out hits the gas guard at contracts/router/msgs/pool.fc:62-67,
 * which zeroes fwd_ton_amount. Router2's jetton wallet therefore sends no
 * transfer_notification, router2 never learns it holds the intermediate jettons,
 * and they are stranded. The transaction does not bounce and nothing is refunded.
 *
 * Two cases run the *same* swap and differ only in the mid-hop fwdGas, which is the
 * whole of the finding. Note what is NOT the discriminator: router2's mid-jetton
 * wallet gains the same 1.992 Token2 either way, because this DEX holds all jettons
 * at the router. The discriminator is whether pool2's reserves account for that
 * balance. In the control they do and the user is paid in Token3; in the exploit
 * they do not, so the jettons sit in router2 with no pool and no owner.
 *
 * Observed against af0a955 (both cases, exact):
 *   router2 mid-jetton wallet   +1992015968  in both
 *   pool2 mid reserve           +1992015968  control / +0 exploit  <-- the leak
 *   user Token3 received        +7928413675  control / +0 exploit
 *   user Token1 spent           -1000000000  in both               <-- paid either way
 *
 * This is not a standalone spec: it relies on the host spec's imports and on the
 * harness defined by the project's own pool specs. Required identifiers:
 *   HOUR_IN_SECONDS, Pool, bc, deployer, expectNotBounced, getWalletBalance,
 *   getWalletContract, initTimestamp, setupDex, swapPayload, toNano
 * (declared in harness.d.ts, which is what CI type-checks this file against.)
 *
 * Run ./apply.py to splice it into a copy of tests/ConstProduct.spec.ts, or paste the
 * block below next to the repo's `should cross-swap on 2 routers` test by hand.
 */

        /**
         * Drives one cross-router swap of 1 Token1 -> Token2 -> Token3 and reports
         * where the value ended up. `midHopFwdGas` is the only knob: it is the
         * `fwdGas2` parameter the repo's own crossRouterSwap helper threads through
         * but that no upstream test ever sets.
         */
        const tob4CrossRouterSwap = async (midHopFwdGas: bigint) => {
            const setup = await setupDex({ createPool: { amount1: toNano(1000), amount2: toNano(2000) } });
            const setup2 = await setupDex({
                createPool: { amount1: toNano(1000), amount2: toNano(4000), name1: "Token2", name2: "Token3" },
                routerId: 2,
            });

            const router = setup.router, router2 = setup2.router;
            const tokenIn = setup.token1, tokenMid = setup.token2, tokenFinal = setup2.token2;

            const routerWalletMid = await getWalletContract(bc, tokenMid, router.address);
            const router2WalletMid = await getWalletContract(bc, tokenMid, router2.address);
            const router2WalletOut = await getWalletContract(bc, tokenFinal, router2.address);
            const walletIn = await getWalletContract(bc, tokenIn, deployer.address);
            const walletFinal = await getWalletContract(bc, tokenFinal, deployer.address);

            const pool2 = bc.openContract(Pool.createFromAddress(await router2.getPoolAddress({
                firstWalletAddress: router2WalletMid.address,
                secondWalletAddress: router2WalletOut.address,
            })));

            // Reserve orientation is decided by the pool, not by argument order.
            const poolData = await pool2.getPoolData();
            const midIsLeft = poolData.leftJettonAddress.equals(router2WalletMid.address);
            const midReserve = (d: { leftReserve: bigint, rightReserve: bigint }) =>
                midIsLeft ? d.leftReserve : d.rightReserve;

            const oldRouter2Mid = await getWalletBalance(router2WalletMid);
            const oldIn = await getWalletBalance(walletIn);
            const oldFinal = await getWalletBalance(walletFinal);
            const oldPool2Mid = midReserve(poolData);

            const msgResult = await walletIn.sendTransfer(deployer.getSender(), {
                value: toNano(3),
                jettonAmount: toNano(1),
                toAddress: router.address,
                responseAddress: deployer.address,
                fwdAmount: toNano("2"),
                fwdPayload: swapPayload({
                    otherTokenWallet: routerWalletMid.address,
                    receiver: router2.address,
                    minOut: 1n,
                    fwdGas: midHopFwdGas,
                    refundAddress: deployer.address,
                    deadline: initTimestamp + HOUR_IN_SECONDS,
                    customPayload: swapPayload({
                        otherTokenWallet: router2WalletOut.address,
                        receiver: deployer.address,
                        minOut: 1n,
                        refundAddress: deployer.address,
                        deadline: initTimestamp + HOUR_IN_SECONDS
                    })
                }),
            });

            // The failure is silent by construction: no bounce, no refund.
            expectNotBounced(msgResult.events);

            return {
                spentIn: oldIn - (await getWalletBalance(walletIn)),
                receivedFinal: (await getWalletBalance(walletFinal)) - oldFinal,
                router2MidGained: (await getWalletBalance(router2WalletMid)) - oldRouter2Mid,
                pool2MidCredited: midReserve(await pool2.getPoolData()) - oldPool2Mid,
            };
        };

        // The amount leg 1 produces. Fixed by the 1000/2000 pool and the 1 Token1 input,
        // so both cases below move exactly this much Token2 into router2.
        const TOB4_MID_AMOUNT = 1992015968n;

        it('POC TOB-STONFI-4 (control): a sane mid-hop fwd_ton_amount completes both legs', async () => {
            // 1 TON is what the repo's own crossRouterSwap helper defaults fwdGas2 to.
            const r = await tob4CrossRouterSwap(toNano("1"));

            expect(r.spentIn).toEqual(toNano(1));
            expect(r.router2MidGained).toEqual(TOB4_MID_AMOUNT);
            // router2 was notified, so pool2 took the jettons into its reserves...
            expect(r.pool2MidCredited).toEqual(TOB4_MID_AMOUNT);
            // ...and paid the user out in Token3.
            expect(r.receivedFinal).toEqual(7928413675n);
        });

        it('POC TOB-STONFI-4: cross-router swap strands mid jettons in router2', async () => {
            // Ask for more forward TON than router1 can afford by the time it pays out.
            const r = await tob4CrossRouterSwap(toNano("1.9"));

            // The user paid exactly as much as in the control...
            expect(r.spentIn).toEqual(toNano(1));
            // ...and router2's wallet gained exactly as much as in the control...
            expect(r.router2MidGained).toEqual(TOB4_MID_AMOUNT);

            // ...but no transfer_notification ever reached router2, so pool2 has no
            // record of the jettons. Nothing in the router accepts a bare balance:
            // this delta is the permanent loss.
            expect(r.pool2MidCredited).toEqual(0n);
            // Leg 2 never ran; the user gets nothing back.
            expect(r.receivedFinal).toEqual(0n);
        });
