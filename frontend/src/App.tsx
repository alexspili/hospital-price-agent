import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, demoIndex, recordedRun, startRun, streamRun } from './api'
import type { Clarification, DemoIndex, RunEvent } from './api'
import { Results } from './Results'
import { Trace } from './TracePane'
import { idle, replay, starting } from './trace'
import type { RunState } from './trace'

export default function App() {
  const [run, setRun] = useState<RunState>(idle)
  const [zip, setZip] = useState('77030')
  const [service, setService] = useState('knee mri')
  const [demo, setDemo] = useState<DemoIndex | null>(null)
  const [recorded, setRecorded] = useState(true) // false once a live run replaces it
  const [asking, setAsking] = useState<Clarification | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const stop = useRef<(() => void) | null>(null)

  const apply = useCallback((event: RunEvent) => setRun((state) => replay([event], state)), [])

  // The page is never empty: it opens on the recorded Houston run, played through the
  // same reducer a live run uses.
  useEffect(() => {
    let cancelled = false
    demoIndex()
      .then(async (index) => {
        const run = await recordedRun(index.zips[0], index.services[0].query)
        if (cancelled) return
        setDemo(index)
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

  async function start(body: { zip: string; service?: string; service_id?: string }) {
    setProblem(null)
    setAsking(null)
    try {
      const started = await startRun(body)
      if (started.status === 'needs_clarification') {
        setAsking(started) // the resolver could not settle it; nothing was scanned
        return
      }
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
          <button type="submit" disabled={running}>
            {running ? 'running…' : 'Run live'}
          </button>
        </form>

        {recorded && demo && (
          <p className="banner">
            A recorded run from {demo.recorded_on}: no network, no database. <strong>Run live</strong> scans for
            real, which takes minutes for a file that is not already cached.
          </p>
        )}
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
