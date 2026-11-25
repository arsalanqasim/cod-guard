import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { json, request } from './api'
import { Failure } from './shared'

type Channel = {
  channel: 'whatsapp' | 'calls'; opted_in: boolean
  attempt: { id: string; status: string } | null
}
type Verification = { channels: Channel[]; live_enabled: boolean }
type Shipment = { courier: string; tracking: string; order_day: string | null; terminal: string | null; evidence_reference: string | null }

const statusLabels: Record<string, string> = {
  queued: 'Queued', accepted: 'Sent to provider', submitting: 'Submitting', unconfirmed: 'Provider acceptance unconfirmed',
  waiting_review: 'Needs staff review', confirmed: 'Buyer confirmed', denied: 'Buyer declined', cancelled: 'Cancelled',
  expired: 'Reply window expired',
}

export function BuyerContact({ path, tenant }: { path: string; tenant: string }) {
  const client = useQueryClient()
  const key = ['merchant-data', tenant, 'buyer-contact', path]
  const query = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => (await request<Verification>(`/merchant${path}/verification`, { signal })).data,
    refetchInterval: 6_000,
  })
  const invalidate = () => client.invalidateQueries({ queryKey: key })
  if (query.error) return <div className="detail-section"><Failure error={query.error} retry={() => void query.refetch()} /></div>
  if (!query.data?.channels.length) return null
  return <section className="detail-section">
    <h3>Contact buyer</h3>
    {!query.data.live_enabled && <p className="muted">Live buyer contact is disabled for this deployment.</p>}
    {query.data.channels.map((channel) =>
      <ContactChannel key={channel.channel} path={path} config={channel} live={query.data.live_enabled} onChange={invalidate} />)}
  </section>
}

function ContactChannel({ path, config, live, onChange }: {
  path: string; config: Channel; live: boolean; onChange: () => Promise<void>
}) {
  const [evidence, setEvidence] = useState('')
  const consent = useMutation({
    mutationFn: (opted_in: boolean) => request(`/merchant${path}/contact-consent/${config.channel}`,
      json('PUT', { opted_in, evidence_reference: evidence.trim() })),
    onSuccess: async () => { setEvidence(''); await onChange() },
  })
  const send = useMutation({
    mutationFn: () => request(`/merchant${path}/verification/${config.channel}`, { method: 'POST' }),
    onSuccess: onChange,
  })
  const label = config.channel === 'whatsapp' ? 'WhatsApp' : 'Urdu confirmation call'
  const action = config.channel === 'whatsapp' ? 'Send WhatsApp confirmation' : 'Trigger confirmation call'
  const busy = config.attempt && ['queued', 'submitting', 'accepted', 'unconfirmed'].includes(config.attempt.status)
  return <div className="contact-channel">
    <div className="connection-row"><span><strong>{label}</strong><small>{config.opted_in ? 'Opted in' : 'Opt-in required'}</small></span>
      {config.attempt && <span className="decision decision-neutral">{statusLabels[config.attempt.status] ?? config.attempt.status}</span>}</div>
    <Button size="sm" variant="outline" disabled={!live || !config.opted_in || !!busy || send.isPending}
      onClick={() => send.mutate()}>{send.isPending ? 'Queuing…' : action}</Button>
    {send.error && <Failure error={send.error} />}
    <details className="contact-consent"><summary>{config.opted_in ? 'Record withdrawal' : 'Record buyer opt-in'}</summary>
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); consent.mutate(!config.opted_in) }}>
        <label htmlFor={`evidence-${config.channel}`}>Evidence reference</label>
        <Input id={`evidence-${config.channel}`} placeholder="Consent record ID" value={evidence}
          pattern="[A-Za-z0-9][A-Za-z0-9_.:\-]{2,95}" onChange={(event) => setEvidence(event.target.value)} required />
        {consent.error && <Failure error={consent.error} />}
        <Button variant="outline" size="sm" type="submit" disabled={!evidence.trim() || consent.isPending}>
          {config.opted_in ? 'Withdraw opt-in' : 'Save opt-in'}
        </Button>
      </form>
    </details>
  </div>
}

export function ShipmentTools({ path, tenant, outcome }: { path: string; tenant: string; outcome?: string | null }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const key = ['merchant-data', tenant, 'shipment', path]
  const query = useQuery({
    queryKey: key, enabled: open,
    queryFn: async ({ signal }) => (await request<{ shipment: Shipment | null }>(`/merchant${path}/shipment`, { signal })).data,
    refetchInterval: open ? 8_000 : false,
  })
  const shipment = query.data?.shipment
  const save = useMutation({
    mutationFn: (data: FormData) => request(`/merchant${path}/shipment`, json('PUT', {
      courier: data.get('courier'), tracking: String(data.get('tracking')).trim(), order_day: data.get('order_day') || null,
    })),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  })
  const confirm = useMutation({
    mutationFn: (data: FormData) => request(`/merchant${path}/refusal-evidence`, json('PUT', {
      confirmed: !shipment?.evidence_reference, reference: String(data.get('reference')).trim(),
    })),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  })
  function submit(event: FormEvent<HTMLFormElement>, run: (data: FormData) => void) {
    event.preventDefault()
    run(new FormData(event.currentTarget))
  }
  return <details className="detail-section" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Courier tracking</summary>
    {query.error && <Failure error={query.error} retry={() => void query.refetch()} />}
    {open && query.isPending && <p className="muted">Loading shipment…</p>}
    {shipment && <dl className="conflict-status"><div><dt>Courier</dt><dd>{shipment.courier}</dd></div>
      <div><dt>Tracking number</dt><dd>{shipment.tracking}</dd></div>
      {shipment.terminal && <div><dt>Courier outcome</dt><dd>{shipment.terminal}</dd></div>}</dl>}
    {query.isSuccess && (!shipment || !shipment.order_day) &&
      <form className="form-stack order-tool-form" onSubmit={(event) => submit(event, save.mutate)}>
        <label htmlFor="courier">Courier</label>
        <select name="courier" id="courier" defaultValue={shipment?.courier ?? 'tcs'}>
          <option value="tcs">TCS</option><option value="postex">PostEx</option>
          <option value="leopards">Leopards</option><option value="trax">Trax</option><option value="other">Other</option>
        </select>
        <label htmlFor="tracking">Tracking number</label>
        <Input name="tracking" id="tracking" defaultValue={shipment?.tracking} minLength={3} maxLength={48} required />
        <label htmlFor="order-day">Order date <span className="muted">(for training data)</span></label>
        <Input name="order_day" id="order-day" type="date" />
        {save.error && <Failure error={save.error} />}
        <Button size="sm" variant="outline" type="submit" disabled={save.isPending}>{shipment ? 'Save order date' : 'Link shipment'}</Button>
      </form>}
    {shipment && (outcome === 'refused' || shipment.terminal === 'refused') &&
      <form className="form-stack order-tool-form" onSubmit={(event) => submit(event, confirm.mutate)}>
        <label htmlFor="refusal-proof">{shipment.evidence_reference ? 'Withdrawal reference' : 'Independent refusal evidence reference'}</label>
        <Input name="reference" id="refusal-proof" required minLength={3} maxLength={96} />
        {confirm.error && <Failure error={confirm.error} />}
        <Button size="sm" variant="outline" type="submit" disabled={confirm.isPending}>
          {shipment.evidence_reference ? 'Withdraw evidence' : 'Confirm refusal evidence'}
        </Button>
      </form>}
  </details>
}
