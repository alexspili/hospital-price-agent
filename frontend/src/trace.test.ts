import { describe, expect, it } from 'vitest'

import type { HospitalResult, RunEvent, Service } from './api'
import type { Counter, RunState } from './trace'
import { counterText, idle, lost, money, reduce, replay, sourceLine, starting, withAllLines } from './trace'

const service: Service = { id: 'cpt-73721', name: 'MRI scan of leg joint', codes: 'CPT 73721', reviewed: true }

function hospital(ccn: string, verdict = 'comparable'): HospitalResult {
  return {
    ccn,
    name: `Hospital ${ccn}`,
    distance_km: 1.6,
    approximate: false,
    url: 'https://example.test/f.csv',
    file_date: '2026-09-01',
    verdict,
    detail: '',
    line_count: 1,
    headline: null,
    lines: [],
  }
}

describe('the trace reducer', () => {
  it('appends trace lines in order and keeps the sequence', () => {
    const state = replay([
      { seq: 1, kind: 'trace', text: 'nearest 5 hospitals to the centre of 77030' },
      { seq: 2, kind: 'trace', ccn: '450289', text: 'Harris Health: cms-hpt.txt found' },
    ])
    expect(state.lines.map((l) => l.text)).toEqual([
      'nearest 5 hospitals to the centre of 77030',
      'Harris Health: cms-hpt.txt found',
    ])
    expect(state.seq).toBe(2)
  })

  it('ignores events it has already seen, so a reconnect does not duplicate the trace', () => {
    const events: RunEvent[] = [
      { seq: 1, kind: 'trace', text: 'one' },
      { seq: 2, kind: 'trace', text: 'two' },
    ]
    // The server replays from Last-Event-ID, which can resend what we have.
    const state = replay([...events, ...events])
    expect(state.lines.map((l) => l.text)).toEqual(['one', 'two'])
  })

  it('replaces a hospital counter instead of appending lines', () => {
    const state = replay([
      { seq: 1, kind: 'progress', ccn: '450289', name: 'Harris Health', phase: 'download', done: 5_000_000, total: 10_000_000 },
      { seq: 2, kind: 'progress', ccn: '450289', name: 'Harris Health', phase: 'extract', done: 1_200_000, total: null },
      { seq: 3, kind: 'progress', ccn: '450068', name: 'Memorial Hermann', phase: 'extract', done: 4_000, total: null },
    ])
    expect(state.lines).toHaveLength(0)
    expect(Object.keys(state.counters).sort()).toEqual(['450068', '450289'])
    expect(state.counters['450289']).toEqual({ name: 'Harris Health', phase: 'extract', done: 1_200_000, total: null })
  })

  it('drops a hospital counter once that hospital has a result', () => {
    const state = replay([
      { seq: 1, kind: 'progress', ccn: '450289', name: 'Harris Health', phase: 'extract', done: 10, total: null },
      { seq: 2, kind: 'hospital', hospital: hospital('450289') },
    ])
    expect(state.counters).toEqual({})
    expect(state.hospitals.map((h) => h.ccn)).toEqual(['450289'])
  })

  it('keeps one row per hospital when a later event revises it', () => {
    const state = replay([
      { seq: 1, kind: 'hospital', hospital: hospital('450289', 'not scanned') },
      { seq: 2, kind: 'hospital', hospital: hospital('450289', 'comparable') },
    ])
    expect(state.hospitals).toHaveLength(1)
    expect(state.hospitals[0].verdict).toBe('comparable')
  })

  it('takes the run order from the result, not the order files finished in', () => {
    const state = replay([
      { seq: 1, kind: 'hospital', hospital: hospital('450068') },
      { seq: 2, kind: 'hospital', hospital: hospital('450289') },
      { seq: 3, kind: 'result', zip: '77030', service, hospitals: [hospital('450289'), hospital('450068')] },
      { seq: 4, kind: 'end' },
    ])
    expect(state.hospitals.map((h) => h.ccn)).toEqual(['450289', '450068'])
    expect(state.service?.codes).toBe('CPT 73721')
    expect(state.status).toBe('done')
  })

  it('names the hospitals without a price once, beside the pairs that have two', () => {
    const state = replay([{ seq: 1, kind: 'result', zip: '77030', service, hospitals: [], comparisons: [{ a: 'A', b: 'C', verdict: 'comparable', detail: '' }], unpriced: ['B'] }])
    expect(state.unpriced).toEqual(['B'])
    expect(state.comparisons).toHaveLength(1)
    expect(replay([{ seq: 1, kind: 'result', zip: '77030', service, hospitals: [] }]).unpriced).toEqual([])
  })

  it('remembers whether the run went to the web, because it changes what the prices mean', () => {
    const cached = replay([{ seq: 1, kind: 'result', zip: '77030', service, live: false, hospitals: [] }])
    expect(cached.live).toBe(false)
    const fresh = replay([{ seq: 1, kind: 'result', zip: '77030', service, live: true, hospitals: [] }])
    expect(fresh.live).toBe(true)
    // A recorded run says nothing about it, and nothing is assumed.
    expect(replay([{ seq: 1, kind: 'result', zip: '77030', service, hospitals: [] }]).live).toBeNull()
  })

  it('a failed run stays failed, and says why', () => {
    const state = replay([
      { seq: 1, kind: 'error', message: 'UnknownZip: 00000 is not a residential ZIP code' },
      { seq: 2, kind: 'end' },
    ])
    expect(state.status).toBe('failed')
    expect(state.error).toContain('00000')
  })

  it('starts empty and running, and a stale event cannot move it', () => {
    expect(idle.status).toBe('idle')
    const state = starting('2026-09-19')
    expect(state.recordedOn).toBe('2026-09-19')
    expect(reduce({ ...state, seq: 5 }, { seq: 5, kind: 'trace', text: 'old' })).toEqual({ ...state, seq: 5 })
  })
})

describe('formatting', () => {
  it('shows a missing price as an em dash, never as zero', () => {
    expect(money(null)).toBe('—')
    expect(money(2735.8)).toBe('$2,735.80')
  })

  it('counts rows, and percentages only when the size is known', () => {
    const at = (c: Partial<Counter>): Counter => ({ name: 'Harris Health', phase: 'extract', done: 0, total: null, ...c })
    expect(counterText(at({ done: 1_400_000 }))).toBe('1,400,000 charges read')
    expect(counterText(at({ phase: 'download', done: 5_000_000, total: 10_000_000 }))).toBe('downloading 5 MB (50%)')
    expect(counterText(at({ phase: 'download', done: 5_000_000 }))).toBe('downloading 5 MB')
  })
})

describe('what the banner says the numbers are', () => {
  const run = (over: Partial<RunState>): RunState => ({ ...starting(), ...over })

  it('never claims a live scan for a run that has not finished one', () => {
    expect(sourceLine(false, undefined, run({ live: false, status: 'running' }))).toMatch(/scanned earlier/)
    expect(sourceLine(false, undefined, run({ live: true, status: 'running' }))).toMatch(/^Scanning live/)
    expect(sourceLine(false, undefined, run({ live: true, status: 'failed' }))).toMatch(/stopped early/)
    expect(sourceLine(false, undefined, run({ live: null, status: 'failed' }))).not.toMatch(/Scanned live/)
    expect(sourceLine(false, undefined, run({ live: true, status: 'done' }))).toBe('Scanned live from each hospital’s own file.')
    expect(sourceLine(true, '2026-09-19', run({}))).toContain('2026-09-19')
  })

  it('knows from the start whether a run goes to the web', () => {
    expect(starting(null, false).live).toBe(false)
    expect(starting(null, true).live).toBe(true)
    expect(starting('2026-09-19').live).toBeNull()
  })

  it('a stream that cannot be resumed fails the run instead of leaving it running', () => {
    const gone = lost(starting(null, true), 'lost the connection')
    expect(gone.status).toBe('failed')
    expect(gone.error).toBe('lost the connection')
    const done = replay([{ seq: 1, kind: 'result', zip: '77030', service, live: true, hospitals: [] }])
    expect(lost(done, 'late')).toBe(done) // a finished run is not un-finished by a late error
  })

  it('takes every line for a hospital without touching its verdict', () => {
    const shown = { ...hospital('450289'), line_count: 12, lines: [] }
    const state = replay([{ seq: 1, kind: 'hospital', hospital: shown }])
    const full = { ...shown, verdict: 'something else', lines: Array(12).fill(null).map((_, i) => line(`row ${i}`)), line_count: 12 }
    const after = withAllLines(state, [full, { ...hospital('999999'), lines: [line('row 1')] }])
    expect(after.hospitals).toHaveLength(1)
    expect(after.hospitals[0].lines).toHaveLength(12)
    expect(after.hospitals[0].verdict).toBe('comparable')
  })
})

function line(ref: string) {
  return { code_type: 'CPT', code: '73721', other_codes: [], description: 'MRI', context: 'outpatient', cash: 1, gross: 2,
           min: null, max: null, setting: 'outpatient', billing_class: null, modifiers: null, ref, note: null }
}
