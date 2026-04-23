// src/App.jsx
/**
 * App - One-Button Pipeline Architecture
 * ======================================
 * 
 * Routes:
 *   /         → OneButtonPage (main CTA)
 *   /admin/*  → AdminControlPanel (admin only)
 * 
 * Removed:
 *   - Multi-step assessment
 *   - AI chat consultation
 *   - Career library
 *   - Profile setup wizard
 *   - Dashboard
 *   - Explore
 * 
 * Kept:
 *   - Feedback widget (global)
 *   - Admin panel
 */
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Suspense } from 'react';
import Header from './components/layout/Header/Header';
import Footer from './components/layout/Footer/Footer';
import FeedbackForm from './components/FeedbackForm';
import { OneButtonPage } from './pages/OneButton';
import AdminLogin from './pages/Admin/Auth/AdminLogin';
import AdminControlPanel from './admin-ui/AdminControlPanel';
import ErrorBoundary from './components/common/ErrorBoundary/ErrorBoundary';
import Loading from './components/common/Loading/Loading';
import './App.css';

function App() {
  return (
    <Router>
      <div className="app">
        <Header />
        <main className="main-content">
          <ErrorBoundary>
            <Suspense fallback={<Loading />}>
              <Routes>
                {/* Main route - One Button Page */}
                <Route path="/" element={<OneButtonPage />} />
                
                {/* Legacy routes redirect to main */}
                <Route path="/profile" element={<Navigate to="/" replace />} />
                <Route path="/assessment" element={<Navigate to="/" replace />} />
                <Route path="/chat" element={<Navigate to="/" replace />} />
                <Route path="/dashboard" element={<Navigate to="/" replace />} />
                <Route path="/library" element={<Navigate to="/" replace />} />
                <Route path="/explore" element={<Navigate to="/" replace />} />
                <Route path="/explain" element={<Navigate to="/" replace />} />
                
                {/* Admin routes */}
                <Route path="/admin/login" element={<AdminLogin />} />
                <Route path="/admin/auth" element={<AdminLogin />} />
                <Route path="/admin/*" element={<AdminControlPanel />} />
                
                {/* Catch-all redirect */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </main>
        <FeedbackForm />
        <Footer />
      </div>
    </Router>
  );
}

export default App;

