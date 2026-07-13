"""
FastAPI application. Agents-first HTTP API for the futarchy prediction market.

Public endpoints (no auth): health, markets, market detail, positions, trades.
User endpoints (API key): /me, buy, sell.
Admin endpoints (admin key): mint, create market, resolve, void, tracked repos.
Webhook: POST /v1/hooks/github — receive GitHub PR events for tracked repos.
"""

import asyncio
import hashlib
import hmac
import logging
import math
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from exchange.core.api_errors import (
    APIError, api_error_handler, translate_engine_error, translate_venue_error,
)
from exchange.core.api_models import (
    AuthResponse,
    DeviceFlowStartRequest, DeviceFlowResponse, DeviceFlowPollRequest,
    AccountResponse, AccountActivityEntry, AccountActivityPage, LockResponse,
    MarketSummary, MarketDetail, PositionEntry, TradeResponse, Candle,
    DepthEntry, DepthResponse,
    BuyRequest, SellRequest, TradeResult,
    CreateAccountResponse,
    CreateServiceAccountRequest, CreateServiceAccountResponse,
    MintRequest, MintResponse,
    CreateMarketRequest, UserCreateMarketRequest, CreateMarketResponse,
    ResolveRequest, HealthResponse, NetHealth,
    AddLiquidityRequest, AddLiquidityResponse,
    InstrumentRequest,
    UpdateMetadataRequest,
    AddRepoRequest, TrackedRepoResponse, WebhookResponse,
    NetMarket, NetMarketList, NetMarginalResponse,
    NetOrderRequest, NetOrderPreviewResponse, NetOrderBalance,
    NetOrder, NetOrderResponse, NetOrdersList,
    NetResolveResponse, NetVoidResponse,
    NetPortfolioResponse, LeaderboardEntry, LeaderboardResponse,
    BookMarket, BookMarketList, BookCreateMarketRequest,
    BookOrderRequest, BookOrder, BookOrderBalance, BookOrderResponse,
    BookOrdersList, BookPositionsList, BookDepth, BookTradesList,
    BookSettlementResponse,
    BatchMarket, BatchMarketList, BatchCreateMarketRequest,
    BatchOrderRequest, BatchOrder, BatchOrderBalance, BatchOrderResponse,
    BatchOrdersList, BatchRoundResponse,
)
from exchange.core.auth import (
    AuthStore, validate_github_token,
    start_device_flow, poll_device_flow,
)
from exchange.core.lmsr import max_loss, prices as lmsr_prices, cost_to_move_price
from exchange.core.market_engine import MarketEngine
from exchange.core.middleware import (
    AuthUser, UserOrAdmin, AdminDep, require_auth, rate_limiter,
    DynamicCORSMiddleware, BodySizeLimitMiddleware,
)
from exchange.core.models import ZERO, Instrument, TrackedRepo, reset_counters
from exchange.core.persistence import save_snapshot, load_snapshot
from exchange.core.risk_engine import RiskEngine, InsufficientBalance
from exchange.venues.amm import AmmVenue
from exchange.venues.base import Venue, VenueError
from exchange.venues.book.engine import BookEngine
from exchange.venues.book.venue import BookVenue
from exchange.venues.batch.engine import BatchEngine, BatchVenue
from exchange.venues.joint.venue import JointVenue

logger = logging.getLogger(__name__)


STATE_PATH = os.environ.get("FUTARCHY_STATE", "./futarchy_state.json")
INITIAL_CREDITS = Decimal(os.environ.get("INITIAL_CREDITS", "1000"))
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
TREASURY_ACCOUNT_ID = os.environ.get("FUTARCHY_TREASURY_ID", "")
GITHUB_OAUTH_REDIRECT_URI = os.environ.get(
    "GITHUB_OAUTH_REDIRECT_URI",
    "https://api.futarchy.ai/v1/auth/callback",
)
DASHBOARD_URL = os.environ.get(
    "FUTARCHY_DASHBOARD_URL",
    "https://api.futarchy.ai/dashboard",
)
GITHUB_OAUTH_STATE_TTL = timedelta(minutes=10)

# Liquidity settings (matching pr-market.yml defaults)
LIQUIDITY_INITIAL = os.environ.get("LIQUIDITY_INITIAL", "40")
LIQUIDITY_STEP = os.environ.get("LIQUIDITY_STEP", "40")
LIQUIDITY_RAMP_STEPS = int(os.environ.get("LIQUIDITY_RAMP_STEPS", "4"))
LIQUIDITY_RAMP_INTERVAL_MINUTES = int(os.environ.get("LIQUIDITY_RAMP_INTERVAL_MINUTES", "30"))
LIQUIDITY_BUDGET = os.environ.get("LIQUIDITY_BUDGET", "200")
MARKET_EXPIRY_CHECK_INTERVAL_SECONDS = float(
    os.environ.get("MARKET_EXPIRY_CHECK_INTERVAL_SECONDS", "60")
)
BATCH_ROUND_CHECK_SECONDS = float(
    os.environ.get("BATCH_ROUND_CHECK_SECONDS", "30")
)
MIN_USER_FUNDING = Decimal(os.environ.get("MIN_USER_FUNDING", "10"))
MAX_USER_FUNDING = Decimal(os.environ.get("MAX_USER_FUNDING", "500"))
USER_MARKET_CAP = int(os.environ.get("USER_MARKET_CAP", "10"))
USER_MARKET_MAX_DAYS = 400

# Transaction-log compaction (I4): once the append-only log exceeds
# TX_LOG_CEILING entries, _save() compacts it down to the most recent
# TX_LOG_KEEP (see RiskEngine.compact_transactions), bounding snapshot size
# and per-save cost. Generous defaults so compaction is rare and users keep
# ample activity history. Set TX_LOG_CEILING=0 to disable.
TX_LOG_CEILING = int(os.environ.get("TX_LOG_CEILING", "50000"))
TX_LOG_KEEP = int(os.environ.get("TX_LOG_KEEP", "25000"))


def _build_joint_venue(risk: RiskEngine, seeds_path: str, joint_data: dict | None):
    """Restore the joint venue from a persisted snapshot, or build it fresh.

    ``joint_data`` is ``venues.get("joint")`` from ``load_snapshot`` — None
    on a fresh boot (no prior snapshot, or the venue was never enabled).
    """
    if joint_data is not None:
        return JointVenue.from_snapshot(joint_data, risk, seeds_path)
    return JointVenue(
        risk,
        seeds_path,
        liquidity=Decimal(os.environ.get("JOINT_LIQUIDITY", "50")),
        max_width=int(os.environ.get("JOINT_MAX_WIDTH", "8")),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load state
    if os.path.exists(STATE_PATH):
        risk, me, auth_store, tracked_repos, venues, instruments = load_snapshot(
            STATE_PATH
        )
    else:
        reset_counters()
        risk = RiskEngine()
        me = MarketEngine(risk)
        auth_store = AuthStore()
        tracked_repos = {}
        venues = {}
        instruments = {}

    app.state.risk = risk
    app.state.me = me
    app.state.auth_store = auth_store or AuthStore()
    app.state.tracked_repos = tracked_repos
    app.state.instruments = instruments
    # Raw venues section as loaded from disk (or {} on a fresh boot). Kept
    # around so _save() can pass it through unchanged when app.state.joint
    # is None but the section wasn't empty — see save_snapshot's
    # ``venues`` passthrough kwarg. Not touched once app.state.joint takes
    # over persisting its own section.
    app.state.venues = venues

    seeds_path = os.environ.get("EXCHANGE_SEEDS_PATH")
    app.state.joint = (
        _build_joint_venue(risk, seeds_path, venues.get("joint"))
        if seeds_path
        else None
    )
    app.state.book = (
        BookVenue.from_snapshot(venues["book"], risk)
        if "book" in venues
        else BookVenue(BookEngine(risk))
    )
    app.state.batch = (
        BatchVenue.from_snapshot(venues["batch"], risk)
        if "batch" in venues
        else BatchVenue(BatchEngine(risk))
    )
    app.state.venues_by_kind: dict[str, Venue] = {
        "amm": AmmVenue(me),
        "book": app.state.book,
        "batch": app.state.batch,
    }
    if app.state.joint is not None:
        app.state.venues_by_kind["net"] = app.state.joint

    app.state.github_oauth_states = {}
    app.state.lock = asyncio.Lock()
    await _reconcile_expired_markets_once()

    app.state.expiry_stop_event = asyncio.Event()
    app.state.expiry_task = None
    if MARKET_EXPIRY_CHECK_INTERVAL_SECONDS > 0:
        app.state.expiry_task = asyncio.create_task(
            _expired_market_reconciler(app.state.expiry_stop_event)
        )
    app.state.batch_round_stop_event = asyncio.Event()
    app.state.batch_round_task = None
    if BATCH_ROUND_CHECK_SECONDS > 0:
        await _close_due_batch_rounds_once()
        app.state.batch_round_task = asyncio.create_task(
            _batch_round_reconciler(app.state.batch_round_stop_event)
        )

    try:
        yield
    finally:
        app.state.expiry_stop_event.set()
        expiry_task = getattr(app.state, "expiry_task", None)
        if expiry_task is not None:
            await expiry_task
        app.state.batch_round_stop_event.set()
        batch_round_task = getattr(app.state, "batch_round_task", None)
        if batch_round_task is not None:
            await batch_round_task


app = FastAPI(
    title="Futarchy Exchange API",
    version="2.0.0",
    description=(
        "HTTP API for the Futarchy Exchange: independent per-market LMSR "
        "trading (buy/sell) alongside the joint MSR net venue for staked "
        "probability-edit orders across causally-linked variables and an "
        "always-on complete-set order book."
    ),
    lifespan=lifespan,
)
app.add_exception_handler(APIError, api_error_handler)

# Middleware order matters: Starlette's add_middleware() inserts each new
# entry at the front of the stack, so the LAST one added ends up OUTERMOST
# (runs first on the way in, last on the way out — see
# Starlette.build_middleware_stack). CORS is added last so it wraps
# everything, including 413s from the body-size guard and error responses
# from deeper middleware/handlers.
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(DynamicCORSMiddleware)


def _save():
    """Save state to disk. Called after every mutation.

    ``joint_venue=app.state.joint`` whenever a venue is live; otherwise the
    raw ``venues`` section loaded at startup is passed through unchanged so
    a save with the venue disabled never erases previously-persisted venue
    state (see save_snapshot's ``venues`` kwarg).
    """
    if TX_LOG_CEILING and len(app.state.risk.transactions) > TX_LOG_CEILING:
        app.state.risk.compact_transactions(TX_LOG_KEEP)
    book = getattr(app.state, "book", None)
    if book is not None and book.engine.risk is not app.state.risk:
        book = None
    batch = getattr(app.state, "batch", None)
    if batch is not None and batch.engine.risk is not app.state.risk:
        batch = None
    save_snapshot(app.state.risk, app.state.me, STATE_PATH,
                  auth_store=app.state.auth_store,
                  tracked_repos=app.state.tracked_repos,
                  joint_venue=app.state.joint,
                  book_venue=book,
                  batch_venue=batch,
                  venues=getattr(app.state, "venues", None),
                  instruments=getattr(app.state, "instruments", {}))


def _outcome_from_reason(reason: str) -> str | None:
    for prefix in (
        "lock:position:",
        "increase_lock:position:",
        "decrease_lock:position:",
    ):
        if reason.startswith(prefix):
            return reason[len(prefix):]
    return None


def _tx_outcome(tx, market) -> str | None:
    if tx.trade_id is not None and market is not None:
        for trade in market.trades:
            if trade.id == tx.trade_id:
                return trade.outcome
    return _outcome_from_reason(tx.reason)


def _activity_summary(tx, market, outcome: str | None) -> str:
    reason = tx.reason
    outcome_label = outcome.upper() if outcome else "position"

    if reason == "mint":
        return "Initial credits"
    if reason == "checkpoint":
        return "Opening balance (older history compacted)"

    if reason.startswith("lock:position:"):
        return f"Bought {outcome_label}"
    if reason.startswith("increase_lock:position:"):
        return f"Bought more {outcome_label}"
    if reason.startswith("decrease_lock:position:"):
        if market is not None and market.status == "void":
            return f"Void refund for {outcome_label}"
        return f"Released {outcome_label} collateral"

    if reason == "lock:conditional_loss":
        return "Sale loss reserved"
    if reason == "increase_lock:conditional_loss":
        return "Additional sale loss reserved"
    if reason == "decrease_lock:conditional_loss":
        if market is not None and market.status == "void":
            return "Void refund"
        return "Loss offset released"

    if reason == "trade_pnl:in":
        return "Sale profit reserved"
    if reason == "trade_pnl:out":
        return "Sale profit paid out"
    if reason == "pnl_net:in":
        return "Loss offset received"
    if reason == "pnl_net:out":
        return "Profit offset returned"
    if reason == "void_return_cp:out":
        return "Void profit return"
    if reason == "void_return_cp:in":
        return "Void profit reclaimed"

    if reason == "settlement":
        if market is not None and market.status == "void":
            return "Void settlement"
        if market is not None and market.status == "resolved":
            if tx.available_delta > ZERO:
                if outcome and market.resolution == outcome:
                    return f"Resolved {outcome_label} payout"
                return "Resolved market payout"
            return "Resolved market loss"
        return "Market settlement"

    return reason.replace("_", " ").replace(":", " ")


def _build_account_activity(account_id: int) -> list[AccountActivityEntry]:
    account_txs = [
        tx for tx in app.state.risk.transactions
        if tx.account_id == account_id
    ]
    available = ZERO
    frozen = ZERO
    entries: list[AccountActivityEntry] = []

    for tx in account_txs:
        available += tx.available_delta
        frozen += tx.frozen_delta
        market = app.state.me.markets.get(tx.market_id) if tx.market_id else None
        outcome = _tx_outcome(tx, market)
        total_delta = tx.available_delta + tx.frozen_delta
        entries.append(
            AccountActivityEntry(
                tx_id=tx.id,
                created_at=tx.created_at,
                summary=_activity_summary(tx, market, outcome),
                reason=tx.reason,
                outcome=outcome,
                available_delta=str(tx.available_delta),
                frozen_delta=str(tx.frozen_delta),
                total_delta=str(total_delta),
                available_after=str(available),
                frozen_after=str(frozen),
                total_after=str(available + frozen),
                market_id=tx.market_id,
                market_question=market.question if market else None,
                market_status=market.status if market else None,
                market_resolution=market.resolution if market else None,
                trade_id=tx.trade_id,
                lock_id=tx.lock_id,
            )
        )

    entries.reverse()
    return entries


def _github_oauth_states() -> dict[str, datetime]:
    states = getattr(app.state, "github_oauth_states", None)
    if states is None:
        states = {}
        app.state.github_oauth_states = states
    return states


def _prune_github_oauth_states(now: datetime | None = None) -> None:
    current = now or datetime.now(timezone.utc)
    cutoff = current - GITHUB_OAUTH_STATE_TTL
    states = _github_oauth_states()
    expired = [
        state
        for state, created_at in states.items()
        if created_at <= cutoff
    ]
    for state in expired:
        states.pop(state, None)


async def _exchange_github_oauth_code(code: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise ValueError(f"github_api_error:{resp.status_code}")

    data = resp.json()
    if "error" in data:
        raise ValueError(f"github_api_error:{data['error']}")

    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("github_api_error:missing_access_token")

    return access_token


async def _authenticate_github_identity(gh: dict) -> AuthResponse:
    async with app.state.lock:
        auth_store = app.state.auth_store
        existing = auth_store.get_by_github_id(gh["id"])

        if existing:
            user, raw_key = auth_store.create_user(
                gh["id"], gh["login"], existing.account_id)
        else:
            acc = app.state.risk.create_account()
            if INITIAL_CREDITS > ZERO:
                app.state.risk.mint(acc.id, INITIAL_CREDITS)
            user, raw_key = auth_store.create_user(
                gh["id"], gh["login"], acc.id)

        _save()

    return AuthResponse(
        api_key=raw_key,
        account_id=user.account_id,
        github_login=user.github_login,
    )


def _parse_deadline(deadline: str | None) -> datetime | None:
    if not deadline:
        return None

    normalized = deadline
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning("Skipping market with invalid deadline: %s", deadline)
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_user_deadline(deadline: str | None) -> None:
    if not deadline:
        raise APIError(400, "deadline_required", "A deadline is required")
    parsed = _parse_deadline(deadline)
    if parsed is None:
        raise APIError(400, "invalid_deadline", "Deadline must be ISO 8601")
    current = _now()
    if parsed <= current:
        raise APIError(400, "invalid_deadline", "Deadline must be in the future")
    if parsed > current + timedelta(days=USER_MARKET_MAX_DAYS):
        raise APIError(
            400, "deadline_out_of_bounds",
            f"Deadline must be within {USER_MARKET_MAX_DAYS} days",
        )


def _validate_user_market(
    question: str, outcomes: list[str] | None,
) -> tuple[str, list[str]]:
    question = question.strip()
    if not question:
        raise APIError(400, "invalid_question", "Question must not be empty")
    values = (
        [value.strip() for value in outcomes]
        if outcomes is not None else ["yes", "no"]
    )
    if not 2 <= len(values) <= 8 or any(not value for value in values):
        raise APIError(
            400, "invalid_outcomes", "Provide 2 to 8 non-empty outcomes")
    if len(set(values)) != len(values):
        raise APIError(400, "invalid_outcomes", "Outcomes must be unique")
    return question, values


def _validate_user_funding(raw: str) -> Decimal:
    try:
        funding = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise APIError(400, "invalid_funding", f"Invalid funding: {raw}")
    if not funding.is_finite():
        raise APIError(400, "invalid_funding", "Funding must be finite")
    if not MIN_USER_FUNDING <= funding <= MAX_USER_FUNDING:
        raise APIError(
            400, "funding_out_of_bounds",
            f"Funding must be between {MIN_USER_FUNDING} and {MAX_USER_FUNDING}",
        )
    return funding


def _creator_metadata(account_id: int, *, funded: bool = False) -> dict:
    metadata = {
        "creator_account_id": account_id,
        "resolver": {"type": "creator"},
    }
    if funded:
        metadata["funding_account_id"] = account_id
    return metadata


def _creator_open_market_count(account_id: int) -> int:
    count = sum(
        market.status == "open"
        and market.metadata.get("creator_account_id") == account_id
        for market in app.state.me.markets.values()
    )
    book = getattr(app.state, "book", None)
    if book is not None and book.engine.risk is app.state.risk:
        count += sum(
            market.status == "open"
            and market.metadata.get("creator_account_id") == account_id
            for market in book.engine.markets.values()
        )
    return count


def _enforce_creator_cap(account_id: int) -> None:
    if _creator_open_market_count(account_id) >= USER_MARKET_CAP:
        raise APIError(
            409, "market_cap_reached",
            f"Account may have at most {USER_MARKET_CAP} open self-serve markets",
        )


def _user_category_id(account_id: int, question: str) -> str:
    slug = re.sub(
        r"[^a-z0-9]+", "-", question.lower()
    ).strip("-")[:48].rstrip("-")
    slug = slug or "market"
    existing = {market.category_id for market in app.state.me.markets.values()}
    nonce = len(existing)
    while True:
        short_hash = hashlib.sha256(
            f"{account_id}\0{question}\0{nonce}".encode()
        ).hexdigest()[:8]
        category_id = f"user/{account_id}/{slug}-{short_hash}"
        if category_id not in existing:
            return category_id
        nonce += 1


def _authorize_market_resolver(
    user, metadata: dict, deadline: str | None,
) -> None:
    if user is None:
        return
    if (
        metadata.get("creator_account_id") != user.account_id
        or metadata.get("resolver", {}).get("type") != "creator"
    ):
        raise APIError(
            403, "not_resolver", "Caller is not this market's resolver")
    parsed = _parse_deadline(deadline)
    if parsed is None or _now() < parsed:
        raise APIError(
            403, "before_deadline", "Creator cannot settle before deadline")


def _authorize_market_void(user, metadata: dict) -> None:
    """Voiding is an admin/system action only — creators may never void.

    A creator-resolved market must be *resolved* to an outcome after its
    deadline. Letting the creator void instead gives them an asymmetric
    escape: resolve when their own position wins, void when it loses. Since
    ``void`` forgives losses and returns profits "to source", a losing
    creator voiding claws back the counterparty's winnings — so every
    creator market carries negative expected value for anyone trading
    against it. Only the admin key (``user is None``) may void; a genuinely
    ambiguous market is voided by an administrator, not self-served.
    """
    if user is not None:
        raise APIError(
            403, "void_forbidden",
            "Creators must resolve their market to an outcome; only an "
            "administrator can void a market.")


async def _reconcile_expired_markets_once(
    now: datetime | None = None,
) -> list[int]:
    current = now or _now()
    expired_ids: list[int] = []

    async with app.state.lock:
        for market in list(app.state.me.markets.values()):
            if market.status != "open":
                continue
            if market.metadata.get("resolver", {}).get("type") == "creator":
                continue

            deadline = _parse_deadline(market.deadline)
            if deadline is None or deadline > current:
                continue

            try:
                app.state.me.void(market.id)
                expired_ids.append(market.id)
            except ValueError:
                continue

        if expired_ids:
            _save()

    if expired_ids:
        logger.info("Voided %d expired markets: %s", len(expired_ids), expired_ids)

    return expired_ids


async def _expired_market_reconciler(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await _reconcile_expired_markets_once()
        except Exception:
            logger.exception("Expired market reconciliation failed")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=MARKET_EXPIRY_CHECK_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            continue


async def _close_due_batch_rounds_once(now: datetime | None = None) -> list[int]:
    current = now or datetime.now(timezone.utc)
    closed: list[int] = []
    async with app.state.lock:
        for market in app.state.batch.engine.markets.values():
            started = _parse_deadline(market.round_started_at or market.created_at)
            if (
                market.status != "open"
                or market.round_seconds is None
                or started is None
                or (current - started).total_seconds() < market.round_seconds
            ):
                continue
            try:
                app.state.batch.close_round(market.id)
                closed.append(market.id)
            except VenueError:
                logger.exception("Failed to close batch market %s", market.id)
        if closed:
            _save()
    return closed


async def _batch_round_reconciler(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await _close_due_batch_rounds_once()
        except Exception:
            logger.exception("Batch round reconciliation failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=BATCH_ROUND_CHECK_SECONDS)
        except asyncio.TimeoutError:
            continue


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# ---------------------------------------------------------------------------
# Landing page + Health (public)
# ---------------------------------------------------------------------------

@app.get("/")
@app.get("/landing")
async def landing():
    return FileResponse(STATIC_DIR / "landing.html", media_type="text/html")

@app.get("/dashboard")
async def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html", media_type="text/html")

@app.get("/install.sh")
async def install_script():
    return FileResponse(
        STATIC_DIR / "install.sh", media_type="text/plain; charset=utf-8")

@app.get("/v1/health")
async def health() -> HealthResponse:
    auth_store = app.state.auth_store
    joint = getattr(app.state, "joint", None)
    return HealthResponse(
        status="ok",
        markets=len(app.state.me.markets),
        ledger_accounts=len(app.state.risk.accounts),
        users=(
            len(auth_store.users) +
            len(getattr(auth_store, "local_users", {}))
        ),
        net=NetHealth(
            markets=len(joint.market_ids()) if joint is not None else 0,
            orders=joint.orders_count() if joint is not None else 0,
            enabled=joint is not None,
        ),
        venues={
            kind: venue.stats()
            for kind, venue in getattr(app.state, "venues_by_kind", {}).items()
        },
    )


# ---------------------------------------------------------------------------
# Auth (no API key required)
# ---------------------------------------------------------------------------

@app.get("/v1/auth/github/login")
async def auth_github_login(prompt: str | None = None) -> RedirectResponse:
    """Start GitHub OAuth web flow."""
    if not GITHUB_CLIENT_ID:
        raise APIError(501, "github_oauth_unavailable",
                       "GITHUB_CLIENT_ID not configured")
    if prompt is not None and prompt != "select_account":
        raise APIError(400, "github_oauth_invalid_prompt",
                       "Unsupported OAuth prompt")

    state = secrets.token_urlsafe(32)
    async with app.state.lock:
        _prune_github_oauth_states()
        _github_oauth_states()[state] = datetime.now(timezone.utc)

    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_OAUTH_REDIRECT_URI,
        "state": state,
    }
    if prompt:
        params["prompt"] = prompt
    return RedirectResponse(
        url=f"https://github.com/login/oauth/authorize?{urlencode(params)}",
        status_code=302,
    )


@app.get("/v1/auth/callback")
async def auth_github_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Finish GitHub OAuth web flow and redirect to the dashboard."""
    if error:
        raise APIError(400, "github_oauth_denied",
                       f"GitHub authorization failed: {error}")
    if not code or not state:
        raise APIError(400, "github_oauth_invalid_request",
                       "Missing OAuth code or state")
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise APIError(501, "github_oauth_unavailable",
                       "GitHub OAuth not fully configured")

    async with app.state.lock:
        _prune_github_oauth_states()
        issued_at = _github_oauth_states().pop(state, None)

    if issued_at is None:
        raise APIError(400, "github_oauth_invalid_state",
                       "Invalid or expired OAuth state")

    try:
        access_token = await _exchange_github_oauth_code(code)
        gh = await validate_github_token(access_token)
    except ValueError as e:
        raise APIError(502, "github_api_error", str(e))

    auth = await _authenticate_github_identity(gh)
    fragment = urlencode({
        "auth": auth.api_key,
        "account_id": auth.account_id,
        "login": auth.github_login,
    })
    return RedirectResponse(url=f"{DASHBOARD_URL}#{fragment}", status_code=302)


@app.post("/v1/auth/device")
async def auth_device_start(req: DeviceFlowStartRequest) -> DeviceFlowResponse:
    """Start GitHub OAuth device flow."""
    if not GITHUB_CLIENT_ID:
        raise APIError(501, "device_flow_unavailable",
                       "GITHUB_CLIENT_ID not configured")
    try:
        data = await start_device_flow(GITHUB_CLIENT_ID)
    except ValueError as e:
        raise APIError(502, "github_api_error", str(e))

    return DeviceFlowResponse(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        expires_in=data["expires_in"],
        interval=data.get("interval", 5),
    )


@app.post("/v1/auth/device/token")
async def auth_device_poll(req: DeviceFlowPollRequest) -> AuthResponse:
    """Poll GitHub OAuth device flow for completion."""
    if not GITHUB_CLIENT_ID:
        raise APIError(501, "device_flow_unavailable",
                       "GITHUB_CLIENT_ID not configured")

    try:
        token_data = await poll_device_flow(GITHUB_CLIENT_ID, req.device_code)
    except ValueError as e:
        code = str(e)
        if code == "device_flow_pending":
            raise APIError(202, "device_flow_pending",
                           "Authorization pending. Keep polling.")
        if code == "device_flow_expired":
            raise APIError(410, "device_flow_expired",
                           "Device code expired. Start a new flow.")
        raise APIError(502, "github_api_error", str(e))

    # We have an access_token — exchange it for our API key
    access_token = token_data["access_token"]
    try:
        gh = await validate_github_token(access_token)
    except ValueError:
        raise APIError(502, "github_api_error",
                       "Failed to validate GitHub access token")

    return await _authenticate_github_identity(gh)


# ---------------------------------------------------------------------------
# Public market data (no auth required)
# ---------------------------------------------------------------------------

_CANDLE_SECONDS = {"hour": 3600, "day": 86400}


def _candles(tape, interval: str) -> list[Candle]:
    """Aggregate timestamp/price/size triples into UTC OHLCV buckets."""
    if interval not in _CANDLE_SECONDS:
        raise APIError(400, "invalid_interval", "interval must be hour or day")
    seconds = _CANDLE_SECONDS[interval]
    points = []
    for timestamp, price, volume in tape:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        points.append((parsed.timestamp(), float(price), float(volume)))
    points.sort(key=lambda point: point[0])

    buckets: dict[int, list[float]] = {}
    for timestamp, price, volume in points:
        bucket = int(timestamp) // seconds * seconds
        candle = buckets.setdefault(bucket, [price, price, price, price, 0.0])
        candle[1] = max(candle[1], price)
        candle[2] = min(candle[2], price)
        candle[3] = price
        candle[4] += volume
    return [
        Candle(t=t, o=v[0], h=v[1], l=v[2], c=v[3], v=v[4])
        for t, v in buckets.items()
    ]

@app.get("/v1/markets")
async def list_markets(
    category: str | None = None,
    category_id: str | None = None,
    status: str | None = None,
) -> list[MarketSummary]:
    """List all markets with current prices.

    Optional filters:
    - category: exact match on market category
    - category_id: prefix match (e.g. "pr_merge/repo#7" matches
      "pr_merge/repo#7@2026-02-24")
    - status: exact match or comma-separated list (e.g. "resolved,void")
    """
    status_set = set(status.split(",")) if status else None
    result = []
    for m in app.state.me.markets.values():
        if category is not None and m.category != category:
            continue
        if category_id is not None and not m.category_id.startswith(category_id):
            continue
        if status_set is not None and m.status not in status_set:
            continue
        p = lmsr_prices(m.q, m.b) if m.status == "open" else {}
        result.append(MarketSummary(
            market_id=m.id,
            question=m.question,
            category=m.category,
            category_id=m.category_id,
            status=m.status,
            outcomes=m.outcomes,
            prices={o: str(v) for o, v in p.items()},
            b=str(m.b),
            liquidity=str(max_loss(m.b, len(m.outcomes))),
            num_trades=len(m.trades),
            resolution=m.resolution,
            created_at=m.created_at,
            deadline=m.deadline,
            resolved_at=m.resolved_at,
        ))
    return result


@app.post("/v1/markets")
async def create_user_market(
    req: UserCreateMarketRequest, user: AuthUser,
) -> CreateMarketResponse:
    question, outcomes = _validate_user_market(req.question, req.outcomes)
    _validate_user_deadline(req.deadline)
    funding = _validate_user_funding(req.funding)
    b = funding / Decimal(str(math.log(len(outcomes))))

    async with app.state.lock:
        _enforce_creator_cap(user.account_id)
        metadata = _creator_metadata(user.account_id, funded=True)
        try:
            market, amm = app.state.me.create_market(
                question=question,
                category="user",
                category_id=_user_category_id(user.account_id, question),
                metadata=metadata,
                b=b,
                outcomes=outcomes,
                deadline=req.deadline,
                funding_account_id=user.account_id,
                funding=funding,
            )
        except (ValueError, InsufficientBalance) as err:
            raise translate_engine_error(err) from err
        _save()

    return CreateMarketResponse(
        market_id=market.id,
        amm_account_id=amm.id,
        b=str(market.b),
    )


@app.get("/v1/markets/{market_id}")
async def get_market(market_id: int) -> MarketDetail:
    """Get full market detail including LMSR state."""
    m = app.state.me.markets.get(market_id)
    if m is None:
        raise APIError(404, "market_not_found", f"Market {market_id} not found")

    p = lmsr_prices(m.q, m.b) if m.status == "open" else {}

    # Compute volume (sum of all trade values)
    volume = sum(t.amount * t.price for t in m.trades)

    return MarketDetail(
        market_id=m.id,
        question=m.question,
        category=m.category,
        category_id=m.category_id,
        status=m.status,
        outcomes=m.outcomes,
        prices={o: str(v) for o, v in p.items()},
        b=str(m.b),
        liquidity=str(max_loss(m.b, len(m.outcomes))),
        num_trades=len(m.trades),
        resolution=m.resolution,
        created_at=m.created_at,
        deadline=m.deadline,
        amm_account_id=m.amm_account_id,
        q={o: str(v) for o, v in m.q.items()},
        volume=str(volume),
        resolved_at=m.resolved_at,
        metadata=m.metadata,
        creator_account_id=m.metadata.get("creator_account_id"),
        resolver=m.metadata.get("resolver", {"type": "admin"}),
    )


@app.post("/v1/markets/{market_id}/resolve")
async def resolve_market(
    market_id: int, req: ResolveRequest, user: UserOrAdmin,
) -> dict:
    async with app.state.lock:
        market = app.state.me.markets.get(market_id)
        if market is None:
            raise APIError(404, "market_not_found", f"Market {market_id} not found")
        _authorize_market_resolver(user, market.metadata, market.deadline)
        try:
            app.state.me.resolve(market_id, req.outcome)
            _save()
        except ValueError as err:
            raise translate_engine_error(err) from err
    return {"market_id": market_id, "resolution": req.outcome}


@app.post("/v1/markets/{market_id}/void")
async def void_market(market_id: int, user: UserOrAdmin) -> dict:
    async with app.state.lock:
        market = app.state.me.markets.get(market_id)
        if market is None:
            raise APIError(404, "market_not_found", f"Market {market_id} not found")
        _authorize_market_void(user, market.metadata)
        try:
            app.state.me.void(market_id)
            _save()
        except ValueError as err:
            raise translate_engine_error(err) from err
    return {"market_id": market_id, "status": "void"}


@app.get("/v1/markets/{market_id}/positions")
async def get_market_positions(market_id: int) -> list[PositionEntry]:
    """Get all positions in a market. Public — shows all participants."""
    m = app.state.me.markets.get(market_id)
    if m is None:
        raise APIError(404, "market_not_found", f"Market {market_id} not found")

    result = []
    for acc_id, pos in m.positions.items():
        # Skip AMM account and zero positions
        if acc_id == m.amm_account_id:
            continue
        if all(v == ZERO for v in pos.values()):
            continue
        acc = app.state.risk.get_account(acc_id)
        locks = [
            LockResponse(
                lock_id=lk.lock_id, market_id=lk.market_id,
                amount=str(lk.amount), lock_type=lk.lock_type,
            )
            for lk in acc.locks_for_market(market_id)
        ]
        result.append(PositionEntry(
            account_id=acc_id,
            positions={o: str(v) for o, v in pos.items()},
            locks=locks,
        ))
    return result


@app.get("/v1/markets/{market_id}/depth")
async def get_market_depth(market_id: int) -> DepthResponse:
    """Synthetic depth table: cost to move each outcome to target prices.

    Computed server-side from the LMSR cost function with exact Decimal math.
    Only available for open markets.
    """
    m = app.state.me.markets.get(market_id)
    if m is None:
        raise APIError(404, "market_not_found", f"Market {market_id} not found")
    if m.status != "open":
        return DepthResponse(market_id=m.id, rows=[])

    targets = [Decimal("0.6"), Decimal("0.7"), Decimal("0.8"),
               Decimal("0.9"), Decimal("0.95")]
    rows = []
    for outcome in m.outcomes:
        for tp in targets:
            try:
                amount, trade_cost = cost_to_move_price(m.q, m.b, outcome, tp)
            except (ValueError, ZeroDivisionError):
                continue
            if amount <= ZERO:
                continue
            rows.append(DepthEntry(
                target=f"{int(tp * 100)}%",
                outcome=outcome,
                cost=str(trade_cost),
                shares=str(amount),
            ))
    return DepthResponse(market_id=m.id, rows=rows)


@app.get("/v1/markets/{market_id}/trades")
async def get_market_trades(market_id: int) -> list[TradeResponse]:
    """Get all trades in a market. Public."""
    m = app.state.me.markets.get(market_id)
    if m is None:
        raise APIError(404, "market_not_found", f"Market {market_id} not found")

    return [
        TradeResponse(
            trade_id=t.id,
            market_id=t.market_id,
            outcome=t.outcome,
            amount=str(t.amount),
            price=str(t.price),
            value=str(t.amount * t.price),
            buyer_account_id=t.buyer.account_id,
            seller_account_id=t.seller.account_id,
            created_at=t.created_at,
        )
        for t in m.trades
    ]


@app.get("/v1/markets/{market_id}/candles")
async def get_market_candles(
    market_id: int, interval: str = "hour"
) -> list[Candle]:
    """YES-axis AMM candles from its timestamped trade tape."""
    market = app.state.me.markets.get(market_id)
    if market is None:
        raise APIError(404, "market_not_found", f"Market {market_id} not found")
    binary = set(market.outcomes) == {"yes", "no"}
    return _candles(
        (
            (
                trade.created_at,
                1 - trade.price if binary and trade.outcome == "no" else trade.price,
                trade.amount,
            )
            for trade in market.trades
        ),
        interval,
    )


# ---------------------------------------------------------------------------
# Cross-venue instrument registry.
# ---------------------------------------------------------------------------

_INSTRUMENT_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def yes_price(venue: str, market: dict) -> float | None:
    """Extract the live YES price from a venue's ``get_market`` record."""
    if venue == "net":
        value = market.get("marginals", {}).get("yes")
    elif venue == "amm":
        value = market.get("prices", {}).get("yes")
    elif venue == "book":
        bid, ask = market.get("bestBid"), market.get("bestAsk")
        value = (
            None if bid is None or ask is None
            else (Decimal(bid) + Decimal(ask)) / 2
        )
    elif venue == "batch":
        value = market.get("postedPrice")
    else:
        value = None
    return None if value is None else float(value)


@app.get("/v1/instruments")
async def list_instruments() -> list[dict]:
    result = []
    async with app.state.lock:
        for instrument in getattr(app.state, "instruments", {}).values():
            listings = []
            for listing in instrument.listings:
                venue = listing["venue"]
                market_id = listing["marketId"]
                market = app.state.venues_by_kind[venue].get_market(market_id)
                listings.append({
                    "venue": venue,
                    "marketId": market_id,
                    "yesPrice": yes_price(venue, market),
                    "status": market.get("status", "open"),
                })
            result.append({
                "instrumentId": instrument.instrument_id,
                "title": instrument.title,
                "listings": listings,
            })
    return result


@app.post("/v1/admin/instruments")
async def admin_create_instrument(req: InstrumentRequest, _: AdminDep) -> dict:
    slug = req.instrumentId.strip()
    if not _INSTRUMENT_SLUG.fullmatch(slug):
        raise APIError(
            400, "invalid_instrument_id",
            "instrumentId must be a lowercase slug",
        )

    listings = [listing.model_dump() for listing in req.listings]
    async with app.state.lock:
        instruments = getattr(app.state, "instruments", {})
        if slug in instruments:
            raise APIError(409, "instrument_exists", f"Instrument '{slug}' exists")
        for listing in listings:
            venue = listing["venue"]
            market_id = listing["marketId"]
            adapter = app.state.venues_by_kind.get(venue)
            if adapter is None:
                raise APIError(
                    404, "invalid_listing",
                    f"Listing {venue}:{market_id} has no live venue",
                )
            try:
                adapter.get_market(market_id)
            except (VenueError, TypeError, ValueError) as err:
                raise APIError(
                    404, "invalid_listing",
                    f"Listing {venue}:{market_id} does not resolve",
                ) from err
        instrument = Instrument(slug, req.title, listings)
        instruments[slug] = instrument
        app.state.instruments = instruments
        _save()
    return {
        "instrumentId": instrument.instrument_id,
        "title": instrument.title,
        "listings": instrument.listings,
        "createdAt": instrument.created_at,
    }


@app.delete("/v1/admin/instruments/{instrument_id}")
async def admin_delete_instrument(instrument_id: str, _: AdminDep) -> dict:
    async with app.state.lock:
        instruments = getattr(app.state, "instruments", {})
        if instrument_id not in instruments:
            raise APIError(
                404, "instrument_not_found",
                f"Instrument '{instrument_id}' not found",
            )
        del instruments[instrument_id]
        _save()
    return {"deleted": instrument_id}


# ---------------------------------------------------------------------------
# Leaderboard (public, no auth) — top accounts by total balance.
# ---------------------------------------------------------------------------

@app.get("/v1/leaderboard")
async def get_leaderboard() -> LeaderboardResponse:
    """Public top-50 accounts by total balance (available + frozen).

    Excludes three account classes that would otherwise dominate or
    pollute a "who's winning" board:
      - every market's AMM account (``MarketEngine.create_market`` mints
        one account per market and stores it as ``market.amm_account_id``
        — never a real trader's account);
      - the venue treasury, when the net venue is enabled
        (``app.state.joint.treasury_account_id``, seeded with 1,000,000
        credits — ``TREASURY_SEED`` in venues/joint/venue.py);
      - service accounts, i.e. the bot/agent accounts created via
        ``POST /v1/admin/service-accounts``. Those ``User`` records are
        stored in ``auth_store.local_users`` (keyed by username,
        ``github_id=0``) and marked with ``is_service_account=True`` by
        that endpoint. The exclusion test is the explicit flag, not
        ``local_users`` membership: legacy entries left over from the
        removed ``POST /v1/auth/register`` path (real humans, kept in
        ``local_users`` for auth continuity per core/auth.py) have
        ``is_service_account=False`` and must still appear on the board.

    Logins are resolved from ``auth_store.users`` (github_id -> User): an
    account owned by a real GitHub identity gets its login; any other
    account still in the ranking (e.g. one created via the plain
    ``POST /v1/admin/accounts``, or a legacy local human) gets ``null``.
    """
    auth_store = app.state.auth_store

    async with app.state.lock:
        excluded_ids = {
            m.amm_account_id for m in app.state.me.markets.values()
        }
        joint = getattr(app.state, "joint", None)
        if joint is not None:
            excluded_ids.add(joint.treasury_account_id)
        excluded_ids |= {
            u.account_id for u in auth_store.local_users.values()
            if u.is_service_account
        }

        login_by_account = {
            u.account_id: u.github_login for u in auth_store.users.values()
        }

        ranked = sorted(
            (acc for acc in app.state.risk.accounts.values()
             if acc.id not in excluded_ids),
            key=lambda a: a.total,
            reverse=True,
        )[:50]
        entries = [
            LeaderboardEntry(
                login=login_by_account.get(acc.id),
                accountId=acc.id,
                total=str(acc.total),
            )
            for acc in ranked
        ]
    return LeaderboardResponse(entries=entries)


# ---------------------------------------------------------------------------
# Complete-set order-book venue.
# ---------------------------------------------------------------------------

def _book() -> BookVenue:
    return app.state.book


@app.get("/v1/book/markets")
async def list_book_markets() -> BookMarketList:
    venue = _book()
    async with app.state.lock:
        markets = [BookMarket(**venue.get_market(mid)) for mid in venue.market_ids()]
    return BookMarketList(markets=markets, count=len(markets))


@app.get("/v1/book/markets/{market_id}")
async def get_book_market(market_id: int) -> BookMarket:
    async with app.state.lock:
        try:
            return BookMarket(**_book().get_market(market_id))
        except VenueError as err:
            raise translate_venue_error(err) from err


@app.get("/v1/book/markets/{market_id}/orderbook")
async def get_book_orderbook(market_id: int) -> BookDepth:
    async with app.state.lock:
        try:
            return BookDepth(**_book().orderbook(market_id))
        except VenueError as err:
            raise translate_venue_error(err) from err


@app.get("/v1/book/markets/{market_id}/trades")
async def get_book_trades(
    market_id: int, limit: int = Query(default=100, ge=1, le=500)
) -> BookTradesList:
    async with app.state.lock:
        try:
            trades = _book().trades_for(market_id, limit)
        except VenueError as err:
            raise translate_venue_error(err) from err
    return BookTradesList(trades=trades)


@app.get("/v1/book/markets/{market_id}/candles")
async def get_book_candles(
    market_id: int, interval: str = "hour"
) -> list[Candle]:
    """YES-axis candles from complete-set book fills."""
    async with app.state.lock:
        try:
            _book().get_market(market_id)
        except VenueError as err:
            raise translate_venue_error(err) from err
        fills = list(_book().engine.trades.get(market_id, []))
    return _candles(
        ((fill.created_at, fill.price, fill.size) for fill in fills), interval
    )


@app.post("/v1/book/orders")
async def place_book_order(req: BookOrderRequest, user: AuthUser) -> BookOrderResponse:
    async with app.state.lock:
        try:
            order = _book().place(user.account_id, req.model_dump())
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
        account = app.state.risk.get_account(user.account_id)
        balance = BookOrderBalance(
            available=str(account.available_balance),
            frozen=str(account.frozen_balance),
        )
    return BookOrderResponse(**order, balance=balance)


@app.delete("/v1/book/orders/{order_id}")
async def cancel_book_order(order_id: int, user: AuthUser) -> BookOrderResponse:
    async with app.state.lock:
        try:
            order = _book().cancel(user.account_id, order_id)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
        account = app.state.risk.get_account(user.account_id)
        balance = BookOrderBalance(
            available=str(account.available_balance),
            frozen=str(account.frozen_balance),
        )
    return BookOrderResponse(**order, balance=balance)


@app.get("/v1/book/orders/mine")
async def list_my_book_orders(user: AuthUser) -> BookOrdersList:
    async with app.state.lock:
        orders = list(reversed(_book().orders_for(user.account_id)))
    return BookOrdersList(orders=[BookOrder(**order) for order in orders])


@app.get("/v1/book/positions/mine")
async def list_my_book_positions(user: AuthUser) -> BookPositionsList:
    async with app.state.lock:
        positions = _book().positions_for(user.account_id)
    return BookPositionsList(positions=positions)


@app.post("/v1/book/markets")
async def create_book_market(
    req: BookCreateMarketRequest, user: UserOrAdmin,
) -> BookMarket:
    if user is None:
        question = req.question
        metadata = {"resolver": {"type": "admin"}}
    else:
        question, _ = _validate_user_market(req.question, None)
        _validate_user_deadline(req.deadline)
        metadata = _creator_metadata(user.account_id)

    async with app.state.lock:
        if user is not None:
            _enforce_creator_cap(user.account_id)
        market = _book().create_market(question, req.deadline, metadata)
        _save()
    return BookMarket(**market)


@app.post("/v1/book/markets/{market_id}/resolve")
async def resolve_book_market(
    market_id: int, req: ResolveRequest, user: UserOrAdmin,
) -> BookSettlementResponse:
    async with app.state.lock:
        market = _book().engine.markets.get(market_id)
        if market is None:
            try:
                _book().get_market(market_id)
            except VenueError as err:
                raise translate_venue_error(err) from err
        _authorize_market_resolver(user, market.metadata, market.deadline)
        try:
            report = _book().resolve(market_id, req.outcome)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return BookSettlementResponse(**report)


@app.post("/v1/book/markets/{market_id}/void")
async def void_book_market(
    market_id: int, user: UserOrAdmin,
) -> BookSettlementResponse:
    async with app.state.lock:
        market = _book().engine.markets.get(market_id)
        if market is None:
            try:
                _book().get_market(market_id)
            except VenueError as err:
                raise translate_venue_error(err) from err
        _authorize_market_void(user, market.metadata)
        try:
            report = _book().void(market_id)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return BookSettlementResponse(**report)


# ---------------------------------------------------------------------------
# Sealed-round batch LMSR venue.
# ---------------------------------------------------------------------------

def _batch() -> BatchVenue:
    return app.state.batch


@app.get("/v1/batch/markets")
async def list_batch_markets() -> BatchMarketList:
    venue = _batch()
    async with app.state.lock:
        markets = [BatchMarket(**venue.get_market(mid)) for mid in venue.market_ids()]
    return BatchMarketList(markets=markets, count=len(markets))


@app.get("/v1/batch/markets/{market_id}")
async def get_batch_market(market_id: int) -> BatchMarket:
    async with app.state.lock:
        try:
            return BatchMarket(**_batch().get_market(market_id))
        except VenueError as err:
            raise translate_venue_error(err) from err


@app.post("/v1/batch/orders")
async def place_batch_order(
    req: BatchOrderRequest, user: AuthUser
) -> BatchOrderResponse:
    async with app.state.lock:
        try:
            order = _batch().place(user.account_id, req.model_dump())
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
        account = app.state.risk.get_account(user.account_id)
        balance = BatchOrderBalance(
            available=str(account.available_balance),
            frozen=str(account.frozen_balance),
        )
    return BatchOrderResponse(**order, balance=balance)


@app.get("/v1/batch/orders/mine")
async def list_my_batch_orders(user: AuthUser) -> BatchOrdersList:
    async with app.state.lock:
        orders = list(reversed(_batch().orders_for(user.account_id)))
    return BatchOrdersList(orders=[BatchOrder(**order) for order in orders])


@app.post("/v1/batch/markets")
async def create_batch_market(
    req: BatchCreateMarketRequest, _: AdminDep
) -> BatchMarket:
    if req.b is not None and req.funding is not None:
        raise APIError(
            400, "invalid_target", "Provide either 'b' or 'funding', not both"
        )
    try:
        b = (
            Decimal(req.funding) / Decimal(2).ln()
            if req.funding is not None
            else Decimal(req.b or "100")
        )
    except InvalidOperation as err:
        raise APIError(400, "invalid_target", "b and funding must be decimals") from err
    async with app.state.lock:
        try:
            market = _batch().create_market(
                req.question, b=b, round_seconds=req.roundSeconds
            )
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return BatchMarket(**market)


@app.post("/v1/batch/markets/{market_id}/close-round")
async def close_batch_round(market_id: int, _: AdminDep) -> BatchRoundResponse:
    async with app.state.lock:
        try:
            result = _batch().close_round(market_id)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return BatchRoundResponse(**result)


@app.post("/v1/batch/markets/{market_id}/resolve")
async def resolve_batch_market(
    market_id: int, req: ResolveRequest, _: AdminDep
) -> dict:
    async with app.state.lock:
        try:
            report = _batch().resolve(market_id, req.outcome)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return {"market": BatchMarket(**report["market"]).model_dump()}


@app.post("/v1/batch/markets/{market_id}/void")
async def void_batch_market(market_id: int, _: AdminDep) -> dict:
    async with app.state.lock:
        try:
            report = _batch().void(market_id)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return {"market": BatchMarket(**report["market"]).model_dump()}


# ---------------------------------------------------------------------------
# Net venue (Plan B: joint/factored market) read routes — public, no auth.
# ---------------------------------------------------------------------------

def _require_joint() -> JointVenue:
    """The live venue, or a 503 ``net_venue_disabled`` when none is wired."""
    joint = getattr(app.state, "joint", None)
    if joint is None:
        raise APIError(503, "net_venue_disabled",
                        "the net venue is not enabled (EXCHANGE_SEEDS_PATH unset)")
    return joint


def _parse_context(raw: str | None) -> dict[str, str]:
    """Parse "gcx_a=yes|gcx_b=no" into {"gcx_a": "yes", "gcx_b": "no"}.

    Same pipe-separated ``var=outcome`` encoding as the venue's own
    ``parse_cpt_key`` (venues/joint/inference/network_model.py). ``None``
    or empty string means no context. Any malformed segment (missing "=",
    empty var, empty outcome) is a 400, not a silently-dropped pair.
    """
    if not raw:
        return {}
    context: dict[str, str] = {}
    for part in raw.split("|"):
        variable_id, sep, outcome_id = part.partition("=")
        if not sep or not variable_id or not outcome_id:
            raise APIError(400, "invalid_context",
                            f"malformed context segment: {part!r}")
        context[variable_id] = outcome_id
    return context


def _paper_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _paper_status(record: dict) -> str:
    return {"open": "active", "void": "closed"}.get(
        str(record.get("status", "active")), str(record.get("status", "active"))
    )


def _graph_market(record: dict, conditional: dict[str, float] | None = None) -> dict:
    market = {
        key: record[key]
        for key in ("id", "variableId", "title", "anchor", "ftmImplied")
        if key in record
    }
    market["marginals"] = {key: float(value) for key, value in record["marginals"].items()}
    market["status"] = _paper_status(record)
    if record.get("parents"):
        market["parents"] = list(record["parents"])
    if conditional is not None:
        market["conditionalMarginals"] = {
            key: round(float(value), 6) for key, value in conditional.items()
        }
    return market


def _to_net_market(record: dict) -> NetMarket:
    """Build a ``NetMarket`` response from a venue ``get_market()`` dict.

    Copies every mutable field (outcomes, marginals, parents) rather than
    handing the venue's live dict/lists to the response model by reference
    — the venue may hold these as internal state (seed records, freshly
    computed marginals) that must never be mutated through a response
    object held elsewhere.
    """
    return NetMarket(
        id=str(record["id"]),
        variableId=str(record["variableId"]),
        title=record.get("title", ""),
        description=record.get("description"),
        status=record.get("status", "open"),
        outcomes=[dict(o) for o in record.get("outcomes", [])],
        marginals={o: float(p) for o, p in record["marginals"].items()},
        parents=list(record.get("parents", [])),
    )


@app.get("/v1/net/network")
async def get_net_network():
    """Paper-server-compatible network nodes, edges, and joint diagnostics."""
    joint = _require_joint()
    async with app.state.lock:
        entries = [
            (str(market_id), joint.get_market(market_id))
            for market_id in joint.market_ids()
        ]
        id_by_variable = {
            str(record["variableId"]): market_id for market_id, record in entries
        }
        nodes = [
            {
                "marketId": market_id,
                "variableId": str(record["variableId"]),
                "title": str(record.get("title", "")),
                "status": _paper_status(record),
            }
            for market_id, record in entries
        ]
        edges = [
            {
                "from": id_by_variable[parent],
                "to": market_id,
                "fromVariableId": parent,
                "toVariableId": str(record["variableId"]),
            }
            for market_id, record in entries
            for parent in record.get("parents", [])
            if parent in id_by_variable
        ]
        stats = joint.inference_stats()
    return {
        "nodes": nodes,
        "edges": edges,
        "joint": stats,
        "meta": {"timestamp": _paper_timestamp()},
    }


@app.get("/v1/net/markets")
async def list_net_markets(fields: str | None = None, context: str | None = None):
    """List net markets, with a paper-compatible bulk graph projection."""
    if fields is None:
        if context is not None:
            raise APIError(400, "invalid_query", "context is only supported with fields=graph")
    elif fields != "graph":
        raise APIError(400, "invalid_query", "fields must be graph")

    joint = _require_joint()
    ctx = _parse_context(context) if fields == "graph" else {}
    async with app.state.lock:
        records = [joint.get_market(mid) for mid in joint.market_ids()]
        if fields == "graph":
            try:
                conditional = joint.all_marginals(ctx) if ctx else {}
            except VenueError as err:
                raise translate_venue_error(err) from err
        else:
            conditional = {}

    if fields == "graph":
        markets = [
            _graph_market(
                record,
                conditional.get(str(record["variableId"])) if ctx else None,
            )
            for record in records
            if _paper_status(record) != "resolved"
        ]
        filters = {
            "status": None,
            "sort": None,
            "q": None,
            "include_resolved": False,
            "fields": "graph",
        }
        if context:
            filters["context"] = context
        return {
            "markets": markets,
            "count": len(markets),
            "meta": {"timestamp": _paper_timestamp(), "filters": filters},
        }

    markets = [_to_net_market(record) for record in records]
    return NetMarketList(markets=markets, count=len(markets))


@app.get("/v1/net/markets/{market_id}")
async def get_net_market(market_id: str) -> NetMarket:
    """Get one net-venue market's live detail."""
    joint = _require_joint()
    async with app.state.lock:
        try:
            record = joint.get_market(market_id)
        except VenueError as err:
            raise translate_venue_error(err) from err
    return _to_net_market(record)


@app.get("/v1/net/marginal")
async def get_net_marginal(
    variable: str,
    context: str | None = None,
) -> NetMarginalResponse:
    """P(variable | context) under the net venue's current belief state."""
    joint = _require_joint()
    ctx = _parse_context(context)
    async with app.state.lock:
        try:
            result = joint.marginal(variable, ctx)
        except VenueError as err:
            raise translate_venue_error(err) from err
    return NetMarginalResponse(variable=variable, context=ctx, marginal=dict(result))


# ---------------------------------------------------------------------------
# Net venue: staked probability-edit orders (Task B3) — authed.
# ---------------------------------------------------------------------------

_TARGET_MIN = 0.001
_TARGET_MAX = 0.999


def _check_target_clamp(target: float) -> None:
    """Reject a target outside [0.001, 0.999] with 400 invalid_target.

    Must run BEFORE any venue call (preview_edit/place_edit) — see
    planB-constraints.md's API-level target clamp requirement.
    """
    if not (_TARGET_MIN <= target <= _TARGET_MAX):
        raise APIError(
            400, "invalid_target",
            f"target must be within [{_TARGET_MIN}, {_TARGET_MAX}]: {target}",
        )


def _to_net_order(order: dict) -> NetOrder:
    """Copy a venue order record into a response model.

    Every mutable field is copied (context/fill/remainingContext) rather
    than handed to the response model by reference — the venue's order
    dict is live internal state (see ``_to_net_market`` above for the same
    discipline on market records).
    """
    return NetOrder(
        orderId=order["orderId"],
        accountId=order["accountId"],
        variableId=order["variableId"],
        outcomeId=order["outcomeId"],
        target=order["target"],
        context=dict(order["context"]),
        before=order["before"],
        after=order["after"],
        stake=order["stake"],
        lockId=order["lockId"],
        status=order["status"],
        fill=dict(order["fill"]),
        remainingContext=dict(order["remainingContext"]),
    )


@app.post("/v1/net/orders/preview")
async def preview_net_order(req: NetOrderRequest, user: AuthUser) -> NetOrderPreviewResponse:
    """Quote the stake for a probability edit without touching any state."""
    _check_target_clamp(req.target)
    joint = _require_joint()
    async with app.state.lock:
        try:
            result = joint.preview_edit(
                user.account_id, req.variableId, req.outcomeId, req.target,
                req.context,
            )
        except VenueError as err:
            raise translate_venue_error(err) from err
    return NetOrderPreviewResponse(
        stake=result["stake"],
        before=result["before"],
        after=result["after"],
        b=str(result["b"]),
    )


@app.post("/v1/net/orders")
async def place_net_order(req: NetOrderRequest, user: AuthUser) -> NetOrderResponse:
    """Place a staked probability edit; freezes the worst-case stake."""
    _check_target_clamp(req.target)
    joint = _require_joint()
    async with app.state.lock:
        try:
            order = joint.place_edit(
                user.account_id, req.variableId, req.outcomeId, req.target,
                req.context,
            )
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
        account = app.state.risk.get_account(user.account_id)
        balance = NetOrderBalance(
            available=str(account.available_balance),
            frozen=str(account.frozen_balance),
        )
    base = _to_net_order(order)
    return NetOrderResponse(**base.model_dump(), balance=balance)


@app.get("/v1/net/orders/mine")
async def list_my_net_orders(user: AuthUser) -> NetOrdersList:
    """The caller's own net-venue orders, newest-first."""
    joint = _require_joint()
    async with app.state.lock:
        # orders_for() already filters by accountId == the caller's own
        # before any copy is made, so another account's order is never
        # even converted to a response model.
        mine = joint.orders_for(user.account_id)
    orders = [_to_net_order(o) for o in reversed(mine)]
    return NetOrdersList(orders=orders)


# ---------------------------------------------------------------------------
# Net venue: admin settlement (Task B4) — resolve/void a market's variable.
# ---------------------------------------------------------------------------

@app.post("/v1/net/markets/{market_id}/resolve")
async def resolve_net_market(
    market_id: str, req: ResolveRequest, _: AdminDep,
) -> NetResolveResponse:
    """Resolve the variable behind ``market_id`` and settle affected orders.

    ``market_id`` is the venue's own market id (route path param); the
    venue itself only knows about variable ids, so the market's
    ``variableId`` is looked up via ``get_market`` before calling
    ``resolve_variable``. Both the lookup and the resolve happen under the
    same lock/save discipline as every other mutating ``/v1/net`` route.
    """
    joint = _require_joint()
    async with app.state.lock:
        try:
            record = joint.get_market(market_id)
            variable_id = str(record["variableId"])
            report = joint.resolve_variable(variable_id, req.outcome)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return NetResolveResponse(
        marketId=market_id,
        variableId=variable_id,
        outcome=req.outcome,
        settled=list(report["settled"]),
        calledOff=list(report["calledOff"]),
        awaiting=list(report["awaiting"]),
        treasuryDelta=report["treasuryDelta"],
    )


@app.post("/v1/net/markets/{market_id}/void")
async def void_net_market(market_id: str, _: AdminDep) -> NetVoidResponse:
    """Void the variable behind ``market_id``, refunding every affected order."""
    joint = _require_joint()
    async with app.state.lock:
        try:
            record = joint.get_market(market_id)
            variable_id = str(record["variableId"])
            report = joint.void_variable(variable_id)
            _save()
        except VenueError as err:
            raise translate_venue_error(err) from err
    return NetVoidResponse(
        marketId=market_id,
        variableId=variable_id,
        calledOff=list(report["calledOff"]),
    )


# ---------------------------------------------------------------------------
# User endpoints (API key required)
# ---------------------------------------------------------------------------

@app.get("/v1/me/net")
async def get_my_net_portfolio(user: AuthUser) -> NetPortfolioResponse:
    """The caller's net-venue portfolio: own orders, open stake, settled pnl.

    Deliberately does NOT 503 when the venue is disabled, unlike every
    other ``/v1/net/*`` route (see ``_require_joint``) — this is an
    account/portfolio route, not a venue-market route, and
    planB-constraints.md's 503 rule is scoped to the latter. A trader's
    "me" page should render an empty portfolio when the venue is off,
    not break.
    """
    joint = getattr(app.state, "joint", None)
    if joint is None:
        return NetPortfolioResponse(orders=[], openStake="0", settledPnl="0")

    async with app.state.lock:
        # Same accountId-filter-before-copy discipline as /v1/net/orders/mine.
        mine = joint.orders_for(user.account_id)
        orders = [_to_net_order(o) for o in reversed(mine)]
        open_stake = sum(
            (Decimal(o["stake"]) for o in mine
             if o["status"] in ("open", "awaiting_context")),
            ZERO,
        )
        settled_pnl = sum(
            (Decimal(o["payout"]) for o in mine if o["status"] == "settled"),
            ZERO,
        )
    return NetPortfolioResponse(
        orders=orders, openStake=str(open_stake), settledPnl=str(settled_pnl),
    )


@app.get("/v1/me")
async def get_me(user: AuthUser) -> AccountResponse:
    """Get authenticated user's account."""
    acc = app.state.risk.get_account(user.account_id)
    locks = [
        LockResponse(
            lock_id=lk.lock_id, market_id=lk.market_id,
            amount=str(lk.amount), lock_type=lk.lock_type,
        )
        for lk in acc.locks
    ]
    return AccountResponse(
        account_id=acc.id,
        available=str(acc.available_balance),
        frozen=str(acc.frozen_balance),
        total=str(acc.total),
        locks=locks,
    )


@app.get("/v1/me/activity")
async def get_my_activity(
    user: AuthUser,
    limit: int = Query(50, ge=1, le=200),
    before_tx_id: int | None = Query(None, ge=1),
) -> AccountActivityPage:
    """Get authenticated user's account activity with cursor pagination."""
    entries = _build_account_activity(user.account_id)
    if before_tx_id is not None:
        entries = [entry for entry in entries if entry.tx_id < before_tx_id]

    page_entries = entries[:limit]
    has_more = len(entries) > limit
    next_before_tx_id = page_entries[-1].tx_id if has_more and page_entries else None
    return AccountActivityPage(
        entries=page_entries,
        has_more=has_more,
        next_before_tx_id=next_before_tx_id,
    )


@app.post("/v1/markets/{market_id}/buy")
async def buy(market_id: int, req: BuyRequest, user: AuthUser) -> TradeResult:
    """Buy outcome tokens."""
    try:
        budget = Decimal(req.budget)
    except InvalidOperation:
        raise APIError(400, "invalid_amount", f"Invalid budget: {req.budget}")
    if budget <= ZERO:
        raise APIError(400, "invalid_amount", "Budget must be positive")

    async with app.state.lock:
        try:
            trade = app.state.me.buy(
                market_id, user.account_id, req.outcome, budget)
            _save()
        except (ValueError, InsufficientBalance) as e:
            raise translate_engine_error(e)

    return TradeResult(
        trade_id=trade.id,
        outcome=trade.outcome,
        amount=str(trade.amount),
        price=str(trade.price),
        value=str(trade.amount * trade.price),
    )


@app.post("/v1/markets/{market_id}/sell")
async def sell(market_id: int, req: SellRequest, user: AuthUser) -> TradeResult:
    """Sell outcome tokens."""
    try:
        amount = Decimal(req.amount)
    except InvalidOperation:
        raise APIError(400, "invalid_amount", f"Invalid amount: {req.amount}")
    if amount <= ZERO:
        raise APIError(400, "invalid_amount", "Amount must be positive")

    async with app.state.lock:
        try:
            trade = app.state.me.sell(
                market_id, user.account_id, req.outcome, amount)
            _save()
        except (ValueError, InsufficientBalance) as e:
            raise translate_engine_error(e)

    return TradeResult(
        trade_id=trade.id,
        outcome=trade.outcome,
        amount=str(trade.amount),
        price=str(trade.price),
        value=str(trade.amount * trade.price),
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@app.post("/v1/admin/accounts")
async def admin_create_account(_: AdminDep) -> CreateAccountResponse:
    """Create a new account (e.g. treasury). Returns account_id."""
    async with app.state.lock:
        acc = app.state.risk.create_account()
        _save()
    return CreateAccountResponse(account_id=acc.id)


@app.post("/v1/admin/service-accounts")
async def admin_create_service_account(
        req: CreateServiceAccountRequest, _: AdminDep
) -> CreateServiceAccountResponse:
    """Create a service account (bot/agent) with a username and API key.

    Optionally mint initial credits. Returns the raw API key once.
    """
    username = req.username.strip()
    if not username or len(username) > 40:
        raise APIError(400, "invalid_username",
                       "Username must be 1-40 characters")

    async with app.state.lock:
        auth_store = app.state.auth_store
        if username in auth_store.local_users:
            raise APIError(409, "username_taken",
                           f"Username '{username}' is already taken")

        acc = app.state.risk.create_account()

        if req.initial_credits:
            try:
                amount = Decimal(req.initial_credits)
            except InvalidOperation:
                raise APIError(400, "invalid_amount",
                               f"Invalid credits: {req.initial_credits}")
            if amount > ZERO:
                app.state.risk.mint(acc.id, amount)

        import hashlib
        import secrets
        raw_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        from exchange.core.auth import User, _now
        user = User(
            github_id=0,
            github_login=username,
            account_id=acc.id,
            api_key_hash=key_hash,
            is_service_account=True,
        )
        auth_store.local_users[username] = user
        auth_store.key_to_user[key_hash] = user

        _save()

    return CreateServiceAccountResponse(
        account_id=acc.id,
        username=username,
        api_key=raw_key,
    )


@app.post("/v1/admin/mint")
async def admin_mint(req: MintRequest, _: AdminDep) -> MintResponse:
    """Mint credits to an account."""
    try:
        amount = Decimal(req.amount)
    except InvalidOperation:
        raise APIError(400, "invalid_amount", f"Invalid amount: {req.amount}")
    if amount <= ZERO:
        raise APIError(400, "invalid_amount", "Amount must be positive")

    async with app.state.lock:
        try:
            app.state.risk.mint(req.account_id, amount)
            _save()
        except ValueError as e:
            raise translate_engine_error(e)

    acc = app.state.risk.get_account(req.account_id)
    return MintResponse(account_id=acc.id, available=str(acc.available_balance))


@app.post("/v1/admin/markets")
async def admin_create_market(req: CreateMarketRequest,
                              _: AdminDep) -> CreateMarketResponse:
    """Create a new market. Supply either `b` (LMSR parameter) or `funding`
    (dollar amount — converted to appropriate b)."""
    import math as _math

    if req.funding is not None and req.b is not None:
        raise APIError(400, "invalid_request",
                       "Provide either 'b' or 'funding', not both")

    n_outcomes = len(req.outcomes) if req.outcomes else 2

    if req.funding is not None:
        try:
            funding = Decimal(req.funding)
        except InvalidOperation:
            raise APIError(400, "invalid_amount",
                           f"Invalid funding: {req.funding}")
        if funding <= ZERO:
            raise APIError(400, "invalid_amount", "Funding must be positive")
        # b = funding / ln(n)
        b = funding / Decimal(str(_math.log(n_outcomes)))
    else:
        b_str = req.b or "100"
        try:
            b = Decimal(b_str)
        except InvalidOperation:
            raise APIError(400, "invalid_amount", f"Invalid b: {b_str}")

    metadata = dict(req.metadata)
    metadata.setdefault("resolver", {"type": "admin"})

    async with app.state.lock:
        try:
            market, amm = app.state.me.create_market(
                question=req.question,
                category=req.category,
                category_id=req.category_id,
                metadata=metadata,
                b=b,
                outcomes=req.outcomes,
                deadline=req.deadline,
                funding_account_id=req.funding_account_id,
            )
        except (ValueError, InsufficientBalance) as e:
            raise translate_engine_error(e)
        _save()

    return CreateMarketResponse(
        market_id=market.id,
        amm_account_id=amm.id,
        b=str(market.b),
    )


@app.post("/v1/admin/markets/{market_id}/resolve")
async def admin_resolve(market_id: int, req: ResolveRequest,
                        _: AdminDep) -> dict:
    """Resolve a market."""
    async with app.state.lock:
        try:
            app.state.me.resolve(market_id, req.outcome)
            _save()
        except ValueError as e:
            raise translate_engine_error(e)

    return {"market_id": market_id, "resolution": req.outcome}


@app.post("/v1/admin/markets/{market_id}/void")
async def admin_void(market_id: int, _: AdminDep) -> dict:
    """Void a market."""
    async with app.state.lock:
        try:
            app.state.me.void(market_id)
            _save()
        except ValueError as e:
            raise translate_engine_error(e)

    return {"market_id": market_id, "status": "void"}


@app.post("/v1/admin/markets/{market_id}/add-liquidity")
async def admin_add_liquidity(market_id: int, req: AddLiquidityRequest,
                              _: AdminDep) -> AddLiquidityResponse:
    """Add liquidity to a market. AMM must have sufficient available balance."""
    try:
        amount = Decimal(req.amount)
    except InvalidOperation:
        raise APIError(400, "invalid_amount", f"Invalid amount: {req.amount}")
    if amount <= ZERO:
        raise APIError(400, "invalid_amount", "Amount must be positive")

    async with app.state.lock:
        try:
            app.state.me.add_liquidity(
                market_id, amount,
                funding_account_id=req.funding_account_id)
            _save()
        except (ValueError, InsufficientBalance) as e:
            raise translate_engine_error(e)

    m = app.state.me.markets[market_id]
    return AddLiquidityResponse(
        market_id=market_id,
        b=str(m.b),
        funding_added=str(amount),
    )


@app.patch("/v1/admin/markets/{market_id}/status")
async def admin_override_status(market_id: int, req: dict,
                                _: AdminDep) -> dict:
    """Admin override: correct a market's status.

    Only allowed on markets with 0 trades (no settlement reversal needed).
    Accepts {"status": "void"} to correct a wrongly-resolved market.
    """
    m = app.state.me.markets.get(market_id)
    if m is None:
        raise APIError(404, "market_not_found", f"Market {market_id} not found")

    new_status = req.get("status")
    if new_status not in ("void", "resolved", "open"):
        raise APIError(400, "invalid_status",
                       "Status must be 'void', 'resolved', or 'open'")

    if len(m.trades) > 0:
        raise APIError(409, "has_trades",
                       f"Market {market_id} has {len(m.trades)} trades; "
                       "status override not safe without settlement reversal")

    async with app.state.lock:
        old_status = m.status
        old_resolution = m.resolution
        m.status = new_status
        if new_status == "void":
            m.resolution = None

        # Record in the ledger — every state change must be auditable.
        from exchange.core.models import Transaction
        tx = Transaction.new(
            account_id=m.amm_account_id,
            available_delta=ZERO,
            frozen_delta=ZERO,
            reason="admin_status_override",
            market_id=market_id,
        )
        app.state.risk.transactions.append(tx)

        _save()

    return {"market_id": market_id, "old_status": old_status,
            "old_resolution": old_resolution,
            "new_status": new_status, "tx_id": tx.id}


@app.patch("/v1/admin/markets/{market_id}/metadata")
async def admin_update_metadata(market_id: int, req: UpdateMetadataRequest,
                                _: AdminDep) -> dict:
    """Merge keys into a market's metadata."""
    m = app.state.me.markets.get(market_id)
    if m is None:
        raise APIError(404, "market_not_found", f"Market {market_id} not found")

    async with app.state.lock:
        m.metadata.update(req.metadata)
        _save()

    return {"market_id": market_id, "metadata": m.metadata}


# ---------------------------------------------------------------------------
# Admin: Tracked Repos
# ---------------------------------------------------------------------------

@app.get("/v1/admin/repos")
async def admin_list_repos(_: AdminDep) -> list[TrackedRepoResponse]:
    """List tracked repos."""
    return [
        TrackedRepoResponse(
            repo=r.repo,
            enabled=r.enabled,
            has_webhook_secret=r.webhook_secret is not None,
            added_at=r.added_at,
        )
        for r in app.state.tracked_repos.values()
    ]


@app.post("/v1/admin/repos")
async def admin_add_repo(req: AddRepoRequest, _: AdminDep) -> TrackedRepoResponse:
    """Add a tracked repo for webhook-based PR markets."""
    slug = req.repo.strip().lower()
    if "/" not in slug or len(slug.split("/")) != 2:
        raise APIError(400, "invalid_repo",
                       "Repo must be in 'owner/name' format")

    async with app.state.lock:
        repo = TrackedRepo.new(
            repo=slug,
            webhook_secret=req.webhook_secret,
            enabled=req.enabled,
        )
        app.state.tracked_repos[slug] = repo
        _save()

    return TrackedRepoResponse(
        repo=repo.repo,
        enabled=repo.enabled,
        has_webhook_secret=repo.webhook_secret is not None,
        added_at=repo.added_at,
    )


@app.delete("/v1/admin/repos/{repo_slug:path}")
async def admin_delete_repo(repo_slug: str, _: AdminDep) -> dict:
    """Remove a tracked repo. Use URL-encoded slug (e.g. snapshot-labs%2Fsx-monorepo)."""
    slug = repo_slug.strip().lower()
    async with app.state.lock:
        if slug not in app.state.tracked_repos:
            raise APIError(404, "repo_not_found",
                           f"Repo '{slug}' is not tracked")
        del app.state.tracked_repos[slug]
        _save()

    return {"deleted": slug}


# ---------------------------------------------------------------------------
# GitHub Webhook
# ---------------------------------------------------------------------------

def _verify_webhook_signature(payload: bytes, signature: str,
                              secret: str) -> bool:
    """Verify GitHub HMAC-SHA256 webhook signature."""
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/v1/hooks/github")
async def github_webhook(request: Request) -> WebhookResponse:
    """Receive GitHub pull_request webhook events for tracked repos."""
    body = await request.body()
    event_type = request.headers.get("x-github-event", "")

    # Ping event — GitHub sends this on webhook creation.
    # Handle before JSON parsing since GitHub may send form-encoded pings.
    if event_type == "ping":
        return WebhookResponse(
            action="pong", skipped=True,
            reason="Webhook configured successfully")

    if event_type != "pull_request":
        return WebhookResponse(
            action="ignored", skipped=True,
            reason=f"Event type '{event_type}' is not pull_request")

    # Parse payload — supports both JSON and form-encoded (payload= field)
    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            payload = await request.json()
        else:
            # GitHub form-encoded: body is payload=<url-encoded JSON>
            from urllib.parse import parse_qs
            form = parse_qs(body.decode())
            import json as _json
            payload = _json.loads(form["payload"][0])
    except Exception:
        raise APIError(400, "invalid_payload",
                       "Invalid payload. Set webhook content type to "
                       "application/json.")

    action = payload.get("action", "")
    pr = payload.get("pull_request", {})
    repo_full = payload.get("repository", {}).get("full_name", "")
    repo_slug = repo_full.strip().lower()

    # Look up tracked repo
    tracked = app.state.tracked_repos.get(repo_slug)
    if tracked is None:
        raise APIError(404, "repo_not_tracked",
                       f"Repo '{repo_full}' is not tracked")
    if not tracked.enabled:
        return WebhookResponse(
            action=action, skipped=True,
            reason=f"Repo '{repo_full}' is disabled")

    # Validate HMAC signature
    if tracked.webhook_secret:
        signature = request.headers.get("x-hub-signature-256", "")
        if not signature:
            raise APIError(401, "signature_missing",
                           "X-Hub-Signature-256 header required")
        if not _verify_webhook_signature(body, signature,
                                         tracked.webhook_secret):
            raise APIError(401, "signature_invalid",
                           "Webhook signature verification failed")

    # Route by action
    if action == "opened":
        return await _handle_pr_opened(tracked, pr, repo_slug)
    elif action == "closed":
        return await _handle_pr_closed(pr, repo_slug)
    else:
        return WebhookResponse(
            action=action, skipped=True,
            reason=f"Action '{action}' is not handled")


async def _handle_pr_opened(tracked: TrackedRepo, pr: dict,
                            repo_slug: str) -> WebhookResponse:
    """Create a market for a newly opened PR."""
    import math as _math

    pr_num = pr.get("number")
    pr_title = pr.get("title", "")
    pr_url = pr.get("html_url", "")

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    deadline = tomorrow.isoformat().replace("+00:00", "Z")
    next_liquidity = (now + timedelta(minutes=LIQUIDITY_RAMP_INTERVAL_MINUTES)
                      ).strftime("%Y-%m-%dT%H:%M:%SZ")

    category_id = f"{repo_slug}#{pr_num}@{today}"

    # Idempotency: check if market already exists
    for m in app.state.me.markets.values():
        if m.category == "pr_merge" and m.category_id == category_id:
            return WebhookResponse(
                action="opened", market_id=m.id, skipped=True,
                reason=f"Market already exists for {category_id}")

    question = f"Will PR #{pr_num} '{pr_title}' merge by {deadline}?"
    funding = Decimal(LIQUIDITY_INITIAL)
    b = funding / Decimal(str(_math.log(2)))

    # Determine funding source
    funding_account_id = int(TREASURY_ACCOUNT_ID) if TREASURY_ACCOUNT_ID else None

    metadata = {
        "pr_number": pr_num,
        "pr_url": pr_url,
        "repo": repo_slug,
        "liquidity_budget": LIQUIDITY_BUDGET,
        "liquidity_step": LIQUIDITY_STEP,
        "liquidity_steps_remaining": LIQUIDITY_RAMP_STEPS,
        "next_liquidity_at": next_liquidity,
        "resolver": {
            "type": "github_pr", "repo": repo_slug, "pr_number": pr_num,
        },
    }

    async with app.state.lock:
        try:
            market, amm = app.state.me.create_market(
                question=question,
                category="pr_merge",
                category_id=category_id,
                metadata=metadata,
                b=b,
                deadline=deadline,
                funding_account_id=funding_account_id,
            )
        except (ValueError, InsufficientBalance) as e:
            raise translate_engine_error(e)
        _save()

    logger.info("Webhook created market %d for %s", market.id, category_id)
    return WebhookResponse(action="opened", market_id=market.id)


async def _handle_pr_closed(pr: dict, repo_slug: str) -> WebhookResponse:
    """Resolve all open markets for a closed PR."""
    pr_num = pr.get("number")
    merged = pr.get("merged", False)
    outcome = "yes" if merged else "no"
    category_prefix = f"{repo_slug}#{pr_num}"

    resolved_ids = []
    async with app.state.lock:
        for m in list(app.state.me.markets.values()):
            if (m.category == "pr_merge"
                    and m.category_id.startswith(category_prefix)
                    and m.status == "open"):
                try:
                    app.state.me.resolve(m.id, outcome)
                    resolved_ids.append(m.id)
                except ValueError:
                    pass  # already resolved/void
        if resolved_ids:
            _save()

    if not resolved_ids:
        return WebhookResponse(
            action="closed", skipped=True, resolution=outcome,
            reason=f"No open markets found for {category_prefix}")

    logger.info("Webhook resolved %d markets for %s as %s",
                len(resolved_ids), category_prefix, outcome)
    return WebhookResponse(
        action="closed", market_id=resolved_ids[0], resolution=outcome)
