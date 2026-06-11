import './lib/amplify' // must be first — configures Amplify before any component renders
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './features/auth'

// AuthProvider wraps the router so route guards (SPEC-008 ProtectedLayout) can
// call useAuth; BrowserRouter nests inside it.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
)
