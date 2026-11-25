import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cable } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { json, request } from './api'
import { Failure } from './shared'

type Connection = {
  id: string; kind: string; name: string; address: string; active: boolean
  options?: Record<string, boolean>
  setup?: { status: string; error: string | null }
}
type ApiKey = { id: string; name: string; scope: string; revoked_at: string | null }
type Delivery = { id: string; status: string; attempts: number; error: string | null }
type PrivacyRequest = { id: string; shop: string; topic: string; status: string }
type FormResult = {
  authorize_url?: string; installation_code?: string; key?: string; signing_secret?: string
  callback_url?: string; verify_token?: string; status?: string
}
type Setting = { name: string; label: string; type?: string; value?: string | boolean; placeholder?: string }
type FormValues = Record<string, string | boolean>

const tabs = ['Storefronts', 'ERP and webhooks', 'Buyer verification', 'Couriers'] as const
const captions: Record<string, string> = {
  shopify: 'Shopify', woocommerce: 'WooCommerce', erp_webhook: 'ERP webhook',
  whatsapp: 'WhatsApp', calls: 'Urdu confirmation calls', tcs: 'TCS',
}

export function Connections({ tenant }: { tenant: string }) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<typeof tabs[number]>('Storefronts')
  const client = useQueryClient()
  const scope = ['merchant-data', tenant, 'connections']
  const accounts = useQuery({
    queryKey: [...scope, 'list'], enabled: open,
    queryFn: async ({ signal }) => (await request<Connection[]>('/merchant/connections', { signal })).data,
    refetchInterval: open ? 6_000 : false,
  })
  const keys = useQuery({
    queryKey: [...scope, 'keys'], enabled: open && (tab === 'ERP and webhooks' || tab === 'Couriers'),
    queryFn: async ({ signal }) => (await request<ApiKey[]>('/merchant/api-keys', { signal })).data,
  })
  const deliveries = useQuery({
    queryKey: [...scope, 'deliveries'], enabled: open && tab === 'ERP and webhooks',
    queryFn: async ({ signal }) => (await request<Delivery[]>('/merchant/webhook-deliveries', { signal })).data,
    refetchInterval: open && tab === 'ERP and webhooks' ? 6_000 : false,
  })
  const refresh = () => client.invalidateQueries({ queryKey: scope })
  const remove = useMutation({ mutationFn: (path: string) => request(path, { method: 'DELETE' }), onSuccess: refresh })

  function connections(kinds: string[]) {
    return (accounts.data ?? []).filter((account) => account.active && kinds.includes(account.kind))
  }

  return <Dialog open={open} onOpenChange={(value) => { setOpen(value); if (!value) remove.reset() }}>
    <DialogTrigger asChild><Button variant="ghost" size="sm"><Cable size={17} /> Connections</Button></DialogTrigger>
    <DialogContent className="connections-dialog">
      <DialogHeader><DialogTitle>Connections</DialogTitle>
        <DialogDescription>Set up order sources, buyer contact, and courier updates for this store.</DialogDescription></DialogHeader>
      <nav className="queue-tabs connection-tabs" aria-label="Connection types">
        {tabs.map((entry) => <button type="button" key={entry} aria-pressed={tab === entry}
          onClick={() => { setTab(entry); remove.reset() }}>{entry}</button>)}
      </nav>
      {accounts.error && <Failure error={accounts.error} retry={() => void accounts.refetch()} />}
      {remove.error && <Failure error={remove.error} />}
      {tab === 'Storefronts' && <div className="connection-stack">
        {connections(['shopify', 'woocommerce']).map((account) => <section className="connected-account" key={account.id}>
          <div><strong>{account.name}</strong><p className="muted">{captions[account.kind]}</p></div>
          {account.setup && <p role="status">{account.setup.error ?? (account.setup.status === 'done' ? 'Order sync configured' : 'Setting up order sync…')}</p>}
          <SettingsForm legend="Write-back settings" method="PUT"
            path={account.kind === 'shopify' ? `/merchant/shopify/${account.id}/holds` : `/merchant/woocommerce/${account.id}/writeback`}
            fields={account.kind === 'shopify'
              ? [{ name: 'enforce', label: 'Apply and release COD-Guard fulfillment holds', type: 'checkbox', value: account.options?.enforce }]
              : [
                { name: 'hold_on_unverified', label: 'Set unverified orders to on hold', type: 'checkbox', value: account.options?.hold_on_unverified },
                { name: 'release_on_confirmed', label: 'Release COD-Guard holds after confirmation', type: 'checkbox', value: account.options?.release_on_confirmed },
                { name: 'write_outcomes', label: 'Write courier outcomes as private notes', type: 'checkbox', value: account.options?.write_outcomes },
              ]} button="Save settings" onDone={refresh} />
        </section>)}
        <SettingsForm legend="Shopify" path="/merchant/shopify/authorize" onDone={refresh} button="Prepare Shopify connection" fields={[
          { name: 'shop', label: 'Shopify domain', placeholder: 'store.myshopify.com' },
          { name: 'cod_gateway', label: 'Exact COD payment method name', value: 'Cash on Delivery (COD)' },
          { name: 'protected_fields', label: 'Shopify approved access to buyer contact fields', type: 'checkbox' },
        ]} />
        <SettingsForm legend="WooCommerce" path="/merchant/woocommerce/authorize" onDone={refresh} button="Connect WooCommerce" fields={[
          { name: 'url', label: 'Store URL', type: 'url', placeholder: 'https://shop.example.com' },
        ]} />
        <ShopifyPrivacy tenant={tenant} />
      </div>}
      {tab === 'ERP and webhooks' && <div className="connection-stack">
        <section>
          <h3>API keys</h3>
          {keys.error && <Failure error={keys.error} />}
          {(keys.data ?? []).filter((key) => !key.revoked_at).map((key) =>
            <div className="connection-row" key={key.id}><span>{key.name} <small>{key.scope}</small></span>
              <Button variant="outline" size="sm" onClick={() => remove.mutate(`/merchant/api-keys/${key.id}`)} disabled={remove.isPending}>Revoke key</Button></div>)}
          <SettingsForm legend="Create an order intake key" path="/merchant/api-keys" onDone={refresh} button="Create order key"
            fields={[{ name: 'name', label: 'Key name' }]} />
        </section>
        <section>
          <h3>Decision webhooks</h3>
          {connections(['erp_webhook']).map((account) => <div className="connection-row" key={account.id}>
            <span>{account.name}<small>{account.address}</small></span>
            <Button variant="outline" size="sm" onClick={() => remove.mutate(`/merchant/webhooks/${account.id}`)} disabled={remove.isPending}>Disable</Button></div>)}
          <SettingsForm legend="Add recipient" path="/merchant/webhooks" onDone={refresh} button="Create webhook" fields={[
            { name: 'name', label: 'Webhook name' }, { name: 'url', label: 'HTTPS destination', type: 'url' },
          ]} />
          {deliveries.error && <Failure error={deliveries.error} />}
          {!!deliveries.data?.length && <details><summary>Recent delivery attempts</summary>
            <ul className="connection-stack">{deliveries.data.slice(0, 10).map((item) =>
              <li key={item.id}>{item.status} · {item.attempts} {item.attempts === 1 ? 'attempt' : 'attempts'}
                {item.error && <p className="muted">{item.error}</p>}</li>)}</ul>
          </details>}
        </section>
      </div>}
      {tab === 'Buyer verification' && <div className="connection-stack">
        {connections(['whatsapp', 'calls']).map((account) => <p key={account.id}>{account.name} connected</p>)}
        <SettingsForm legend="WhatsApp Business" path="/merchant/channels/whatsapp" onDone={refresh} button="Save WhatsApp sender" fields={[
          { name: 'waba_id', label: 'Business account ID' }, { name: 'phone_number_id', label: 'Phone number ID' },
          { name: 'template_id', label: 'Approved utility template ID' }, { name: 'token', label: 'Access token', type: 'password' },
          { name: 'app_secret', label: 'App secret', type: 'password' },
          { name: 'business_verified', label: 'Meta approved the business and utility template', type: 'checkbox' },
        ]} />
        <SettingsForm legend="Urdu calls through Twilio" path="/merchant/channels/calls" onDone={refresh} button="Save call settings" fields={[
          { name: 'account_sid', label: 'Account SID' }, { name: 'auth_token', label: 'Auth token', type: 'password' },
          { name: 'from_number', label: 'Twilio phone number' }, { name: 'prompt_url', label: 'Public Urdu prompt audio URL', type: 'url' },
        ]} />
      </div>}
      {tab === 'Couriers' && <div className="connection-stack">
        {connections(['tcs']).map((account) => <p key={account.id}>{account.name} connected</p>)}
        <SettingsForm legend="TCS" path="/merchant/couriers/tcs" method="PUT" onDone={refresh} button="Save tracking token"
          fields={[{ name: 'token', label: 'Merchant tracking bearer token', type: 'password' }]} />
        <section><h3>Forwarded courier events</h3>
          <p className="muted">Use a courier event key to forward terminal updates for linked PostEx, Leopards, TCS, or other shipments.</p>
          {(keys.data ?? []).filter((key) => key.scope === 'courier:write' && !key.revoked_at).map((key) =>
            <div className="connection-row" key={key.id}><span>{key.name}</span>
              <Button variant="outline" size="sm" onClick={() => remove.mutate(`/merchant/api-keys/${key.id}`)} disabled={remove.isPending}>Revoke key</Button></div>)}
          <SettingsForm legend="Courier event key" path="/merchant/api-keys" onDone={refresh} button="Create courier key"
            extra={{ scope: 'courier:write' }} fields={[{ name: 'name', label: 'Key name' }]} />
        </section>
        <a className="order-link" href="/api/merchant/learning/dataset">Download eligible training data</a>
      </div>}
    </DialogContent>
  </Dialog>
}

function ShopifyPrivacy({ tenant }: { tenant: string }) {
  const client = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const queryKey = ['merchant-data', tenant, 'shopify-privacy']
  const requests = useQuery({
    queryKey, enabled: expanded,
    queryFn: async ({ signal }) => (await request<PrivacyRequest[]>('/merchant/shopify/privacy', { signal })).data,
    refetchInterval: expanded ? 10_000 : false,
  })
  const finish = useMutation({
    mutationFn: (id: string) => request(`/merchant/shopify/privacy/${id}/complete`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey }),
  })
  const labels: Record<string, string> = {
    'customers/data_request': 'Customer data request', 'customers/redact': 'Customer redaction',
    'shop/redact': 'Store redaction',
  }
  return <details className="connection-form" onToggle={(event) => setExpanded(event.currentTarget.open)}>
    <summary>Shopify privacy requests</summary>
    {expanded && requests.isPending && <p>Loading requests…</p>}
    {requests.error && <Failure error={requests.error} />}
    {finish.error && <Failure error={finish.error} />}
    {requests.data?.length === 0 && <p className="muted">No privacy requests received.</p>}
    {requests.data?.map((entry) => <div className="connection-row privacy-row" key={entry.id}>
      <span>{labels[entry.topic] ?? entry.topic}<small>{entry.shop}</small></span>
      <span className="muted">{entry.status === 'review' ? 'Needs review' : entry.status}</span>
      {entry.topic === 'customers/data_request' && entry.status === 'ready' && <div className="privacy-actions">
        <a className="order-link" href={`/api/merchant/shopify/privacy/${entry.id}/export`}>Download data</a>
        <Button type="button" variant="outline" size="sm" disabled={finish.isPending}
          onClick={() => finish.mutate(entry.id)}>Mark completed</Button>
      </div>}
    </div>)}
  </details>
}

function SettingsForm({ legend, fields, path, method = 'POST', extra = {}, button, onDone }: {
  legend: string; fields: Setting[]; path: string; method?: string; extra?: FormValues; button: string
  onDone: () => Promise<void>
}) {
  const action = useMutation({
    mutationFn: async (values: FormValues) => (await request<FormResult>(path, json(method, { ...extra, ...values }))).data,
    onSuccess: onDone,
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    action.mutate(Object.fromEntries(fields.map((field) => [field.name,
      field.type === 'checkbox' ? values.has(field.name) : String(values.get(field.name)).trim(),
    ])), { onSuccess: () => {
      form.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach((input) => { input.value = '' })
    } })
  }
  const data = action.data
  return <details className="connection-form">
    <summary>{legend}</summary>
    <form className="form-stack" onSubmit={submit}>
      {fields.map((field) => field.type === 'checkbox'
        ? <label key={field.name} className="check-line"><input name={field.name} type="checkbox" defaultChecked={!!field.value} />{field.label}</label>
        : <label key={field.name} className="field-line">{field.label}
          <Input name={field.name} type={field.type ?? 'text'} defaultValue={String(field.value ?? '')} placeholder={field.placeholder}
            autoComplete={field.type === 'password' ? 'new-password' : undefined} required /></label>)}
      {action.error && <Failure error={action.error} />}
      <Button type="submit" disabled={action.isPending}>{action.isPending ? 'Saving…' : button}</Button>
    </form>
    {data && <div className="connection-result" role="status">
      {data.authorize_url && <a className="order-link" href={data.authorize_url} rel="noopener noreferrer">Authorize store</a>}
      {data.installation_code && <Secret label="Shopify Admin pairing code" value={data.installation_code} />}
      {data.key && <Secret label="API key. Copy it now." value={data.key} />}
      {data.signing_secret && <Secret label="Signing secret. Copy it now." value={data.signing_secret} />}
      {data.callback_url && <Secret label="Meta callback URL" value={data.callback_url} />}
      {data.verify_token && <Secret label="Meta verification token" value={data.verify_token} />}
      {!Object.keys(data).some((key) => ['authorize_url', 'key', 'signing_secret', 'callback_url'].includes(key)) && <p>Settings saved.</p>}
    </div>}
  </details>
}

function Secret({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return <div className="connection-secret"><strong>{label}</strong><code>{value}</code>
    <Button variant="outline" size="sm" type="button" onClick={async () => {
      try { await navigator.clipboard.writeText(value); setCopied(true) } catch { setCopied(false) }
    }}>{copied ? 'Copied' : 'Copy'}</Button></div>
}
