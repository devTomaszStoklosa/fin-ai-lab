import { useState } from 'react'
import type { FormEvent } from 'react'
import { ImportFailure, approveImportConfig, proposeImportConfig } from './api'
import type { ProposePreview, Snapshot } from './api'
import { trimTrailingZeros } from './format'

type Props = {
  portfolioId: string
  file: File
  valuationDate: string
  onApproved: (result: { snapshot: Snapshot; warnings: string[] }) => void
  onCancel: () => void
}

function ProposeConfig({ portfolioId, file, valuationDate, onApproved, onCancel }: Props) {
  const [broker, setBroker] = useState('')
  const [proposal, setProposal] = useState<ProposePreview | null>(null)
  const [proposing, setProposing] = useState(false)
  const [approving, setApproving] = useState(false)
  const [errors, setErrors] = useState<string[] | null>(null)

  function handlePropose(event: FormEvent) {
    event.preventDefault()
    if (!broker.trim()) return
    setProposing(true)
    setErrors(null)
    proposeImportConfig(portfolioId, file, broker.trim(), valuationDate)
      .then(setProposal)
      .catch((e: Error) => setErrors(e instanceof ImportFailure ? e.errors : [e.message]))
      .finally(() => setProposing(false))
  }

  function handleApprove() {
    if (!proposal) return
    setApproving(true)
    setErrors(null)
    approveImportConfig(portfolioId, file, proposal.config, valuationDate)
      .then(onApproved)
      .catch((e: Error) => setErrors(e instanceof ImportFailure ? e.errors : [e.message]))
      .finally(() => setApproving(false))
  }

  function handleReject() {
    // Propose never saves anything, so "reject" is a purely local reset --
    // no request needed, there is nothing on the server to undo.
    setProposal(null)
  }

  return (
    <div className="propose-config">
      <p className="muted small">
        Nierozpoznany format pliku. Zaproponuj nazwę brokera, a model spróbuje wywnioskować
        mapowanie kolumn.
      </p>

      {proposal === null ? (
        <form className="propose-form" onSubmit={handlePropose}>
          <label>
            Nazwa brokera
            <input
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
              placeholder="np. Interactive Brokers"
            />
          </label>
          <div className="propose-actions">
            <button type="submit" disabled={!broker.trim() || proposing}>
              {proposing ? 'Analizuję…' : 'Zaproponuj konfigurację'}
            </button>
            <button type="button" className="btn-ghost" onClick={onCancel}>
              Anuluj
            </button>
          </div>
        </form>
      ) : (
        <div className="proposal-preview">
          <h3>Proponowana konfiguracja — {proposal.config.broker}</h3>
          <p className="muted small">
            Arkusz: {proposal.config.sheet_name ?? '—'}, wiersz nagłówka:{' '}
            {proposal.config.header_row}
          </p>
          <ul className="mapping-list">
            {Object.entries(proposal.config.column_mapping).map(([header, field]) => (
              <li key={header}>
                <span className="mono">{header}</span> → {field}
              </li>
            ))}
          </ul>

          <p className="muted small">Pierwsze pozycje z tym mapowaniem:</p>
          <table className="positions">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Ilość</th>
                <th>Śr. koszt</th>
                <th>Wartość</th>
              </tr>
            </thead>
            <tbody>
              {proposal.positions.slice(0, 5).map((position) => (
                <tr key={position.instrument_name}>
                  <td>{position.instrument_name}</td>
                  <td>{trimTrailingZeros(position.quantity)}</td>
                  <td>
                    {position.avg_cost ? trimTrailingZeros(position.avg_cost) : '—'}{' '}
                    {position.cost_currency ?? ''}
                  </td>
                  <td>
                    {position.market_value ? trimTrailingZeros(position.market_value) : '—'}{' '}
                    {position.market_currency ?? ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="propose-actions">
            <button type="button" onClick={handleApprove} disabled={approving}>
              {approving ? 'Zapisuję…' : 'Zatwierdź i zaimportuj'}
            </button>
            <button type="button" className="btn-ghost" onClick={handleReject}>
              Odrzuć
            </button>
          </div>
        </div>
      )}

      {errors && (
        <div className="banner banner-error">
          {errors.map((error) => (
            <p key={error}>{error}</p>
          ))}
        </div>
      )}
    </div>
  )
}

export default ProposeConfig
