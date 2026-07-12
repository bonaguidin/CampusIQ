import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { AcademicSnapshot } from '../components/AcademicSnapshot';
import { CareerPanel } from '../components/CareerPanel';
import { GapAnalysisPanel } from '../components/GapAnalysisPanel';
import { FitAnalysisPanel } from '../components/FitAnalysisPanel';
import { ShiftAnalysisPanel } from '../components/ShiftAnalysisPanel';
import type { ProfileCompleteness } from '../types/student';

// ── Types ──────────────────────────────────────────────────────────────────

type NavSection = 'overview' | 'academic' | 'career';

// ── Readiness Rail (sidebar signature element) ─────────────────────────────

const FEATURES = [
  { key: 'FIT'   as const, label: 'FIT',   subtitle: 'Role Explorer' },
  { key: 'GAP'   as const, label: 'GAP',   subtitle: 'Readiness Check' },
  { key: 'SHIFT' as const, label: 'SHIFT', subtitle: 'Trend Guidance' },
] as const;

function ReadinessRail({ completeness }: { completeness: ProfileCompleteness }) {
  const overall = Math.round((completeness.overall ?? 0) * 100);
  const academic = Math.round((completeness.academic ?? 0) * 100);
  const career   = Math.round((completeness.career   ?? 0) * 100);

  return (
    <div className="readiness-rail">
      <div className="readiness-heading">Readiness</div>

      <div className="readiness-overall">
        <span className="readiness-pct">{overall}%</span>
        <span className="readiness-pct-label">overall</span>
      </div>

      {/* FIT / GAP / SHIFT gauge — vertical line connects the dots */}
      <div className="readiness-marks">
        {FEATURES.map(({ key, label, subtitle }) => {
          const ready = completeness.by_feature?.[key]?.ready ?? false;
          return (
            <div
              key={key}
              className={`readiness-mark${ready ? ' readiness-mark--ready' : ''}`}
              aria-label={`${label}: ${ready ? 'ready' : 'incomplete'}`}
            >
              <span className="readiness-mark-name">{label}</span>
              <span className="readiness-mark-label">{subtitle}</span>
              <span className="readiness-mark-status">
                {ready ? 'Ready' : '—'}
              </span>
            </div>
          );
        })}
      </div>

      <div className="readiness-bars">
        {[
          { label: 'Academic', pct: academic },
          { label: 'Career',   pct: career   },
        ].map(({ label, pct }) => (
          <div key={label} className="readiness-bar-row">
            <div className="readiness-bar-header">
              <span className="readiness-bar-label">{label}</span>
              <span className="readiness-bar-pct">{pct}%</span>
            </div>
            <div
              className="readiness-bar-track"
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${label} completeness: ${pct}%`}
            >
              <div className="readiness-bar-fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Overview Section ───────────────────────────────────────────────────────

function OverviewSection() {
  const { profile, resetCareer } = useAuth();
  const [resetting, setResetting] = useState(false);

  if (!profile) return null;

  const { student, profile_completeness, courses } = profile;

  const gradYear = student.expected_graduation
    ? student.expected_graduation.slice(0, 4)
    : null;

  async function handleReset() {
    setResetting(true);
    try {
      await resetCareer();
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="stage-section">
      {/* Student identity — editorial serif */}
      <div className="overview-header">
        <h1 className="overview-name">{student.name}</h1>
        <div className="overview-vitals">
          <span>{student.major_current}</span>
          <span className="overview-vitals-sep" aria-hidden="true">·</span>
          <span>{student.institution}</span>
          {gradYear && (
            <>
              <span className="overview-vitals-sep" aria-hidden="true">·</span>
              <span>Expected {gradYear}</span>
            </>
          )}
        </div>
      </div>

      {/* Key stats in mono — the instrument feel */}
      <div className="overview-stats">
        <div className="overview-stat">
          <span className="overview-stat-value">
            {student.gpa_current.toFixed(2)}
          </span>
          <span className="overview-stat-label">GPA</span>
        </div>
        <div className="overview-stat">
          <span className="overview-stat-value">
            {courses.length}
          </span>
          <span className="overview-stat-label">Courses</span>
        </div>
        <div className="overview-stat">
          <span className="overview-stat-value">
            {student.classification}
          </span>
          <span className="overview-stat-label">Standing</span>
        </div>
      </div>

      {/* Two-column grid: feature status + completion */}
      <div className="overview-grid">
        <div className="overview-block">
          <div className="overview-block-title">Feature Readiness</div>
          <div className="overview-feature-list">
            {FEATURES.map(({ key, label, subtitle }) => {
              const ready = profile_completeness.by_feature?.[key]?.ready ?? false;
              return (
                <div key={key} className="overview-feature-row">
                  <span className="overview-feature-name">{label}</span>
                  <span className="overview-feature-desc">{subtitle}</span>
                  <span
                    className={`overview-feature-badge ${
                      ready
                        ? 'overview-feature-badge--ready'
                        : 'overview-feature-badge--pending'
                    }`}
                  >
                    {ready ? 'Ready' : 'Incomplete'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="overview-block">
          <div className="overview-block-title">Profile Completeness</div>
          <div className="overview-progress">
            {[
              { label: 'Academic', value: profile_completeness.academic ?? 0 },
              { label: 'Career',   value: profile_completeness.career   ?? 0 },
              { label: 'Overall',  value: profile_completeness.overall  ?? 0 },
            ].map(({ label, value }) => {
              const pct = Math.round(value * 100);
              return (
                <div key={label} className="overview-progress-row">
                  <div className="overview-progress-header">
                    <span className="overview-progress-label">{label}</span>
                    <span className="overview-progress-pct">{pct}%</span>
                  </div>
                  <div
                    className="overview-progress-track"
                    role="progressbar"
                    aria-valuenow={pct}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${label}: ${pct}%`}
                  >
                    <div
                      className="overview-progress-fill"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Demo reset */}
      <div className="overview-demo">
        <div className="overview-demo-title">Demo Controls</div>
        <p className="overview-demo-note">
          Reset career data to the original profile (clears any localStorage edits).
        </p>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => { void handleReset(); }}
          disabled={resetting}
          aria-busy={resetting}
        >
          {resetting ? 'Resetting…' : 'Reset to original'}
        </button>
      </div>
    </div>
  );
}

// ── Dashboard Page ─────────────────────────────────────────────────────────

const NAV_ITEMS: { key: NavSection; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'academic', label: 'Academic' },
  { key: 'career',   label: 'Career'   },
];

const SECTION_TITLES: Record<NavSection, string> = {
  overview: 'Overview',
  academic: 'Academic Record',
  career:   'Career Profile',
};

export function DashboardPage() {
  const { profile, logout } = useAuth();
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState<NavSection>('overview');
  const [railOpen, setRailOpen] = useState(false);

  // RequireAuth guarantees profile is non-null here
  if (!profile) return null;

  const { student, profile_completeness, career } = profile;

  // Derive two-letter monogram
  const initials = student.name
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  function handleLogout() {
    logout();
    void navigate('/login');
  }

  function navigateTo(section: NavSection) {
    setActiveSection(section);
    setRailOpen(false);
  }

  return (
    <div className="shell">
      {/* Mobile overlay — click to close rail */}
      {railOpen && (
        <div
          className="rail-overlay"
          onClick={() => setRailOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── Left Rail ── */}
      <aside
        className={`rail${railOpen ? ' rail--open' : ''}`}
        aria-label="Dashboard navigation"
      >
        {/* Identity */}
        <div className="rail-identity">
          <div className="rail-monogram" aria-hidden="true">
            {initials}
          </div>
          <div className="rail-name">{student.name}</div>
          <div className="rail-meta">
            <span>{student.classification}</span>
            <span className="rail-dot" aria-hidden="true">·</span>
            <span className="rail-gpa">{student.gpa_current.toFixed(2)}</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="rail-nav" aria-label="Dashboard sections">
          {NAV_ITEMS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`rail-item${activeSection === key ? ' rail-item--active' : ''}`}
              onClick={() => navigateTo(key)}
              aria-current={activeSection === key ? 'page' : undefined}
            >
              {label}
            </button>
          ))}
        </nav>

        {/* Readiness Rail — signature instrument element */}
        <ReadinessRail completeness={profile_completeness} />

        {/* Footer — logout */}
        <div className="rail-footer">
          <button
            type="button"
            className="rail-logout"
            onClick={handleLogout}
          >
            Logout
          </button>
        </div>
      </aside>

      {/* ── Main Stage ── */}
      <div className="stage">
        {/* Topbar */}
        <header className="topbar">
          <button
            type="button"
            className="topbar-menu"
            onClick={() => setRailOpen(true)}
            aria-label="Open navigation"
            aria-expanded={railOpen}
          >
            {/* Hamburger icon via CSS pseudo-elements + span */}
            <span className="topbar-menu-icon" aria-hidden="true">
              <span />
            </span>
          </button>
          <h2 className="topbar-title">{SECTION_TITLES[activeSection]}</h2>
        </header>

        {/* Content — keyed on activeSection so entrance animation replays */}
        <main className="stage-main">
          <div className="stage-inner">
            {activeSection === 'overview' && (
              <OverviewSection key="overview" />
            )}

            {activeSection === 'academic' && (
              <div key="academic" className="stage-section">
                <h2 className="academic-section-heading">Academic Record</h2>
                <AcademicSnapshot
                  courses={profile.courses}
                  enrollments={profile.enrollments}
                  assignments={profile.assignments}
                  submissions={profile.submissions}
                  examTopicTags={profile.examTopicTags}
                />
              </div>
            )}

            {activeSection === 'career' && (
              <div key="career" className="stage-section">
                <h2 className="career-section-heading">Career Profile</h2>
                {career !== null ? (
                  <>
                    <GapAnalysisPanel />
                    <FitAnalysisPanel />
                    <ShiftAnalysisPanel />
                    <CareerPanel career={career} />
                  </>
                ) : (
                  <p className="career-empty">
                    Career profile not set up yet — complete onboarding to unlock
                    this section.
                  </p>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
