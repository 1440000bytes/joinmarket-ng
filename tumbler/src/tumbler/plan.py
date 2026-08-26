"""
Tumbler plan data model.

A ``Plan`` is an ordered list of ``Phase`` objects. Each phase is one of:

* :class:`TakerCoinjoinPhase` - a single taker CoinJoin (optionally sweep).
* :class:`MakerSessionPhase` - run a maker bot for a bounded time or
  until a target number of CoinJoins complete.

The plan and its phases form the single source of truth for a running
tumble. Progress is persisted to a YAML file (see :mod:`tumbler.persistence`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from jmcore.bitcoin import address_to_scriptpubkey_for_network
from pydantic import BaseModel, Field, model_validator


class PhaseKind(StrEnum):
    """Discriminator for the phase variants."""

    TAKER_COINJOIN = "taker_coinjoin"
    MAKER_SESSION = "maker_session"


class PhaseStatus(StrEnum):
    """Lifecycle of an individual phase.

    ``AWAITING_CONFIRMATION`` marks a taker transaction that broadcast but has
    not passed the inter-phase confirmation gate. ``SKIPPED`` marks a taker
    phase whose source mixdepth had no spendable
    funds at execution time (for example, all UTXOs were frozen after the
    plan was built, or the mixdepth never received coins). Skipped phases
    are terminal like ``COMPLETED`` and do not fail the plan.
    """

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class PlanStatus(StrEnum):
    """Lifecycle of the overall plan."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Recommended minimum number of external destination addresses for a plan.
#
# Three destinations guarantee that the final funds cannot be trivially
# re-aggregated by correlating two sweeps: with only two destinations, an
# observer who identifies one recipient can deduce the other. Three breaks
# pairwise identifiability and matches the reference tumbler's recommendation.
#
# This is only enforced at the CLI boundary; library consumers (the
# ``jmwalletd`` API, tests, development tooling, JAM v2 which sends to a
# single address) may pass fewer destinations. Protocol-level validation
# only requires ``>= 1`` here.
MIN_DESTINATIONS = 3
INTERNAL_DESTINATION = "INTERNAL"
BitcoinNetwork = Literal["mainnet", "testnet", "signet", "regtest"]


def validate_tumbler_destinations(
    destinations: list[str], network: BitcoinNetwork | None = None
) -> None:
    """Validate user-supplied external tumbler destinations.

    Networkless plans retain compatibility with older callers that use
    synthetic addresses, but still reject empty, sentinel, and obvious
    textual duplicates. Network-aware validation compares decoded scripts so
    equivalent address encodings cannot be used as distinct exits.
    """
    textual_destinations: dict[str, int] = {}
    script_destinations: dict[bytes, int] = {}
    for index, destination in enumerate(destinations):
        if not destination or not destination.strip():
            raise ValueError(f"invalid destination at position {index + 1}: address is empty")
        if destination.casefold() == INTERNAL_DESTINATION.casefold():
            raise ValueError(
                f"invalid destination at position {index + 1}: INTERNAL is not external"
            )

        lower_destination = destination.lower()
        is_bech32_candidate = lower_destination.startswith(("bc1", "tb1", "bcrt1"))
        is_uniform_case = destination == lower_destination or destination == destination.upper()
        textual_key = lower_destination if is_bech32_candidate and is_uniform_case else destination
        previous_index = textual_destinations.get(textual_key)
        if previous_index is not None:
            raise ValueError(
                f"duplicate destination at positions {previous_index + 1} and {index + 1}"
            )
        textual_destinations[textual_key] = index

        if network is None:
            continue
        try:
            scriptpubkey = address_to_scriptpubkey_for_network(destination, network)
        except ValueError as exc:
            raise ValueError(f"invalid destination at position {index + 1}") from exc
        previous_index = script_destinations.get(scriptpubkey)
        if previous_index is not None:
            raise ValueError(
                f"duplicate destination at positions {previous_index + 1} and {index + 1}"
            )
        script_destinations[scriptpubkey] = index


class _PhaseBase(BaseModel):
    """Fields shared by every phase variant."""

    index: int = Field(..., ge=0, description="Zero-based position within the plan.")
    status: PhaseStatus = PhaseStatus.PENDING
    wait_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Delay to sleep after this phase completes, before the next starts.",
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    # Retry bookkeeping (taker phases only use this; maker phases ignore it).
    attempt_count: int = Field(
        default=0,
        ge=0,
        description="Number of attempts made for this phase (for retry tracking).",
    )


class TakerCoinjoinPhase(_PhaseBase):
    """A single taker CoinJoin."""

    kind: Literal[PhaseKind.TAKER_COINJOIN] = PhaseKind.TAKER_COINJOIN
    mixdepth: int = Field(..., ge=0, le=9)
    # Exactly one of amount / amount_fraction must be set (validated below).
    amount: int | None = Field(default=None, ge=0)
    amount_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    counterparty_count: int = Field(..., ge=1, le=20)
    destination: str = Field(
        ...,
        description="A bitcoin address, or the sentinel 'INTERNAL' to pick the "
        "next mixdepth's internal address at execution time.",
    )
    txid: str | None = Field(
        default=None, description="Broadcast txid, set once the CoinJoin is broadcast."
    )
    rounding_sigfigs: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description=(
            "If set, round the resolved sat amount to this many significant "
            "figures before dispatching to the taker. Mirrors the reference "
            "implementation's ``rounding`` schedule entry: a sub-BTC amount "
            "like 0.13256 BTC rounded to 2 sigfigs becomes 0.13 BTC, which "
            "obfuscates the relationship between the wallet balance and the "
            "CoinJoin amount. Sweeps (amount==0 / amount_fraction==0) ignore "
            "this field."
        ),
    )

    @model_validator(mode="after")
    def _validate_amount(self) -> TakerCoinjoinPhase:
        if self.amount is None and self.amount_fraction is None:
            raise ValueError("TakerCoinjoinPhase requires 'amount' or 'amount_fraction'")
        if self.amount is not None and self.amount_fraction is not None:
            raise ValueError("TakerCoinjoinPhase must not set both 'amount' and 'amount_fraction'")
        return self

    @property
    def is_sweep(self) -> bool:
        """A sweep empties the mixdepth: amount==0 or amount_fraction==0."""
        return (self.amount == 0) or (self.amount_fraction == 0.0)


class MakerSessionPhase(_PhaseBase):
    """
    Run a maker bot as part of the tumble.

    The session ends when any configured bound is reached: ``duration_seconds``
    elapses, ``target_cj_count`` CoinJoins have been served, or no CoinJoin has
    been served for ``idle_timeout_seconds`` (whichever comes first). At least
    one of ``duration_seconds`` or ``target_cj_count`` must be set;
    ``idle_timeout_seconds`` is an optional safety fallback so the phase does
    not hang forever when the maker is never chosen as counterparty.
    """

    kind: Literal[PhaseKind.MAKER_SESSION] = PhaseKind.MAKER_SESSION
    duration_seconds: float | None = Field(default=None, gt=0.0)
    target_cj_count: int | None = Field(default=None, ge=1)
    idle_timeout_seconds: float | None = Field(default=None, gt=0.0)
    cj_served: int = Field(default=0, ge=0, description="CoinJoins served so far.")

    @model_validator(mode="after")
    def _validate_bound(self) -> MakerSessionPhase:
        if self.duration_seconds is None and self.target_cj_count is None:
            raise ValueError("MakerSessionPhase requires 'duration_seconds' or 'target_cj_count'")
        return self


Phase = Annotated[
    TakerCoinjoinPhase | MakerSessionPhase,
    Field(discriminator="kind"),
]


class PlanParameters(BaseModel):
    """
    User-facing knobs captured for audit and resume. The builder records
    what it was told; the runner does not re-derive phases from these.
    """

    maker_count_min: int = Field(default=5, ge=1, le=20)
    maker_count_max: int = Field(default=9, ge=1, le=20)
    time_lambda_seconds: float = Field(default=6.0 * 60.0 * 60.0, gt=0.0)
    include_maker_sessions: bool = True
    mincjamount_sats: int = Field(default=100_000, ge=0)
    max_phase_retries: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Maximum number of re-tries for a failed taker CoinJoin phase. "
        "Exhausting retries fails the entire plan.",
    )
    seed: int | None = None

    @model_validator(mode="after")
    def _validate_maker_count(self) -> PlanParameters:
        if self.maker_count_max < self.maker_count_min:
            raise ValueError("maker_count_max must be >= maker_count_min")
        return self


class Plan(BaseModel):
    """A tumble plan with per-phase progress tracking."""

    plan_id: str = Field(default_factory=lambda: uuid4().hex)
    wallet_name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: PlanStatus = PlanStatus.PENDING
    destinations: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "External destination addresses. "
            f"The CLI enforces at least {MIN_DESTINATIONS} to avoid pairwise "
            "re-aggregation heuristics; library consumers may pass fewer."
        ),
    )
    network: BitcoinNetwork | None = None
    parameters: PlanParameters = Field(default_factory=PlanParameters)
    phases: list[Phase] = Field(default_factory=list)
    current_phase: int = Field(
        default=0,
        ge=0,
        description="Index of the next phase to run (0 == plan not started).",
    )
    error: str | None = None
    previous_phase_maker_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_phase_indices(self) -> Plan:
        validate_tumbler_destinations(self.destinations, self.network)
        for i, phase in enumerate(self.phases):
            if phase.index != i:
                raise ValueError(
                    f"phases[{i}].index must equal its list position (got {phase.index})"
                )
        if self.current_phase > len(self.phases):
            raise ValueError("current_phase exceeds number of phases")
        return self

    def current(self) -> Phase | None:
        """Return the phase at ``current_phase``, or ``None`` if the plan is done."""
        if self.current_phase >= len(self.phases):
            return None
        return self.phases[self.current_phase]

    def touch(self) -> None:
        """Update ``updated_at`` to now (UTC)."""
        self.updated_at = datetime.now(UTC)


def is_safely_resumable_confirmation_wait(plan: Plan) -> bool:
    """Return whether ``plan`` can resume at its confirmation gate only.

    This intentionally recognizes only a current taker phase with a persisted
    broadcast txid. Older persisted plans recorded that phase as ``COMPLETED``
    before the confirmation gate; that representation is safe only when a
    later phase proves the plan had not finished.
    """
    current = plan.current()
    if not isinstance(current, TakerCoinjoinPhase) or not current.txid:
        return False
    if current.status == PhaseStatus.AWAITING_CONFIRMATION:
        return True
    return current.status == PhaseStatus.COMPLETED and plan.current_phase + 1 < len(plan.phases)


def reset_plan_for_resume(plan: Plan) -> int:
    """Reset a terminal-state plan so the runner can pick it up again.

    Completed, skipped, and confirmation-waiting phases are preserved; FAILED,
    RUNNING, and CANCELLED phases are rolled back to PENDING with cleared
    error/timestamp metadata so the runner re-attempts them. ``current_phase``
    is moved to the first non-terminal phase and the plan status is reset to
    PENDING.

    Returns the number of phases that were rolled back.
    """
    rollback_statuses = {PhaseStatus.FAILED, PhaseStatus.RUNNING, PhaseStatus.CANCELLED}
    rolled_back = 0
    first_pending: int | None = None

    # Migrate plans persisted by older runners after broadcast but before the
    # confirmation gate. At that point the current phase was incorrectly
    # labelled COMPLETED even though ``current_phase`` had not advanced.
    current = plan.current()
    if (
        isinstance(current, TakerCoinjoinPhase)
        and current.status == PhaseStatus.COMPLETED
        and current.txid
        and plan.current_phase + 1 < len(plan.phases)
    ):
        current.status = PhaseStatus.AWAITING_CONFIRMATION
        current.finished_at = None

    for index, phase in enumerate(plan.phases):
        if phase.status in rollback_statuses:
            phase.status = PhaseStatus.PENDING
            phase.error = None
            phase.started_at = None
            phase.finished_at = None
            # Keep ``attempt_count`` so retry budgets carry across resumes;
            # otherwise a stuck phase would silently get unlimited retries.
            rolled_back += 1
        if first_pending is None and phase.status not in (
            PhaseStatus.COMPLETED,
            PhaseStatus.SKIPPED,
        ):
            first_pending = index

    plan.current_phase = first_pending if first_pending is not None else len(plan.phases)
    plan.status = PlanStatus.PENDING
    plan.error = None
    plan.touch()
    return rolled_back


def round_to_significant_figures(value: int, sigfigs: int) -> int:
    """Round ``value`` to ``sigfigs`` significant figures in base 10.

    Mirrors ``round_to_significant_figures`` in the reference
    ``jmclient.taker``: the smallest power of ten greater than ``value`` is
    used as the scale, then the value is rounded to ``sigfigs`` sigfigs
    around it. Examples (``sigfigs=2``)::

        13_256_421 -> 13_000_000
        9_876      -> 9_900
        1_000_000  -> 1_000_000
        0          -> 0

    Raises ``ValueError`` if ``value`` is negative or ``sigfigs`` is not in
    ``[1, 8]`` (matching the model bounds).
    """
    if value < 0:
        raise ValueError("round_to_significant_figures requires a non-negative value")
    if not 1 <= sigfigs <= 8:
        raise ValueError("sigfigs must be in [1, 8]")
    if value == 0:
        return 0
    for p in range(-10, 20):
        power10 = 10**p
        if power10 > value:
            sf_power10 = 10**sigfigs
            return int(round(value / power10 * sf_power10) * power10 / sf_power10)
    raise RuntimeError("round_to_significant_figures: value out of range")
