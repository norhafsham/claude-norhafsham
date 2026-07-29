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
 * Observed output:
 *   router2 mid-jetton balance: 1000000000000n -> 1001992015968n  (+1.992 Token2, stranded)
 *   user  final-jetton balance: 96000000000000n -> 96000000000000n (unchanged, leg 2 never ran)
 *
 * This is not a standalone spec: it relies on the host spec's imports and on the
 * harness defined inside the `describe` block of the project's own pool specs.
 * Required identifiers:
 *   HOUR_IN_SECONDS, bc, deployer, expectNotBounced, getWalletBalance,
 *   getWalletContract, initTimestamp, setupDex, swapPayload, toNano
 * (declared in harness.d.ts, which is what CI type-checks this file against).
 *
 * Run ./apply.py to splice it into a copy of tests/ConstProduct.spec.ts, or paste the
 * block below next to the repo's `should cross-swap on 2 routers` test by hand.
 */

        it('POC TOB-STONFI-4: cross-router swap strands mid jettons in router2', async () => {
            let setup = await setupDex({ createPool: { amount1: toNano(1000), amount2: toNano(2000) } });
            let setup2 = await setupDex({
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

            const oldRouter2Mid = await getWalletBalance(router2WalletMid);
            const oldFinal = await getWalletBalance(walletFinal);

            // The user asks for a fwd_ton_amount on the mid hop that router1 cannot
            // afford by the time it pays out -- exactly the report's exploit scenario.
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
                    fwdGas: toNano("1.9"),
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

            expectNotBounced(msgResult.events);

            const newRouter2Mid = await getWalletBalance(router2WalletMid);
            const newFinal = await getWalletBalance(walletFinal);

            console.log("TOB-4 router2 mid-jetton balance:", oldRouter2Mid, "->", newRouter2Mid);
            console.log("TOB-4 user final-jetton balance:", oldFinal, "->", newFinal);

            // no transfer_notification reached router2, so the second leg never ran
            expect(newFinal).toEqual(oldFinal);
            // ...and the mid jettons are now sitting in router2 with no way out
            expect(newRouter2Mid).toBeGreaterThan(oldRouter2Mid);
        });
