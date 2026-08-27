import { useEffect, useMemo, useState } from 'react';
import {
  SyllabusApiError,
  calculateSyllabusGrade,
  confirmSyllabusGradeModel,
  getSyllabusGradeProfile,
  ingestSyllabus,
  listSyllabusGradeProfiles,
  saveSyllabusGradeState,
  solveSyllabusTarget,
  submitSyllabusCorrections,
  type SyllabusCalculationResult,
  type SyllabusCategory,
  type SyllabusFinding,
  type SyllabusGradeModel,
  type SyllabusProfileDetail,
  type SyllabusProfileSummary,
  type SyllabusRule,
  type SyllabusTargetResult,
} from '../api/syllabusGradeProfiles';

// Presentation copy for machine-readable reconciliation finding codes. The
// code itself stays available (data-finding-code) for tests/telemetry; this
// mapping is the ONLY place backend codes turn into student-facing text.
const FINDING_COPY: Record<string, string> = {
  possible_curve: 'Your syllabus says grades may be curved, but it does not provide a formula.',
  unknown_weight: "We couldn't determine this category's weight.",
  unknown_assessment_count: "The syllabus doesn't say exactly how many assessments are in this category.",
  ambiguous_rule: "We found a grading rule, but couldn't determine exactly how it works.",
  missing_grade_scale: "This syllabus doesn't specify a letter-grade scale.",
  unresolved_assessment_category_reference: "This assessment refers to a grading category we couldn't match.",
  unresolved_rule_reference: "A grading rule refers to a category or assessment we couldn't match.",
  category_weight_validation: 'The category weights in this syllabus may not add up to 100%.',
  duplicate_category: 'We found what may be the same grading category listed twice.',
  duplicate_assessment: 'We found what may be the same assessment listed twice.',
  non_deterministic_grading_rule: "CampusIQ can't calculate this rule automatically.",
  grading_method_unknown: "We couldn't determine how this course is graded.",
  overlapping_grade_thresholds: 'The letter-grade cutoffs in this syllabus overlap.',
  grade_threshold_ordering_anomaly: 'The letter-grade cutoffs in this syllabus look out of order.',
  missing_claim_evidence: "We found this value, but couldn't confirm it against the syllabus text.",
  partial_claim_evidence: "We found this value, but couldn't confirm it against the syllabus text.",
  claim_evidence_value_mismatch: 'This value may not match what the syllabus actually says.',
  claim_evidence_consistency_unverifiable: "We couldn't automatically confirm this value against the syllabus text.",
  evidence_page_out_of_range: "This citation doesn't match the syllabus pages we reviewed.",
};

function findingCopy(finding: SyllabusFinding): string {
  return FINDING_COPY[finding.code] ?? finding.message;
}

function ruleTypeLabel(ruleType: SyllabusRule['rule_type']): string {
  switch (ruleType) {
    case 'replacement':
      return 'Score replacement';
    case 'drop':
      return 'Dropped score';
    case 'curve':
      return 'Curve';
    case 'extra_credit':
      return 'Extra credit';
    case 'late_work':
      return 'Late work';
    case 'makeup':
      return 'Makeup work';
    default:
      return 'Grading rule';
  }
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value}%`;
}

interface UploadFields {
  institution: string;
  courseCode: string;
  term: string;
  section: string;
}

type GradeStateDraft = Record<string, { actual: string; projected: string }>;

function draftFromModel(model: SyllabusGradeModel | null): GradeStateDraft {
  const draft: GradeStateDraft = {};
  if (!model) return draft;
  for (const category of model.categories) {
    if (category.weight !== null) draft[`category:${category.name}`] = { actual: '', projected: '' };
  }
  for (const assessment of model.assessments) {
    if ((assessment.weight !== null || assessment.points !== null) && assessment.category === null) {
      draft[`assessment:${assessment.name}`] = { actual: '', projected: '' };
    }
  }
  return draft;
}

function draftFromSavedState(draft: GradeStateDraft, detail: SyllabusProfileDetail): GradeStateDraft {
  const next: GradeStateDraft = { ...draft };
  for (const c of detail.grade_state?.category_scores ?? []) {
    const key = `category:${c.category_name}`;
    if (key in next) {
      next[key] = { actual: c.actual_score != null ? String(c.actual_score) : '', projected: '' };
    }
  }
  for (const a of detail.grade_state?.assessment_scores ?? []) {
    const key = `assessment:${a.assessment_name}`;
    if (key in next) {
      next[key] = { actual: a.actual_score != null ? String(a.actual_score) : '', projected: '' };
    }
  }
  return next;
}

function buildGradeState(draft: GradeStateDraft, useProjectedFallback: boolean) {
  const category_scores: { category_name: string; actual_score?: number; projected_score?: number }[] = [];
  const assessment_scores: { assessment_name: string; actual_score?: number; projected_score?: number }[] = [];
  for (const [key, values] of Object.entries(draft)) {
    const [kind, name] = key.split(/:(.*)/s);
    const actual = values.actual.trim() === '' ? null : Number(values.actual);
    const projected = values.projected.trim() === '' ? null : Number(values.projected);
    let entry: { actual_score?: number; projected_score?: number } | null = null;
    if (actual !== null && !Number.isNaN(actual)) {
      entry = { actual_score: actual };
    } else if (useProjectedFallback && projected !== null && !Number.isNaN(projected)) {
      entry = { projected_score: projected };
    }
    if (!entry) continue;
    if (kind === 'category') category_scores.push({ category_name: name, ...entry });
    else assessment_scores.push({ assessment_name: name, ...entry });
  }
  return { category_scores, assessment_scores };
}

function actualOnlyState(draft: GradeStateDraft) {
  return buildGradeState(draft, false);
}

interface Props {
  accessToken: string | null;
}

export function GradeCalculatorPanel({ accessToken }: Props) {
  const [profiles, setProfiles] = useState<SyllabusProfileSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SyllabusProfileDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [showUpload, setShowUpload] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fields, setFields] = useState<UploadFields>({ institution: '', courseCode: '', term: '', section: '' });
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [gradeDraft, setGradeDraft] = useState<GradeStateDraft>({});
  const [calcResult, setCalcResult] = useState<SyllabusCalculationResult | null>(null);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [showBreakdown, setShowBreakdown] = useState(false);

  const [targetComponent, setTargetComponent] = useState('');
  const [targetLetter, setTargetLetter] = useState('');
  const [targetNumeric, setTargetNumeric] = useState('');
  const [targetResult, setTargetResult] = useState<SyllabusTargetResult | null>(null);
  const [targetError, setTargetError] = useState<string | null>(null);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    listSyllabusGradeProfiles(accessToken)
      .then((items) => { if (!cancelled) setProfiles(items); })
      .catch((err: unknown) => {
        if (cancelled) return;
        setListError(err instanceof SyllabusApiError ? err.message : 'Could not load your grade calculators.');
        setProfiles([]);
      });
    return () => { cancelled = true; };
  }, [accessToken]);

  function loadDetail(profileId: string) {
    if (!accessToken) return;
    setSelectedProfileId(profileId);
    setDetail(null);
    setDetailError(null);
    setCalcResult(null);
    setTargetResult(null);
    setGradeDraft({});
    getSyllabusGradeProfile(accessToken, profileId)
      .then((d) => {
        setDetail(d);
        setGradeDraft(draftFromSavedState(draftFromModel(d.confirmed_grade_model ?? d.extracted_grade_model), d));
      })
      .catch((err: unknown) => {
        setDetailError(err instanceof SyllabusApiError ? err.message : 'Could not load this grade calculator.');
      });
  }

  async function refreshDetail() {
    if (!accessToken || !selectedProfileId) return;
    const d = await getSyllabusGradeProfile(accessToken, selectedProfileId);
    setDetail(d);
    setGradeDraft((prev) => draftFromSavedState({ ...draftFromModel(d.confirmed_grade_model ?? d.extracted_grade_model), ...prev }, d));
    return d;
  }

  async function handleUpload() {
    if (!accessToken || !file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const created = await ingestSyllabus(accessToken, file, {
        institution: fields.institution || undefined,
        course_code: fields.courseCode || undefined,
        term: fields.term || undefined,
        section: fields.section || undefined,
      });
      const summary: SyllabusProfileSummary = {
        id: created.id,
        institution: created.course.institution,
        course_code: created.course.course_code,
        term: created.course.term,
        section: created.course.section,
        review_state: created.review_state,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        calculator_ready: created.calculator_ready,
        current_grade: null,
      };
      setProfiles((prev) => [...(prev ?? []), summary]);
      setShowUpload(false);
      setFile(null);
      setDetail(created);
      setSelectedProfileId(created.id);
      setGradeDraft(draftFromModel(created.confirmed_grade_model ?? created.extracted_grade_model));
    } catch (err) {
      setUploadError(err instanceof SyllabusApiError ? err.message : "CampusIQ couldn't process this syllabus.");
    } finally {
      setUploading(false);
    }
  }

  async function handleIgnoreRule(ruleIndex: number, warningIndices: number[]) {
    if (!accessToken || !selectedProfileId) return;
    setBusy(true);
    setActionError(null);
    try {
      await submitSyllabusCorrections(accessToken, selectedProfileId, [
        { target_type: 'rule', operation: 'remove_rule', rule_index: ruleIndex },
        ...warningIndices.map((warning_index) => ({ target_type: 'warning' as const, operation: 'dismiss_warning', warning_index })),
      ]);
      await refreshDetail();
    } catch (err) {
      setActionError(err instanceof SyllabusApiError ? err.message : 'Could not save your correction.');
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (!accessToken || !selectedProfileId) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await confirmSyllabusGradeModel(accessToken, selectedProfileId);
      setDetail(updated);
      setGradeDraft((prev) => ({ ...draftFromModel(updated.confirmed_grade_model ?? updated.extracted_grade_model), ...prev }));
    } catch (err) {
      setActionError(err instanceof SyllabusApiError ? err.message : 'Could not confirm this grading model.');
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveActualGrades() {
    if (!accessToken || !selectedProfileId || !detail) return;
    setBusy(true);
    setActionError(null);
    try {
      const state = actualOnlyState(gradeDraft);
      const saved = await saveSyllabusGradeState(accessToken, selectedProfileId, state, detail.grade_state_revision);
      setDetail((prev) => (prev ? { ...prev, grade_state: state, grade_state_revision: saved.revision } : prev));
    } catch (err) {
      if (err instanceof SyllabusApiError && err.status === 409) {
        setActionError('Your saved grades changed in another session. Reloading the latest values.');
        const fresh = await refreshDetail();
        if (fresh) {
          setGradeDraft(draftFromSavedState(draftFromModel(fresh.confirmed_grade_model ?? fresh.extracted_grade_model), fresh));
        }
      } else {
        setActionError(err instanceof SyllabusApiError ? err.message : 'Could not save your grades.');
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleCalculate() {
    if (!accessToken || !selectedProfileId) return;
    setCalcError(null);
    try {
      const combined = buildGradeState(gradeDraft, true);
      const result = await calculateSyllabusGrade(accessToken, selectedProfileId, combined);
      setCalcResult(result);
    } catch (err) {
      setCalcError(err instanceof SyllabusApiError ? err.message : 'Could not calculate your grade.');
      setCalcResult(null);
    }
  }

  async function handleSolveTarget() {
    if (!accessToken || !selectedProfileId || !targetComponent) return;
    setTargetError(null);
    try {
      const combined = buildGradeState(gradeDraft, true);
      const target = targetLetter
        ? { target_component: targetComponent, target_letter: targetLetter }
        : { target_component: targetComponent, target_grade: Number(targetNumeric) };
      const result = await solveSyllabusTarget(accessToken, selectedProfileId, combined, target);
      setTargetResult(result);
    } catch (err) {
      setTargetError(err instanceof SyllabusApiError ? err.message : 'Could not solve for that target.');
      setTargetResult(null);
    }
  }

  const scoreableNames = useMemo(() => {
    const model = detail?.confirmed_grade_model ?? detail?.extracted_grade_model ?? null;
    if (!model) return [];
    const names: string[] = [];
    for (const c of model.categories) if (c.weight !== null) names.push(c.name);
    for (const a of model.assessments) if ((a.weight !== null || a.points !== null) && a.category === null) names.push(a.name);
    return names;
  }, [detail]);

  if (!accessToken) {
    return (
      <div className="card grade-calculator-panel">
        <p className="empty-state">Sign in to use the Grade Calculator.</p>
      </div>
    );
  }

  // ── Detail view (upload processing / review / confirmed calculator) ──────
  if (selectedProfileId) {
    return (
      <div className="grade-calculator-panel" data-testid="grade-calculator-detail">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setSelectedProfileId(null); setDetail(null); }}>
          ← Back to your calculators
        </button>

        {detailError && <p className="login-error" role="alert">{detailError}</p>}

        {!detail && !detailError && (
          <div className="card" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <p>Loading your grade calculator…</p>
          </div>
        )}

        {detail && (
          <>
            <h2 className="academic-section-heading">
              {detail.course.course_code ?? 'Untitled course'}
              {detail.course.term ? ` — ${detail.course.term}` : ''}
            </h2>

            {actionError && <p className="login-error" role="alert">{actionError}</p>}

            {!detail.calculator_ready && (
              <div className="card grade-review-card">
                <h3 className="card-heading">
                  {detail.confirmed_reconciliation ? 'Still needs your review' : 'Needs your review'}
                </h3>
                <SyllabusGradingBreakdown model={detail.extracted_grade_model} />
                <SyllabusRulesList model={detail.extracted_grade_model} onIgnoreRule={handleIgnoreRule} busy={busy} />
                <SyllabusFindingsList
                  findings={(detail.confirmed_reconciliation ?? detail.reconciliation)?.findings ?? []}
                />
                <button type="button" className="btn btn-primary" onClick={handleConfirm} disabled={busy} aria-busy={busy}>
                  {busy ? 'Confirming…' : 'Confirm'}
                </button>
              </div>
            )}

            {detail.calculator_ready && detail.review_state !== 'confirmed' && (
              <div className="card grade-review-card">
                <h3 className="card-heading">Review grading breakdown</h3>
                <SyllabusGradingBreakdown model={detail.confirmed_grade_model} />
                <SyllabusRulesList model={detail.confirmed_grade_model} onIgnoreRule={undefined} busy={busy} />
                <button type="button" className="btn btn-primary" onClick={handleConfirm} disabled={busy} aria-busy={busy}>
                  {busy ? 'Confirming…' : 'Confirm'}
                </button>
              </div>
            )}

            {detail.calculator_ready && (
              <>
                <div className="card">
                  <h3 className="card-heading">Enter your grades</h3>
                  <p className="empty-state">Leave a field blank if you don't know it yet — blank never counts as zero.</p>
                  {scoreableNames.map((name) => {
                    const key = `${detail.confirmed_grade_model?.categories.some((c) => c.name === name) ? 'category' : 'assessment'}:${name}`;
                    return (
                      <div className="grade-entry-row" key={key}>
                        <label htmlFor={`actual-${key}`}>{name}</label>
                        <input
                          id={`actual-${key}`}
                          type="number"
                          min={0}
                          max={100}
                          className="form-input"
                          value={gradeDraft[key]?.actual ?? ''}
                          onChange={(e) => setGradeDraft((prev) => ({ ...prev, [key]: { ...prev[key], actual: e.target.value, projected: prev[key]?.projected ?? '' } }))}
                          placeholder="—"
                        />
                        <label htmlFor={`hypo-${key}`} className="sr-only">Hypothetical {name} score</label>
                        <input
                          id={`hypo-${key}`}
                          type="number"
                          min={0}
                          max={100}
                          className="form-input grade-entry-hypothetical"
                          value={gradeDraft[key]?.projected ?? ''}
                          onChange={(e) => setGradeDraft((prev) => ({ ...prev, [key]: { ...prev[key], projected: e.target.value, actual: prev[key]?.actual ?? '' } }))}
                          placeholder="What if?"
                        />
                      </div>
                    );
                  })}
                  <div className="grade-entry-actions">
                    <button type="button" className="btn btn-primary btn-sm" onClick={handleSaveActualGrades} disabled={busy} aria-busy={busy}>
                      {busy ? 'Saving…' : 'Save grades'}
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={handleCalculate}>
                      Calculate
                    </button>
                  </div>
                </div>

                {calcError && <p className="login-error" role="alert">{calcError}</p>}

                {calcResult && (
                  <div className="card" role="status" aria-live="polite">
                    <h3 className="card-heading">Current grade</h3>
                    <p className="overview-stat-value">{calcResult.current_grade !== null ? `${calcResult.current_grade}%` : '—'}</p>
                    <p className="empty-state">
                      {calcResult.completed_weight !== null
                        ? `Based on ${calcResult.completed_weight}% of the course completed.`
                        : 'No grades entered yet.'}
                    </p>

                    <h3 className="card-heading">Projected grade</h3>
                    {calcResult.projected_grade !== null ? (
                      <p className="overview-stat-value">{calcResult.projected_grade}%</p>
                    ) : (
                      <p className="empty-state">Enter a hypothetical score for every remaining component to see your projected grade.</p>
                    )}

                    {calcResult.applied_rules.filter((r) => r.changed_calculation).map((rule, i) => (
                      <p key={i} className="grade-rule-explanation">
                        {rule.rule_type === 'replacement'
                          ? `${rule.source} replacement applied: your ${rule.source} score replaces your ${rule.target} score in this scenario.`
                          : `${rule.description}`}
                      </p>
                    ))}

                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowBreakdown((v) => !v)}>
                      {showBreakdown ? 'Hide breakdown' : 'Show breakdown'}
                    </button>
                    {showBreakdown && (
                      <div className="real-course-table" role="table" aria-label="Calculation breakdown">
                        {calcResult.components.map((c) => (
                          <div className="real-course-row" role="row" key={c.name}>
                            <span role="cell">{c.name}</span>
                            <span role="cell">entered: {c.original_score ?? '—'}</span>
                            <span role="cell">effective: {c.effective_score ?? '—'}</span>
                            <span role="cell">weight: {formatPercent(c.weight_percent)}</span>
                            <span role="cell">contribution: {c.contribution ?? '—'}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="card">
                  <h3 className="card-heading">Target grade</h3>
                  <label htmlFor="target-component" className="form-label">Solve for</label>
                  <select id="target-component" className="form-input" value={targetComponent} onChange={(e) => setTargetComponent(e.target.value)}>
                    <option value="">Choose a component</option>
                    {scoreableNames.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                  <label htmlFor="target-letter" className="form-label">Target grade</label>
                  <select id="target-letter" className="form-input" value={targetLetter} onChange={(e) => setTargetLetter(e.target.value)}>
                    <option value="">Custom number…</option>
                    {(detail.confirmed_grade_model?.grade_thresholds ?? []).map((t) => (
                      <option key={t.letter} value={t.letter}>{t.letter}</option>
                    ))}
                  </select>
                  {!targetLetter && (
                    <>
                      <label htmlFor="target-numeric" className="form-label">Numeric target</label>
                      <input id="target-numeric" type="number" className="form-input" value={targetNumeric} onChange={(e) => setTargetNumeric(e.target.value)} />
                    </>
                  )}
                  <button type="button" className="btn btn-primary btn-sm" onClick={handleSolveTarget} disabled={!targetComponent}>
                    Solve
                  </button>

                  {targetError && <p className="login-error" role="alert">{targetError}</p>}

                  {targetResult && (
                    <p role="status" aria-live="polite" className="grade-target-result">
                      {targetResult.already_achieved && "You've already reached this target under the grades and assumptions entered."}
                      {!targetResult.already_achieved && targetResult.feasible && targetResult.required_score !== null &&
                        `You need about ${targetResult.required_score}% on the ${targetResult.target_component} to finish with ${targetResult.target_label ? `an ${targetResult.target_label}` : 'this target'}.`}
                      {!targetResult.already_achieved && !targetResult.feasible && targetResult.required_score !== null &&
                        `You would need ${targetResult.required_score}% on the ${targetResult.target_component}. This target isn't reachable under the current assumptions.`}
                      {targetResult.required_score === null && "CampusIQ needs more grades entered to solve for this target."}
                    </p>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>
    );
  }

  // ── List / empty state / upload form ──────────────────────────────────────
  return (
    <div className="grade-calculator-panel" data-testid="grade-calculator-list">
      <h2 className="academic-section-heading">Grade Calculator</h2>

      {!showUpload && (
        <>
          {profiles === null && !listError && <p className="empty-state">Loading your grade calculators…</p>}
          {listError && <p className="login-error" role="alert">{listError}</p>}

          {profiles !== null && profiles.length === 0 && (
            <div className="real-empty">
              <h3>See what you need to reach your target grade</h3>
              <p>Upload your syllabus and CampusIQ will identify how your course is graded, let you verify it, and calculate scenarios.</p>
              <button type="button" className="btn btn-primary" onClick={() => setShowUpload(true)}>
                Upload syllabus
              </button>
            </div>
          )}

          {profiles !== null && profiles.length > 0 && (
            <>
              <div className="real-course-table" role="table" aria-label="Your grade calculators">
                {profiles.map((p) => (
                  <div className="real-course-row" role="row" key={p.id}>
                    <button type="button" className="grade-profile-row-button" onClick={() => loadDetail(p.id)}>
                      <span role="cell"><strong>{p.course_code ?? 'Untitled course'}</strong><small>{p.term ?? ''}</small></span>
                      <span role="cell">{p.review_state === 'confirmed' ? 'Confirmed' : p.review_state === 'reconfirm_required' ? 'Needs reconfirmation' : 'Review needed'}</span>
                      <span role="cell">{p.current_grade !== null && p.current_grade !== undefined ? `${p.current_grade}%` : '—'}</span>
                    </button>
                  </div>
                ))}
              </div>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowUpload(true)}>
                Upload another syllabus
              </button>
            </>
          )}
        </>
      )}

      {showUpload && (
        <form
          className="login-form"
          onSubmit={(e) => { e.preventDefault(); void handleUpload(); }}
        >
          <label className="form-label" htmlFor="syllabus-file">Syllabus PDF</label>
          <input
            id="syllabus-file"
            type="file"
            accept="application/pdf"
            className="form-input"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <label className="form-label" htmlFor="syllabus-course-code">Course code</label>
          <input id="syllabus-course-code" className="form-input" value={fields.courseCode} onChange={(e) => setFields((f) => ({ ...f, courseCode: e.target.value }))} placeholder="e.g. PHYS 207" />
          <label className="form-label" htmlFor="syllabus-term">Term</label>
          <input id="syllabus-term" className="form-input" value={fields.term} onChange={(e) => setFields((f) => ({ ...f, term: e.target.value }))} placeholder="e.g. Fall 2026" />

          {uploading && (
            <p role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" /> Reading syllabus and finding grading information…
            </p>
          )}
          {uploadError && <p className="login-error" role="alert">{uploadError}</p>}

          <div className="grade-entry-actions">
            <button type="submit" className="btn btn-primary" disabled={!file || uploading} aria-busy={uploading}>
              {uploading ? 'Processing…' : 'Upload syllabus'}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setShowUpload(false)} disabled={uploading}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function SyllabusGradingBreakdown({ model }: { model: SyllabusGradeModel | null }) {
  if (!model) return null;
  const weighted: SyllabusCategory[] = model.categories.filter((c) => c.weight !== null);
  if (weighted.length === 0) return null;
  const total = weighted.reduce((sum, c) => sum + (c.weight ?? 0), 0);
  return (
    <div className="real-course-table" role="table" aria-label="Grading breakdown">
      <h4 className="card-heading">Grading breakdown</h4>
      {weighted.map((c) => (
        <div className="real-course-row" role="row" key={c.name}>
          <span role="cell">{c.name}</span>
          <span role="cell">{formatPercent(c.weight)}</span>
          <span role="cell">{c.count === null ? 'Number of assessments: Unknown' : `${c.count} assessments`}</span>
          <span role="cell" className="grade-evidence-note">
            {c.evidence?.page ? `Source: page ${c.evidence.page}` : ''}
          </span>
        </div>
      ))}
      <div className="real-course-row" role="row">
        <span role="cell"><strong>Total</strong></span>
        <span role="cell"><strong>{total}%</strong></span>
      </div>
    </div>
  );
}

function SyllabusRulesList({
  model,
  onIgnoreRule,
  busy,
}: {
  model: SyllabusGradeModel | null;
  onIgnoreRule: ((ruleIndex: number, warningIndices: number[]) => void) | undefined;
  busy: boolean;
}) {
  if (!model || model.rules.length === 0) return null;
  return (
    <div className="grade-rules-list">
      <h4 className="card-heading">Special grading rules</h4>
      {model.rules.map((rule, index) => {
        const isDeterministic = rule.rule_type === 'replacement' && rule.source && rule.target;
        const relatedWarningIndices = model.warnings
          .map((w, wi) => ({ w, wi }))
          .filter(({ w }) => w.type === 'possible_curve' || w.type === 'ambiguous_rule')
          .map(({ wi }) => wi);
        return (
          <div className="grade-rule-card" key={index}>
            <p className="grade-rule-title">{ruleTypeLabel(rule.rule_type)}</p>
            <p>{rule.description}</p>
            {rule.evidence?.page && <p className="grade-evidence-note">Source: page {rule.evidence.page}</p>}
            {!isDeterministic && (
              <p className="empty-state">The syllabus does not provide enough information for CampusIQ to calculate this rule.</p>
            )}
            {!isDeterministic && onIgnoreRule && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy}
                onClick={() => onIgnoreRule(index, relatedWarningIndices)}
              >
                Ignore this rule for What-If calculations
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SyllabusFindingsList({ findings }: { findings: SyllabusFinding[] }) {
  const relevant = findings.filter((f) => f.severity !== 'valid');
  if (relevant.length === 0) return null;
  return (
    <ul className="grade-findings-list" aria-label="Grading review notes">
      {relevant.map((finding, i) => (
        <li key={i} data-finding-code={finding.code} className={`grade-finding grade-finding--${finding.severity}`}>
          {findingCopy(finding)}
        </li>
      ))}
    </ul>
  );
}
