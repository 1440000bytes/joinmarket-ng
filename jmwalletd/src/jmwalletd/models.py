"""Pydantic request/response models for the wallet daemon API.

All models match the schemas defined in the reference JoinMarket OpenAPI spec
(jm-wallet-rpc.yaml) to ensure JAM compatibility.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared / Error
# ---------------------------------------------------------------------------


class ErrorMessage(BaseModel):
    """Standard error response body."""

    message: str = ""


# ---------------------------------------------------------------------------
# Token / Auth
# ---------------------------------------------------------------------------


class TokenRequest(BaseModel):
    """POST /api/v1/token request."""

    grant_type: str
    refresh_token: str


class TokenResponse(BaseModel):
    """Token issuance response (used by create, unlock, recover, refresh)."""

    walletname: str = ""
    token: str
    token_type: str = "bearer"
    expires_in: int = 1800
    scope: str = ""
    refresh_token: str


# ---------------------------------------------------------------------------
# Wallet lifecycle
# ---------------------------------------------------------------------------


class CreateWalletRequest(BaseModel):
    """POST /api/v1/wallet/create request."""

    walletname: str
    password: str
    wallettype: str = "sw-fb"


class CreateWalletResponse(BaseModel):
    """Response for wallet create and recover."""

    walletname: str
    seedphrase: str
    token: str
    token_type: str = "bearer"
    expires_in: int = 1800
    scope: str = ""
    refresh_token: str


class RecoverWalletRequest(BaseModel):
    """POST /api/v1/wallet/recover request."""

    walletname: str
    password: str
    wallettype: str = "sw-fb"
    seedphrase: str


class UnlockWalletRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/unlock request."""

    password: str


class UnlockWalletResponse(BaseModel):
    """Response for wallet unlock."""

    walletname: str
    token: str
    token_type: str = "bearer"
    expires_in: int = 1800
    scope: str = ""
    refresh_token: str


class LockWalletResponse(BaseModel):
    """Response for wallet lock."""

    walletname: str
    already_locked: bool


class ListWalletsResponse(BaseModel):
    """Response for GET /api/v1/wallet/all."""

    wallets: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Wallet info / display
# ---------------------------------------------------------------------------


class GetInfoResponse(BaseModel):
    """Response for GET /api/v1/getinfo."""

    version: str


class SessionResponse(BaseModel):
    """Response for GET /api/v1/session."""

    session: bool
    maker_running: bool
    coinjoin_in_process: bool
    schedule: list[list[str | int | float]] | None = None
    wallet_name: str = ""
    offer_list: list[dict[str, str | int | float]] | None = None
    nickname: str | None = None
    rescanning: bool = False
    block_height: int | None = None


class WalletDisplayEntry(BaseModel):
    """A single address entry in the wallet display."""

    hd_path: str
    address: str
    amount: str
    available_balance: str = "0.00000000"
    status: str = ""
    label: str = ""
    extradata: str = ""


class WalletDisplayBranch(BaseModel):
    """A branch (external/internal/bond) within an account."""

    branch: str
    balance: str
    available_balance: str = "0.00000000"
    entries: list[WalletDisplayEntry] = Field(default_factory=list)


class WalletDisplayAccount(BaseModel):
    """A single account (mixdepth) in the wallet display."""

    account: str
    account_balance: str
    available_balance: str = "0.00000000"
    branches: list[WalletDisplayBranch] = Field(default_factory=list)


class WalletInfo(BaseModel):
    """The walletinfo object within the display response."""

    wallet_name: str = "JM wallet"
    total_balance: str = "0.00000000"
    available_balance: str = "0.00000000"
    accounts: list[WalletDisplayAccount] = Field(default_factory=list)


class WalletDisplayResponse(BaseModel):
    """Response for GET /api/v1/wallet/{walletname}/display."""

    walletname: str
    walletinfo: WalletInfo


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


class GetAddressResponse(BaseModel):
    """Response for new address / timelock address requests."""

    address: str


# ---------------------------------------------------------------------------
# UTXOs
# ---------------------------------------------------------------------------


class UTXOEntry(BaseModel):
    """A single UTXO in the listutxos response."""

    utxo: str  # "txid:vout"
    address: str
    path: str
    label: str = ""
    value: int
    tries: int = 0
    tries_remaining: int = 3
    external: bool = False
    mixdepth: int
    confirmations: int
    frozen: bool = False


class ListUtxosResponse(BaseModel):
    """Response for GET /api/v1/wallet/{walletname}/utxos."""

    utxos: list[UTXOEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


class GetSeedResponse(BaseModel):
    """Response for GET /api/v1/wallet/{walletname}/getseed."""

    seedphrase: str


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TxInput(BaseModel):
    """A transaction input."""

    outpoint: str
    scriptSig: str = ""
    nSequence: int = 4294967295
    witness: str = ""


class TxOutput(BaseModel):
    """A transaction output."""

    value_sats: int
    scriptPubKey: str
    address: str


class TxInfo(BaseModel):
    """Full transaction information."""

    hex: str
    inputs: list[TxInput] = Field(default_factory=list)
    outputs: list[TxOutput] = Field(default_factory=list)
    txid: str
    nLockTime: int = 0
    nVersion: int = 2


class DirectSendRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/taker/direct-send request."""

    mixdepth: int
    amount_sats: int
    destination: str
    txfee: int | None = None


class DirectSendResponse(BaseModel):
    """Response for direct-send."""

    txinfo: TxInfo


# ---------------------------------------------------------------------------
# Coinjoin / Taker
# ---------------------------------------------------------------------------


class DoCoinjoinRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/taker/coinjoin request."""

    mixdepth: int
    amount_sats: int
    counterparties: int
    destination: str
    txfee: int | None = None


class TumblerOptions(BaseModel):
    """Optional tumbler configuration."""

    addrcount: int | None = None
    minmakercount: int | None = None
    makercountrange: list[int] | None = None
    mixdepthcount: int | None = None
    mintxcount: int | None = None
    txcountparams: list[int] | None = None
    timelambda: float | None = None
    stage1_timelambda_increase: float | None = None
    liquiditywait: int | None = None
    waittime: float | None = None
    mixdepthsrc: int | None = None
    restart: bool | None = None
    schedulefile: str | None = None
    mincjamount: int | None = None
    amtmixdepths: int | None = None
    rounding_chance: float | None = None
    rounding_sigfig_weights: list[int] | None = None


class RunScheduleRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/taker/schedule request."""

    destination_addresses: list[str] | None = None
    tumbler_options: TumblerOptions | None = None


class GetScheduleResponse(BaseModel):
    """Response for schedule get/start."""

    schedule: list[list[str | int | float]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Maker
# ---------------------------------------------------------------------------


class StartMakerRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/maker/start request.

    All fields are strings per the reference implementation.
    """

    txfee: str
    cjfee_a: str
    cjfee_r: str
    ordertype: str
    minsize: str


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ConfigGetRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/configget request."""

    section: str
    field: str


class ConfigGetResponse(BaseModel):
    """Response for configget."""

    configvalue: str


class ConfigSetRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/configset request."""

    section: str
    field: str
    value: str


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------


class FreezeRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/freeze request.

    Note: the field name uses a hyphen in the reference API JSON.
    We use Field(alias=...) to handle this.
    """

    utxo_string: str = Field(alias="utxo-string")
    freeze: bool

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Sign message
# ---------------------------------------------------------------------------


class SignMessageRequest(BaseModel):
    """POST /api/v1/wallet/{walletname}/signmessage request."""

    hd_path: str
    message: str


class SignMessageResponse(BaseModel):
    """Response for signmessage."""

    signature: str
    message: str
    address: str


# ---------------------------------------------------------------------------
# Rescan
# ---------------------------------------------------------------------------


class RescanBlockchainResponse(BaseModel):
    """Response for rescanblockchain."""

    walletname: str


class RescanInfoResponse(BaseModel):
    """Response for getrescaninfo."""

    rescanning: bool
    progress: float | None = None


# ---------------------------------------------------------------------------
# Yield generator report
# ---------------------------------------------------------------------------


class YieldGenReportResponse(BaseModel):
    """Response for yieldgen/report."""

    yigen_data: list[str] = Field(default_factory=list)
