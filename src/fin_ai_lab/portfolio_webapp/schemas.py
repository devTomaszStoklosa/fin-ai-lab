from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from fin_ai_lab.filings_rag.service import Citation, IndexedCompany, RefusalReason
from fin_ai_lab.investment_committee.service import CommitteeReport, ComparisonReport
from fin_ai_lab.market_pulse.service import IndicatorObservation, Regime
from fin_ai_lab.portfolio_webapp.instrument_overrides import QuoteCurrency
from fin_ai_lab.portfolio_xray.canonical import AssetClass
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig

CommitteeVariant = Literal["single", "committee", "compare"]
CommitteeJobStatus = Literal["pending", "running", "awaiting_confirmation", "done", "failed"]


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    broker: str | None = None
    account_type: str | None = None


class PortfolioOut(BaseModel):
    id: UUID
    name: str
    broker: str | None
    account_type: str | None
    created_at: datetime


class PositionOut(BaseModel):
    id: UUID
    broker: str
    account_type: str
    instrument_name: str
    isin: str | None
    symbol: str | None
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal | None
    cost_currency: str | None
    market_value: Decimal | None
    market_currency: str | None
    valuation_date: date
    resolution_status: str
    figi: str | None
    ticker: str | None
    exchange_code: str | None
    identification_rule: str | None
    quote_currency: str | None
    return_pct: Decimal | None


class SnapshotOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    broker: str
    valuation_date: date
    imported_at: datetime
    source_file_date_min: date | None
    source_file_date_max: date | None
    positions: list[PositionOut]


class ImportResponse(BaseModel):
    snapshot: SnapshotOut
    warnings: list[str]
    # #241: how many XTB cash operations of the file were new; None when the
    # file carries none (Bossa, or an export without the sheet).
    cash_operations_added: int | None = None
    # #249: how many Closed Positions lots of the file were new; None when it has none.
    closed_lots_added: int | None = None


class PositionPreviewOut(BaseModel):
    """A position as it would come out of a *proposed* (not yet saved)
    parser config -- no id, no resolution/FIGI fields, since nothing has
    been persisted or run through OpenFIGI yet."""

    instrument_name: str
    isin: str | None
    symbol: str | None
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal | None
    cost_currency: str | None
    market_value: Decimal | None
    market_currency: str | None


class ProposePreview(BaseModel):
    config: ParserConfig
    positions: list[PositionPreviewOut]
    warnings: list[str]


class PositionCreate(BaseModel):
    instrument_name: str = Field(min_length=1, max_length=200)
    isin: str | None = None
    symbol: str | None = None
    asset_class: AssetClass
    quantity: Decimal = Field(gt=0)
    avg_cost: Decimal = Field(gt=0)
    # #288: stored as the position's valuation_date. Omitted: today on
    # creation, unchanged on an update. The value is never sent: it follows
    # the owner's valuations (ManualValuationIn), else the purchase price.
    purchased_on: date | None = None


class ManualValuationIn(BaseModel):
    # Per unit, in PLN like every manual position (#288).
    unit_value: Decimal = Field(ge=0)


class ManualValuationOut(BaseModel):
    valued_on: date
    unit_value: Decimal
    value: Decimal  # unit_value x the position's quantity, in PLN


class MetricsOut(BaseModel):
    position_count: int
    total_value: Decimal | None
    base_currency: str
    hhi: Decimal | None
    effective_positions: Decimal | None
    top5_share: Decimal | None
    allocation_by_asset_class: dict[str, Decimal]
    allocation_by_currency: dict[str, Decimal]


class ReportOut(BaseModel):
    id: UUID
    snapshot_id: UUID
    generated_at: datetime
    model: str
    cost_usd: Decimal
    content_md: str


class AggregatorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    member_instrument_keys: list[str] = []
    member_aggregator_ids: list[UUID] = []


class LlmUsageOut(BaseModel):
    model: str
    calls_today: int
    rpd_limit: int


class MarketPulseIndicatorsOut(BaseModel):
    regime: Regime
    regime_signals: list[str]
    indicators: list[IndicatorObservation]


class MarketPulseBriefOut(BaseModel):
    date: date
    text: str


class MarketPulseAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class MarketPulseAskOut(BaseModel):
    text: str
    tool_calls: list[str]


class ComparisonReportOut(BaseModel):
    columns: list[str]
    rows: list[list[str]]
    zero_support_notes: list[str]
    corpus_size: int
    corpus_latest_headline_date: date | None


class FilingsIndexOut(BaseModel):
    # None: no index has been built yet (`fin-ai-lab filings-rag build-index`).
    built_at: datetime | None
    companies: list[IndexedCompany]


class FilingsAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    # None: search every indexed company.
    company: str | None = None


class FilingsAnswerOut(BaseModel):
    text: str
    refused: bool
    refusal_reason: RefusalReason | None
    citations: list[Citation]


class CommitteeAnalysisRequest(BaseModel):
    variant: CommitteeVariant
    regenerate: bool = False


class CommitteeJobOut(BaseModel):
    job_id: UUID
    variant: CommitteeVariant
    status: CommitteeJobStatus
    created_at: datetime
    finished_at: datetime | None
    cost_usd: Decimal | None
    error: str | None
    result: CommitteeReport | ComparisonReport | None


class ConfirmBudgetRequest(BaseModel):
    approve: bool


class AggregatorOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    name: str
    member_instrument_keys: list[str]
    member_aggregator_ids: list[UUID]
    value: Decimal
    base_currency: str


class ValuedPositionOut(BaseModel):
    """A current position valued at today's quote (S10). current_price is
    per unit in price_currency -- the currency the broker recorded the
    position's value in, the same one avg_cost is in, so return_pct compares
    like with like. value is in the base currency."""

    portfolio_id: UUID
    position_id: UUID
    instrument_key: str
    instrument_name: str
    isin: str | None
    symbol: str | None
    broker: str
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal | None
    cost_currency: str | None
    current_price: Decimal | None
    price_currency: str | None
    # The instrument's own trading currency (S11's currency breakdown); None
    # when yfinance never told us.
    quote_currency: str | None = None
    price_date: date | None
    value: Decimal | None
    return_pct: Decimal | None
    is_manual: bool
    # What the valuation priced it with (#285): the Yahoo symbol of its daily
    # closes and the listing currency whose NBP rate moves its value; None
    # where it had neither, so the Instruments screen can ask the owner.
    yahoo_ticker: str | None = None
    valued_quote_currency: str | None = None
    # A manual position's latest valuation by the owner (#288); None before
    # the first one (it is then worth its purchase price) and for imports.
    valued_on: date | None = None


class InvestmentOut(BaseModel):
    """fin-ai-lab#238: what the purchases are worth against what they cost,
    in the base currency. `not_covered` names what the imports do not carry
    yet, so the page can say what the result leaves out."""

    invested: Decimal
    proceeds: Decimal
    open_value: Decimal
    # #241: earned on the side, from XTB cash operations. Zero where the
    # import has none (see not_covered).
    dividends: Decimal = Decimal(0)  # net of withholding tax
    interest: Decimal = Decimal(0)  # on free funds, net of its tax
    other: Decimal = Decimal(0)  # fees, swaps, corrections
    # Deposits minus withdrawals -- the money the owner put in, the base for
    # a percentage. None where the import has no deposit data (Bossa).
    net_deposits: Decimal | None = None
    result: Decimal
    not_covered: list[Literal["closed_positions", "dividends"]]


class PortfolioSeriesOut(BaseModel):
    id: UUID
    name: str
    broker: str | None
    account_type: str | None
    current_value: Decimal
    position_count: int
    # One value per entry of ValuationOut.dates, in the base currency.
    values: list[Decimal]
    # None when the result cannot be stated (no cost data, missing FX rate).
    investment: InvestmentOut | None = None
    # fin-ai-lab#273, the benchmark comparison -- with `values`, enough for
    # the page to chain the return of any set of portfolios it shows: per
    # day, the previous day's holdings at this day's prices (0 on the first
    # day), and dividends credited, net of withholding tax (only days with
    # one). `dividends_included` is False where the imports carry no
    # dividends -- the return then leaves them out.
    prior_holdings_values: list[Decimal] = []
    dividends_by_day: dict[date, Decimal] = {}
    dividends_included: bool = False
    # How much of that return the history can see: per day, the value held
    # without daily quotes (constant, so no return), and the gain the return
    # captured over the chart (price moves + dividends) -- to set against
    # `investment.result`, which comes from the actual cash flows.
    unquoted_values: list[Decimal] = []
    history_gain: Decimal = Decimal(0)
    # Deposits minus withdrawals, in PLN at the NBP rate of their own day:
    # per chart day (only days with one) and summed before its first day --
    # for "the same deposits into the benchmark".
    deposits_by_day: dict[date, Decimal] = {}
    deposits_before_start: Decimal = Decimal(0)


class CompositionChangeOut(BaseModel):
    date: date
    portfolio_id: UUID
    instrument_name: str
    quantity_change: Decimal


class AssetOut(BaseModel):
    """One asset across the portfolios in scope (S12): every current
    position holding it -- in several accounts, or under several brokers'
    keys joined into one asset -- summed. A per-unit figure is averaged only
    where every member states it in the same currency, else None: never a
    mix of currencies."""

    instrument_key: str  # the asset key (instruments.py)
    instrument_name: str
    isin: str | None
    symbol: str | None
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal | None
    cost_currency: str | None
    current_price: Decimal | None
    price_currency: str | None
    quote_currency: str | None
    value: Decimal | None
    return_pct: Decimal | None
    position_ids: list[UUID]


class ValuationOut(BaseModel):
    base_currency: str
    computed_at: datetime
    # Latest trading day any quote came from -- "today" only while markets
    # are open, the last session's close otherwise.
    prices_as_of: date | None
    total_value: Decimal
    dates: list[date]
    totals: list[Decimal]
    portfolios: list[PortfolioSeriesOut]
    positions: list[ValuedPositionOut]
    assets: list[AssetOut] = []
    changes: list[CompositionChangeOut]
    warnings: list[str]
    # S12: pairs of instruments in scope that look like one asset and wait
    # for the owner's answer (the linking form lists them).
    link_suggestion_count: int = 0
    # #273: what 1 held on the first day grew to, every portfolio together,
    # deposits, purchases and sales left out (valuation.return_index).
    return_index: list[Decimal] = []


class BenchmarkOptionOut(BaseModel):
    """One built-in benchmark (fin-ai-lab#273) -- every one with dividends
    in its series, so the comparison with a portfolio's return is fair."""

    id: str
    label: str
    ticker: str
    note: str


class BenchmarkOut(BaseModel):
    """A benchmark on the valuation's day axis, in the base currency:
    dividend-adjusted closes x the NBP rate of each day, as an index equal
    to 1 on the first day with a price. Days before that day repeat it."""

    ticker: str
    label: str
    note: str | None
    quote_currency: str
    base_currency: str
    dates: list[date]
    values: list[Decimal]
    first_price_date: date
    prices_as_of: date


class DividendYearOut(BaseModel):
    year: int
    total: Decimal
    months: list[Decimal]  # twelve, January first


class DividendInstrumentOut(BaseModel):
    # The asset key (S12); None when the payment names no instrument the
    # portfolio holds or traded -- `name` is then the label from its row.
    instrument_key: str | None
    name: str
    payment_count: int
    last_paid_on: date
    total: Decimal
    last_12_months: Decimal


class DividendPaymentOut(BaseModel):
    paid_on: date
    portfolio_id: UUID
    portfolio_name: str
    instrument_key: str | None
    name: str
    amount: Decimal  # credited to the account, in `currency`
    currency: str
    # NBP rate of the payment day; None (and no amount_base) without one.
    fx_rate: Decimal | None
    amount_base: Decimal | None
    is_correction: bool


class DividendHistoryOut(BaseModel):
    """fin-ai-lab#265: dividends credited to the accounts in scope, in the
    base currency at the NBP rate of each payment's day -- the same amounts
    the investment result counts as `dividends`."""

    base_currency: str
    total: Decimal
    last_12_months: Decimal
    current_year: Decimal
    years: list[DividendYearOut]  # oldest first, up to the current year
    instruments: list[DividendInstrumentOut]  # largest total first
    payments: list[DividendPaymentOut]  # newest first
    warnings: list[str]


class DividendForecastRowOut(BaseModel):
    instrument_key: str  # the asset key (S12)
    name: str
    quantity: Decimal  # held today
    # Paid per share over the last 12 months; None without payouts.
    per_share: Decimal | None
    per_share_currency: str | None
    estimate: Decimal  # gross, in the base currency, for the target year
    # Last 12 months' payouts over the latest close, in percent (Yahoo only).
    yield_pct: Decimal | None
    # Where the per-share amounts come from: Yahoo, the account's own XTB
    # statements (Yahoo doesn't know the instrument), or nowhere.
    source: Literal["yahoo", "history", "none"]
    # Yahoo and the XTB statements disagree by more than 25% per payout.
    mismatch: bool
    # #267: after the tax withheld before payout (gross where unknown) and
    # what is still due in the tax return, both in the base currency.
    credited: Decimal = Decimal(0)
    top_up: Decimal = Decimal(0)
    # The withholding rate in percent; None when unknown or when the
    # asset's holdings (IKE and a regular account) differ.
    withholding_pct: Decimal | None = None
    tax_basis: Literal["statement", "rule", "unknown", "mixed"] = "unknown"


class DividendForecastOut(BaseModel):
    """fin-ai-lab#266: the last 12 months' per-share payouts again, in the
    same months of `year`, times today's quantity at today's NBP rate. A
    description, not a forecast. `total`/`months` are gross; #267 adds what
    reaches the accounts and the top-up still due in the tax return."""

    base_currency: str
    year: int
    total: Decimal
    months: list[Decimal]  # twelve, January first
    rows: list[DividendForecastRowOut]  # largest estimate first
    warnings: list[str]
    total_credited: Decimal = Decimal(0)
    months_credited: list[Decimal] = []
    total_top_up: Decimal = Decimal(0)


class InstrumentOut(BaseModel):
    """One instrument as one broker records it, and the asset it belongs to."""

    key: str
    asset_key: str
    asset_name: str
    # How it joined its asset: the same FIGI, or the owner's decision; None
    # when nothing joined it to anything.
    linked_by: Literal["figi", "owner"] | None
    name: str
    broker: str
    isin: str | None
    symbol: str | None
    ticker: str | None
    exchange_code: str | None
    figi: str | None
    asset_class: str
    portfolio_names: list[str]
    quantity: Decimal
    # Today's value of one unit in the base currency -- evidence for the
    # owner: one instrument costs the same through either broker.
    unit_value: Decimal | None
    is_manual: bool
    # #285: what prices it -- the Yahoo symbol and listing currency the
    # valuation used, whether it found daily closes -- and the owner's own
    # entry for the two, when there is one.
    yahoo_ticker: str | None = None
    quote_currency: str | None = None
    has_quotes: bool = False
    owner_yahoo_ticker: str | None = None
    owner_quote_currency: str | None = None


class SuggestionOut(BaseModel):
    key_a: str
    key_b: str
    reasons: list[str]


class InstrumentsOut(BaseModel):
    base_currency: str
    prices_as_of: date | None
    instruments: list[InstrumentOut]
    suggestions: list[SuggestionOut]


class InstrumentLinkIn(BaseModel):
    key_a: str = Field(min_length=1, max_length=300)
    key_b: str = Field(min_length=1, max_length=300)
    same: bool


class InstrumentDetachIn(BaseModel):
    key: str = Field(min_length=1, max_length=300)


class InstrumentOwnerDataIn(BaseModel):
    """#285: the owner's Yahoo symbol and quote currency for one instrument;
    both empty clears the entry."""

    key: str = Field(min_length=1, max_length=300)
    # Yahoo's own symbol, suffix included ("SEDG", "VUAA.L"); checked like a
    # benchmark ticker (REQ-122) by the endpoint.
    yahoo_ticker: str | None = Field(default=None, max_length=40)
    quote_currency: QuoteCurrency | None = None


class BreakdownGroupOut(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None
    position: int


class BreakdownOut(BaseModel):
    id: UUID
    name: str
    is_default: bool
    groups: list[BreakdownGroupOut]
    # instrument key -> group id; an instrument absent here is "Bez grupy".
    assignments: dict[str, UUID]


class BreakdownCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class BreakdownUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_default: bool = False


class BreakdownGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None


class AssignmentIn(BaseModel):
    instrument_key: str = Field(min_length=1, max_length=300)
    group_id: UUID | None = None


class ShareNodeOut(BaseModel):
    """One node of a breakdown's tree with its share -- percentages computed
    by the backend in Decimal (REQ-084), the frontend only draws them."""

    id: str
    name: str
    kind: Literal["root", "group", "asset", "ungrouped"]
    value: Decimal
    share_of_parent: Decimal
    share_of_total: Decimal
    asset_count: int
    symbol: str | None = None
    portfolio_name: str | None = None
    children: list["ShareNodeOut"]


class SharesOut(BaseModel):
    breakdown_id: str
    breakdown_name: str
    base_currency: str
    total_value: Decimal
    prices_as_of: date | None
    root: ShareNodeOut
    warnings: list[str]
