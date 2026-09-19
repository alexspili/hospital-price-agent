// What the API sends, and the three calls the page makes. The shapes come from
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
  ref: string
  note: string | null
}

export type HospitalResult = {
  ccn: string
  name: string
  distance_km: number
  approximate: boolean
  url: string | null
  file_date: string | null
  verdict: string
  detail: string
  line_count: number
  headline: Line | null
  lines: Line[]
}

export type Service = { id: string | null; name: string; codes: string; reviewed: boolean }

export type RunEvent =
  | { seq: number; kind: 'trace'; ccn?: string; text: string }
  | { seq: number; kind: 'progress'; ccn: string; name: string; phase: 'download' | 'extract'; done: number; total: number | null }
  | { seq: number; kind: 'hospital'; hospital: HospitalResult }
  | { seq: number; kind: 'result'; zip: string; service: Service; hospitals: HospitalResult[] }
  | { seq: number; kind: 'error'; message: string }
  | { seq: number; kind: 'end' }

export type Clarification = {
  status: 'needs_clarification'
  verdict: string
  question: string
  asked_claude: boolean
  candidates: Service[]
}

export type Started = { status: 'started'; run_id: string; service: Service }

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

async function detail(r: Response): Promise<string> {
  try {
    const body = await r.json()
    return body.detail ?? r.statusText
  } catch {
    return r.statusText
  }
}

export const demoIndex = () => get<DemoIndex>('/api/demo')

export const recordedRun = (zip: string, service: string) =>
  get<RecordedRun>(`/api/demo?zip=${encodeURIComponent(zip)}&service=${encodeURIComponent(service)}`)

export async function startRun(body: { zip: string; service?: string; service_id?: string }): Promise<Started | Clarification> {
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
const KINDS = ['trace', 'progress', 'hospital', 'result', 'error', 'end'] as const

export function streamRun(runId: string, onEvent: (event: RunEvent) => void): () => void {
  const source = new EventSource(`/api/runs/${runId}/events`)
  for (const kind of KINDS) {
    source.addEventListener(kind, (e) => {
      const event = JSON.parse((e as MessageEvent).data) as RunEvent
      onEvent(event)
      if (event.kind === 'end') source.close()
    })
  }
  return () => source.close()
}
