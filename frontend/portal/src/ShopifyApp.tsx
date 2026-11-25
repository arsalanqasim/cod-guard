import { createElement, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, json, request } from './api'
import { Failure } from './shared'

type AdminOrder = { order_id: string; external_id: string; product: string; storefront_conflict: number; decision: string }

async function shopifyRequest<T>(path: string, init?: RequestInit) {
  const bridge = (window as Window & { shopify?: { idToken: () => Promise<string> } }).shopify
  if (!bridge?.idToken) throw new Error('Open this page inside Shopify Admin.')
  const headers = new Headers(init?.headers)
  headers.set('Authorization', `Bearer ${await bridge.idToken()}`)
  return (await request<T>(`/providers/shopify/embedded/${path}`, { ...init, headers })).data
}

export function ShopifyApp() {
  const client = useQueryClient()
  const [code, setCode] = useState('')
  const queue = useQuery({
    queryKey: ['shopify-queue'],
    queryFn: ({ signal }) => shopifyRequest<AdminOrder[]>('orders', { signal }),
  })
  const pair = useMutation({
    mutationFn: () => shopifyRequest('link', json('POST', { code: code.trim() })),
    onSuccess: async () => { setCode(''); await client.invalidateQueries({ queryKey: ['shopify-queue'] }) },
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    pair.mutate()
  }
  const needsPairing = queue.error instanceof ApiError && queue.error.status === 403

  return createElement('s-page', { heading: 'COD-Guard' },
    createElement('s-section', { heading: needsPairing ? 'Link this store' : 'Dispatch queue' },
      <div className="shopify-app-content">
        {needsPairing && <form className="form-stack" onSubmit={submit}>
          <p>Create a Shopify connection in the COD-Guard portal and paste its pairing code here.</p>
          <label htmlFor="pair-code">Pairing code</label>
          <Input id="pair-code" name="code" value={code} onChange={(event) => setCode(event.target.value)} required />
          {pair.error && <Failure error={pair.error} />}
          <Button type="submit" disabled={!code.trim() || pair.isPending}>Link Shopify store</Button>
        </form>}
        {queue.isPending && <p role="status">Loading orders…</p>}
        {queue.error && !needsPairing && <Failure error={queue.error} retry={() => void queue.refetch()} />}
        {queue.data?.length === 0 && <p>No Shopify COD orders have synced yet.</p>}
        {!!queue.data?.length && <>
          <table className="orders"><thead><tr><th>Order</th><th>Product</th><th>Decision</th></tr></thead>
            <tbody>{queue.data.map((row) => <tr key={row.order_id}>
              <td>{row.external_id}</td><td>{row.product}</td><td>{row.storefront_conflict ? 'Store conflict' : row.decision.replaceAll('_', ' ')}</td>
            </tr>)}</tbody></table>
          <p><a className="order-link" href="/" target="_blank" rel="noopener noreferrer">Open merchant portal to review orders</a></p>
        </>}
      </div>))
}
