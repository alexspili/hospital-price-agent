import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, config, demoIndex, recordedRun, startRun, streamRun } from './api'
import type { Clarification, Config, DemoIndex, RunEvent, RunRequest } from './api'
import { Results } from './Results'
import { Trace } from './TracePane'
import { idle, replay, starting } from './trace'
import type { RunState } from './trace'

const PIN_KEY = 'hpa.pin' // this browser only; it goes nowhere but /api/runs

export default function App() {
  const [run, setRun] = useState<RunState>(idle)
  const [zip, setZip] = useState('77030')
  const [service, setService] = useState('knee mri')
  const [live, setLive] = useState(false)
  const [pin, setPin] = useState(readPin)
  const [limits, setLimits] = useState<Config | null>(null)
  const [demo, setDemo] = useState<DemoIndex | null>(null)
  const [recorded, setRecorded] = useState(true) // false once a run of our own replaces it
  const [asking, setAsking] = useState<Clarification | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const stop = useRef<(() => void) | null>(null)

  const apply = useCallback((event: RunEvent) => setRun((state) => replay([event], state)), [])

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
        setZip(run.zip)
        setService(run.query)
        setRun(replay(run.events, starting(run.recorded_on)))
      })
      .catch((e: Error) => !cancelled && setProblem(e.message))
    return () => {
      cancelled = true
      stop.current?.()
    }
  }, [])

  async function start(body: RunRequest) {
    setProblem(null)
    setAsking(null)
    try {
      const started = await startRun({ ...body, live, pin: live ? pin : undefined })
      if (started.status === 'needs_clarification') {
        setAsking(started) // the resolver could not settle it; nothing was scanned
        return
      }
      if (live) savePin(pin)
      stop.current?.()
      setRecorded(false)
      setRun(starting())
      stop.current = streamRun(started.run_id, apply)
    } catch (e) {
      setProblem(e instanceof ApiError ? e.message : (e as Error).message)
    }
  }

  const running = run.status === 'running' && !recorded

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
          </datalist>
          <label className="check">
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            run live
          </label>
          {live && limits?.live_needs_pin && (
            <label>
              PIN
              <input value={pin} onChange={(e) => setPin(e.target.value)} size={8} type="password" required />
            </label>
          )}
          <button type="submit" disabled={running}>
            {running ? 'running…' : live ? 'Scan live' : 'Show prices'}
          </button>
        </form>

        <p className="banner">
          {state(recorded, demo?.recorded_on, run)}{' '}
          {live
            ? 'A live scan goes out to the web, and takes minutes for a file that is not already cached.'
            : 'Tick “run live” to go and fetch the files now.'}
          {limits?.runs_per_hour ? ` Live scans are limited to ${limits.runs_per_hour} an hour.` : ''}
        </p>
        {problem && <p className="problem">{problem}</p>}
        {asking && (
          <div className="asking">
            <p>
              <strong>{asking.verdict}</strong>: {asking.question}
            </p>
            <p className="candidates">
              {asking.candidates.map((c) => (
                <button key={c.id} type="button" onClick={() => void start({ zip: zip.trim(), service_id: c.id! })}>
                  {c.name} <span className="codes">{c.codes}</span>
                </button>
              ))}
            </p>
          </div>
        )}
      </header>

      <main className="split">
        <Trace run={run} />
        <Results run={run} />
      </main>
    </div>
  )
}

/** Where the numbers on screen came from — said plainly, because it changes what they mean. */
function state(recorded: boolean, recordedOn: string | undefined, run: RunState): string {
  if (recorded) return `A recorded run from ${recordedOn ?? 'earlier'}: no network, no database.`
  if (run.live === false) return 'Answered from files scanned earlier — nothing was fetched just now.'
  return 'Scanned live from each hospital’s own file.'
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
    // nothing to do: the PIN stays in this page's memory for the session
  }
}
