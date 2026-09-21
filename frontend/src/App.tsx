import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { createPortfolio, fetchHealth, fetchPortfolios } from './api'
import type { Portfolio } from './api'
import './App.css'

function App() {
  const [portfolios, setPortfolios] = useState<Portfolio[] | null>(null)
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [broker, setBroker] = useState('xtb')
  const [accountType, setAccountType] = useState('regular')

  function reloadPortfolios() {
    fetchPortfolios()
      .then(setPortfolios)
      .catch((e: Error) => setError(e.message))
  }

  useEffect(() => {
    fetchHealth()
      .then(() => setHealthy(true))
      .catch(() => setHealthy(false))
    reloadPortfolios()
  }, [])

  function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    createPortfolio({ name: name.trim(), broker, account_type: accountType })
      .then(() => {
        setName('')
        reloadPortfolios()
      })
      .catch((e: Error) => setError(e.message))
  }

  return (
    <div className="page">
      <header className="topbar">
        <span className="wordmark">Portfel</span>
        <span className="tag">lokalne narzędzie</span>
        <span className="spacer" />
        <span className={`health ${healthy ? 'ok' : healthy === false ? 'down' : ''}`}>
          {healthy === null ? 'sprawdzam…' : healthy ? 'backend OK' : 'backend niedostępny'}
        </span>
      </header>

      <main className="content">
        <h1>Twoje portfele</h1>
        {error && <p className="error">{error}</p>}

        {portfolios === null ? (
          <p>Wczytywanie…</p>
        ) : portfolios.length === 0 ? (
          <p className="muted">Brak portfeli — dodaj pierwszy poniżej.</p>
        ) : (
          <div className="grid">
            {portfolios.map((p) => (
              <div className="card" key={p.id}>
                <div className="badges">
                  {p.broker && <span className="badge">{p.broker.toUpperCase()}</span>}
                  {p.account_type && <span className="badge muted-badge">{p.account_type}</span>}
                </div>
                <div className="name">{p.name}</div>
                <div className="muted small">
                  utworzono {new Date(p.created_at).toLocaleDateString('pl-PL')}
                </div>
              </div>
            ))}
          </div>
        )}

        <form className="create-form" onSubmit={handleCreate}>
          <h2>Nowy portfel</h2>
          <label>
            Nazwa
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="np. XTB — Rachunek zwykły" />
          </label>
          <label>
            Broker
            <select value={broker} onChange={(e) => setBroker(e.target.value)}>
              <option value="xtb">XTB</option>
              <option value="bossa">Bossa</option>
              <option value="other">inny</option>
            </select>
          </label>
          <label>
            Typ konta
            <select value={accountType} onChange={(e) => setAccountType(e.target.value)}>
              <option value="regular">zwykły</option>
              <option value="ike">IKE</option>
              <option value="ikze">IKZE</option>
              <option value="other">inny</option>
            </select>
          </label>
          <button type="submit">Dodaj portfel</button>
        </form>
      </main>
    </div>
  )
}

export default App
