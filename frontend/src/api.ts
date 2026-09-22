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
}

export type PositionUpdate = PositionCreate & {
  market_value: string
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

export function createPortfolio(payload: PortfolioCreate): Promise<Portfolio> {
  return fetch('/api/portfolios', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => asJson(r))
}

export function fetchSnapshots(portfolioId: string): Promise<Snapshot[]> {
  return fetch(`/api/portfolios/${portfolioId}/snapshots`).then((r) => asJson(r))
}

export async function importFile(
  portfolioId: string,
  file: File,
  valuationDate: string,
): Promise<{ snapshot: Snapshot; warnings: string[] }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('valuation_date', valuationDate)

  const response = await fetch(`/api/portfolios/${portfolioId}/import`, {
    method: 'POST',
    body: formData,
  })
  const body = await response.json()

  if (!response.ok) {
    const detail = body.detail ?? {}
    throw new ImportFailure(detail.errors ?? [response.statusText], detail.warnings ?? [])
  }
  return body as { snapshot: Snapshot; warnings: string[] }
}

export async function importBossaFile(
  portfolioId: string,
  file: File,
  valuationDate: string,
): Promise<{ snapshot: Snapshot; warnings: string[] }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('valuation_date', valuationDate)

  const response = await fetch(`/api/portfolios/${portfolioId}/import/bossa`, {
    method: 'POST',
    body: formData,
  })
  const body = await response.json()

  if (!response.ok) {
    const detail = body.detail ?? {}
    throw new ImportFailure(detail.errors ?? [response.statusText], detail.warnings ?? [])
  }
  return body as { snapshot: Snapshot; warnings: string[] }
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
  const body = await response.json()

  if (!response.ok) {
    const detail = body.detail ?? {}
    throw new ImportFailure(detail.errors ?? [response.statusText], detail.warnings ?? [])
  }
  return body as ProposePreview
}

export function fetchPositions(portfolioId: string): Promise<Position[]> {
  return fetch(`/api/portfolios/${portfolioId}/positions`).then((r) => asJson(r))
}

export function createPosition(portfolioId: string, payload: PositionCreate): Promise<Position> {
  return fetch(`/api/portfolios/${portfolioId}/positions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => asJson(r))
}

export function updatePosition(
  portfolioId: string,
  positionId: string,
  payload: PositionUpdate,
): Promise<Position> {
  return fetch(`/api/portfolios/${portfolioId}/positions/${positionId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => asJson(r))
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
  const body = await response.json()

  if (!response.ok) {
    const detail = body.detail ?? {}
    throw new ImportFailure(detail.errors ?? [response.statusText], detail.warnings ?? [])
  }
  return body as { snapshot: Snapshot; warnings: string[] }
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
