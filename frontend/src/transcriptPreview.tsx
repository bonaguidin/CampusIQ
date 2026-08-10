import { createRoot } from 'react-dom/client';
import { TranscriptFlow } from './pages/TranscriptPage';
import './index.css';
createRoot(document.getElementById('root')!).render(<TranscriptFlow accessToken="preview-session-token" />);
