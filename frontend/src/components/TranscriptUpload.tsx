import { useRef, useState } from 'react';
import { uploadTranscript } from '../api/transcript';
import type { TranscriptUploadResult } from '../lib/transcriptApi.mjs';

export function TranscriptUpload({ accessToken, onUploaded }: { accessToken: string; onUploaded(result: TranscriptUploadResult, fileName: string): void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<TranscriptUploadResult | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const result = await uploadTranscript(accessToken, file);
      if (result.ok) onUploaded(result, file.name);
      else setFailure(result);
    } finally { setBusy(false); }
  }

  return <main className="transcript-shell transcript-upload-shell">
    <section className="transcript-paper transcript-upload-card" aria-labelledby="transcript-upload-title">
      <p className="transcript-kicker">Academic record intake</p>
      <h1 id="transcript-upload-title">Add your transcript</h1>
      <p className="transcript-lede">Upload an academic transcript. GradusIQ will extract the courses, then let you verify every record before confirmation.</p>
      <form onSubmit={submit} className="transcript-upload-form">
        <label htmlFor="transcript-file">Transcript file</label>
        <input id="transcript-file" ref={input} type="file" accept=".pdf,.docx" disabled={busy} onChange={(event) => { setFile(event.target.files?.[0] ?? null); setFailure(null); }} />
        <p className="transcript-help">PDF or Word (.docx), up to 10 MB. Scanned documents without selectable text are not supported.</p>
        {failure && <div className="transcript-error" role="alert"><strong>We could not process that file.</strong><p>{failure.message}</p></div>}
        <button className="btn btn-primary" type="submit" disabled={!file || busy}>{busy ? 'Extracting academic records…' : 'Upload transcript'}</button>
        {failure && <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => { setFile(null); setFailure(null); if (input.current) input.current.value = ''; }}>Choose another file</button>}
      </form>
      <p className="transcript-footnote">Extraction can take a few seconds. Parsed records remain pending until you confirm them.</p>
    </section>
  </main>;
}
