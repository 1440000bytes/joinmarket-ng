/**
 * E2E test: Start maker and verify offer loads.
 *
 * This test validates the fix for the "Loading offer..." forever bug.
 * After starting the maker bot, the offer should appear in the session
 * and the Earn tab should display the offer details instead of showing
 * "Loading offer..." indefinitely.
 */

import { test, expect, loginViaUI } from "../fixtures";

test.describe("Maker / Earn", () => {
  test("start maker via UI and verify offer is displayed", async ({
    page,
    fundedWallet,
  }) => {
    // Log in with the funded wallet.
    await loginViaUI(page, fundedWallet.walletName, fundedWallet.password);

    // Navigate to the Earn tab directly to avoid matching Cheatsheet links.
    await page.goto("/earn", { waitUntil: "domcontentloaded", timeout: 15_000 });

    // Dismiss the Cheatsheet dialog which opens on every page navigation.
    // The × close button is an absolutely-positioned button in the dialog's
    // top-right corner. Click it directly by bounding box offset.
    for (let i = 0; i < 6; i++) {
      await page.waitForTimeout(500);
      const dialog = page.locator('[role="dialog"]:visible').first();
      if (!(await dialog.isVisible().catch(() => false))) break;

      // Try clicking the × button: it's the only <button> that is absolutely
      // positioned, always at top-right. Use the bounding box of the dialog
      // and click near its top-right corner.
      const box = await dialog.boundingBox();
      if (box) {
        // Click just inside the top-right corner (close button zone).
        await page.mouse.click(box.x + box.width - 20, box.y + 20);
        await page.waitForTimeout(600);
        continue;
      }
      // Fallback: Escape
      await page.keyboard.press("Escape");
      await page.waitForTimeout(600);
    }

    // Fill in the earn form with an absolute fee offer.
    // The inputs start disabled while the form loads wallet state — wait for enabled.
    // Use force:true to bypass any lingering Radix backdrop that intercepts pointer events.
    const feeInput = page.locator("#offerAbsoluteFee");
    await expect(feeInput).toBeEnabled({ timeout: 20_000 });
    await feeInput.fill("250");

    const minAmountInput = page.locator("#offerMinAmount");
    await minAmountInput.fill("100000");

    // Click "Start Earning!" — force:true to bypass any backdrop.
    await page.getByRole("button", { name: "Start Earning!" }).click({ force: true });

    // The maker should start. We might briefly see "Waiting for maker
    // to start..." or "Loading offer..." but it should resolve.

    // BUG FIX VALIDATION: The offer card should appear within a
    // reasonable time, NOT stay at "Loading offer..." forever.
    await expect(page.getByText("Offer Id")).toBeVisible({
      timeout: 90_000,
    });

    // Verify the offer card displays the expected details.
    await expect(page.getByText("absolute")).toBeVisible();
    await expect(page.getByText("Minimum Size")).toBeVisible();
    await expect(page.getByText("Maximum Size")).toBeVisible();
    await expect(page.getByText("Transaction Fee")).toBeVisible();

    // The "Loading offer..." text should NOT be visible.
    await expect(page.getByText("Loading offer...")).not.toBeVisible();

    // Take a screenshot to verify the offer card.
    await page.screenshot({
      path: "test-results/maker-offer-displayed.png",
      fullPage: true,
    });

    // Stop the maker.
    await page.getByRole("button", { name: "Stop" }).click();

    // Wait for the maker to stop - the form should reappear.
    await expect(
      page.getByRole("button", { name: "Start Earning!" }),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("offer_list is populated in session API after maker starts", async ({
    fundedWallet,
    walletApi,
  }) => {
    const { token } = fundedWallet;

    // Start the maker via API.
    await walletApi.startMaker(token, {
      ordertype: "sw0absoffer",
      cjfee_a: 250,
      minsize: 100_000,
    });

    // Wait for the session to show maker_running with offers.
    const session = await walletApi.waitForSession(
      token,
      (s) =>
        s.maker_running === true &&
        Array.isArray(s.offer_list) &&
        s.offer_list.length > 0,
      90_000,
    );

    // Validate the offer list.
    expect(session.offer_list).not.toBeNull();
    expect(session.offer_list!.length).toBeGreaterThan(0);

    const offer = session.offer_list![0];
    expect(offer.ordertype).toBe("sw0absoffer");
    expect(offer.cjfee).toBeTruthy();
    expect(Number(offer.minsize)).toBeGreaterThanOrEqual(100_000);

    // Stop the maker.
    await walletApi.stopMaker(token);

    // Verify maker stops.
    const stopped = await walletApi.waitForSession(
      token,
      (s) => s.maker_running === false,
      30_000,
    );
    expect(stopped.maker_running).toBe(false);
  });
});
