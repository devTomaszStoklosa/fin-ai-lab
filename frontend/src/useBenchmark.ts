import { useEffect, useRef, useState } from 'react'
import { fetchBenchmark } from './api'
import type { Benchmark } from './api'

const STORAGE_KEY = 'fin-ai-lab.benchmark'
const DEFAULT_TICKER = 'ETFBW20TR.WA' // WIG20, through its total-return fund

// The chosen benchmark, remembered in this browser only (#273) -- a
// convenience: storage may be blocked or empty, and the default then applies.
export function useStoredBenchmarkTicker() {
  const [ticker, setTicker] = useState<string>(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY) ?? DEFAULT_TICKER
    } catch {
      return DEFAULT_TICKER
    }
  })

  function choose(next: string) {
    setTicker(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Not remembered next time; the choice still applies now.
    }
  }

  return [ticker, choose] as const
}

// The response and the request it answers -- loading is derived from the
// two not matching, rather than set inside the effect.
type State = { key: string | null; benchmark: Benchmark | null; error: string | null }

// The benchmark on the valuation's day axis (`start` = its first day). Asked
// for only while `enabled` -- the chart's comparison mode -- so Yahoo is never
// queried for a benchmark nobody looks at. The previous series stays while a
// new one loads (the chart dims instead of jumping).
export function useBenchmark(ticker: string, start: string | null, enabled: boolean) {
  const [state, setState] = useState<State>({ key: null, benchmark: null, error: null })
  const [refreshToken, setRefreshToken] = useState(0)
  // An explicit "odśwież" bypasses today's quote cache once, like the
  // valuation's own refresh.
  const bypassCache = useRef(false)
  const key = `${ticker}|${start}|${refreshToken}`

  useEffect(() => {
    if (!enabled || start === null) return
    let cancelled = false
    const refresh = bypassCache.current
    bypassCache.current = false
    const requested = `${ticker}|${start}|${refreshToken}`
    fetchBenchmark(ticker, start, refresh)
      .then((benchmark) => {
        if (!cancelled) setState({ key: requested, benchmark, error: null })
      })
      .catch((e: Error) => {
        if (!cancelled) setState({ key: requested, benchmark: null, error: e.message })
      })
    return () => {
      cancelled = true
    }
  }, [ticker, start, enabled, refreshToken])

  function refresh() {
    bypassCache.current = true
    setRefreshToken((token) => token + 1)
  }

  const loading = enabled && start !== null && state.key !== key
  return {
    benchmark: state.benchmark,
    error: loading ? null : state.error,
    loading,
    refresh,
  }
}
