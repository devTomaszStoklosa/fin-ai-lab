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
