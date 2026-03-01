/**
 * Bitcoin Core RPC helper for test setup only (mining blocks, funding wallets).
 * Not used for any user-facing interactions.
 *
 * Uses the `fidelity_funder` wallet which is pre-funded by the compose setup
 * and has spendable UTXOs regardless of current block height / halvings.
 */

const BITCOIN_RPC_URL = process.env.BITCOIN_RPC_URL || "http://localhost:18443";
const BITCOIN_RPC_USER = process.env.BITCOIN_RPC_USER || "test";
const BITCOIN_RPC_PASS = process.env.BITCOIN_RPC_PASS || "test";
// fidelity_funder is funded by the wallet-funder compose service and has
// spendable BTC at any block height.
const BITCOIN_RPC_WALLET = process.env.BITCOIN_RPC_WALLET || "fidelity_funder";

let rpcId = 0;

const AUTH = "Basic " + Buffer.from(`${BITCOIN_RPC_USER}:${BITCOIN_RPC_PASS}`).toString("base64");

async function rpcWallet<T = unknown>(
  wallet: string,
  method: string,
  params: unknown[] = [],
): Promise<T> {
  const res = await fetch(`${BITCOIN_RPC_URL}/wallet/${wallet}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: AUTH },
    body: JSON.stringify({ jsonrpc: "2.0", id: ++rpcId, method, params }),
  });
  if (!res.ok) throw new Error(`Bitcoin RPC ${method} HTTP ${res.status}`);
  const data: { result: T; error: { message: string } | null } = await res.json();
  if (data.error) throw new Error(`Bitcoin RPC ${method}: ${data.error.message}`);
  return data.result;
}

async function rpcBase<T = unknown>(method: string, params: unknown[] = []): Promise<T> {
  const res = await fetch(BITCOIN_RPC_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: AUTH },
    body: JSON.stringify({ jsonrpc: "2.0", id: ++rpcId, method, params }),
  });
  if (!res.ok) throw new Error(`Bitcoin RPC ${method} HTTP ${res.status}`);
  const data: { result: T; error: { message: string } | null } = await res.json();
  if (data.error) throw new Error(`Bitcoin RPC ${method}: ${data.error.message}`);
  return data.result;
}

/** Generic wallet-scoped RPC call using the default BITCOIN_RPC_WALLET. */
export async function rpc<T = unknown>(method: string, params: unknown[] = []): Promise<T> {
  return rpcWallet<T>(BITCOIN_RPC_WALLET, method, params);
}

/** Mine `count` blocks; rewards go to the fidelity_funder wallet. */
export async function mineBlocks(count: number): Promise<void> {
  const addr = await rpcWallet<string>(BITCOIN_RPC_WALLET, "getnewaddress");
  await rpcBase("generatetoaddress", [count, addr]);
}

/**
 * Mine `count` blocks directly to a specific address.
 * Uses the base (no-wallet) endpoint so any address works.
 */
export async function generateToAddress(count: number, address: string): Promise<void> {
  await rpcBase("generatetoaddress", [count, address]);
}

/**
 * Send BTC to an address using the fidelity_funder wallet.
 * Returns the txid.
 */
export async function sendToAddress(address: string, amountBtc: number): Promise<string> {
  return rpcWallet<string>(BITCOIN_RPC_WALLET, "sendtoaddress", [address, amountBtc]);
}

export async function getBlockCount(): Promise<number> {
  return rpcBase<number>("getblockcount");
}
