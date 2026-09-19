import { useEffect, useRef } from 'react'

import { counterText } from './trace'
import type { RunState } from './trace'

// The left pane: the work as it happens, one line per event, with a moving counter per
// hospital that is still reading a file. The counters sit at the bottom and are replaced
// in place, never appended (SPEC "Behaviour rules": a moving row counter, not a spinner).
export function Trace({ run }: { run: RunState }) {
  const bottom = useRef<HTMLDivElement>(null)
  const counters = Object.entries(run.counters)

  // Follow a live run; a recorded one opens at its first line, where a reader starts.
  useEffect(() => {
    if (run.status === 'running') bottom.current?.scrollIntoView({ block: 'end' })
  }, [run.seq, run.status])

  return (
    <section className="trace" aria-label="trace">
      <h2>
        trace
        {run.status === 'running' && <span className="pulse"> live</span>}
      </h2>
      <div className="lines">
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
        <div ref={bottom} />
      </div>
    </section>
  )
}
