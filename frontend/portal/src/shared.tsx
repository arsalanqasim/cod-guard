import { Button } from '@/components/ui/button'
import { AlertTriangle } from 'lucide-react'
import type { Order } from './api'

const number = new Intl.NumberFormat('en-PK', { maximumFractionDigits: 2 })

export function money(value?: number | null) {
  return value == null ? '—' : `PKR ${number.format(value)}`
}

export function Decision({ order }: { order: Order }) {
  const labels = { SHIP: 'Ship', VERIFY_FIRST: 'Verify first', HOLD: 'Hold', HOLD_CANCEL: 'Hold / cancel' }
  if (order.storefront_conflict) return <span className="decision decision-conflict"><AlertTriangle size={13} aria-hidden />Store conflict</span>
  if (order.outcome) return <span className="decision decision-neutral capitalize">{order.outcome}</span>
  if (order.queue_status !== 'open') return <span className="decision decision-neutral">Closed at store</span>
  if (order.needs_review) return <span className="decision decision-review">Review reply</span>
  const tone = order.decision === 'SHIP' ? 'ready' : order.decision === 'VERIFY_FIRST' ? 'review' : 'conflict'
  return <span className={`decision decision-${tone}`}>{labels[order.decision]}</span>
}

export function sourceName(value: string) {
  const sources: Record<string, string> = { SHADOW: 'CSV import', SHOPIFY: 'Shopify', WOOCOMMERCE: 'WooCommerce', SYNTHETIC: 'Demo' }
  return sources[value.toUpperCase()] ?? value
}

export function Brand() {
  return <span className="brand"><span className="brand-mark" aria-hidden="true" />COD-Guard</span>
}

export function Failure({ error, retry }: { error: Error; retry?: () => void }) {
  return <div className="notice notice-error" role="alert">
    <span>{error.message || 'Check your connection and try again.'}</span>
    {retry && <Button type="button" size="sm" variant="outline" onClick={retry}>Retry</Button>}
  </div>
}
