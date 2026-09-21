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
