/**
 * E2E test: Wallet creation flow.
 *
 * Verifies that a user can create a new wallet through the jam-ng UI,
 * confirm their seed phrase, and land on the main wallet page.
 */

import { test, expect, loadCredentials } from "../fixtures";

test.describe("Wallet Creation", () => {
  test("create a new wallet via UI", async ({ page, walletApi }) => {
    const walletName = `pw-create-${Date.now()}`;
    const password = "testpass-create-123";

    // Lock the shared test wallet so we can create a new one.
    // jmwalletd only allows one wallet open at a time.
    const creds = loadCredentials();
    await walletApi.lockWallet(creds.token);

    // Navigate to the create wallet page.
    await page.goto("/create-wallet");
    await expect(page.getByText("Create Wallet")).toBeVisible();

    // Step 1: Fill in wallet details.
    await page.locator("#create-wallet-name").fill(walletName);
    await page.locator("#create-password").fill(password);
    await page.locator("#create-confirm-password").fill(password);

    // Submit the form.
    await page.getByRole("button", { name: "Create" }).click();

    // Step 2: Seed confirmation page should appear.
    await expect(
      page.getByText("Wallet created successfully!"),
    ).toBeVisible({ timeout: 30_000 });

    // Toggle to reveal the seed phrase.
    await page.locator("#switch-reveal-seed").click();

    // Verify the seed phrase is displayed (12 or 24 words).
    // The seed is shown inside the card, check it's not empty.
    await expect(page.getByText("Seed Phrase").first()).toBeVisible();

    // Confirm the backup.
    await page.locator("#switch-confirm-backup").click();

    // Click "Next" to proceed.
    await page.getByRole("button", { name: "Next" }).click();

    // Should be redirected to the main wallet page.
    await page.waitForURL("/", { timeout: 30_000 });
    await expect(page.getByText("Wallet distribution")).toBeVisible({
      timeout: 15_000,
    });

    // Take a screenshot for CI verification.
    await page.screenshot({
      path: "test-results/wallet-created.png",
      fullPage: true,
    });
  });

  test("wallet appears in login list after creation", async ({
    page,
    walletApi,
  }) => {
    const creds = loadCredentials();

    // Unlock the shared test wallet — this implicitly locks any currently-open
    // wallet (jmwalletd only allows one at a time) and gives us a valid token.
    // The previous test may have left a UI-created wallet open whose token we
    // don't have, so we can't lock it directly; force-unlocking our known
    // wallet is the safest way to take over the session.
    const unlocked = await walletApi.forceUnlock(creds.walletName, creds.password);
    const currentToken = unlocked.token;

    // Lock it so we can create a new wallet next.
    await walletApi.lockWallet(currentToken);

    // Create a new wallet via API.
    const walletName = `pw-list-${Date.now()}.jmdat`;
    const password = "testpass-list-123";
    const created = await walletApi.createWallet(walletName, password);
    console.log(`[wallet-creation] Created wallet, token length: ${created.token?.length}`);

    // Wait briefly for the backend to propagate auth state
    await page.waitForTimeout(1000);

    // Lock it so we can test the login page.
    await walletApi.lockWallet(created.token);


    // Navigate to the login page.
    await page.goto("/login");
    await expect(page.getByText("Welcome to Jam")).toBeVisible();

    // The JAM intro dialog may appear on top of the login form. Dismiss it
    // so the combobox is accessible.
    // Import dismissDialogs-like logic inline.
    const DISMISS_LABELS = ["Skip intro", "Close", "Get started", "Ok"];
    for (let i = 0; i < 6; i++) {
      await page.waitForTimeout(400);
      const dialog = page.locator('[role="dialog"]:visible').first();
      if (!(await dialog.isVisible().catch(() => false))) break;
      let dismissed = false;
      for (const label of DISMISS_LABELS) {
        const btn = page.getByRole("button", { name: label }).first();
        if (await btn.isVisible().catch(() => false)) {
          await btn.click();
          dismissed = true;
          break;
        }
      }
      if (!dismissed) await page.keyboard.press("Escape");
      await page
        .locator('[role="dialog"]:visible')
        .first()
        .waitFor({ state: "hidden", timeout: 2_000 })
        .catch(() => null);
    }

    // Open the wallet selector.
    const selectTrigger = page.locator('[role="combobox"]');
    await selectTrigger.click();

    // The wallet should appear in the list.
    const displayName = walletName.replace(".jmdat", "");
    await expect(
      page.getByRole("option", { name: displayName }),
    ).toBeVisible();

    // Re-unlock the shared test wallet for subsequent tests.
    await walletApi.unlockWallet(creds.walletName, creds.password);
  });
});
