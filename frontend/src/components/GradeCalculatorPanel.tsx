import { useEffect, useMemo, useState } from 'react';
import { fetchPlannedCourses, fetchTerms } from '../api/planning';
import type { PlannedCourse, PlanningTerm } from '../lib/termPlanning.mjs';
import type { AcademicCourse } from '../types/studentIntelligenceProfile';
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
//
// Codes handled below in FINDING_TEMPLATES are deliberately absent here:
// their backend `message` already carries the one distinguishing detail
// (which rule, which two letters, which category) that tells two findings
// of the same code apart, and this flat map has no way to say that.
const FINDING_COPY: Record<string, string> = {
  possible_curve: 'Your syllabus says grades may be curved, but it does not provide a formula.',
  unknown_weight: "We couldn't determine this category's weight.",
  unknown_assessment_count: "The syllabus doesn't say exactly how many assessments are in this category.",
  ambiguous_rule: "We found a grading rule, but couldn't determine exactly how it works.",
  missing_grade_scale: "This syllabus doesn't specify a letter-grade scale.",
  category_weight_validation: 'The category weights in this syllabus may not add up to 100%.',
  grading_method_unknown: "We couldn't determine how this course is graded.",
  missing_claim_evidence: "We found this value, but couldn't confirm it against the syllabus text.",
  partial_claim_evidence: "We found this value, but couldn't confirm it against the syllabus text.",
  claim_evidence_value_mismatch: 'This value may not match what the syllabus actually says.',
  claim_evidence_consistency_unverifiable: "We couldn't automatically confirm this value against the syllabus text.",
  evidence_page_out_of_range: "This citation doesn't match the syllabus pages we reviewed.",
};

// Per-code templates that parse the backend's specific `message` (which
// already names the rule/letters/category involved) into short,
// friendly text -- instead of the one-generic-sentence-per-code approach
// above, which made every occurrence of a code read identically even when
// each one was about a different rule or a different pair of letters.
const FINDING_TEMPLATES: Record<string, (finding: SyllabusFinding) => string | null> = {
  non_deterministic_grading_rule: (finding) => {
    const m = /^(\S+) rule is not structured precisely enough to apply deterministically: (.*)$/.exec(finding.message);
    if (!m) return null;
    const label = ruleTypeLabel(m[1] as SyllabusRule['rule_type']).toLowerCase();
    return `CampusIQ can't calculate this ${label} rule automatically: ${m[2]}`;
  },
  overlapping_grade_thresholds: (finding) => {
    const m = /^thresholds '(.+?)' \(([\d.]+)-([\d.]+)\) and '(.+?)' \(([\d.]+)-([\d.]+)\) overlap$/.exec(finding.message);
    if (!m) return null;
    return `Letter grades ${m[1]} and ${m[4]} have overlapping cutoffs: ${m[1]} is ${m[2]}–${m[3]}, ${m[4]} is ${m[5]}–${m[6]}.`;
  },
  grade_threshold_ordering_anomaly: (finding) => {
    const m = /^threshold '(.+?)' has a lower minimum \(([\d.]+)\) than the generally-lower grade '(.+?)' \(([\d.]+)\)$/.exec(finding.message);
    if (!m) return null;
    return `${m[1]} (${m[2]}) has a lower cutoff than ${m[3]} (${m[4]}), which is usually the lower grade.`;
  },
  unresolved_rule_reference: (finding) => {
    const m = /^rule (?:source|target)='(.+?)' does not match any known category or assessment$/.exec(finding.message);
    if (!m) return null;
    return `A grading rule references "${m[1]}", but CampusIQ couldn't match it to a category or assessment.`;
  },
  unresolved_assessment_category_reference: (finding) => {
    const m = /^assessment '(.+?)' references category '(.+?)', which is not a known category$/.exec(finding.message);
    if (!m) return null;
    return `"${m[1]}" references a category ("${m[2]}") CampusIQ couldn't find in this syllabus.`;
  },
  duplicate_category: (finding) => {
    if (!finding.field) return null;
    return `Multiple categories may be the same ("${finding.field}") — check for a duplicate.`;
  },
  duplicate_assessment: (finding) => {
    if (!finding.field) return null;
    return `Multiple assessments may be the same ("${finding.field.split(':')[0]}") — check for a duplicate.`;
  },
};

function findingCopy(finding: SyllabusFinding): string {
  const templated = FINDING_TEMPLATES[finding.code]?.(finding);
  if (templated) return templated;
  return FINDING_COPY[finding.code] ?? finding.message;
}

// Mirrors the backend's _normalize_name (reconciliation.py): lowercase,
// collapsed whitespace. Findings whose `field` is a normalized name
// (duplicate_category) are matched against category rows through this.
function normalizeName(name: string): string {
  return name.toLowerCase().split(/\s+/).filter(Boolean).join(' ');
}

type FindingWithKey = { finding: SyllabusFinding; key: number };

/**
 * Groups findings by where they should render inline: next to the rule
 * card they're about (`rule:{index}`), next to the category row they're
 * about (`category:{name}`), or `general` as a fallback for every finding
 * whose `field` doesn't identify a row this panel currently renders
 * (course-level findings, threshold findings -- thresholds have no
 * dedicated row in the review step -- and evidence-coverage findings).
 * `key` is the finding's index in the source array, used as a stable,
 * session-only dismiss key (see dismissedFindingKeys in
 * GradeCalculatorPanel).
 */
function groupFindingsByAnchor(
  findings: SyllabusFinding[],
  model: SyllabusGradeModel | null,
): Map<string, FindingWithKey[]> {
  const map = new Map<string, FindingWithKey[]>();
  findings.forEach((finding, key) => {
    let anchor = 'general';
    if (finding.code === 'non_deterministic_grading_rule') {
      const m = /^rules\[(\d+)\]$/.exec(finding.field ?? '');
      if (m) anchor = `rule:${m[1]}`;
    } else if (finding.code === 'duplicate_category' && finding.field && model) {
      const match = model.categories.find((c) => normalizeName(c.name) === finding.field);
      if (match) anchor = `category:${match.name}`;
    }
    const bucket = map.get(anchor);
    if (bucket) bucket.push({ finding, key });
    else map.set(anchor, [{ finding, key }]);
  });
  return map;
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

// Rule types that carry an informational grading policy -- a curve, a
// late-work / makeup rule, an extra-credit or catch-all "other" -- rather
// than a formula the calculator can execute. These feed the persistent
// "Professor's rules" panel next to the calculator. Deterministic
// replacement/drop rules are executed by the calculator itself and stay
// out of it; a malformed replacement/drop (missing source/target) is a
// broken deterministic rule, not a professor policy, so it's excluded too.
const PROFESSOR_RULE_TYPES: ReadonlySet<SyllabusRule['rule_type']> = new Set([
  'curve',
  'extra_credit',
  'late_work',
  'makeup',
  'other',
]);

// Reconciliation finding codes that became informational-only when PR #61
// moved them into NON_BLOCKING_WARNING_CODES: a correctly-extracted curve /
// late-work / makeup rule has no deterministic formula, but it's a fact to
// see while calculating, not an ambiguity to resolve. The backend still
// emits them for display; the calculator surfaces them in the Professor's
// rules panel, so they're filtered out of the "Needs your review" list.
const RULE_INFO_FINDING_CODES: ReadonlySet<string> = new Set([
  'non_deterministic_grading_rule',
  'possible_curve',
  'ambiguous_rule',
]);

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
  courses: AcademicCourse[];
  institutionName: string | null;
}

interface EligibleCourse {
  code: string;
  title: string | null;
}

export function GradeCalculatorPanel({ accessToken, courses, institutionName }: Props) {
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
  const [academicTerms, setAcademicTerms] = useState<PlanningTerm[]>([]);
  const [plannedCourses, setPlannedCourses] = useState<PlannedCourse[]>([]);
  const [academicDataLoaded, setAcademicDataLoaded] = useState(false);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Dismissed inline findings, session-only: NOT persisted anywhere (no API
  // call, no backend field). Keyed by the finding's index in its source
  // findings array, so it resets whenever that array is recreated -- a
  // fresh page load, or reselecting a calculator -- because a stale index
  // set is meaningless against a different or re-fetched findings array. If
  // this ever needs to survive reload, it needs a real backend field (see
  // the investigation: `findings` has no dismissed/acknowledged concept at
  // all today), not just re-reading this state.
  const [dismissedFindingKeys, setDismissedFindingKeys] = useState<Set<number>>(new Set());

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

  useEffect(() => {
    if (!accessToken || !showUpload) return;
    let cancelled = false;
    setAcademicDataLoaded(false);
    void Promise.all([
      fetchTerms({ slug: null, accessToken }),
      fetchPlannedCourses({ slug: null, accessToken }),
    ]).then(([termResult, plannedResult]) => {
      if (cancelled) return;
      setAcademicTerms(termResult.terms);
      setPlannedCourses(plannedResult.plannedCourses);
      setAcademicDataLoaded(true);
    });
    return () => { cancelled = true; };
  }, [accessToken, showUpload]);

  const eligibleCoursesByTerm = useMemo(() => {
    const byTerm = new Map<string, Map<string, EligibleCourse>>();
    const add = (termId: string | null, code: string, title: string | null) => {
      if (!termId || !code.trim()) return;
      const normalizedCode = code.trim().toUpperCase();
      const termCourses = byTerm.get(termId) ?? new Map<string, EligibleCourse>();
      const existing = termCourses.get(normalizedCode);
      termCourses.set(normalizedCode, {
        code: existing?.code ?? code.trim(),
        title: existing?.title ?? title,
      });
      byTerm.set(termId, termCourses);
    };
    courses.filter((course) => course.status === 'in_progress')
      .forEach((course) => add(course.term_id, course.course_code, course.title));
    plannedCourses.forEach((course) => add(course.term_id, course.course_code, course.title));
    return byTerm;
  }, [courses, plannedCourses]);

  const eligibleTerms = useMemo(() => {
    const inProgressTermIds = new Set(
      courses.filter((course) => course.status === 'in_progress').map((course) => course.term_id),
    );
    const byLabel = new Map<string, PlanningTerm>();
    for (const term of academicTerms) {
      if (term.id !== null && eligibleCoursesByTerm.has(term.id) && !byLabel.has(term.label)) {
        byLabel.set(term.label, term);
      }
    }
    return [...byLabel.values()].sort((a, b) => {
      const relevance = (term: PlanningTerm) => term.id && inProgressTermIds.has(term.id) ? 0 : term.is_upcoming ? 1 : 2;
      const relevanceDelta = relevance(a) - relevance(b);
      if (relevanceDelta !== 0) return relevanceDelta;
      if (a.year !== b.year) return b.year - a.year;
      return (b.sequence ?? 0) - (a.sequence ?? 0) || a.label.localeCompare(b.label);
    });
  }, [academicTerms, courses, eligibleCoursesByTerm]);

  const selectedTerm = eligibleTerms.find((term) => term.label === fields.term) ?? null;
  const selectedTermCourses = useMemo(() => {
    if (!selectedTerm?.id) return [];
    return [...(eligibleCoursesByTerm.get(selectedTerm.id)?.values() ?? [])]
      .sort((a, b) => a.code.localeCompare(b.code));
  }, [eligibleCoursesByTerm, selectedTerm]);

  useEffect(() => {
    if (!showUpload || fields.term || eligibleTerms.length === 0) return;
    const inProgressTermIds = new Set(
      courses.filter((course) => course.status === 'in_progress').map((course) => course.term_id),
    );
    const defaultTerm = eligibleTerms.find((term) => term.id && inProgressTermIds.has(term.id))
      ?? eligibleTerms.find((term) => term.is_upcoming)
      ?? eligibleTerms[0];
    setFields((current) => ({ ...current, term: defaultTerm.label, courseCode: '' }));
  }, [courses, eligibleTerms, fields.term, showUpload]);

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
        institution: institutionName || fields.institution || undefined,
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

  // Reselecting a calculator (or the initial load of one) starts review
  // findings fresh -- dismissal is session-only and must not leak between
  // calculators or survive a reopen. See dismissedFindingKeys above.
  useEffect(() => {
    setDismissedFindingKeys(new Set());
  }, [selectedProfileId]);

  // Rule-informational findings (curve / late-work / makeup) are shown in
  // the Professor's rules panel, not here -- filter them out before they
  // reach the review list. Cutoff-overlap and unknown-assessment-count
  // findings stay.
  const reviewFindings = useMemo(
    () =>
      ((detail?.confirmed_reconciliation ?? detail?.reconciliation)?.findings ?? []).filter(
        (finding) => !RULE_INFO_FINDING_CODES.has(finding.code),
      ),
    [detail],
  );
  const findingsByAnchor = useMemo(
    () => groupFindingsByAnchor(reviewFindings, detail?.extracted_grade_model ?? null),
    [reviewFindings, detail],
  );

  function handleDismissFinding(key: number) {
    setDismissedFindingKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  }

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
                <GeneralFindings
                  findings={findingsByAnchor.get('general') ?? []}
                  dismissedFindingKeys={dismissedFindingKeys}
                  onDismissFinding={handleDismissFinding}
                />
                <SyllabusGradingBreakdown
                  model={detail.extracted_grade_model}
                  findingsByAnchor={findingsByAnchor}
                  dismissedFindingKeys={dismissedFindingKeys}
                  onDismissFinding={handleDismissFinding}
                />
                <SyllabusRulesList
                  model={detail.extracted_grade_model}
                  onIgnoreRule={handleIgnoreRule}
                  busy={busy}
                  findingsByAnchor={findingsByAnchor}
                  dismissedFindingKeys={dismissedFindingKeys}
                  onDismissFinding={handleDismissFinding}
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
                <SyllabusRulesList model={detail.confirmed_grade_model} onIgnoreRule={undefined} busy={busy} findingsByAnchor={EMPTY_FINDINGS_BY_ANCHOR} />
                <button type="button" className="btn btn-primary" onClick={handleConfirm} disabled={busy} aria-busy={busy}>
                  {busy ? 'Confirming…' : 'Confirm'}
                </button>
              </div>
            )}

            {detail.calculator_ready && (
              <>
                <ProfessorsRules model={detail.confirmed_grade_model ?? detail.extracted_grade_model} />

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
          <label className="form-label" htmlFor="syllabus-term">Term</label>
          <select
            id="syllabus-term"
            className="form-input"
            value={fields.term}
            onChange={(e) => setFields((f) => ({ ...f, term: e.target.value, courseCode: '' }))}
            disabled={!academicDataLoaded || eligibleTerms.length === 0}
          >
            <option value="">Select a term</option>
            {eligibleTerms.map((term) => <option key={term.key} value={term.label}>{term.label}</option>)}
          </select>
          <label className="form-label" htmlFor="syllabus-course-code">Course</label>
          <select
            id="syllabus-course-code"
            className="form-input"
            value={fields.courseCode}
            onChange={(e) => setFields((f) => ({ ...f, courseCode: e.target.value }))}
            disabled={!selectedTerm || selectedTermCourses.length === 0}
          >
            <option value="">Select a course</option>
            {selectedTermCourses.map((course) => (
              <option key={course.code.toUpperCase()} value={course.code}>
                {course.code}{course.title ? ` — ${course.title}` : ''}
              </option>
            ))}
          </select>
          {academicDataLoaded && eligibleTerms.length === 0 && (
            <p className="empty-state">No current or planned courses are available. Add your courses in Academic before uploading a syllabus.</p>
          )}
          {selectedTerm && selectedTermCourses.length === 0 && (
            <p className="empty-state">No courses are available for this term.</p>
          )}

          {uploading && (
            <p role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" /> Reading syllabus and finding grading information…
            </p>
          )}
          {uploadError && <p className="login-error" role="alert">{uploadError}</p>}

          <div className="grade-entry-actions">
            <button type="submit" className="btn btn-primary" disabled={!file || !selectedTerm || !fields.courseCode || uploading} aria-busy={uploading}>
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

const EMPTY_FINDINGS_BY_ANCHOR: Map<string, FindingWithKey[]> = new Map();

/**
 * One finding, rendered small and inline where it's relevant -- not as a
 * card in a separate flat list. Styled after the .rv-field/.rv-glyph
 * provenance pattern (review/FieldRow.tsx): a small marker column plus
 * compact text. Dismiss reuses the .dash-notice-dismiss "x" pattern
 * (DashboardSuccessNotice.tsx), scaled down for inline use.
 */
function InlineFinding({
  finding,
  onDismiss,
}: {
  finding: SyllabusFinding;
  onDismiss: () => void;
}) {
  return (
    <p className={`grade-inline-finding grade-inline-finding--${finding.severity}`} data-finding-code={finding.code}>
      <span className="grade-inline-finding-glyph" aria-hidden="true">
        {finding.severity === 'error' ? '!' : '·'}
      </span>
      <span className="grade-inline-finding-text">{findingCopy(finding)}</span>
      <button
        type="button"
        className="grade-inline-finding-dismiss"
        onClick={onDismiss}
        aria-label="Dismiss this finding"
      >
        ×
      </button>
    </p>
  );
}

function InlineFindings({
  findings,
  dismissedFindingKeys,
  onDismissFinding,
}: {
  findings: FindingWithKey[];
  dismissedFindingKeys: Set<number>;
  onDismissFinding: (key: number) => void;
}) {
  const visible = findings.filter(({ finding, key }) => finding.severity !== 'valid' && !dismissedFindingKeys.has(key));
  if (visible.length === 0) return null;
  return (
    <div className="grade-inline-findings">
      {visible.map(({ finding, key }) => (
        <InlineFinding key={key} finding={finding} onDismiss={() => onDismissFinding(key)} />
      ))}
    </div>
  );
}

/**
 * Fallback for findings whose `field` doesn't identify a row this panel
 * currently renders (course-level findings like grading_method_unknown,
 * threshold findings -- there's no per-threshold row in the review step --
 * and evidence-coverage findings). Same inline/small-font/dismiss
 * treatment as InlineFindings, just grouped at the top of the review card
 * instead of anchored to a specific row.
 */
function GeneralFindings({
  findings,
  dismissedFindingKeys,
  onDismissFinding,
}: {
  findings: FindingWithKey[];
  dismissedFindingKeys: Set<number>;
  onDismissFinding: (key: number) => void;
}) {
  const visible = findings.filter(({ finding, key }) => finding.severity !== 'valid' && !dismissedFindingKeys.has(key));
  if (visible.length === 0) return null;
  return (
    <div className="grade-inline-findings grade-inline-findings--general" aria-label="Grading review notes">
      {visible.map(({ finding, key }) => (
        <InlineFinding key={key} finding={finding} onDismiss={() => onDismissFinding(key)} />
      ))}
    </div>
  );
}

function SyllabusGradingBreakdown({
  model,
  findingsByAnchor = EMPTY_FINDINGS_BY_ANCHOR,
  dismissedFindingKeys = new Set(),
  onDismissFinding = () => {},
}: {
  model: SyllabusGradeModel | null;
  findingsByAnchor?: Map<string, FindingWithKey[]>;
  dismissedFindingKeys?: Set<number>;
  onDismissFinding?: (key: number) => void;
}) {
  if (!model) return null;
  const weighted: SyllabusCategory[] = model.categories.filter((c) => c.weight !== null);
  if (weighted.length === 0) return null;
  const total = weighted.reduce((sum, c) => sum + (c.weight ?? 0), 0);
  return (
    <div className="real-course-table" role="table" aria-label="Grading breakdown">
      <h4 className="card-heading">Grading breakdown</h4>
      {weighted.map((c) => (
        <div className="grade-breakdown-row" key={c.name}>
          <div className="real-course-row" role="row">
            <span role="cell">{c.name}</span>
            <span role="cell">{formatPercent(c.weight)}</span>
            <span role="cell">{c.count === null ? 'Number of assessments: Unknown' : `${c.count} assessments`}</span>
            <span role="cell" className="grade-evidence-note">
              {c.evidence?.page ? `Source: page ${c.evidence.page}` : ''}
            </span>
          </div>
          <InlineFindings
            findings={findingsByAnchor.get(`category:${c.name}`) ?? []}
            dismissedFindingKeys={dismissedFindingKeys}
            onDismissFinding={onDismissFinding}
          />
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
  findingsByAnchor = EMPTY_FINDINGS_BY_ANCHOR,
  dismissedFindingKeys = new Set(),
  onDismissFinding = () => {},
}: {
  model: SyllabusGradeModel | null;
  onIgnoreRule: ((ruleIndex: number, warningIndices: number[]) => void) | undefined;
  busy: boolean;
  findingsByAnchor?: Map<string, FindingWithKey[]>;
  dismissedFindingKeys?: Set<number>;
  onDismissFinding?: (key: number) => void;
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
            <InlineFindings
              findings={findingsByAnchor.get(`rule:${index}`) ?? []}
              dismissedFindingKeys={dismissedFindingKeys}
              onDismissFinding={onDismissFinding}
            />
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

/**
 * Persistent "Professor's rules" reference panel, shown beside the What-If
 * calculator. Renders the informational grading policies (curve, late
 * work, makeup, extra credit, other) straight from the grade model's
 * rules[] -- NOT from the reconciliation findings array. Per the
 * syllabus-review redesign (planning-docs/syllabus-review-redesign-spec.md
 * §2C): these are facts to see while running scenarios, never things to
 * resolve or dismiss, so there's no dismiss control and no blocking
 * behavior. Deterministic replacement/drop rules are executed by the
 * calculator and reported in its own output, so they're not repeated here.
 */
function ProfessorsRules({ model }: { model: SyllabusGradeModel | null }) {
  const rules = (model?.rules ?? []).filter((rule) => PROFESSOR_RULE_TYPES.has(rule.rule_type));
  if (rules.length === 0) return null;
  return (
    <div className="card professors-rules" data-testid="professors-rules" aria-label="Professor's rules">
      <h3 className="card-heading">Professor's rules</h3>
      {rules.map((rule, index) => (
        <div className="professors-rule" key={index}>
          <p className="professors-rule-type">{ruleTypeLabel(rule.rule_type)}</p>
          <p className="professors-rule-text">{rule.description}</p>
          {rule.evidence?.page && <p className="grade-evidence-note">Source: page {rule.evidence.page}</p>}
        </div>
      ))}
    </div>
  );
}
