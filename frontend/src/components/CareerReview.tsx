import { useCallback, useEffect, useState } from 'react';
import { confirmCareerRecords, fetchCareerReview, patchCareerRow } from '../api/resume';
import {
  CERT_STATUS_VALUES,
  CHILD_TABLES,
  REVIEW_SECTIONS,
  changedFields,
  formatListInput,
  parseListInput,
} from '../lib/resumeApi.mjs';
import type {
  NormalizedConfirm,
  ReviewField,
  ReviewRow,
  ReviewSections,
  SectionKey,
} from '../lib/resumeApi.mjs';

interface CareerReviewProps {
  accessToken: string;
  onConfirmed(result: NormalizedConfirm): void;
}

/** Per-row UI state: an inline message, and whether editing is still allowed. */
interface RowState {
  message: string | null;
  tone: 'error' | 'saved';
  locked: boolean;
}

type RowStates = Record<string, RowState>;

const EMPTY_SECTIONS: ReviewSections = {
  career_profile: null,
  certifications: [],
  work_experience: [],
  projects: [],
};

function rowKey(table: SectionKey, id: string) {
  return `${table}:${id}`;
}

function titleFor(table: SectionKey, row: ReviewRow, index: number): string {
  const section = REVIEW_SECTIONS[table];
  const field = section.titleField;
  const value = field ? row[field] : null;
  if (typeof value === 'string' && value.trim()) return value;
  return `${section.singular} ${String(index + 1)}`;
}

// ── one editable field ──────────────────────────────────────────────────────

interface FieldEditorProps {
  field: ReviewField;
  idPrefix: string;
  value: unknown;
  disabled: boolean;
  onChange(next: unknown): void;
  /**
   * `overrides` exists for the list editor, which parses its text on blur and
   * must commit that parsed value in the same handler. setDrafts is
   * asynchronous, so a plain onChange-then-onCommit would diff against the
   * pre-change draft and silently skip the edit.
   */
  onCommit(overrides?: Record<string, unknown>): void;
}

/**
 * Comma-separated editor for a text[] column.
 *
 * Holds the RAW TEXT locally and only parses on blur. Parsing on every
 * keystroke would make the field unusable: typing "React," parses to
 * ["React"], which formats back to "React", so the comma disappears from under
 * the cursor the moment it is typed.
 */
function ListFieldEditor({
  field,
  idPrefix,
  value,
  disabled,
  onChange,
  onCommit,
}: FieldEditorProps) {
  const id = `${idPrefix}-${field.name}`;
  const [text, setText] = useState(() => formatListInput(value));
  const [lastValue, setLastValue] = useState(value);

  // Adopt an externally-changed value (the server's saved version, or a
  // reverted edit) without clobbering what is being typed.
  if (value !== lastValue) {
    setLastValue(value);
    setText(formatListInput(value));
  }

  return (
    <div className="form-group">
      <label className="form-label" htmlFor={id}>
        {field.label}
      </label>
      <input
        id={id}
        className="form-input"
        type="text"
        disabled={disabled}
        value={text}
        placeholder="Comma separated"
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          const parsed = parseListInput(text);
          onChange(parsed);
          onCommit({ [field.name]: parsed });
        }}
      />
    </div>
  );
}

function FieldEditor(props: FieldEditorProps) {
  const { field, idPrefix, value, disabled, onChange, onCommit } = props;
  const id = `${idPrefix}-${field.name}`;

  if (field.type === 'list') {
    return <ListFieldEditor {...props} />;
  }

  if (field.type === 'textarea') {
    return (
      <div className="form-group">
        <label className="form-label" htmlFor={id}>
          {field.label}
        </label>
        <textarea
          id={id}
          className="form-textarea"
          rows={3}
          disabled={disabled}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => onCommit()}
        />
      </div>
    );
  }

  if (field.type === 'status') {
    return (
      <div className="form-group">
        <label className="form-label" htmlFor={id}>
          {field.label}
        </label>
        <select
          id={id}
          className="form-select"
          disabled={disabled}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => {
            onChange(event.target.value === '' ? null : event.target.value);
          }}
          onBlur={() => onCommit()}
        >
          <option value="">Not stated</option>
          {CERT_STATUS_VALUES.map((status) => (
            <option key={status} value={status}>
              {status === 'completed' ? 'Completed' : 'In progress'}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div className="form-group">
      <label className="form-label" htmlFor={id}>
        {field.label}
      </label>
      <input
        id={id}
        className="form-input"
        type="text"
        disabled={disabled}
        value={typeof value === 'string' ? value : ''}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => onCommit()}
      />
    </div>
  );
}

// ── the screen ──────────────────────────────────────────────────────────────

export function CareerReview({ accessToken, onConfirmed }: CareerReviewProps) {
  const [sections, setSections] = useState<ReviewSections>(EMPTY_SECTIONS);
  const [drafts, setDrafts] = useState<Record<string, ReviewRow>>({});
  const [rowStates, setRowStates] = useState<RowStates>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let active = true;
    void (async () => {
      const result = await fetchCareerReview(accessToken);
      if (!active) return;
      if (result.ok) {
        setSections(result.sections);
        const initial: Record<string, ReviewRow> = {};
        if (result.sections.career_profile) {
          initial[rowKey('career_profile', result.sections.career_profile.id)] = {
            ...result.sections.career_profile,
          };
        }
        for (const table of CHILD_TABLES) {
          for (const row of result.sections[table]) {
            initial[rowKey(table, row.id)] = { ...row };
          }
        }
        setDrafts(initial);
      } else {
        setLoadError(result.message);
      }
      setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [accessToken]);

  const setRowState = useCallback((key: string, state: RowState | null) => {
    setRowStates((prev) => {
      const next = { ...prev };
      if (state === null) delete next[key];
      else next[key] = state;
      return next;
    });
  }, []);

  const removeRow = useCallback((table: SectionKey, id: string) => {
    setSections((prev) => {
      if (table === 'career_profile') return { ...prev, career_profile: null };
      return { ...prev, [table]: prev[table].filter((row) => row.id !== id) };
    });
  }, []);

  const commit = useCallback(
    async (table: SectionKey, original: ReviewRow, overrides?: Record<string, unknown>) => {
      const key = rowKey(table, original.id);
      const stored = drafts[key];
      if (!stored) return;
      const draft = overrides ? { ...stored, ...overrides } : stored;

      const changes = changedFields(table, original, draft);
      if (Object.keys(changes).length === 0) return;

      const result = await patchCareerRow(accessToken, table, original.id, changes);

      if (result.ok && result.row) {
        // Adopt the server's version, not the draft: it reflects any
        // normalization the backend applied (status lower-cased, blanks nulled).
        const saved = result.row;
        setSections((prev) => {
          if (table === 'career_profile') return { ...prev, career_profile: saved };
          return {
            ...prev,
            [table]: prev[table].map((row) => (row.id === saved.id ? saved : row)),
          };
        });
        setDrafts((prev) => ({ ...prev, [key]: { ...saved } }));
        setRowState(key, { message: 'Saved', tone: 'saved', locked: false });
        return;
      }

      if (result.kind === 'not_found') {
        // Gone, for a reason the backend deliberately will not disclose.
        removeRow(table, original.id);
        setRowState(key, null);
        return;
      }

      if (result.kind === 'already_confirmed') {
        // Lock it and restore the stored values -- the edit did not apply.
        setDrafts((prev) => ({ ...prev, [key]: { ...original } }));
        setRowState(key, { message: result.message, tone: 'error', locked: true });
        return;
      }

      // conflict | invalid | anything else: keep what they typed so it can be
      // corrected, but make clear it is not saved.
      setRowState(key, { message: result.message, tone: 'error', locked: false });
    },
    [accessToken, drafts, removeRow, setRowState],
  );

  function updateDraft(key: string, fieldName: string, value: unknown) {
    setDrafts((prev) => ({ ...prev, [key]: { ...prev[key], [fieldName]: value } }));
  }

  async function handleConfirm() {
    setConfirming(true);
    setConfirmError(null);
    try {
      const result = await confirmCareerRecords(accessToken);
      if (result.ok) {
        onConfirmed(result);
        return;
      }
      setConfirmError(result.message);
    } finally {
      setConfirming(false);
    }
  }

  function renderRow(table: SectionKey, row: ReviewRow, index: number) {
    const key = rowKey(table, row.id);
    const draft = drafts[key] ?? row;
    const state = rowStates[key];
    const locked = state?.locked ?? false;

    return (
      <div className="resume-row" key={key}>
        <div className="resume-row-header">
          <h3 className="resume-row-title">{titleFor(table, draft, index)}</h3>
          {locked && <span className="resume-row-locked">Confirmed — read only</span>}
        </div>

        <div className="resume-row-fields">
          {REVIEW_SECTIONS[table].fields.map((field) => (
            <FieldEditor
              key={field.name}
              field={field}
              idPrefix={key}
              value={draft[field.name]}
              disabled={locked}
              onChange={(next) => updateDraft(key, field.name, next)}
              onCommit={(overrides) => {
                void commit(table, row, overrides);
              }}
            />
          ))}
        </div>

        {state?.message && (
          <p
            className={state.tone === 'error' ? 'resume-row-error' : 'resume-row-saved'}
            role={state.tone === 'error' ? 'alert' : 'status'}
          >
            {state.message}
          </p>
        )}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="spinner" role="status" aria-label="Loading your records" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Could not load your records</p>
          </div>
          <div className="login-form">
            <p className="login-error" role="alert">
              {loadError}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const hasProfile = sections.career_profile !== null;
  const pending =
    (hasProfile ? 1 : 0) + CHILD_TABLES.reduce((n, t) => n + sections[t].length, 0);

  if (pending === 0) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Nothing to review</p>
          </div>
          <div className="login-form">
            <p className="resume-intro">
              There is nothing waiting for your review — everything from your resume has already
              been confirmed.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="resume-review-bg">
      <div className="resume-review">
        <header className="resume-review-header">
          <h1 className="login-logo">GradusIQ</h1>
          <h2 className="resume-review-title">Review what we found</h2>
          <p className="resume-intro">
            Everything below came from your resume and is not saved to your profile yet. Correct
            anything that is wrong — changes save as you go — then confirm.
          </p>
        </header>

        {hasProfile && sections.career_profile && (
          <section className="resume-section">
            <h2 className="resume-section-title">{REVIEW_SECTIONS.career_profile.label}</h2>
            {renderRow('career_profile', sections.career_profile, 0)}
          </section>
        )}

        {CHILD_TABLES.map((table) =>
          sections[table].length === 0 ? null : (
            <section className="resume-section" key={table}>
              <h2 className="resume-section-title">
                {REVIEW_SECTIONS[table].label}
                <span className="resume-section-count">{sections[table].length}</span>
              </h2>
              {sections[table].map((row, index) => renderRow(table, row, index))}
            </section>
          ),
        )}

        <footer className="resume-review-footer">
          {confirmError && (
            <p className="login-error" role="alert">
              {confirmError}
            </p>
          )}
          <button
            type="button"
            className="btn btn-primary btn-full"
            onClick={() => {
              void handleConfirm();
            }}
            disabled={confirming}
          >
            {confirming ? <span className="btn-loading">Saving…</span> : 'Confirm all'}
          </button>
          <p className="login-note">
            Confirming saves everything above to your profile. Entries you have not corrected are
            saved as they appear.
          </p>
        </footer>
      </div>
    </div>
  );
}
