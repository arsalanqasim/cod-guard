import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, AudioLines, Box, Clock3 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { fileUpload, json, request, type Membership, type Order, type VoiceJob } from './api'
import { Decision, Failure, money, sourceName } from './shared'
import { BuyerContact, ShipmentTools } from './OrderTools'

const localTime = new Intl.DateTimeFormat('en-PK', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Karachi' })
const decisionLabels = { SHIP: 'Ship', VERIFY_FIRST: 'Verify first', HOLD: 'Hold', HOLD_CANCEL: 'Hold / cancel' }
const sourceStatuses = {
  open: 'Open at store',
  closed_cancelled: 'Cancelled at store',
  closed_at_source: 'Closed at store',
  out_of_cod_scope: 'No longer eligible for COD',
}

export function OrderPane({ summary, merchant }: { summary: Order; merchant: Membership }) {
  const path = `/orders/${encodeURIComponent(summary.order_id)}`
  const detailKey = ['merchant-data', merchant.tenant_id, 'detail', summary.order_id]
  const order = useQuery({
    queryKey: detailKey,
    queryFn: async ({ signal }) => (await request<Order>(path, { signal })).data,
    refetchInterval: 10_000,
  })
  const data = order.data ?? summary
  const packer = merchant.role === 'packer'
  const available = order.isSuccess && !order.isError && !packer && data.queue_status === 'open'
    && !data.storefront_conflict && !data.outcome
  const queryClient = useQueryClient()

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: detailKey }),
      queryClient.invalidateQueries({ queryKey: ['merchant-data', merchant.tenant_id, 'orders'] }),
    ])
  }

  return <article className="order-sheet">
    <header className="order-header">
      <div><p className="order-id">{data.source_order_id ?? data.order_id}</p>
        <h2>{data.customer_name ?? data.product}</h2></div>
      <Decision order={data} />
    </header>
    <dl className="order-facts">
      <div><dt>Destination</dt><dd>{data.city || 'Unspecified'}</dd></div>
      {!packer && <div><dt>COD amount</dt><dd>{money(data.amount_pkr)}</dd></div>}
      <div><dt>Source</dt><dd>{sourceName(data.data_source)}</dd></div>
      {data.phone && <div><dt>Buyer phone</dt><dd>{data.phone}</dd></div>}
    </dl>
    <div className="parcel"><Box size={18} aria-hidden="true" /><span>{data.product}</span>
      {data.items_count != null && <span className="parcel-quantity">Qty {data.items_count}</span>}</div>
    {order.error && <Failure error={order.error} retry={() => void order.refetch()} />}
    {order.isPending && <p className="loading-detail" role="status">Loading order history…</p>}
    {order.isSuccess && !packer && <>
      {data.storefront_conflict && <section className="conflict-sheet" aria-label="Storefront conflict">
        <h3><AlertTriangle size={18} aria-hidden="true" /> Store and saved decision differ</h3>
        <dl className="conflict-status">
          <div><dt>Current source state</dt><dd>{sourceStatuses[data.queue_status]}</dd></div>
          <div><dt>Saved decision</dt><dd>{decisionLabels[data.decision]}</dd></div>
        </dl>
        <p>Check the order in its source store before sending it to packing.</p>
      </section>}
      {!data.storefront_conflict && <section className="detail-section action-section">
        <h3>{data.next_action?.title ?? 'Dispatch decision'}</h3>
        <p>{data.next_action?.next_step ?? data.decision_why}</p>
        {!!data.reasons?.length && <details><summary>Risk signals</summary><ul>{data.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details>}
      </section>}
      <section className="detail-section">
        <h3><Clock3 size={17} aria-hidden="true" /> Buyer evidence</h3>
        {data.messages?.length ? <ul className="messages">{data.messages.map((message, index) =>
          <li key={`${message.decision_revision}-${index}`}>
            <p dir="auto">{message.text ?? 'Reply expired'}</p>
            <span>{message.source} {message.at ? <time dateTime={message.at}>{localTime.format(new Date(message.at))}</time> : null}</span>
          </li>)}</ul> : <p className="muted">No buyer replies recorded.</p>}
      </section>
      {available && !data.verified && <BuyerContact path={path} tenant={merchant.tenant_id} />}
      {available && <ReviewActions path={path} order={data} tenant={merchant.tenant_id} onChange={refresh} />}
      <ShipmentTools path={path} tenant={merchant.tenant_id} outcome={data.outcome} />
    </>}
  </article>
}

function ReviewActions({ path, order, tenant, onChange }: {
  path: string; order: Order; tenant: string; onChange: () => Promise<void>
}) {
  const [reply, setReply] = useState('')
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [outcome, setOutcome] = useState('')

  useEffect(() => {
    if (!audioFile) return
    const url = URL.createObjectURL(audioFile)
    setAudioUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [audioFile])

  const verify = useMutation({
    mutationFn: () => request(`${path}/verify`, json('POST', { text: reply.trim() })),
    onSuccess: async () => { setReply(''); await onChange() },
  })
  const upload = useMutation({
    mutationFn: async (file: File) => (await request<VoiceJob>(`${path}/voice`, { method: 'POST', body: fileUpload(file) })).data,
    onSuccess: (job) => setJobId(job.job_id),
  })
  const status = useQuery({
    queryKey: ['merchant-data', tenant, 'voice', jobId],
    queryFn: async ({ signal }) => (await request<VoiceJob>(`${path}/voice/${jobId}`, { signal })).data,
    enabled: !!jobId,
    refetchInterval: ({ state }) => state.data?.status === 'done' || state.data?.status === 'failed' ? false : 1500,
  })
  const saveOutcome = useMutation({
    mutationFn: () => request(`${path}/outcome`, json('POST', { outcome })),
    onSuccess: onChange,
  })
  const processing = jobId && (!status.data || status.data.status === 'queued' || status.data.status === 'running')

  function submitReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    verify.mutate()
  }

  return <>
    <details className="detail-section voice-section">
      <summary><AudioLines size={18} aria-hidden="true" /> Review a voice note</summary>
      <div className="form-stack">
        <label htmlFor="audio-file">Audio file</label>
        <Input id="audio-file" type="file" accept=".ogg,.mp3,.wav,.m4a,.webm" disabled={!!processing || upload.isPending}
          onChange={(event) => {
            setAudioUrl(null); setAudioFile(event.target.files?.[0] ?? null); setJobId(null); upload.reset()
          }} />
        {audioUrl && <audio src={audioUrl} controls preload="metadata" />}
        <Button variant="outline" size="sm" disabled={!audioFile || !!processing || upload.isPending}
          onClick={() => { if (audioFile) upload.mutate(audioFile) }}>Transcribe voice note</Button>
        {upload.error && <Failure error={upload.error} />}
        {processing && !status.error && <span role="status" className="muted">Transcribing audio…</span>}
        {status.error && <Failure error={status.error} retry={() => void status.refetch()} />}
        {status.data?.error && <p className="notice notice-error" role="alert">{status.data.error}</p>}
        {status.data?.result && <div className="transcript">
          <strong>Draft transcript</strong>
          <p dir="auto">{status.data.result.text}</p>
          {status.data.result.warning && <p>{status.data.result.warning}</p>}
          <Button variant="outline" size="sm" onClick={() => setReply(status.data?.result?.text ?? '')}>Use in buyer reply</Button>
        </div>}
      </div>
    </details>
    <form className="detail-section form-stack" onSubmit={submitReply}>
      <label htmlFor="buyer-reply">Record buyer reply</label>
      <textarea id="buyer-reply" dir="auto" rows={2} maxLength={2000} value={reply}
        placeholder="Type the buyer’s reply" onChange={(event) => { setReply(event.target.value); verify.reset() }} />
      {verify.error && <Failure error={verify.error} />}
      {verify.isSuccess && <p className="notice" role="status">Buyer reply saved.</p>}
      <Button type="submit" disabled={!reply.trim() || verify.isPending}>{verify.isPending ? 'Saving…' : 'Save buyer reply'}</Button>
    </form>
    {order.decision === 'SHIP' && order.decision_revision != null && !order.needs_review && <form className="detail-section form-stack"
      onSubmit={(event) => { event.preventDefault(); saveOutcome.mutate() }}>
      <label htmlFor="shipment-outcome">Shipment outcome</label>
      <select id="shipment-outcome" value={outcome} onChange={(event) => setOutcome(event.target.value)}>
        <option value="">Select a final outcome</option><option value="delivered">Delivered</option>
        <option value="returned">Returned</option><option value="refused">Refused</option>
      </select>
      {saveOutcome.error && <Failure error={saveOutcome.error} />}
      <Button variant="outline" disabled={!outcome || saveOutcome.isPending}>Record outcome</Button>
    </form>}
  </>
}
