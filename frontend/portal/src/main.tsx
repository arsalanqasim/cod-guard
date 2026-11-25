import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError } from './api'
import { App } from './App'
import { ShopifyApp } from './ShopifyApp'
import '@fontsource/barlow-semi-condensed/latin-700.css'
import '@fontsource/source-sans-3/latin-400.css'
import '@fontsource/source-sans-3/latin-600.css'
import './index.css'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: (attempt, error) => attempt === 0 && (!(error instanceof ApiError) || error.status >= 500),
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      {window.location.pathname === '/shopify/app' ? <ShopifyApp /> : <App />}
    </QueryClientProvider>
  </StrictMode>,
)
