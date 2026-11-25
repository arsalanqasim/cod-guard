import { useDeferredValue, useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, PackageOpen, RefreshCw, Search, Upload, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { fileUpload, json, request, type ImportReceipt, type Order, type Session } from './api'
import { Brand, Decision, Failure, money, sourceName } from './shared'
import { OrderPane } from './OrderPane'
import { Connections } from './Connections'

const views = [
  { value: 'queue', label: 'Active queue' },
  { value: 'conflicts', label: 'Store conflicts' },
  { value: 'packing', label: 'Ready to pack' },
  { value: 'closed', label: 'Closed orders' },
] as const
type View = typeof views[number]['value']
const pageSize = 25

export function Workspace({ session, onSession }: {
  session: Session
  onSession: (session: Session | null) => Promise<void>
}) {
  const tenant = session.merchant
  const queryClient = useQueryClient()
  const packing = tenant.role === 'packer'
  const [view, setView] = useState<View>(packing ? 'packing' : 'queue')
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [mobileDetail, setMobileDetail] = useState(false)
  const detailHeading = useRef<HTMLElement>(null)
  const queueKey = ['merchant-data', tenant.tenant_id, 'orders']
  const queue = useQuery({
    queryKey: [...queueKey, view, deferredSearch, page],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ view, search: deferredSearch, limit: String(pageSize), offset: String(page * pageSize) })
      const { data, response } = await request<Order[]>(`/orders?${params}`, { signal })
      return { rows: data, total: Number(response.headers.get('X-Total-Count') ?? data.length) }
    },
    refetchInterval: 10_000,
  })
  const logout = useMutation({
    mutationFn: () => request('/auth/session', { method: 'DELETE' }),
    onSuccess: () => onSession(null),
  })
  const switchStore = useMutation({
    mutationFn: async (tenant_id: string) => (await request<Session>('/auth/session/tenant', json('POST', { tenant_id }))).data,
    onSuccess: onSession,
  })
  const rows = queue.data?.rows ?? []
  const total = queue.data?.total ?? 0
  const current = rows.find((order) => order.order_id === selected) ?? rows[0]
  const showingDetail = mobileDetail && current
  useEffect(() => {
    if (showingDetail && window.matchMedia('(max-width: 54rem)').matches) {
      detailHeading.current?.focus()
    }
  }, [showingDetail])

  return <>
    <header className="topbar">
      <div className="topbar-inner">
        <Brand />
        <div className="store-control">
          {session.memberships.length > 1
            ? <select aria-label="Active store" value={tenant.tenant_id} disabled={switchStore.isPending}
                onChange={(event) => switchStore.mutate(event.target.value)}>
                {session.memberships.map((store) => <option key={store.tenant_id} value={store.tenant_id}>{store.name}</option>)}
              </select>
            : <span>{tenant.name}</span>}
        </div>
        <div className="topbar-actions">
          {tenant.role === 'owner' && <Connections tenant={tenant.tenant_id} />}
          {tenant.role === 'owner' && <TeamInvite />}
          <Button variant="ghost" size="sm" onClick={() => logout.mutate()} disabled={logout.isPending}>Sign out</Button>
        </div>
      </div>
    </header>
    <main className="workspace">
      {(logout.error || switchStore.error) && <Failure error={(logout.error ?? switchStore.error)!} />}
      <div className="workspace-heading">
        <div><h1>{packing ? 'Packing queue' : 'Dispatch queue'}</h1>
          {packing && <p>Approved orders waiting to be packed.</p>}</div>
        {!packing && <ImportOrders onImported={() => queryClient.invalidateQueries({ queryKey: queueKey })} />}
      </div>
      <div className={`workbench ${showingDetail ? 'show-detail' : ''}`}>
        <section className="queue" aria-label="Order queue">
          {!packing && <nav className="queue-tabs" aria-label="Order views">
            {views.map(({ value, label }) => <button type="button" key={value} aria-pressed={view === value}
              onClick={() => { setView(value); setPage(0); setSelected(null); setMobileDetail(false) }}>{label}</button>)}
          </nav>}
          <div className="queue-toolbar">
            <div className="queue-search"><Search size={17} aria-hidden="true" />
              <Input aria-label="Search orders" placeholder="Search order ID or product" maxLength={200} value={search}
                onChange={(event) => { setSearch(event.target.value); setPage(0); setSelected(null) }} />
            </div>
            <Button variant="outline" size="icon" aria-label="Refresh queue" onClick={() => void queue.refetch()} disabled={queue.isFetching}>
              <RefreshCw size={16} aria-hidden="true" />
            </Button>
          </div>
          {queue.isPending && <p className="queue-empty" role="status">Loading orders…</p>}
          {queue.error && <Failure error={queue.error} retry={() => void queue.refetch()} />}
          {!queue.isPending && !queue.isError && !rows.length && <div className="queue-empty">
            <PackageOpen size={27} aria-hidden="true" />
            <strong>{page > 0 ? 'No orders on this page' : 'No matching orders'}</strong>
            <span>{search ? 'Try a different order ID or product.' : view === 'conflicts' ? 'Storefront conflicts will appear here.' : 'Orders appear here as they reach this stage.'}</span>
          </div>}
          {rows.length > 0 && <table className="orders">
            <thead><tr><th scope="col">Order</th><th scope="col" className="city-column">Destination</th>
              <th scope="col">Decision</th>{!packing && <th scope="col" className="amount">COD amount</th>}</tr></thead>
            <tbody>{rows.map((order) => <tr key={order.order_id} className={current?.order_id === order.order_id ? 'selected' : ''}>
              <td><button className="order-link" aria-current={current?.order_id === order.order_id ? 'true' : undefined}
                onClick={() => { setSelected(order.order_id); setMobileDetail(true) }}>{order.source_order_id ?? order.order_id}</button>
                <span className="row-subtitle">{order.product}</span></td>
              <td className="city-column">{order.city || '—'}<span className="row-subtitle">{sourceName(order.data_source)}</span></td>
              <td><Decision order={order} /></td>
              {!packing && <td className="amount">{money(order.amount_pkr)}</td>}
            </tr>)}</tbody>
          </table>}
          <footer className="queue-footer">
            <span aria-live="polite">{total ? `${Math.min(page * pageSize + 1, total)}–${Math.min((page + 1) * pageSize, total)} of ${total}` : '0 orders'}</span>
            <div>
              <Button variant="ghost" size="icon" aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft size={17} /></Button>
              <Button variant="ghost" size="icon" aria-label="Next page" disabled={(page + 1) * pageSize >= total} onClick={() => setPage(page + 1)}><ChevronRight size={17} /></Button>
            </div>
          </footer>
        </section>
        <section className="detail" ref={detailHeading} tabIndex={-1} aria-label="Order detail">
          {current && <><Button className="back-to-queue" variant="ghost" onClick={() => setMobileDetail(false)}><ChevronLeft size={18} /> Back to queue</Button>
            <OrderPane key={current.order_id} summary={current} merchant={tenant} /></>}
          {!current && <div className="detail-empty"><PackageOpen size={26} aria-hidden="true" /><p>Select an order to see its dispatch details.</p></div>}
        </section>
      </div>
    </main>
  </>
}

function ImportOrders({ onImported }: { onImported: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null)
  const [key, setKey] = useState('')
  const run = useMutation({
    mutationFn: async (upload: File) => (await request<ImportReceipt>('/orders/import', {
      method: 'POST', headers: { 'Idempotency-Key': key }, body: fileUpload(upload),
    })).data,
    onSuccess: onImported,
  })
  return <Dialog onOpenChange={(open) => {
    if (!open && !run.isPending) { setFile(null); setKey(''); run.reset() }
  }}>
    <DialogTrigger asChild><Button><Upload size={17} /> Import orders</Button></DialogTrigger>
    <DialogContent>
      <DialogHeader><DialogTitle>Import orders</DialogTitle>
        <DialogDescription>Add a CSV with order ID, customer name, product, and phone columns.</DialogDescription></DialogHeader>
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); if (file) run.mutate(file) }}>
        <label htmlFor="order-file">Order CSV</label>
        <Input id="order-file" type="file" accept=".csv,text/csv" onChange={(event) => {
          setFile(event.target.files?.[0] ?? null); setKey(crypto.randomUUID()); run.reset()
        }} />
        <code className="csv-header">order_id,customer_name,product,phone</code>
        {run.error && <Failure error={run.error} />}
        {run.data && <div className="notice" role="status">
          <strong>{run.data.imported} {run.data.imported === 1 ? 'order' : 'orders'} imported</strong>
          {!!run.data.errors.length && <ul className="import-errors">{run.data.errors.map((row) =>
            <li key={row.row}>Row {row.row}: {row.error}</li>)}</ul>}
        </div>}
        <Button type="submit" disabled={!file || run.isPending || run.isSuccess}>{run.isPending ? 'Importing…' : 'Import CSV'}</Button>
      </form>
    </DialogContent>
  </Dialog>
}

function TeamInvite() {
  const mutation = useMutation({
    mutationFn: (form: FormData) => request('/auth/invitations', json('POST', {
      email: String(form.get('email')).trim(), role: String(form.get('role')),
    })),
  })
  function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    mutation.mutate(new FormData(event.currentTarget))
  }
  return <Dialog onOpenChange={(open) => { if (open) mutation.reset() }}>
    <DialogTrigger asChild><Button variant="ghost" size="sm"><UserPlus size={17} /> Invite staff</Button></DialogTrigger>
    <DialogContent>
      <DialogHeader><DialogTitle>Invite staff</DialogTitle>
        <DialogDescription>Send a team member an invitation code for this store.</DialogDescription></DialogHeader>
      <form className="form-stack" onSubmit={invite}>
        <label htmlFor="staff-email">Work email</label>
        <Input id="staff-email" name="email" type="email" autoComplete="email" required />
        <label htmlFor="staff-role">Role</label>
        <select id="staff-role" name="role"><option value="ops">Operations</option><option value="packer">Packer</option></select>
        {mutation.error && <Failure error={mutation.error} />}
        {mutation.isSuccess && <p className="notice" role="status">Invitation sent.</p>}
        <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? 'Sending…' : 'Send invitation'}</Button>
      </form>
    </DialogContent>
  </Dialog>
}
