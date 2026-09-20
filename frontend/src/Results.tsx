import type { HospitalResult, Line, Pair } from './api'
import { miles, money } from './trace'
import type { RunState } from './trace'

// The right pane: one card per hospital, in nearest-first order. A verdict is always
// shown, including "unknown"; a price is only ever shown with the context and the source
// row it came from.
export function Results({ run, note, onShowAll }: { run: RunState; note?: string | null; onShowAll?: () => void }) {
  const service = run.service
  return (
    <section className="results" aria-label="results" aria-live="polite">
      <h2>
        results
        {service && (
          <span className="service">
            {service.name} <span className="codes">{service.codes}</span>
            <span
              className={service.reviewed ? 'tag reviewed' : 'tag'}
              title={
                service.reviewed
                  ? 'A person has checked that this catalog entry means this service and looked at how hospitals list it.'
                  : 'Nobody has yet checked by hand that this catalog entry maps to what hospitals list; the code match is automatic.'
              }
            >
              {service.reviewed ? 'mapping reviewed' : 'mapping unreviewed'}
            </span>
          </span>
        )}
      </h2>
      {/* The catalog's own caveat for the entry, and what Claude said if it chose it:
          the name alone does not say "without contrast". */}
      {service?.notes && <p className="note">{service.notes}</p>}
      {note && <p className="note">Claude picked this entry: {note}</p>}
      {run.hospitals.length > 0 && <Glossary />}
      {run.hospitals.length === 0 && <p className="empty">{run.status === 'running' ? 'looking…' : 'nothing yet'}</p>}
      {run.hospitals.map((h) => (
        <Hospital key={h.ccn} hospital={h} onShowAll={onShowAll} />
      ))}
      <Comparisons pairs={run.comparisons} />
    </section>
  )
}

// A verdict per hospital says whether its own rows make sense. This says whether two
// hospitals' prices can be put side by side — which is a different question, and the one
// a reader is actually asking when they look at two numbers.
function Comparisons({ pairs }: { pairs: Pair[] }) {
  if (pairs.length === 0) return null
  const comparable = pairs.filter((p) => p.verdict === 'comparable').length
  return (
    <details className="comparisons">
      <summary>
        side by side: {comparable} of {pairs.length} pairs comparable
      </summary>
      {pairs.map((p) => (
        <p key={`${p.a}|${p.b}`} className={p.verdict === 'comparable' ? 'ok' : p.verdict === 'unknown' ? 'unsure' : 'thin'}>
          {p.a} vs {p.b}: <strong>{p.verdict}</strong>
          {p.detail && <span className="detail"> ({p.detail})</span>}
        </p>
      ))}
    </details>
  )
}

// What the four numbers are, in the words a visitor asks with. These are the hospital's
// own published figures for one billing code, not a bill: a doctor's fee, anaesthesia or
// a second code on the same visit are separate lines, often in a separate file.
function Glossary() {
  return (
    <details className="glossary">
      <summary>what these prices mean</summary>
      <dl>
        <dt>cash</dt>
        <dd>the hospital's discounted price for a patient paying without insurance, for this one code</dd>
        <dt>gross</dt>
        <dd>the list price before any discount; almost nobody pays it, but it is what the rule requires first</dd>
        <dt>negotiated</dt>
        <dd>the lowest and highest rate the hospital has agreed with any insurer; an insured patient pays a share of one of them</dd>
        <dt>facility / professional</dt>
        <dd>whether the line is the hospital's own charge or a doctor's fee; only facility charges are put side by side</dd>
        <dt>outpatient / inpatient</dt>
        <dd>the setting the charge applies to; the 70 CMS services are outpatient, so an inpatient-only line is a different price</dd>
        <dt>comparable</dt>
        <dd>a hospital's own lines for the code agree and state their context; the side-by-side verdict below says whether two hospitals' lines match</dd>
      </dl>
      <p>
        None of these is the total a visit would cost: that depends on what else is billed with it. A missing amount means the
        file left it blank, and nothing is filled in.
      </p>
    </details>
  )
}

function Hospital({ hospital: h, onShowAll }: { hospital: HospitalResult; onShowAll?: () => void }) {
  const priced = h.headline
  return (
    <article className={`hospital ${verdictClass(h.verdict)}`}>
      <h3>
        <span>
          {h.name}
          {h.hospital_type && h.hospital_type !== 'Acute Care Hospitals' && (
            <span className="tag kind">{h.hospital_type}</span>
          )}
        </span>
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
            <thead>
              <tr>
                <th scope="col">code</th>
                <th scope="col">description</th>
                <th scope="col">cash</th>
                <th scope="col">gross</th>
                <th scope="col">negotiated</th>
                <th scope="col">context</th>
                <th scope="col">source</th>
              </tr>
            </thead>
            <tbody>
              {h.lines.map((l) => (
                <tr key={l.ref}>
                  <td className="code">
                    {l.code_type} {l.code}
                    {l.other_codes.length > 0 && <span className="also"> + {l.other_codes.join(', ')}</span>}
                  </td>
                  <td className="desc">
                    {l.description}
                    {l.note && <span className="also"> (file says: {l.note})</span>}
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
          {h.line_count > h.lines.length && (
            <p className="more">
              …{h.line_count - h.lines.length} more
              {onShowAll && (
                <button type="button" className="chip" onClick={onShowAll}>
                  show every line
                </button>
              )}
            </p>
          )}
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
