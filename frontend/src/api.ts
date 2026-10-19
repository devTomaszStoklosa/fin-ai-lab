export type Portfolio = {
  id: string
  name: string
  broker: string | null
  account_type: string | null
  created_at: string
}

export type PortfolioCreate = {
  name: string
  broker: string | null
  account_type: string | null
}

export type Position = {
  id: string
  broker: string
  account_type: string
  instrument_name: string
  isin: string | null
  symbol: string | null
  asset_class: string
  quantity: string
  avg_cost: string | null
  cost_currency: string | null
  market_value: string | null
  market_currency: string | null
  valuation_date: string
  resolution_status: string
  figi: string | null
  ticker: string | null
  exchange_code: string | null
  identification_rule: string | null
  quote_currency: string | null
  return_pct: string | null
}

export type PositionCreate = {
  instrument_name: string
  isin: string | null
  symbol: string | null
  asset_class: string
  quantity: string
  avg_cost: string
  // #288: stored as the position's valuation_date. Its value is never sent:
  // it follows the owner's valuations (ManualValuation), else the cost.
  purchased_on: string
}

// One of the owner's own valuations of a manual position (#288), per unit in
// PLN; value is unit_value x the position's quantity.
export type ManualValuation = {
  valued_on: string
  unit_value: string
  value: string
}

export type LlmUsage = {
  model: string
  calls_today: number
  rpd_limit: number
}

export type MarketPulseIndicator = {
  series_id: string
  label: string
  value: string
  unit: string
  as_of_date: string
  source: string
  previous_value: string | null
  change: string | null
}

export type MarketPulseIndicators = {
  regime: 'risk-on' | 'neutral' | 'risk-off'
  regime_signals: string[]
  indicators: MarketPulseIndicator[]
}

export type MarketPulseBrief = {
  date: string
  text: string
}

export type MarketPulseAskAnswer = {
  text: string
  tool_calls: string[]
}

export type FilingType = '10-K' | 'annual-report-pl' | 'half-year-report-pl' | 'quarterly-report-pl'

export type IndexedCompany = {
  company: string
  filing_type: FilingType
  fiscal_period: string
  language: 'en' | 'pl'
  sections: string[]
  chunk_count: number
}

export type FilingsIndex = {
  // null: no index built yet (`fin-ai-lab filings-rag build-index`).
  built_at: string | null
  companies: IndexedCompany[]
}

export type FilingsCitation = {
  company: string
  filing_type: FilingType
  fiscal_period: string
  section: string
  excerpt: string
}

export type FilingsAnswer = {
  text: string
  refused: boolean
  refusal_reason: 'no_relevant_chunk' | 'company_not_in_corpus' | null
  citations: FilingsCitation[]
}

export type ComparisonReport = {
  columns: string[]
  rows: string[][]
  zero_support_notes: string[]
  corpus_size: number
  corpus_latest_headline_date: string | null
}

export type Snapshot = {
  id: string
  portfolio_id: string
  broker: string
  valuation_date: string
  imported_at: string
  source_file_date_min: string | null
  source_file_date_max: string | null
  positions: Position[]
}

export type ParserConfig = {
  broker: string
  version: number
  sheet_name: string | null
  header_row: number
  row_filter: { require_non_empty: string[]; require_empty: string[] } | null
  expected_headers: string[]
  column_mapping: Record<string, string>
  number_format: 'pl' | 'en'
  date_format: string
  encoding: string
  delimiter: string | null
}

export type PositionPreview = {
  instrument_name: string
  isin: string | null
  symbol: string | null
  asset_class: string
  quantity: string
  avg_cost: string | null
  cost_currency: string | null
  market_value: string | null
  market_currency: string | null
}

export type ProposePreview = {
  config: ParserConfig
  positions: PositionPreview[]
  warnings: string[]
}

export type Metrics = {
  position_count: number
  total_value: string | null
  base_currency: string
  hhi: string | null
  effective_positions: string | null
  top5_share: string | null
  allocation_by_asset_class: Record<string, string>
  allocation_by_currency: Record<string, string>
}

export type Report = {
  id: string
  snapshot_id: string
  generated_at: string
  model: string
  cost_usd: string
  content_md: string
}

export type Aggregator = {
  id: string
  portfolio_id: string
  name: string
  member_instrument_keys: string[]
  member_aggregator_ids: string[]
  value: string
  base_currency: string
}

// S10 -- every money field is a decimal string from the backend (Decimal,
// quantized); the frontend only formats and plots them.
export type ValuedPosition = {
  portfolio_id: string
  position_id: string
  instrument_key: string
  instrument_name: string
  isin: string | null
  symbol: string | null
  broker: string
  asset_class: string
  quantity: string
  avg_cost: string | null
  cost_currency: string | null
  current_price: string | null
  price_currency: string | null
  quote_currency: string | null
  price_date: string | null
  value: string | null
  return_pct: string | null
  is_manual: boolean
  // A manual position's latest valuation day (#288); null before the first.
  valued_on: string | null
}

export type NotCovered = 'closed_positions' | 'dividends'

// What the purchases are worth against what they cost, in the base currency.
// not_covered lists what the imports do not carry yet.
export type Investment = {
  invested: string
  proceeds: string
  open_value: string
  // Earned on the side, from XTB cash operations (zero without them).
  dividends: string // after withholding tax
  interest: string // on free funds, after its tax
  other: string // fees, swaps, corrections
  // Deposits minus withdrawals; null where the import has no deposit data.
  net_deposits: string | null
  result: string
  not_covered: NotCovered[]
}

export type PortfolioSeries = {
  id: string
  name: string
  broker: string | null
  account_type: string | null
  current_value: string
  position_count: number
  values: string[]
  // null when the result cannot be stated (no cost data, missing rate).
  investment: Investment | null
  // #273: per day, the previous day's holdings at this day's prices (with
  // `values`, enough to chain the return of any set of portfolios shown).
  prior_holdings_values: string[]
  // Dividends credited, net of withholding tax, by ISO date (days with one).
  dividends_by_day: Record<string, string>
  // False where the imports carry no dividends: the return leaves them out.
  dividends_included: boolean
  // Per day, the value held without daily quotes (constant, so no return).
  unquoted_values: string[]
  // The gain the return captured over the chart (price moves + dividends),
  // to set against investment.result, which comes from the cash flows.
  history_gain: string
  // Deposits minus withdrawals in PLN: by ISO date, and before the first day.
  deposits_by_day: Record<string, string>
  deposits_before_start: string
}

export type CompositionChange = {
  date: string
  portfolio_id: string
  instrument_name: string
  quantity_change: string
}

export type Valuation = {
  base_currency: string
  computed_at: string
  prices_as_of: string | null
  total_value: string
  dates: string[]
  totals: string[]
  portfolios: PortfolioSeries[]
  positions: ValuedPosition[]
  // S12: one row per asset -- positions of one instrument in several
  // accounts, or joined across brokers, summed by the backend.
  assets: Asset[]
  changes: CompositionChange[]
  warnings: string[]
  // Pairs that look like one asset and wait for the owner's answer.
  link_suggestion_count: number
  // #273: what 1 held on the first day grew to, every portfolio together.
  return_index: string[]
}

// --- #273: benchmark comparison ----------------------------------------------

export type BenchmarkOption = {
  id: string
  label: string
  ticker: string
  note: string
}

export type Benchmark = {
  ticker: string
  label: string
  note: string | null
  quote_currency: string
  base_currency: string
  dates: string[]
  // In PLN, 1 on first_price_date; days before it repeat 1.
  values: string[]
  first_price_date: string
  prices_as_of: string
}

export type Asset = {
  instrument_key: string
  instrument_name: string
  isin: string | null
  symbol: string | null
  asset_class: string
  quantity: string
  avg_cost: string | null
  cost_currency: string | null
  current_price: string | null
  price_currency: string | null
  quote_currency: string | null
  value: string | null
  return_pct: string | null
  position_ids: string[]
}

// S11 -- breakdowns ("podziały"): the owner's own trees of groups, and the
// shares tree the backend computes for one of them (or a built-in one).
export type BreakdownGroup = {
  id: string
  name: string
  parent_id: string | null
  position: number
}

export type Breakdown = {
  id: string
  name: string
  is_default: boolean
  groups: BreakdownGroup[]
  // instrument key -> group id; a key absent here is "Bez grupy".
  assignments: Record<string, string>
}

export type ShareNode = {
  id: string
  name: string
  kind: 'root' | 'group' | 'asset' | 'ungrouped'
  value: string
  share_of_parent: string
  share_of_total: string
  asset_count: number
  symbol: string | null
  portfolio_name: string | null
  children: ShareNode[]
}

export type Shares = {
  breakdown_id: string
  breakdown_name: string
  base_currency: string
  total_value: string
  prices_as_of: string | null
  root: ShareNode
  warnings: string[]
}

export const BUILTIN_BREAKDOWNS = [
  { id: 'builtin:asset', name: 'Aktywa' },
  { id: 'builtin:asset_class', name: 'Klasa aktywów' },
  { id: 'builtin:currency', name: 'Waluta notowań' },
  { id: 'builtin:portfolio', name: 'Portfel' },
] as const

export const DEFAULT_BUILTIN_BREAKDOWN = 'builtin:asset_class'

export type AggregatorCreate = {
  name: string
  member_instrument_keys: string[]
  member_aggregator_ids: string[]
}

// The exact string P1's service.import_file returns when a file's format
// signature matches no approved config -- the propose/approve flow only
// makes sense to offer for this specific failure, not any import error.
export const UNKNOWN_FORMAT_ERROR = 'Unknown file format'

export class ImportFailure extends Error {
  errors: string[]
  warnings: string[]

  constructor(errors: string[], warnings: string[]) {
    super(errors.join('; ') || 'Import failed')
    this.errors = errors
    this.warnings = warnings
  }
}

async function asJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export function fetchHealth(): Promise<{ status: string }> {
  return fetch('/health').then((r) => asJson(r))
}

export function fetchPortfolios(): Promise<Portfolio[]> {
  return fetch('/api/portfolios').then((r) => asJson(r))
}

export function fetchLlmUsage(): Promise<LlmUsage[]> {
  return fetch('/api/llm-usage').then((r) => asJson(r))
}

export function fetchMarketPulseBrief(): Promise<MarketPulseBrief | null> {
  return fetch('/api/market-pulse/brief/latest').then((r) => asJson(r))
}

export function fetchMarketPulseIndicators(): Promise<MarketPulseIndicators> {
  return fetch('/api/market-pulse/indicators').then((r) => asJson(r))
}

export function fetchComparisonReport(): Promise<ComparisonReport | null> {
  return fetch('/api/news-classifier/comparison-report').then((r) => asJson(r))
}

export async function askMarketPulse(question: string): Promise<MarketPulseAskAnswer> {
  const response = await fetch('/api/market-pulse/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!response.ok) {
    // Same reasoning as generateReport: an HTTPException we raise comes back
    // as {detail: "..."}, but an unhandled exception gets FastAPI's default
    // plain-text 500 body -- parse safely before deciding what to show.
    const body = await response.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(detail)
  }
  return response.json()
}

export function fetchFilingsIndex(): Promise<FilingsIndex> {
  return fetch('/api/filings-rag/companies').then((r) => asJson(r))
}

export async function askFilings(question: string, company: string | null): Promise<FilingsAnswer> {
  const response = await fetch('/api/filings-rag/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, company }),
  })
  if (!response.ok) {
    // Same reasoning as askMarketPulse: our own errors come back as
    // {detail: "..."}, an unhandled one as a plain-text 500.
    const body = await response.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(detail)
  }
  return response.json()
}

export function createPortfolio(payload: PortfolioCreate): Promise<Portfolio> {
  return fetch('/api/portfolios', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => asJson(r))
}

export function fetchAllValuation(refresh = false): Promise<Valuation> {
  return fetch(`/api/valuation${refresh ? '?refresh=true' : ''}`).then((r) => asJson(r))
}

export function fetchPortfolioValuation(portfolioId: string, refresh = false): Promise<Valuation> {
  return fetch(
    `/api/portfolios/${portfolioId}/valuation${refresh ? '?refresh=true' : ''}`,
  ).then((r) => asJson(r))
}

export function fetchBenchmarks(): Promise<BenchmarkOption[]> {
  return fetch('/api/benchmarks').then((r) => asJson(r))
}

export async function fetchBenchmark(ticker: string, start: string, refresh = false): Promise<Benchmark> {
  const params = new URLSearchParams({ ticker, start })
  if (refresh) params.set('refresh', 'true')
  const response = await fetch(`/api/benchmark?${params}`)
  if (!response.ok) {
    // Same reasoning as askMarketPulse: our own errors (unknown ticker,
    // Yahoo down, no NBP rate) come back as {detail: "..."}.
    const body = await response.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(detail)
  }
  return response.json()
}

// --- #265: dividend history ------------------------------------------------

export type DividendYear = {
  year: number
  total: string
  months: string[] // twelve, January first
}

export type DividendInstrument = {
  // Asset key; null when the payment names no instrument held or traded.
  instrument_key: string | null
  name: string
  payment_count: number
  last_paid_on: string
  total: string
  last_12_months: string
}

export type DividendPayment = {
  paid_on: string
  portfolio_id: string
  portfolio_name: string
  instrument_key: string | null
  name: string
  amount: string // credited to the account, in `currency`
  currency: string
  fx_rate: string | null // NBP rate of the payment day
  amount_base: string | null
  is_correction: boolean
}

// Dividends credited to the accounts in scope, in the base currency at the
// NBP rate of each payment's day -- what the investment result counts.
export type DividendHistory = {
  base_currency: string
  total: string
  last_12_months: string
  current_year: string
  years: DividendYear[] // oldest first
  instruments: DividendInstrument[] // largest total first
  payments: DividendPayment[] // newest first
  warnings: string[]
}

export type DividendSource = 'yahoo' | 'history' | 'none'

export type DividendForecastRow = {
  instrument_key: string
  name: string
  quantity: string
  per_share: string | null // paid per share over the last 12 months
  per_share_currency: string | null
  estimate: string // gross, base currency, for `year`
  yield_pct: string | null // last 12 months' payouts / latest close
  source: DividendSource
  mismatch: boolean // Yahoo and the XTB statement differ by > 25%
  // #267: after the tax withheld before payout (gross where unknown), and
  // what is still due in the tax return -- never subtracted from `credited`.
  credited: string
  top_up: string
  withholding_pct: string | null // null: unknown, or different per account
  tax_basis: DividendTaxBasis
}

export type DividendTaxBasis = 'statement' | 'rule' | 'unknown' | 'mixed'

// #266: the last 12 months' per-share payouts again, in the same months of
// `year` (the next calendar year), at today's quantity and NBP rate. `total`
// and `months` are gross; #267 adds the credited amounts and the top-up.
export type DividendForecast = {
  base_currency: string
  year: number
  total: string
  months: string[] // twelve, January first
  rows: DividendForecastRow[] // largest estimate first
  warnings: string[]
  total_credited: string // what reaches the accounts (#267)
  months_credited: string[]
  total_top_up: string // still due in the tax return, regular accounts
}

export function fetchDividendForecast(portfolioId?: string): Promise<DividendForecast> {
  const url = portfolioId
    ? `/api/portfolios/${portfolioId}/dividends/forecast`
    : '/api/dividends/forecast'
  return fetch(url).then((r) => asJson(r))
}

export function fetchDividendHistory(portfolioId?: string): Promise<DividendHistory> {
  const url = portfolioId
    ? `/api/portfolios/${portfolioId}/dividends/history`
    : '/api/dividends/history'
  return fetch(url).then((r) => asJson(r))
}

export function fetchSnapshots(portfolioId: string): Promise<Snapshot[]> {
  return fetch(`/api/portfolios/${portfolioId}/snapshots`).then((r) => asJson(r))
}

async function asImportResponse<T>(response: Response): Promise<T> {
  // An HTTPException we raise ourselves comes back as {detail: {errors,
  // warnings}}, but an *unhandled* exception (e.g. a value that slips past
  // our own validation, like issue #186's decimal parse crash) gets
  // FastAPI's default plain-text 500 body, not JSON -- parsing that
  // unconditionally throws and hides the real error behind a JSON parse
  // failure. Parse safely first, then decide what to show.
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail ?? {}
    throw new ImportFailure(detail.errors ?? [response.statusText], detail.warnings ?? [])
  }
  return body as T
}

export type ImportOutcome = {
  snapshot: Snapshot
  warnings: string[]
  // New XTB cash operations of the file; null or absent when it carries none.
  cash_operations_added?: number | null
  // New Closed Positions lots of the file; null or absent when it has none.
  closed_lots_added?: number | null
}

export async function importFile(
  portfolioId: string,
  file: File,
  valuationDate: string,
): Promise<ImportOutcome> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('valuation_date', valuationDate)

  const response = await fetch(`/api/portfolios/${portfolioId}/import`, {
    method: 'POST',
    body: formData,
  })
  return asImportResponse(response)
}

export async function importBossaFile(
  portfolioId: string,
  file: File,
  valuationDate: string,
): Promise<ImportOutcome> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('valuation_date', valuationDate)

  const response = await fetch(`/api/portfolios/${portfolioId}/import/bossa`, {
    method: 'POST',
    body: formData,
  })
  return asImportResponse(response)
}

export async function proposeImportConfig(
  portfolioId: string,
  file: File,
  broker: string,
  valuationDate: string,
): Promise<ProposePreview> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('broker', broker)
  formData.append('valuation_date', valuationDate)

  const response = await fetch(`/api/portfolios/${portfolioId}/import/propose`, {
    method: 'POST',
    body: formData,
  })
  return asImportResponse(response)
}

export function fetchPositions(portfolioId: string): Promise<Position[]> {
  return fetch(`/api/portfolios/${portfolioId}/positions`).then((r) => asJson(r))
}

// A refused date (#288) comes back as a readable 422 -- hence asJsonOrDetail.
export function createPosition(portfolioId: string, payload: PositionCreate): Promise<Position> {
  return sendJson('POST', `/api/portfolios/${portfolioId}/positions`, payload).then((r) =>
    asJsonOrDetail(r),
  )
}

export function updatePosition(
  portfolioId: string,
  positionId: string,
  payload: PositionCreate,
): Promise<Position> {
  return sendJson('PUT', `/api/portfolios/${portfolioId}/positions/${positionId}`, payload).then(
    (r) => asJsonOrDetail(r),
  )
}

function valuationsUrl(portfolioId: string, positionId: string): string {
  return `/api/portfolios/${portfolioId}/positions/${positionId}/valuations`
}

export function fetchManualValuations(
  portfolioId: string,
  positionId: string,
): Promise<ManualValuation[]> {
  return fetch(valuationsUrl(portfolioId, positionId)).then((r) => asJson(r))
}

// One valuation per day: saving a day that already has one replaces it.
export function saveManualValuation(
  portfolioId: string,
  positionId: string,
  valuedOn: string,
  unitValue: string,
): Promise<ManualValuation> {
  return sendJson('PUT', `${valuationsUrl(portfolioId, positionId)}/${valuedOn}`, {
    unit_value: unitValue,
  }).then((r) => asJsonOrDetail(r))
}

export async function deleteManualValuation(
  portfolioId: string,
  positionId: string,
  valuedOn: string,
): Promise<void> {
  const response = await fetch(`${valuationsUrl(portfolioId, positionId)}/${valuedOn}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
}

export async function deletePortfolio(portfolioId: string): Promise<void> {
  const response = await fetch(`/api/portfolios/${portfolioId}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
}

export async function deletePosition(portfolioId: string, positionId: string): Promise<void> {
  const response = await fetch(`/api/portfolios/${portfolioId}/positions/${positionId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
}

export function fetchMetrics(portfolioId: string): Promise<Metrics> {
  return fetch(`/api/portfolios/${portfolioId}/metrics`).then((r) => asJson(r))
}

export function fetchReport(portfolioId: string): Promise<Report | null> {
  return fetch(`/api/portfolios/${portfolioId}/report`).then((r) => asJson(r))
}

export async function generateReport(portfolioId: string, regenerate: boolean): Promise<Report> {
  const response = await fetch(
    `/api/portfolios/${portfolioId}/report?regenerate=${regenerate}`,
    { method: 'POST' },
  )
  if (!response.ok) {
    // An HTTPException we raise ourselves comes back as {detail: "..."},
    // but an unhandled exception (e.g. the LLM provider itself erroring)
    // gets FastAPI's default plain-text 500 body, not JSON -- parsing that
    // as JSON throws and hides the real error behind a parse failure.
    const body = await response.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(detail)
  }
  return response.json()
}

export async function approveImportConfig(
  portfolioId: string,
  file: File,
  config: ParserConfig,
  valuationDate: string,
): Promise<{ snapshot: Snapshot; warnings: string[] }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('config', JSON.stringify(config))
  formData.append('valuation_date', valuationDate)

  const response = await fetch(`/api/portfolios/${portfolioId}/import/approve`, {
    method: 'POST',
    body: formData,
  })
  return asImportResponse(response)
}

async function asJsonOrDetailError<T>(response: Response): Promise<T> {
  if (!response.ok) {
    // Same reasoning as generateReport: a raised HTTPException comes back
    // as {detail: "..."} with a message worth showing (e.g. a rejected
    // cycle, REQ-062) -- fall back to statusText only when the body isn't
    // that shape.
    const body = await response.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(detail)
  }
  return response.json()
}

export function fetchAggregators(portfolioId: string): Promise<Aggregator[]> {
  return fetch(`/api/portfolios/${portfolioId}/aggregators`).then((r) => asJson(r))
}

export function createAggregator(
  portfolioId: string,
  payload: AggregatorCreate,
): Promise<Aggregator> {
  return fetch(`/api/portfolios/${portfolioId}/aggregators`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => asJsonOrDetailError(r))
}

export function updateAggregator(
  portfolioId: string,
  aggregatorId: string,
  payload: AggregatorCreate,
): Promise<Aggregator> {
  return fetch(`/api/portfolios/${portfolioId}/aggregators/${aggregatorId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => asJsonOrDetailError(r))
}

export async function deleteAggregator(portfolioId: string, aggregatorId: string): Promise<void> {
  const response = await fetch(`/api/portfolios/${portfolioId}/aggregators/${aggregatorId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
}

export type CommitteeVariant = 'single' | 'committee' | 'compare'
export type CommitteeJobStatus = 'pending' | 'running' | 'awaiting_confirmation' | 'done' | 'failed'

export type Claim = {
  text: string
  source_type: string
  source_ref: string
}

export type CommitteeBrief = {
  perspective: 'fundamental' | 'macro' | 'sentiment' | 'stress'
  conclusion: string
  confidence: number
  claims: Claim[]
}

export type CommitteeReportResult = {
  portfolio_id: string
  date: string
  briefs: CommitteeBrief[]
  disagreements: string[]
  text: string
  cost_usd: string
}

export type VariantResult = {
  text: string
  cost_usd: string
  latency_ms: number
}

export type ComparisonReportResult = {
  portfolio_id: string
  single_agent: VariantResult
  committee: VariantResult
  quality_winner: 'single_agent' | 'committee' | 'tie'
  quality_reason: string
}

export type CommitteeJob = {
  job_id: string
  variant: CommitteeVariant
  status: CommitteeJobStatus
  created_at: string
  finished_at: string | null
  cost_usd: string | null
  error: string | null
  result: CommitteeReportResult | ComparisonReportResult | null
}

export function startCommitteeAnalysis(
  portfolioId: string,
  variant: CommitteeVariant,
  regenerate: boolean,
): Promise<CommitteeJob> {
  return fetch(`/api/portfolios/${portfolioId}/committee-analysis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ variant, regenerate }),
  }).then((r) => asJson(r))
}

export function fetchCommitteeJob(portfolioId: string, jobId: string): Promise<CommitteeJob> {
  return fetch(`/api/portfolios/${portfolioId}/committee-analysis/${jobId}`).then((r) => asJson(r))
}

export function confirmCommitteeBudget(
  portfolioId: string,
  jobId: string,
  approve: boolean,
): Promise<CommitteeJob> {
  return fetch(`/api/portfolios/${portfolioId}/committee-analysis/${jobId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approve }),
  }).then((r) => asJson(r))
}

// A 422 we raise ourselves carries a readable {detail: "..."} (e.g. moving a
// group into its own subgroup) -- show that, not just the status line.
async function asJsonOrDetail<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(detail)
  }
  return body as T
}

function sendJson(method: string, url: string, payload?: unknown): Promise<Response> {
  return fetch(url, {
    method,
    headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
}

export function fetchBreakdowns(): Promise<Breakdown[]> {
  return fetch('/api/breakdowns').then((r) => asJsonOrDetail(r))
}

export function createBreakdown(name: string): Promise<Breakdown> {
  return sendJson('POST', '/api/breakdowns', { name }).then((r) => asJsonOrDetail(r))
}

export function updateBreakdown(
  id: string,
  payload: { name: string; is_default: boolean },
): Promise<Breakdown> {
  return sendJson('PUT', `/api/breakdowns/${id}`, payload).then((r) => asJsonOrDetail(r))
}

export async function deleteBreakdown(id: string): Promise<void> {
  const response = await sendJson('DELETE', `/api/breakdowns/${id}`)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
}

export function duplicateBreakdown(id: string): Promise<Breakdown> {
  return sendJson('POST', `/api/breakdowns/${id}/duplicate`).then((r) => asJsonOrDetail(r))
}

export function createBreakdownGroup(
  breakdownId: string,
  payload: { name: string; parent_id: string | null },
): Promise<Breakdown> {
  return sendJson('POST', `/api/breakdowns/${breakdownId}/groups`, payload).then((r) =>
    asJsonOrDetail(r),
  )
}

export function updateBreakdownGroup(
  breakdownId: string,
  groupId: string,
  payload: { name: string; parent_id: string | null },
): Promise<Breakdown> {
  return sendJson('PUT', `/api/breakdowns/${breakdownId}/groups/${groupId}`, payload).then((r) =>
    asJsonOrDetail(r),
  )
}

export function deleteBreakdownGroup(breakdownId: string, groupId: string): Promise<Breakdown> {
  return sendJson('DELETE', `/api/breakdowns/${breakdownId}/groups/${groupId}`).then((r) =>
    asJsonOrDetail(r),
  )
}

export function setBreakdownAssignment(
  breakdownId: string,
  instrumentKey: string,
  groupId: string | null,
): Promise<Breakdown> {
  return sendJson('PUT', `/api/breakdowns/${breakdownId}/assignments`, {
    instrument_key: instrumentKey,
    group_id: groupId,
  }).then((r) => asJsonOrDetail(r))
}

export function fetchShares(breakdown: string, portfolioId?: string): Promise<Shares> {
  const params = new URLSearchParams({ breakdown })
  if (portfolioId) params.set('portfolio_id', portfolioId)
  return fetch(`/api/shares?${params}`).then((r) => asJsonOrDetail(r))
}

// --- S12: one asset across brokers ---------------------------------------

export type Instrument = {
  key: string
  asset_key: string
  asset_name: string
  // How it joined its asset; null when nothing joined it to anything.
  linked_by: 'figi' | 'owner' | null
  name: string
  broker: string
  isin: string | null
  symbol: string | null
  ticker: string | null
  exchange_code: string | null
  figi: string | null
  asset_class: string
  portfolio_names: string[]
  quantity: string
  unit_value: string | null
  is_manual: boolean
  // #285: what prices it (null where nothing does) and the owner's own entry.
  yahoo_ticker: string | null
  quote_currency: string | null
  has_quotes: boolean
  owner_yahoo_ticker: string | null
  owner_quote_currency: string | null
}

// What the owner can pick as a listing's currency; GBp is pence (London).
export const QUOTE_CURRENCIES = ['PLN', 'USD', 'EUR', 'GBP', 'GBp'] as const

export type InstrumentSuggestion = {
  key_a: string
  key_b: string
  reasons: string[]
}

export type Instruments = {
  base_currency: string
  prices_as_of: string | null
  instruments: Instrument[]
  suggestions: InstrumentSuggestion[]
}

export function fetchInstruments(): Promise<Instruments> {
  return fetch('/api/instruments').then((r) => asJsonOrDetail(r))
}

export function decideInstrumentLink(keyA: string, keyB: string, same: boolean): Promise<Instruments> {
  return sendJson('POST', '/api/instruments/links', { key_a: keyA, key_b: keyB, same }).then((r) =>
    asJsonOrDetail(r),
  )
}

export function detachInstrument(key: string): Promise<Instruments> {
  return sendJson('POST', '/api/instruments/detach', { key }).then((r) => asJsonOrDetail(r))
}

// Both null clears the owner's entry for the instrument.
export function saveInstrumentOwnerData(
  key: string,
  yahooTicker: string | null,
  quoteCurrency: string | null,
): Promise<Instruments> {
  return sendJson('POST', '/api/instruments/owner-data', {
    key,
    yahoo_ticker: yahooTicker,
    quote_currency: quoteCurrency,
  }).then((r) => asJsonOrDetail(r))
}
