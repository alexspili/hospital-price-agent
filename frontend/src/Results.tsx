import type { HospitalResult, Line } from './api'
import { miles, money } from './trace'
import type { RunState } from './trace'

// The right pane: one card per hospital, in nearest-first order. A verdict is always
// shown, including "unknown"; a price is only ever shown with the context and the source
// row it came from.
export function Results({ run }: { run: RunState }) {
  const service = run.service
  return (
    <section className="results" aria-label="results">
      <h2>
        results
        {service && (
          <span className="service">
            {service.name} <span className="codes">{service.codes}</span>
            <span className={service.reviewed ? 'tag reviewed' : 'tag'}>
              {service.reviewed ? 'mapping reviewed' : 'mapping unreviewed'}
            </span>
          </span>
        )}
      </h2>
      {run.hospitals.length === 0 && <p className="empty">{run.status === 'running' ? 'looking…' : 'nothing yet'}</p>}
      {run.hospitals.map((h) => (
        <Hospital key={h.ccn} hospital={h} />
      ))}
    </section>
  )
}

function Hospital({ hospital: h }: { hospital: HospitalResult }) {
  const priced = h.headline
  return (
    <article className={`hospital ${verdictClass(h.verdict)}`}>
      <h3>
        {h.name}
        <span className="distance">{miles(h.distance_km, h.approximate)}</span>
      </h3>
      <p className="verdict">
        {h.verdict}
        {h.detail && <span className="detail"> — {h.detail}</span>}
      </p>
      {priced && (
        <>
          <table className="prices">
            <tbody>
              <tr>
                <th>cash</th>
                <th>gross</th>
                <th>negotiated</th>
              </tr>
              <tr>
                <td className="cash">{money(priced.cash)}</td>
                <td>{money(priced.gross)}</td>
                <td>{range(priced.min, priced.max)}</td>
              </tr>
            </tbody>
          </table>
          <p className="context">
            {priced.context} · {priced.description}
          </p>
          <Source hospital={h} line={priced} />
        </>
      )}
      {h.lines.length > 0 && (
        <details>
          <summary>
            {h.line_count} matching line{h.line_count === 1 ? '' : 's'} in the file
          </summary>
          <table className="lines">
            <tbody>
              {h.lines.map((l) => (
                <tr key={l.ref}>
                  <td className="code">
                    {l.code_type} {l.code}
                    {l.other_codes.length > 0 && <span className="also"> + {l.other_codes.join(', ')}</span>}
                  </td>
                  <td>{money(l.cash)}</td>
                  <td>{money(l.gross)}</td>
                  <td>{range(l.min, l.max)}</td>
                  <td className="context">{l.context}</td>
                  <td className="ref">{l.ref}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {h.line_count > h.lines.length && <p className="more">…{h.line_count - h.lines.length} more</p>}
        </details>
      )}
      {!priced && h.file_date && <Source hospital={h} line={null} />}
    </article>
  )
}

// Where the number came from: its row or JSON path, the file's date, and the file
// itself. A hospital with no readable file has none of these and gets no dead link.
function Source({ hospital: h, line }: { hospital: HospitalResult; line: Line | null }) {
  const parts = [
    line && (
      <span key="ref" className="ref">
        {line.ref}
      </span>
    ),
    h.file_date && <span key="date">file dated {h.file_date}</span>,
    h.url && (
      <a key="url" href={h.url} target="_blank" rel="noreferrer">
        source file
      </a>
    ),
  ].filter(Boolean)
  return <p className="source">{parts.flatMap((part, i) => (i ? [' · ', part] : [part]))}</p>
}

function range(min: number | null, max: number | null): string {
  return min === null && max === null ? '—' : `${money(min)}–${money(max)}`
}

function verdictClass(verdict: string): string {
  if (verdict === 'comparable') return 'ok'
  if (verdict.startsWith('unknown') || verdict === 'conflicting') return 'unsure'
  return 'thin'
}
