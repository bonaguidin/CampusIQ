import { useMemo, useRef, useState } from 'react';
import { confirmTranscript, patchTranscriptRecord } from '../api/transcript';
import type { TranscriptConfirmResult, TranscriptRecord, TranscriptReviewResult, TranscriptUploadResult } from '../lib/transcriptApi.mjs';

type Draft = Pick<TranscriptRecord, 'course_code' | 'title' | 'credit_hours' | 'letter_grade' | 'status'>;
const draftOf = (row: TranscriptRecord): Draft => ({ course_code: row.course_code, title: row.title, credit_hours: row.credit_hours, letter_grade: row.letter_grade, status: row.status });

export function TranscriptReview({ accessToken, review, uploadResult, sourceName, onConfirmed }: { accessToken: string; review: TranscriptReviewResult & { ok: true }; uploadResult?: TranscriptUploadResult | null; sourceName?: string; onConfirmed(result: TranscriptConfirmResult): void }) {
  const [rows, setRows] = useState(review.records);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState('');
  const editHeading = useRef<HTMLHeadingElement>(null);
  const terms = useMemo(() => new Map(review.terms.map((term) => [term.id, term])), [review.terms]);
  const institution = review.institutions[0]?.name;
  const groups = useMemo(() => {
    const grouped = new Map<string, TranscriptRecord[]>();
    for (const row of rows) {
      const key = row.term_id ?? 'unresolved';
      grouped.set(key, [...(grouped.get(key) ?? []), row]);
    }
    return [...grouped.entries()].sort(([a], [b]) => (terms.get(a)?.sequence ?? 9999) - (terms.get(b)?.sequence ?? 9999));
  }, [rows, terms]);
  const credits = rows.reduce((sum, row) => sum + (Number(row.credit_hours) || 0), 0);

  function begin(row: TranscriptRecord) {
    setEditing(row.id); setDraft(draftOf(row)); setSaveError('');
    requestAnimationFrame(() => editHeading.current?.focus());
  }
  async function save(row: TranscriptRecord) {
    if (!draft || saving) return;
    setSaving(true); setSaveError('');
    const result = await patchTranscriptRecord(accessToken, row.id, draft);
    setSaving(false);
    if (!result.ok || !result.record) { setSaveError(result.message); return; }
    setRows((current) => current.map((item) => item.id === row.id ? result.record! : item));
    setEditing(null); setDraft(null);
  }
  async function confirm() {
    if (confirming) return;
    setConfirming(true); setConfirmError('');
    const result = await confirmTranscript(accessToken);
    setConfirming(false);
    if (!result.ok) { setConfirmError(result.message); return; }
    onConfirmed(result);
  }

  return <main className="transcript-shell">
    <header className="transcript-review-header">
      <div><p className="transcript-kicker">Transcript review</p><h1>Verify your academic record</h1><p>{institution ? `${institution} · ` : ''}{sourceName ? `Read from ${sourceName}` : 'Recovered from your saved review'}</p></div>
      <dl className="transcript-totals"><div><dt>Courses</dt><dd>{rows.length}</dd></div><div><dt>Attempted credits</dt><dd>{credits.toFixed(2)}</dd></div><div><dt>Catalog checks</dt><dd>{review.pendingCatalogReview}</dd></div></dl>
    </header>

    <div className="transcript-notice" role="note"><strong>Credit classification needs verification.</strong> Transcript imports currently default courses to resident credit; transfer and dual-enrollment status are not detected yet.</div>
    {uploadResult && (uploadResult.rejected.length > 0 || uploadResult.warnings.length > 0) && <div className="transcript-error" role="alert"><strong>Some extracted content needs attention.</strong><p>{uploadResult.rejected.length} course row(s) could not be safely stored. {uploadResult.warnings[0] ?? 'Review the stored courses below against your original transcript.'}</p></div>}

    {groups.map(([termId, termRows]) => <section className="transcript-paper transcript-term" key={termId} aria-labelledby={`term-${termId}`}>
      <header><p className="transcript-kicker">Academic term</p><h2 id={`term-${termId}`}>{terms.get(termId)?.label ?? 'Term not resolved'}</h2></header>
      <div className="transcript-course-list">
        {termRows.map((row) => <article className={`transcript-course ${row.needs_catalog_review ? 'needs-review' : ''}`} key={row.id}>
          {editing === row.id && draft ? <div className="transcript-edit-form">
            <h3 ref={editHeading} tabIndex={-1}>Correct {row.course_code}</h3>
            <label>Course code<input value={draft.course_code} onChange={(e) => setDraft({ ...draft, course_code: e.target.value })} /></label>
            <label>Course title<input value={draft.title ?? ''} onChange={(e) => setDraft({ ...draft, title: e.target.value || null })} /></label>
            <label>Credits<input type="number" min="0" max="99.99" step="0.01" value={draft.credit_hours} onChange={(e) => setDraft({ ...draft, credit_hours: e.target.value })} /></label>
            <label>Grade<input value={draft.letter_grade ?? ''} onChange={(e) => setDraft({ ...draft, letter_grade: e.target.value || null })} /></label>
            <label>Status<select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as Draft['status'] })}><option value="completed">Completed</option><option value="in_progress">In progress</option></select></label>
            {saveError && <p className="transcript-error" role="alert">{saveError}</p>}
            <div className="transcript-actions"><button className="btn btn-primary" type="button" disabled={saving} onClick={() => void save(row)}>{saving ? 'Saving…' : 'Save correction'}</button><button className="btn btn-ghost" type="button" disabled={saving} onClick={() => { setEditing(null); setDraft(null); setSaveError(''); }}>Cancel</button></div>
          </div> : <>
            <div className="transcript-course-main"><div><p className="transcript-code">{row.course_code}</p><h3>{row.title || 'Untitled course'}</h3></div><button className="transcript-edit-button" type="button" onClick={() => begin(row)} aria-label={`Edit ${row.course_code}`}>Edit</button></div>
            <dl className="transcript-course-meta"><div><dt>Credits</dt><dd>{row.credit_hours}</dd></div><div><dt>Grade</dt><dd>{row.letter_grade ?? '—'}</dd></div><div><dt>Status</dt><dd>{row.status === 'in_progress' ? 'In progress' : 'Completed'}</dd></div><div><dt>Credit type</dt><dd>{row.credit_type === 'resident' ? 'Resident (default)' : row.credit_type.replace('_', ' ')}</dd></div></dl>
            <div className="transcript-flags">{row.needs_catalog_review && <span>Course code needs catalog review</span>}{!row.counts_toward_gpa && <span>Does not currently count toward GPA</span>}{row.repeat_exclusion && <span>Excluded from GPA: replaced by {row.repeat_exclusion.superseded_by?.course_code ?? 'a later attempt'}; earned hours still count</span>}</div>
          </>}
        </article>)}
      </div>
    </section>)}

    {review.excludedByRepeat.length > 0 && <section className="transcript-paper transcript-repeat-summary"><p className="transcript-kicker">Repeat policy</p><h2>Attempts excluded from GPA</h2>{review.excludedByRepeat.map((row) => <p key={row.id}><strong>{row.course_code}</strong> ({row.letter_grade ?? 'no grade'}) was replaced by {row.repeat_exclusion?.superseded_by?.course_code ?? 'a later attempt'}. It still counts toward earned hours.</p>)}</section>}

    <footer className="transcript-commit"><div><strong>Ready to confirm?</strong><p>Confirming makes these records part of your academic profile. GPA is calculated by the backend after confirmation.</p>{confirmError && <p className="transcript-error" role="alert">{confirmError}</p>}</div><button className="btn btn-primary" type="button" disabled={confirming || editing !== null} onClick={() => void confirm()}>{confirming ? 'Confirming…' : `Confirm ${rows.length} courses`}</button></footer>
  </main>;
}
