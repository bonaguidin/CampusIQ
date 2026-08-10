// Test-only entry point for the persisted resume-flow state machine.
import { createRoot } from 'react-dom/client';
import { ResumeFlow } from './pages/ResumePage';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <ResumeFlow accessToken="preview-session-token" />,
);
