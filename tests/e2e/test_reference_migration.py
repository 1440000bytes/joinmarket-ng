"""Reference-wallet migration regression: legacy JAM wallet to NG maker."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass

import pytest
from loguru import logger

from tests.e2e.docker_utils import get_compose_cmd_prefix

pytestmark = pytest.mark.reference_migration


TEST_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
JAM_WALLET_PASSWORD = "migration-jam-password"
LEGACY_WALLET = "migration_legacy.jmdat"
TAKER_WALLET = "migration_taker.jmdat"
TAKER_WALLET_PASSWORD = "migration-taker-password"
NG_DATA_DIR = "/home/jm/.joinmarket-ng"
BOND_LOCKTIME = "2030-01"
BOND_AMOUNT_BTC = 1.0
DIRECT_SEND_COUNT = 30
DIRECT_SEND_AMOUNT_SATS = 20_000
COINJOIN_AMOUNT_SATS = 1_000_000
INFO_BUDGET_SECONDS = 180
BOND_RECOVERY_BUDGET_SECONDS = 180
MAKER_STARTUP_TIMEOUT_SECONDS = 180
COINJOIN_TIMEOUT_SECONDS = 300

TXID_PATTERN = re.compile(
    r'(?:txid|transaction id|transaction sent)"?\s*(?:=|:)\s*"?([0-9a-f]{64})\b',
    re.IGNORECASE,
)
MIXDEPTH_BALANCE_PATTERN = re.compile(
    r"Mixdepth\s+(\d+):\s+([\d,]+)\s+sats", re.IGNORECASE
)
BONDED_OFFER_PATTERN = re.compile(
    r"\bcreated offer \d+:.*\bbond_value=(\d+)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class CommandResult:
    """A completed external command and its wall-clock duration."""

    completed: subprocess.CompletedProcess[str]
    elapsed_seconds: float

    @property
    def output(self) -> str:
        return self.completed.stdout + self.completed.stderr


def _run_compose(
    args: list[str], *, timeout: int = 60, input_text: str | None = None
) -> CommandResult:
    """Run a Compose command through the suite-isolated Compose prefix."""
    started = time.monotonic()
    completed = subprocess.run(
        get_compose_cmd_prefix() + args,
        capture_output=True,
        check=False,
        input=input_text,
        text=True,
        timeout=timeout,
    )
    return CommandResult(
        completed=completed, elapsed_seconds=time.monotonic() - started
    )


def _run_service(
    service: str,
    args: list[str],
    *,
    timeout: int = 60,
    input_text: str | None = None,
) -> CommandResult:
    """Run a command in an already-running Compose service."""
    return _run_compose(
        ["exec", "-T", service, *args], timeout=timeout, input_text=input_text
    )


def _run_migration_wallet(args: list[str], *, timeout: int) -> CommandResult:
    """Run a one-off NG wallet CLI against migration-maker's persistent volume."""
    return _run_compose(
        ["run", "--rm", "--no-deps", "migration-maker", *args], timeout=timeout
    )


def _run_bitcoin(args: list[str], *, timeout: int = 60) -> CommandResult:
    """Run bitcoin-cli on the main regtest node."""
    return _run_service(
        "bitcoin",
        ["bitcoin-cli", "-regtest", "-rpcuser=test", "-rpcpassword=test", *args],
        timeout=timeout,
    )


def _run_bitcoin_jam(args: list[str], *, timeout: int = 60) -> CommandResult:
    """Run bitcoin-cli on JAM's regtest node."""
    return _run_service(
        "bitcoin-jam",
        [
            "bitcoin-cli",
            "-regtest",
            "-rpcuser=test",
            "-rpcpassword=test",
            "-rpcport=18445",
            *args,
        ],
        timeout=timeout,
    )


def _assert_ok(result: CommandResult, context: str) -> None:
    assert result.completed.returncode == 0, (
        f"{context} failed (exit {result.completed.returncode}) after "
        f"{result.elapsed_seconds:.1f}s:\n{result.output[-4000:]}"
    )


def _extract_txid(result: CommandResult, context: str) -> str:
    _assert_ok(result, context)
    matches = TXID_PATTERN.findall(result.output)
    assert matches, (
        f"{context} did not report a broadcast txid:\n{result.output[-4000:]}"
    )
    return matches[-1]


def _wait_for_nodes_to_sync(timeout: int = 60) -> None:
    """Require the main and JAM nodes to agree on their chain tip."""
    deadline = time.monotonic() + timeout
    last_main = "unavailable"
    last_jam = "unavailable"
    while time.monotonic() < deadline:
        main = _run_bitcoin(["getblockcount"])
        jam = _run_bitcoin_jam(["getblockcount"])
        if main.completed.returncode == 0:
            last_main = main.completed.stdout.strip()
        if jam.completed.returncode == 0:
            last_jam = jam.completed.stdout.strip()
        if (
            main.completed.returncode == 0
            and jam.completed.returncode == 0
            and last_main == last_jam
        ):
            return
        time.sleep(1)
    pytest.fail(
        f"Bitcoin nodes did not sync within {timeout}s: main={last_main}, jam={last_jam}"
    )


def _mine_confirmation_blocks(count: int = 1) -> None:
    """Mine confirmation blocks to test-funder and wait until JAM observes them."""
    assert count > 0
    miner_address = _run_bitcoin(
        ["-rpcwallet=test-funder", "getnewaddress", "", "bech32"]
    )
    _assert_ok(miner_address, "get test-funder mining address")
    mined = _run_bitcoin(
        ["generatetoaddress", str(count), miner_address.completed.stdout.strip()],
        timeout=120,
    )
    _assert_ok(mined, "mine confirmation block")
    _wait_for_nodes_to_sync()


def _fund_address(address: str, amount_btc: float, context: str) -> str:
    """Fund one address from the pre-funded, mature Core wallet."""
    funded = _run_bitcoin(
        ["-rpcwallet=test-funder", "sendtoaddress", address, f"{amount_btc:.8f}"],
        timeout=60,
    )
    _assert_ok(funded, context)
    txid = funded.completed.stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{64}", txid), (
        f"{context} returned invalid txid: {txid!r}"
    )
    return txid


def _remove_jam_wallet(wallet_name: str) -> None:
    """Remove files and locks so fresh Compose volumes remain rerunnable."""
    removed = _run_service(
        "jam",
        [
            "rm",
            "-f",
            f"/root/.joinmarket-ng/wallets/{wallet_name}",
            f"/root/.joinmarket-ng/wallets/.{wallet_name}.lock",
        ],
    )
    _assert_ok(removed, f"remove stale JAM wallet {wallet_name}")


def _recover_legacy_wallet() -> None:
    _remove_jam_wallet(LEGACY_WALLET)
    recovered = _run_service(
        "jam",
        [
            "expect",
            "/scripts/recover_wallet_with_passphrase.exp",
            TEST_MNEMONIC,
            "",
            JAM_WALLET_PASSWORD,
            LEGACY_WALLET,
        ],
        timeout=180,
    )
    _assert_ok(recovered, "restore legacy JAM wallet")


def _jam_wallet_address(wallet_name: str, password: str, mixdepth: int) -> str:
    """Obtain a JAM external receive address for one mixdepth."""
    displayed = _run_service(
        "jam",
        [
            "python3",
            "/src/scripts/wallet-tool.py",
            "--datadir=/root/.joinmarket-ng",
            "--wallet-password-stdin",
            f"/root/.joinmarket-ng/wallets/{wallet_name}",
            "display",
        ],
        timeout=120,
        input_text=f"{password}\n",
    )
    _assert_ok(displayed, f"display JAM wallet {wallet_name}")
    derivation = f"/{mixdepth}'/0/"
    for line in displayed.completed.stdout.splitlines():
        if derivation not in line:
            continue
        for value in line.split():
            if value.startswith("bcrt1"):
                return value
    raise AssertionError(
        f"No mixdepth {mixdepth} external address in JAM wallet display:\n"
        f"{displayed.output[-4000:]}"
    )


def _jam_bond_address() -> str:
    """Derive the canonical future JAM fidelity-bond address."""
    result = _run_service(
        "jam",
        [
            "python3",
            "/src/scripts/wallet-tool.py",
            "--datadir=/root/.joinmarket-ng",
            "--wallet-password-stdin",
            f"/root/.joinmarket-ng/wallets/{LEGACY_WALLET}",
            "gettimelockaddress",
            BOND_LOCKTIME,
        ],
        timeout=120,
        input_text=f"{JAM_WALLET_PASSWORD}\n",
    )
    _assert_ok(result, "derive JAM fidelity-bond address")
    for line in result.completed.stdout.splitlines():
        candidate = line.strip()
        if candidate.startswith("bcrt1q") and len(candidate) > 50:
            return candidate
    raise AssertionError(
        f"JAM did not return a P2WSH bond address:\n{result.output[-4000:]}"
    )


def _run_jam_direct_send(wallet_name: str, destination: str) -> str:
    """Create one zero-counterparty JAM send and return its asserted txid."""
    result = _run_service(
        "jam",
        [
            "python3",
            "/src/scripts/sendpayment.py",
            "--datadir=/root/.joinmarket-ng",
            "--wallet-password-stdin",
            "-N",
            "0",
            "-m",
            "0",
            f"/root/.joinmarket-ng/wallets/{wallet_name}",
            str(DIRECT_SEND_AMOUNT_SATS),
            destination,
            "--yes",
        ],
        timeout=120,
        input_text=f"{JAM_WALLET_PASSWORD}\n",
    )
    return _extract_txid(result, "JAM direct send")


def _create_jam_taker_wallet() -> None:
    _remove_jam_wallet(TAKER_WALLET)
    created = _run_service(
        "jam",
        ["expect", "/scripts/create_wallet.exp", TAKER_WALLET_PASSWORD, TAKER_WALLET],
        timeout=180,
    )
    _assert_ok(created, "create separate JAM taker wallet")


def _stop_conflicting_makers() -> None:
    """Ensure the reference taker can select only migration-maker."""
    services = (
        "maker",
        "maker1",
        "maker2",
        "maker3",
        "maker4",
        "maker5",
        "maker-neutrino",
    )
    stopped = _run_compose(["stop", *services], timeout=60)
    _assert_ok(stopped, "stop conflicting makers")
    for service in services:
        running = _run_compose(["ps", "-q", service])
        _assert_ok(running, f"check {service} is stopped")
        assert not running.completed.stdout.strip(), (
            f"Conflicting maker {service} is still running"
        )


def _assert_required_services() -> None:
    """Fail, rather than skip, when the explicitly provisioned E2E stack is absent."""
    for service in (
        "bitcoin",
        "bitcoin-jam",
        "miner",
        "miner-jam",
        "directory",
        "tor",
        "jam",
    ):
        running = _run_compose(["ps", "-q", service])
        _assert_ok(running, f"check required service {service}")
        assert running.completed.stdout.strip(), (
            f"Required migration service {service!r} is not running. "
            "Start the reference_migration Compose stack before this test."
        )


def _parse_mixdepth_balances(output: str) -> dict[int, int]:
    return {
        int(mixdepth): int(balance.replace(",", ""))
        for mixdepth, balance in MIXDEPTH_BALANCE_PATTERN.findall(output)
    }


def _migration_maker_is_ready(logs: str) -> bool:
    """Require a bonded offer plus a live announcement and listener."""
    lowered = logs.lower()
    has_bonded_offer = any(
        int(value) > 0 for value in BONDED_OFFER_PATTERN.findall(logs)
    )
    has_announcement = "announcing offers" in lowered
    has_listener = "maker bot started. listening for takers" in lowered
    return has_bonded_offer and has_announcement and has_listener


def _wait_for_migration_maker() -> str:
    """Wait for the migrated maker to offer its bond and serve takers."""
    deadline = time.monotonic() + MAKER_STARTUP_TIMEOUT_SECONDS
    latest_logs = ""
    while time.monotonic() < deadline:
        logs = _run_compose(["logs", "--tail=300", "migration-maker"])
        _assert_ok(logs, "read migration-maker logs")
        latest_logs = logs.output
        if _migration_maker_is_ready(latest_logs):
            return latest_logs
        time.sleep(2)
    raise AssertionError(
        "migration-maker did not create and announce a bonded offer and listen "
        f"within {MAKER_STARTUP_TIMEOUT_SECONDS}s:\n{latest_logs[-6000:]}"
    )


def test_migration_maker_readiness_requires_bonded_operational_offer() -> None:
    ready_logs = (
        "Created offer 0: type=sw0absoffer size=1000000-2000000 "
        "(max_available=2000000), cjfee=0.0003, txfee=1000, bond_value=50000000\n"
        "Announcing offers...\n"
        "Maker bot started. Listening for takers...\n"
    )

    assert _migration_maker_is_ready(ready_logs)
    assert not _migration_maker_is_ready(
        ready_logs.replace("bond_value=50000000", "bond_value=0")
    )
    assert not _migration_maker_is_ready(ready_logs.replace("Announcing offers...", ""))
    assert not _migration_maker_is_ready(
        ready_logs.replace("Maker bot started. Listening for takers...", "")
    )


def _run_reference_coinjoin(destination: str) -> str:
    """Run the reference taker against the single migrated NG maker."""
    configure_taker = _run_service(
        "jam",
        [
            "sh",
            "-c",
            "sed -i 's/^minimum_makers = 2$/minimum_makers = 1/' "
            "/root/.joinmarket-ng/joinmarket.cfg && "
            "grep -q '^minimum_makers = 1$' /root/.joinmarket-ng/joinmarket.cfg",
        ],
    )
    _assert_ok(configure_taker, "configure reference taker for one maker")

    try:
        result = _run_service(
            "jam",
            [
                "python3",
                "/src/scripts/sendpayment.py",
                "--datadir=/root/.joinmarket-ng",
                "--wallet-password-stdin",
                "-N",
                "1",
                "-m",
                "0",
                f"/root/.joinmarket-ng/wallets/{TAKER_WALLET}",
                str(COINJOIN_AMOUNT_SATS),
                destination,
                "--yes",
            ],
            timeout=COINJOIN_TIMEOUT_SECONDS,
            input_text=f"{TAKER_WALLET_PASSWORD}\n",
        )
    except subprocess.TimeoutExpired as error:
        _run_service(
            "jam", ["bash", "-c", "pkill -f sendpayment.py || true"], timeout=30
        )
        pytest.fail(
            f"Reference N=1 CoinJoin exceeded {COINJOIN_TIMEOUT_SECONDS}s: "
            f"{error.stdout!r}\n{error.stderr!r}"
        )
    return _extract_txid(result, "reference N=1 CoinJoin")


@pytest.mark.timeout(1200)
def test_migrate_active_reference_wallet_and_make_coinjoin() -> None:
    """Migrate an active JAM wallet by mnemonic alone and use it as a bonded maker."""
    _assert_required_services()
    _stop_conflicting_makers()

    already_running = _run_compose(["ps", "-q", "migration-maker"])
    _assert_ok(already_running, "check migration-maker is initially stopped")
    assert not already_running.completed.stdout.strip(), (
        "migration-maker must remain stopped until the migration test starts it"
    )

    _recover_legacy_wallet()
    legacy_addresses = {
        mixdepth: _jam_wallet_address(LEGACY_WALLET, JAM_WALLET_PASSWORD, mixdepth)
        for mixdepth in (0, 2, 4)
    }
    for mixdepth, address in legacy_addresses.items():
        _fund_address(address, 2.0, f"fund legacy mixdepth {mixdepth}")
    _mine_confirmation_blocks()

    direct_txids: list[str] = []
    for send_number in range(DIRECT_SEND_COUNT):
        destination = _run_bitcoin(
            ["-rpcwallet=test-funder", "getnewaddress", "", "bech32"]
        )
        _assert_ok(
            destination, f"create external address for direct send {send_number + 1}"
        )
        direct_txids.append(
            _run_jam_direct_send(LEGACY_WALLET, destination.completed.stdout.strip())
        )
        if (send_number + 1) % 5 == 0:
            _mine_confirmation_blocks()
    assert len(direct_txids) == DIRECT_SEND_COUNT
    assert len(set(direct_txids)) == DIRECT_SEND_COUNT, "JAM direct sends reused a txid"

    bond_address = _jam_bond_address()
    _fund_address(bond_address, BOND_AMOUNT_BTC, "fund future JAM fidelity bond")
    _mine_confirmation_blocks()

    reference_display = _run_service(
        "jam",
        [
            "python3",
            "/src/scripts/wallet-tool.py",
            "--datadir=/root/.joinmarket-ng",
            "--wallet-password-stdin",
            f"/root/.joinmarket-ng/wallets/{LEGACY_WALLET}",
            "display",
        ],
        timeout=120,
        input_text=f"{JAM_WALLET_PASSWORD}\n",
    )
    _assert_ok(
        reference_display, "record reference wallet balances after history generation"
    )

    imported = _run_compose(
        [
            "run",
            "--rm",
            "--no-deps",
            "-e",
            f"MNEMONIC={TEST_MNEMONIC}",
            "migration-maker",
            "jm-wallet",
            "import",
            "--words",
            "12",
            "--no-prompt-password",
            "--force",
            "--data-dir",
            NG_DATA_DIR,
        ],
        timeout=120,
    )
    _assert_ok(imported, "mnemonic-only NG CLI import")
    assert "Mnemonic saved to:" in imported.output, imported.output[-4000:]

    info = _run_migration_wallet(
        [
            "jm-wallet",
            "info",
            "--network",
            "regtest",
            "--data-dir",
            NG_DATA_DIR,
        ],
        timeout=INFO_BUDGET_SECONDS,
    )
    _assert_ok(info, "first migrated jm-wallet info")
    assert info.elapsed_seconds <= INFO_BUDGET_SECONDS, (
        f"first jm-wallet info exceeded {INFO_BUDGET_SECONDS}s: {info.elapsed_seconds:.1f}s"
    )
    migrated_balances = _parse_mixdepth_balances(info.output)
    for mixdepth in (0, 2, 4):
        assert migrated_balances.get(mixdepth, 0) > 0, (
            f"migrated jm-wallet info did not show a positive mixdepth {mixdepth} balance. "
            f"Reference display:\n{reference_display.output[-2000:]}\n"
            f"NG info:\n{info.output[-4000:]}"
        )

    recovered_bonds = _run_migration_wallet(
        [
            "jm-wallet",
            "recover-bonds",
            "--network",
            "regtest",
            "--data-dir",
            NG_DATA_DIR,
        ],
        timeout=BOND_RECOVERY_BUDGET_SECONDS,
    )
    _assert_ok(recovered_bonds, "one-pass migrated fidelity-bond recovery")
    assert recovered_bonds.elapsed_seconds <= BOND_RECOVERY_BUDGET_SECONDS, (
        f"recover-bonds exceeded {BOND_RECOVERY_BUDGET_SECONDS}s: "
        f"{recovered_bonds.elapsed_seconds:.1f}s"
    )
    assert "Discovered 1 fidelity bond address(es)" in recovered_bonds.output, (
        f"Expected exactly one recovered fidelity bond:\n{recovered_bonds.output[-4000:]}"
    )
    assert bond_address in recovered_bonds.output, recovered_bonds.output[-4000:]
    assert "1.00000000 BTC" in recovered_bonds.output, recovered_bonds.output[-4000:]

    started = _run_compose(["up", "-d", "migration-maker"], timeout=120)
    _assert_ok(started, "start migrated maker")
    _wait_for_migration_maker()

    _create_jam_taker_wallet()
    taker_address = _jam_wallet_address(TAKER_WALLET, TAKER_WALLET_PASSWORD, 0)
    _fund_address(taker_address, 2.0, "fund separate JAM taker wallet")
    _mine_confirmation_blocks(5)
    destination = _run_bitcoin(
        ["-rpcwallet=test-funder", "getnewaddress", "", "bech32"]
    )
    _assert_ok(destination, "create external CoinJoin destination")
    coinjoin_txid = _run_reference_coinjoin(destination.completed.stdout.strip())
    assert re.fullmatch(r"[0-9a-f]{64}", coinjoin_txid), coinjoin_txid
    _mine_confirmation_blocks()

    maker_logs = _run_compose(["logs", "--tail=300", "migration-maker"])
    _assert_ok(maker_logs, "read migrated maker CoinJoin logs")
    if (
        "coinjoin with" not in maker_logs.output.lower()
        or "complete" not in maker_logs.output.lower()
    ):
        logger.warning(
            "CoinJoin broadcast succeeded but maker completion was not retained in log tail"
        )
