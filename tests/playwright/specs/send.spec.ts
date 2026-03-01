/**
 * E2E test: Simple sending (direct, non-collaborative).
 *
 * Verifies that a user with a funded wallet can send bitcoin to an
 * address using the direct send (non-CoinJoin) flow.
 */

import { test, expect, loginViaUI } from "../fixtures";
import * as bitcoinRpc from "../fixtures/bitcoin-rpc";

test.describe("Direct Send", () => {
  test("send bitcoin via UI (non-collaborative)", async ({
    page,
    fundedWallet,
  }) => {
    // Log in with the funded wallet.
    await loginViaUI(page, fundedWallet.walletName, fundedWallet.password);

    // Navigate to the Send tab directly to avoid matching Cheatsheet links.
    await page.goto("/send", { waitUntil: "domcontentloaded", timeout: 15_000 });

    // Dismiss the Cheatsheet dialog which opens on every page navigation.
    for (let i = 0; i < 6; i++) {
      await page.waitForTimeout(500);
      const dialog = page.locator('[role="dialog"]:visible').first();
      if (!(await dialog.isVisible().catch(() => false))) break;
      const box = await dialog.boundingBox();
      if (box) {
        await page.mouse.click(box.x + box.width - 20, box.y + 20);
        await page.waitForTimeout(600);
        continue;
      }
      await page.keyboard.press("Escape");
      await page.waitForTimeout(600);
    }

    await expect(page.getByText("Send from")).toBeVisible({
      timeout: 15_000,
    });

    // Select Jar 1 (Blueberry) which has the most funds.
    // JAM labels jars with fruit names (Apricot=0, Blueberry=1, ...).
    // Use force:true to bypass any lingering Radix backdrop.
    const jars = page.locator("button").filter({ hasText: /Blueberry/i });
    await jars.first().click({ force: true });

    // Generate a destination address from the Bitcoin Core wallet.
    const destinationAddress = await bitcoinRpc.rpc<string>(
      "getnewaddress",
    );

    // Fill in the destination address.
    await page.locator("#send-destination").fill(destinationAddress);

    // Fill in the amount (small amount: 50,000 sats = 0.0005 BTC).
    await page.locator("#send-amount").fill("50000");

    // Disable CoinJoin (use direct send). Open the "Sending options"
    // accordion first, then toggle off the CoinJoin switch.
    const sendingOptions = page.getByText("Sending options");
    // The accordion might already be collapsed; click to expand.
    if (await sendingOptions.isVisible()) {
      await sendingOptions.click({ force: true });
    }

    const cjSwitch = page.locator(
      "#switch-is-collaborative-transaction",
    );
    // If the switch is checked (CoinJoin enabled), uncheck it.
    if (await cjSwitch.isChecked()) {
      await cjSwitch.click({ force: true });
    }

    // Click the send button.
    await page
      .getByRole("button", { name: /Send without privacy/i })
      .click({ force: true });

    // Confirmation dialog should appear.
    await expect(page.getByText("Confirm payment")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByText("Payment without privacy improvement"),
    ).toBeVisible();

    // Take a screenshot of the confirmation dialog.
    await page.screenshot({
      path: "test-results/send-confirmation.png",
      fullPage: true,
    });

    // Confirm the payment.
    await page.getByRole("button", { name: "Confirm" }).click();

    // Wait for the transaction to be sent. The UI should show some
    // success indication (navigation back or toast).
    // After a successful send, the form should reset or show a success state.
    // Wait for the send form to reappear (amount field should be empty).
    await expect(page.locator("#send-amount")).toHaveValue("", {
      timeout: 30_000,
    });

    // Mine a block to confirm the transaction.
    await bitcoinRpc.mineBlocks(1);

    await page.screenshot({
      path: "test-results/send-completed.png",
      fullPage: true,
    });
  });

  test("send via API and verify balance change", async ({
    fundedWallet,
    walletApi,
    bitcoinRpc,
  }) => {
    const { token } = fundedWallet;
    // fundedWallet fixture already called waitForBalance, so we have a confirmed balance.

    // Get the initial wallet display.
    const before = await walletApi.getWalletDisplay(token);
    const balanceBefore = parseFloat(before.walletinfo.total_balance);
    console.log(`[send.spec.ts] Balance before: ${balanceBefore}`);
    expect(balanceBefore).toBeGreaterThan(0);

    // Generate a destination address.
    const destAddr = await bitcoinRpc.rpc<string>("getnewaddress");

    // Send 100,000 sats (0.001 BTC) from mixdepth 1 (Blueberry) which has the most funds.
    const sendResult = await walletApi.directSend(
      token,
      1,
      destAddr,
      100_000,
    );
    expect(sendResult.txid).toBeTruthy();

    // Mine a block.
    await bitcoinRpc.mineBlocks(1);

    // Wait for balance to update.
    await new Promise((r) => setTimeout(r, 3_000));

    // Verify balance decreased.
    const after = await walletApi.getWalletDisplay(token);
    const balanceAfter = parseFloat(after.walletinfo.total_balance);
    expect(balanceAfter).toBeLessThan(balanceBefore);
  });
});
