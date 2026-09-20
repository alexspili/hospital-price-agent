import { useEffect, useRef } from 'react'

import { counterText } from './trace'
import type { RunState } from './trace'

// The left pane: the work as it happens, one line per event, with a moving counter per
// hospital that is still reading a file. The counters sit at the bottom and are replaced
// in place, never appended (SPEC "Behaviour rules": a moving row counter, not a spinner).
export function Trace({ run }: { run: RunState }) {
  const box = useRef<HTMLDivElement>(null)
  const counters = Object.entries(run.counters)

  // Follow a live run inside its own box (never by moving the page, which on a phone
  // would drag the reader away from the prices); a recorded one opens at its first line.
  useEffect(() => {
    const el = box.current
    if (run.status === 'running' && el) el.scrollTop = el.scrollHeight
  }, [run.seq, run.status])

  return (
    <section className="trace" aria-label="trace">
      <h2>
        trace
        {run.status === 'running' && <span className="pulse"> live</span>}
      </h2>
      <div className="lines" ref={box} tabIndex={0}>
        {run.lines.map((line) => (
          <div key={line.seq} className="line">
            {line.text}
          </div>
        ))}
        {counters.map(([ccn, counter]) => (
          <div key={ccn} className="line counter">
            {counter.name}: {counterText(counter)}
          </div>
        ))}
        {run.error && <div className="line failed">{run.error}</div>}
      </div>
    </section>
  )
}
