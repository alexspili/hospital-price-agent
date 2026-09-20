// What the API sends, and the calls the page makes. The shapes come from
// hpa/pipeline.py: a hospital result is computed there, never here. The page formats
// numbers; it never derives one.

export type Line = {
  code_type: string
  code: string
  other_codes: string[]
  description: string
  context: string
  cash: number | null
  gross: number | null
  min: number | null
  max: number | null
  setting: string | null
  billing_class: string | null
  modifiers: string | null
  ref: string
  note: string | null
}

export type HospitalResult = {
  ccn: string
  name: string
  distance_km: number
  approximate: boolean
  hospital_type?: string | null
  url: string | null
  file_date: string | null
  verdict: string
  detail: string
  line_count: number
  headline: Line | null
  lines: Line[]
}

// `notes` is the catalog's own caveat for the entry ("Without contrast. …"): what the
// service name alone does not say, and what a visitor asking for a variant needs to see.
export type Service = { id: string | null; name: string; codes: string; reviewed: boolean; notes?: string | null }

// Whether two hospitals' headline prices can honestly sit side by side.
export type Pair = { a: string; b: string; verdict: string; detail: string }

export type RunEvent =
  | { seq: number; kind: 'trace'; ccn?: string; text: string }
  | { seq: number; kind: 'progress'; ccn: string; name: string; phase: 'download' | 'extract'; done: number; total: number | null }
  | { seq: number; kind: 'hospital'; hospital: HospitalResult }
  | { seq: number; kind: 'result'; zip: string; service: Service; live?: boolean; hospitals: HospitalResult[]; comparisons?: Pair[] }
  | { seq: number; kind: 'error'; message: string }
  | { seq: number; kind: 'end' }

export type Clarification = {
  status: 'needs_clarification'
  verdict: string
  question: string
  asked_claude: boolean
  candidates: Service[]
}

export type Started = {
  status: 'started'
  run_id: string
  service: Service
  live: boolean
  resolver?: { verdict: string; reason: string } | null
  note?: string | null // what Claude said when it settled the name
}

// What this deployment allows, so the page can say so before anyone tries.
export type Config = { live_needs_pin: boolean; max_downloads: number | null; runs_per_hour: number | null }

export type RecordedRun = {
  status: 'recorded'
  recorded_on: string
  zip: string
  query: string
  service: Service
  events: RunEvent[]
}

export type DemoIndex = {
  recorded_on: string
  zips: string[]
  services: { query: string; name: string; codes: string }[]
}

// /api/prices: the stored answer for a service, with every matching line when asked.
export type Prices =
  | { status: 'ok'; service: Service; hospitals: HospitalResult[]; comparisons?: Pair[] }
  | { status: 'needs_clarification'; candidates: Service[] }

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
  }
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new ApiError(r.status, await detail(r))
  return (await r.json()) as T
}

// FastAPI sends a string for its own errors and a list of {loc, msg} for a request that
// failed validation (a one-digit ZIP); a visitor reads a sentence either way.
async function detail(r: Response): Promise<string> {
  try {
    const body = (await r.json()) as { detail?: unknown }
    const d = body.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      const msgs = d.map((x) => {
        const field = Array.isArray(x?.loc) ? String(x.loc[x.loc.length - 1]) : ''
        return field ? `${field}: ${x?.msg ?? 'invalid'}` : String(x?.msg ?? 'invalid')
      })
      if (msgs.length) return msgs.join('; ')
    }
    return r.statusText || `request failed (${r.status})`
  } catch {
    return r.statusText || `request failed (${r.status})`
  }
}

export const config = () => get<Config>('/api/config')

export const demoIndex = () => get<DemoIndex>('/api/demo')

export const recordedRun = (zip: string, service: string) =>
  get<RecordedRun>(`/api/demo?zip=${encodeURIComponent(zip)}&service=${encodeURIComponent(service)}`)

// The 70 services, for a visitor whose words matched none of them.
export const catalogue = () => get<Service[]>('/api/catalog')

// Every matching line for one run's ZIP and service, from what is stored (no scanning).
export const allLines = (zip: string, serviceId: string) =>
  get<Prices>(`/api/prices?zip=${encodeURIComponent(zip)}&service_id=${encodeURIComponent(serviceId)}&all=true`)

export type RunRequest = { zip: string; service?: string; service_id?: string; live?: boolean; pin?: string }

export async function startRun(body: RunRequest): Promise<Started | Clarification> {
  const r = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new ApiError(r.status, await detail(r))
  return (await r.json()) as Started | Clarification
}

// Every event kind arrives as its own SSE event name, so each one gets a listener. The
// browser reconnects on its own and sends Last-Event-ID; the server replays from there.
// When it gives up for good (the run is gone: the server restarted), the page is told,
// rather than left saying "running" forever.
const KINDS = ['trace', 'progress', 'hospital', 'result', 'error', 'end'] as const

export function streamRun(runId: string, onEvent: (event: RunEvent) => void, onLost: (message: string) => void): () => void {
  const source = new EventSource(`/api/runs/${runId}/events`)
  for (const kind of KINDS) {
    source.addEventListener(kind, (e) => {
      // The run's own "error" event shares its name with EventSource's transport error,
      // which carries no data; only a message with data is one of ours.
      const data = (e as MessageEvent).data
      if (typeof data !== 'string') return
      const event = JSON.parse(data) as RunEvent
      onEvent(event)
      if (event.kind === 'end') source.close()
    })
  }
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      onLost('lost the connection to this run and could not resume it (the server may have restarted); run it again')
    }
  }
  return () => source.close()
}
