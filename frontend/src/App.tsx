import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, allLines, catalogue, config, demoIndex, recordedRun, startRun, streamRun } from './api'
import type { Clarification, Config, DemoIndex, RunEvent, RunRequest, Service } from './api'
import { Results } from './Results'
import { Trace } from './TracePane'
import { idle, lost, replay, sourceLine, starting, withAllLines } from './trace'
import type { RunState } from './trace'

const PIN_KEY = 'hpa.pin' // this browser only; it goes nowhere but /api/runs

export default function App() {
  const [run, setRun] = useState<RunState>(idle)
  const [zip, setZip] = useState('')
  const [service, setService] = useState('')
  const [live, setLive] = useState(false)
  const [pin, setPin] = useState(readPin)
  const [limits, setLimits] = useState<Config | null>(null)
  const [demo, setDemo] = useState<DemoIndex | null>(null)
  const [recorded, setRecorded] = useState(true) // false once a run of our own replaces it
  const [asking, setAsking] = useState<Clarification | null>(null)
  const [everything, setEverything] = useState<Service[] | null>(null) // the 70, for the input and for a miss
  const [submitting, setSubmitting] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null) // what Claude said when it settled the name
  const ran = useRef<{ zip: string; serviceId: string | null }>({ zip: '', serviceId: null })
  const requests = useRef(0) // a response is applied only if no newer request has been made
  const lastBody = useRef<RunRequest | null>(null) // what was asked, so a lost run can be asked again
  const lastLive = useRef(false)
  const retried = useRef(false) // a lost cache-first run is retried once, silently
  const startRef = useRef<(body: RunRequest, auto?: boolean) => Promise<void>>(async () => {})
  const stop = useRef<(() => void) | null>(null)

  const apply = useCallback((event: RunEvent) => setRun((state) => replay([event], state)), [])
  // The server no longer has the run (it restarted). A cache-first run costs nothing and
  // is simply asked again; a live one counts against the visitor's hourly limit, so it
  // waits for them to say so.
  const gone = useCallback((message: string) => {
    setRun((state) => lost(state, message))
    if (!lastLive.current && !retried.current && lastBody.current) {
      retried.current = true
      void startRef.current(lastBody.current, true)
    }
  }, [])

  // The page is never empty: it opens on the recorded Houston run, played through the
  // same reducer a live run uses.
  useEffect(() => {
    let cancelled = false
    Promise.all([demoIndex(), config().catch(() => null)])
      .then(async ([index, allowed]) => {
        const run = await recordedRun(index.zips[0], index.services[0].query)
        if (cancelled) return
        setDemo(index)
        setLimits(allowed)
        // A visitor who has already started their own run keeps it; the recording is
        // only the opening view, never something that overwrites what they asked for.
        if (requests.current > 0) return
        setZip(run.zip)
        setService(run.query)
        setRun(replay(run.events, starting(run.recorded_on)))
      })
      .catch((e: Error) => !cancelled && setProblem(e.message))
    catalogue()
      .then((all) => !cancelled && setEverything(all))
      .catch(() => {}) // the input still takes free text
    return () => {
      cancelled = true
      stop.current?.()
    }
  }, [])

  async function start(body: RunRequest, auto = false) {
    if (submitting) return
    if (!auto) retried.current = false
    const mine = ++requests.current
    setSubmitting(true)
    setProblem(null)
    setAsking(null)
    setNote(null)
    try {
      const started = await startRun({ ...body, live, pin: live ? pin : undefined })
      if (mine !== requests.current) return // a newer request has been made; this answer is stale
      if (started.status === 'needs_clarification') {
        setAsking(started) // the resolver could not settle it; nothing was scanned
        return
      }
      if (live) savePin(pin)
      stop.current?.()
      setRecorded(false)
      setNote(started.note ?? null)
      ran.current = { zip: body.zip, serviceId: started.service.id }
      lastBody.current = body
      lastLive.current = started.live
      // The server says whether this run goes to the web when it accepts it, so the
      // banner is right from the first line, not only after the last.
      setRun(starting(null, started.live))
      stop.current = streamRun(started.run_id, apply, gone)
    } catch (e) {
      if (mine === requests.current) setProblem(e instanceof ApiError ? e.message : (e as Error).message)
    } finally {
      if (mine === requests.current) setSubmitting(false)
    }
  }

  startRef.current = start

  // Answering a question: the input then reads what will actually be searched for.
  function pick(c: Service) {
    setService(c.name)
    void start({ zip: zip.trim(), service_id: c.id! })
  }

  // Every matching line for one hospital, from what is stored. Only a run of our own has
  // a service id to ask with; the recorded run shows what it recorded.
  async function showAll() {
    const { zip, serviceId } = ran.current
    const mine = requests.current
    if (!serviceId) return
    try {
      const got = await allLines(zip, serviceId)
      if (mine !== requests.current) return // the visitor has moved on to another run
      if (got.status === 'ok') setRun((state) => withAllLines(state, got.hospitals))
    } catch (e) {
      if (mine === requests.current) setProblem(e instanceof ApiError ? e.message : (e as Error).message)
    }
  }

  const running = (run.status === 'running' && !recorded) || submitting
  const variant = asking?.verdict.startsWith('unsupported variant') ?? false
  const prescanned = demo?.zips ?? []

  return (
    <div className="page">
      <header>
        <h1>hospital price agent</h1>
        <p className="sub">
          Cash prices for one of CMS's 70 shoppable services at the five hospitals nearest a ZIP code, read from
          each hospital's own machine-readable file. Every number keeps its source.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void start({ zip: zip.trim(), service: service.trim() })
          }}
        >
          <label>
            ZIP
            <input value={zip} onChange={(e) => setZip(e.target.value)} size={6} inputMode="numeric" required />
          </label>
          <label>
            Service
            <input value={service} onChange={(e) => setService(e.target.value)} list="recorded-services" size={22} required />
          </label>
          <datalist id="recorded-services">
            {demo?.services.map((s) => (
              <option key={s.query} value={s.query}>
                {s.name} ({s.codes})
              </option>
            ))}
            {everything?.map((s) => (
              <option key={s.id} value={s.name}>
                {s.codes}
              </option>
            ))}
          </datalist>
          <label className="check">
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            run live
          </label>
          {live && limits?.live_needs_pin && (
            <label>
              Password
              <input value={pin} onChange={(e) => setPin(e.target.value)} size={10} type="password" autoComplete="off" required />
            </label>
          )}
          <button type="submit" disabled={running}>
            {submitting ? 'asking…' : running ? 'running…' : live ? 'Scan live' : 'Show prices'}
          </button>
        </form>

        {prescanned.length > 0 && (
          <p className="hint">
            Already scanned, answered without a password or the network:{' '}
            {prescanned.map((z, i) => (
              <span key={z}>
                {i > 0 && ' · '}
                <button type="button" className="chip" onClick={() => setZip(z)}>
                  {z}
                </button>
              </span>
            ))}
            . Any other ZIP lists its nearest hospitals but has no files until someone runs it live.
          </p>
        )}

        <p className="banner">
          {sourceLine(recorded, demo?.recorded_on, run)} {liveNote(live, limits)}
        </p>
        {problem && (
          <p className="problem" role="alert">
            {problem}
          </p>
        )}
        {run.status === 'failed' && run.error && !recorded && (
          <p className="problem" role="alert">
            {run.error}
            {lastBody.current && (
              <button type="button" className="chip" onClick={() => void start(lastBody.current!)}>
                Run again
              </button>
            )}
          </p>
        )}
        {asking && (
          <div className="asking" role="status">
            <p>
              <strong>{asking.verdict}</strong>: {asking.question}
              {asking.asked_claude && <span className="detail"> (Claude was asked, and could not settle it either)</span>}
            </p>
            {asking.candidates.length > 0 ? (
              <p className="candidates">
                {asking.candidates.map((c) => (
                  <button key={c.id} type="button" onClick={() => pick(c)}>
                    {variant ? `search for ${c.name} instead` : c.name} <span className="codes">{c.codes}</span>
                  </button>
                ))}
              </p>
            ) : everything === null ? (
              <p className="detail">loading the list of services…</p>
            ) : (
              <>
                <p className="detail">The list only has these 70 services. Pick one, or try other words.</p>
                <p className="candidates all">
                  {everything.map((c) => (
                    <button key={c.id} type="button" onClick={() => pick(c)}>
                      {c.name} <span className="codes">{c.codes}</span>
                    </button>
                  ))}
                </p>
              </>
            )}
          </div>
        )}
      </header>

      <main className="split">
        <Trace run={run} />
        <Results run={run} note={note} onShowAll={!recorded && ran.current.serviceId ? showAll : undefined} />
      </main>
    </div>
  )
}

/** What a live scan needs and does, said before anyone ticks the box. */
function liveNote(live: boolean, limits: Config | null): string {
  const parts: string[] = []
  if (live) {
    parts.push('A live scan goes out to the web, and takes minutes for a file that is not already cached.')
  } else {
    parts.push('Tick “run live” to go and fetch the files now.')
  }
  const needs: string[] = []
  if (limits?.live_needs_pin) needs.push('the shared password (ask Alex for it)')
  if (limits?.max_downloads) needs.push(`reads at most ${limits.max_downloads} new files per run`)
  if (limits?.runs_per_hour) needs.push(`${limits.runs_per_hour} live runs an hour per address`)
  if (needs.length) parts.push(`Live scans need ${needs.join(', ')}.`)
  return parts.join(' ')
}

function readPin(): string {
  try {
    return sessionStorage.getItem(PIN_KEY) ?? ''
  } catch {
    return '' // a browser that refuses storage simply asks again
  }
}

function savePin(pin: string): void {
  try {
    sessionStorage.setItem(PIN_KEY, pin)
  } catch {
    // nothing to do: the password stays in this page's memory for the session
  }
}
