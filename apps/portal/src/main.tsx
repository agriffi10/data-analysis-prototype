import './lib/amplify' // must be first — configures Amplify before any component renders
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './features/auth'

// AuthProvider wraps the whole app, outside any router added later (SPEC-008
// nests the router inside it so route guards can call useAuth).
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
)
