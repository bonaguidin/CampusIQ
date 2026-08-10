import { Routes, Route, Navigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { SignUpPage } from './pages/SignUpPage';
import { DashboardPage } from './pages/DashboardPage';
import { ResumePage } from './pages/ResumePage';
import { TranscriptPage } from './pages/TranscriptPage';
import { RequireAuth } from './auth/RequireAuth';
import { RequireStudentAccount } from './auth/RequireStudentAccount';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      {/*
        /dashboard keeps RequireAuth: it still serves the demo path unchanged.
        A real (session-path) student is redirected from there to /resume,
        because DashboardPage renders from the demo profile and shows nothing
        for them. See RequireAuth's own note.
      */}
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      {/*
        /resume uses the narrower gate. RequireAuth would admit a demo session
        via its `if (profile)` short-circuit, and demo students have no Postgres
        rows, so every call this flow makes would 404 for them.
      */}
      <Route
        path="/resume"
        element={
          <RequireStudentAccount>
            <ResumePage />
          </RequireStudentAccount>
        }
      />
      <Route
        path="/transcript"
        element={<RequireStudentAccount><TranscriptPage /></RequireStudentAccount>}
      />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
