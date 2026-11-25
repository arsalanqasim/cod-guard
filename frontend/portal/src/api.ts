export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export type Role = 'owner' | 'ops' | 'packer'
export type Membership = { tenant_id: string; name: string; role: Role }
export type Session = { merchant: Membership; memberships: Membership[] }

export type Order = {
  order_id: string
  source_order_id?: string | null
  customer_name?: string
  product: string
  city: string
  items_count?: number
  amount_pkr?: number | null
  data_source: string
  phone?: string
  decision: 'SHIP' | 'VERIFY_FIRST' | 'HOLD' | 'HOLD_CANCEL'
  decision_why?: string
  decision_revision?: number | null
  storefront_conflict?: boolean
  needs_review?: boolean
  verified?: boolean
  queue_status: 'open' | 'closed_cancelled' | 'out_of_cod_scope' | 'closed_at_source'
  outcome?: 'delivered' | 'returned' | 'refused' | null
  reasons?: string[]
  next_action?: { title: string; reason: string; next_step: string }
  messages?: { text: string | null; source: string; intent: string; at: string; decision_revision: number }[]
}

export type ImportReceipt = { imported: number; errors: { row: number; error: string }[] }
export type VoiceJob = {
  job_id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  error?: string
  result?: { text: string; intent: string; warning?: string }
}

export async function request<T>(path: string, init?: RequestInit) {
  const response = await fetch(`/api${path}`, { ...init, credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) {
    const problem = await response.json().catch(() => null)
    const detail = typeof problem?.detail === 'string'
      ? problem.detail
      : response.status === 422 ? 'Check the values and try again.' : 'The service is temporarily unavailable.'
    throw new ApiError(response.status, detail)
  }
  const data = (response.status === 204 ? null : await response.json()) as T
  return { data, response }
}

export function json(method: string, body: object): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export function fileUpload(file: File): FormData {
  const data = new FormData()
  data.set('file', file)
  return data
}
