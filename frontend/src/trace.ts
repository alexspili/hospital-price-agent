// The page's whole state machine: events in, what to draw out.
//
// Events arrive in order and carry a sequence number. A dropped connection is resumed
// with Last-Event-ID, which can replay an event the page already has, so anything not
// newer than what has been seen is ignored. Progress for a hospital replaces that
// hospital's counter rather than appending a line: a moving counter, not a log of one.

import type { HospitalResult, Pair, RunEvent, Service } from './api'

export type TraceLine = { seq: number; ccn?: string; text: string }
export type Counter = { name: string; phase: 'download' | 'extract'; done: number; total: number | null }

export type RunState = {
  seq: number
  status: 'idle' | 'running' | 'done' | 'failed'
  lines: TraceLine[]
  counters: Record<string, Counter>
  hospitals: HospitalResult[]
  comparisons: Pair[] // between hospitals that both have a price
  unpriced: string[] // hospitals with no priced line, named once rather than once per pair
  service: Service | null
  error: string | null
  recordedOn: string | null
  // Did this run go to the web, or answer from files scanned earlier? The page says so,
  // because it changes what the numbers mean. Known from the moment the run starts (the
  // server says so when it accepts the request); null only for a recorded run.
  live: boolean | null
}

export const idle: RunState = {
  seq: 0,
  status: 'idle',
  lines: [],
  counters: {},
  hospitals: [],
  comparisons: [],
  unpriced: [],
  service: null,
  error: null,
  recordedOn: null,
  live: null,
}

export function starting(recordedOn: string | null = null, live: boolean | null = null): RunState {
  return { ...idle, status: 'running', recordedOn, live }
}

export function reduce(state: RunState, event: RunEvent): RunState {
  if (event.seq <= state.seq) return state // already seen: a replayed event after a reconnect
  const next = { ...state, seq: event.seq }
  switch (event.kind) {
    case 'trace':
      return { ...next, lines: [...state.lines, { seq: event.seq, ccn: event.ccn, text: event.text }] }
    case 'progress':
      return {
        ...next,
        counters: { ...state.counters, [event.ccn]: { name: event.name, phase: event.phase, done: event.done, total: event.total } },
      }
    case 'hospital': {
      const { [event.hospital.ccn]: _done, ...counters } = state.counters
      return { ...next, counters, hospitals: upsert(state.hospitals, event.hospital) }
    }
    case 'result':
      // The run's own order is nearest first, whatever order the files finished in.
      return { ...next, hospitals: event.hospitals, comparisons: event.comparisons ?? [], unpriced: event.unpriced ?? [],
               service: event.service, counters: {}, live: event.live ?? state.live, status: 'done' }
    case 'error':
      return { ...next, status: 'failed', error: event.message, counters: {} }
    case 'end':
      return { ...next, status: state.status === 'failed' ? 'failed' : 'done', counters: {} }
  }
}

// The stream ended without the run's own end: a reconnect that found no run to resume.
export function lost(state: RunState, message: string): RunState {
  if (state.status !== 'running') return state
  return { ...state, status: 'failed', error: message, counters: {} }
}

// Every matching line for the hospitals that asked for them, from /api/prices?all=true.
// Only the lines change: the verdict and the headline were computed once and stay.
export function withAllLines(state: RunState, full: HospitalResult[]): RunState {
  const byCcn = new Map(full.map((h) => [h.ccn, h]))
  return {
    ...state,
    hospitals: state.hospitals.map((h) => {
      const f = byCcn.get(h.ccn)
      return f ? { ...h, lines: f.lines, line_count: f.line_count } : h
    }),
  }
}

function upsert(hospitals: HospitalResult[], h: HospitalResult): HospitalResult[] {
  const at = hospitals.findIndex((x) => x.ccn === h.ccn)
  if (at < 0) return [...hospitals, h]
  const copy = [...hospitals]
  copy[at] = h
  return copy
}

export const replay = (events: RunEvent[], from: RunState = starting()): RunState => events.reduce(reduce, from)

/** Where the numbers on screen came from — said plainly, because it changes what they
 * mean. Never claims a live scan for a run that has not finished one. */
export function sourceLine(recorded: boolean, recordedOn: string | undefined, run: RunState): string {
  if (recorded) return `A recorded run from ${recordedOn ?? 'earlier'}: no network, no database.`
  if (run.live === false) {
    return run.status === 'running'
      ? 'Reading files scanned earlier — nothing is being fetched.'
      : 'Answered from files scanned earlier — nothing was fetched just now.'
  }
  if (run.live === true) {
    if (run.status === 'running') return 'Scanning live: reading each hospital’s own file now.'
    if (run.status === 'failed') return 'The live scan stopped early; anything shown was read before it failed.'
    return 'Scanned live from each hospital’s own file.'
  }
  return run.status === 'failed' ? 'The run failed before it read anything.' : 'Starting…'
}

export function money(v: number | null): string {
  return v === null ? '—' : v.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function miles(km: number, approximate: boolean): string {
  return `${approximate ? '~' : ''}${(km / 1.609344).toFixed(1)} mi`
}

export function counterText(c: Counter): string {
  if (c.phase === 'download') {
    const mb = `${(c.done / 1e6).toLocaleString('en-US', { maximumFractionDigits: 0 })} MB`
    return c.total ? `downloading ${mb} (${Math.round((c.done / c.total) * 100)}%)` : `downloading ${mb}`
  }
  return `${c.done.toLocaleString('en-US')} charges read`
}
