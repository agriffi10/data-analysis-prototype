import './index.css';
import { Routes, Route } from 'react-router-dom';
import { RootLayout } from './components/RootLayout';
import { ProtectedLayout } from './components/ProtectedLayout';
import LandingPage from './routes/LandingPage';
import FilesPage from './routes/FilesPage';
import NotFoundPage from './routes/NotFoundPage';

// Route definitions. RootLayout wraps every page with the shared Header;
// ProtectedLayout is a nested sub-layout that gates protected routes on auth
// state (FR-003).
export default function App() {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route path="/" element={<LandingPage />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/files" element={<FilesPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
