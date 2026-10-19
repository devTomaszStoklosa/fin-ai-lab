import { useEffect, useState } from 'react'
import { fetchDividendForecast, fetchDividendHistory } from './api'
import type { DividendForecast, DividendHistory } from './api'
import DividendForecastPanel from './DividendForecastPanel'
import DividendHistoryPanel from './DividendHistoryPanel'

type Props = {
  // Omitted: every portfolio together (the start page).
  portfolioId?: string
  // Changes when the page's data does (an import, a refresh) -- refetch.
  reloadToken?: unknown
}

type Tab = 'history' | 'forecast'

// #265/#266: dividends paid (history) and the next calendar year's
// estimate. The history comes from the database and shows at once; the
// estimate asks Yahoo and arrives later, then also adds its bar to the
// history's chart.
function DividendsCard({ portfolioId, reloadToken }: Props) {
  const [tab, setTab] = useState<Tab>('history')
  const [history, setHistory] = useState<DividendHistory | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [forecast, setForecast] = useState<DividendForecast | null>(null)
  const [forecastError, setForecastError] = useState<string | null>(null)

  useEffect(() => {
    fetchDividendHistory(portfolioId)
      .then((result) => {
        setHistory(result)
        setHistoryError(null)
      })
      .catch((e: Error) => setHistoryError(e.message))
    fetchDividendForecast(portfolioId)
      .then((result) => {
        setForecast(result)
        setForecastError(null)
      })
      .catch((e: Error) => setForecastError(e.message))
  }, [portfolioId, reloadToken])

  const nextYear = forecast?.year ?? new Date().getFullYear() + 1

  return (
    <section className="value-card dividends-card">
      <div className="value-head">
        <div>
          <div className="value-eyebrow">Dywidendy</div>
          <h2>{tab === 'history' ? 'Wypłacone dywidendy' : `Szacunek na ${nextYear}`}</h2>
        </div>
        <div className="segmented" role="group" aria-label="Widok dywidend">
          <button type="button" aria-pressed={tab === 'history'} onClick={() => setTab('history')}>
            Historia
          </button>
          <button type="button" aria-pressed={tab === 'forecast'} onClick={() => setTab('forecast')}>
            Szacunek {nextYear}
          </button>
        </div>
      </div>

      {tab === 'forecast' ? (
        <DividendForecastPanel forecast={forecast} error={forecastError} />
      ) : history === null ? (
        <p className={historyError ? 'error' : 'muted'}>{historyError ?? 'Wczytuję wypłaty dywidend…'}</p>
      ) : (
        <DividendHistoryPanel history={history} forecast={forecast} />
      )}
    </section>
  )
}

export default DividendsCard
