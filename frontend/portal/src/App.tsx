import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, json, request, type Session } from './api'
import { Workspace } from './Workspace'
import { Brand, Failure } from './shared'

const sessionKey = ['session']

export function App() {
  const client = useQueryClient()
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: async ({ signal }) => (await request<Session>('/auth/session', { signal })).data,
  })

  async function changeSession(value: Session | null) {
    await client.cancelQueries({ queryKey: ['merchant-data'] })
    client.removeQueries({ queryKey: ['merchant-data'] })
    if (value) client.setQueryData(sessionKey, value)
    else await client.invalidateQueries({ queryKey: sessionKey })
  }

  if (session.isPending) return <main className="loading" role="status">Opening COD-Guard…</main>
  if (session.error instanceof ApiError && session.error.status === 401) return <SignIn onSession={changeSession} />
  if (session.error) return <main className="loading"><Failure error={session.error} retry={() => void session.refetch()} /></main>
  return <Workspace key={session.data.merchant.tenant_id} session={session.data} onSession={changeSession} />
}

function SignIn({ onSession }: { onSession: (value: Session) => Promise<void> }) {
  const [mode, setMode] = useState<'sign-in' | 'create' | 'invite'>('sign-in')
  const [email, setEmail] = useState('')
  const [proof, setProof] = useState(false)
  const send = useMutation({
    mutationFn: () => request('/auth/email/start', json('POST', { email: email.trim() })),
    onSuccess: () => setProof(true),
  })
  const complete = useMutation({
    mutationFn: async (form: FormData) => {
      return (await request<Session>('/auth/email/complete', json('POST', {
        code: String(form.get('code')).trim(),
        ...(mode === 'create' ? { store_name: String(form.get('store_name')).trim() } : {}),
        ...(mode === 'invite' ? { invitation: String(form.get('invitation')).trim() } : {}),
      }))).data
    },
    onSuccess: onSession,
  })
  function verifyEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    complete.mutate(new FormData(event.currentTarget))
  }
  const title = { 'sign-in': 'Sign in', create: 'Create your store', invite: 'Join your team' }[mode]

  return <main className="signin">
    <section className="signin-heading">
      <Brand />
      <div>
        <h1>Cash-on-delivery<br />dispatch</h1>
        <p>Review buyer replies, catch storefront changes, and decide which orders to pack.</p>
      </div>
    </section>
    <section className="signin-form" aria-label={title}>
      <nav className="mode-nav" aria-label="Account actions">
        {(['sign-in', 'create', 'invite'] as const).map((item) => <button key={item} type="button"
          aria-pressed={mode === item} onClick={() => { setMode(item); complete.reset() }}>
          {{ 'sign-in': 'Sign in', create: 'New store', invite: 'Join team' }[item]}
        </button>)}
      </nav>
      <h2>{proof ? 'Check your email' : title}</h2>
      {!proof && <form className="form-stack" onSubmit={(event) => { event.preventDefault(); send.mutate() }}>
        <label htmlFor="email">Work email</label>
        <Input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        {send.error && <Failure error={send.error} />}
        <Button type="submit" disabled={send.isPending}>{send.isPending ? 'Sending code…' : 'Send sign-in code'}</Button>
      </form>}
      {proof && <form className="form-stack" onSubmit={verifyEmail}>
        <p className="email-sent"><MailCheck aria-hidden="true" size={18} />Code sent to {email.trim()}.</p>
        <label htmlFor="code">Sign-in code</label>
        <Input id="code" name="code" autoComplete="one-time-code" spellCheck={false} required />
        {mode === 'create' && <><label htmlFor="store">Store name</label><Input id="store" name="store_name" maxLength={100} required /></>}
        {mode === 'invite' && <><label htmlFor="invitation">Invitation code</label><Input id="invitation" name="invitation" required /></>}
        {complete.error && <Failure error={complete.error} />}
        <Button type="submit" disabled={complete.isPending}>{complete.isPending ? 'Checking code…' : title}</Button>
        <Button type="button" variant="ghost" onClick={() => { setProof(false); send.reset(); complete.reset() }}>Use another email or request a new code</Button>
      </form>}
    </section>
  </main>
}
