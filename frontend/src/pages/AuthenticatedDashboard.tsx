import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { ChatPanel } from '../components/ChatPanel';
import { DashboardSuccessNotice } from '../components/DashboardSuccessNotice';
import { FitAnalysisPanel } from '../components/FitAnalysisPanel';
import { GapAnalysisPanel } from '../components/GapAnalysisPanel';
import { ShiftAnalysisPanel } from '../components/ShiftAnalysisPanel';
import { TermPlanner } from '../components/TermPlanner';
import { CareerProfile } from '../components/career/CareerProfile';
import { ProfileCompletionContext, type ProfileCompletionRequest } from '../components/profile/ProfileCompletionContext';
import { ProfileCompletionModal } from '../components/profile/ProfileCompletionModal';
import { buildDashboardViewModel } from '../data/dashboardViewModel';

type NavSection = 'overview' | 'academic' | 'career';

const NAV_ITEMS: Array<{ key: NavSection; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'academic', label: 'Academic' },
  { key: 'career', label: 'Career' },
];

export function AuthenticatedDashboard() {
  const { studentAccount, signOutSession, session } = useAuth();
  // The term view reads planned_courses and the catalog through the session
  // bearer token. Absent one, the section falls back to the flat course list
  // below rather than rendering an empty planner.
  const accessToken = session?.access_token ?? null;
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState<NavSection>('overview');
  const [railOpen, setRailOpen] = useState(false);
  const [profileRequest, setProfileRequest] = useState<ProfileCompletionRequest | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);
  const canonical = studentAccount.profile?.intelligence_profile;
  const dashboard = useMemo(
    () => (canonical ? buildDashboardViewModel(canonical) : null),
    [canonical],
  );

  if (!dashboard) return null;

  const displayName = dashboard.name ?? 'Student';
  const major = dashboard.majorCurrent ?? dashboard.majorIntended;
  const readiness = dashboard.completeness.overall;

  async function handleLogout() {
    await signOutSession();
    void navigate('/login');
  }

  function navigateTo(section: NavSection) {
    setActiveSection(section);
    setRailOpen(false);
  }

  return (
    <ProfileCompletionContext.Provider value={setProfileRequest}><div className="shell" data-dashboard-source="authenticated" data-profile-modal-open={profileRequest ? 'true' : undefined}>
      {railOpen && <div className="rail-overlay" onClick={() => setRailOpen(false)} aria-hidden="true" />}
      <aside className={`rail${railOpen ? ' rail--open' : ''}`} aria-label="Dashboard navigation">
        <div className="rail-identity">
          <div className="rail-monogram" aria-hidden="true">{dashboard.initials || 'ST'}</div>
          <div className="rail-name">{displayName}</div>
          <div className="rail-meta">
            <span>{dashboard.classification ?? 'Student'}</span>
            <span className="rail-dot" aria-hidden="true">·</span>
            <span className="rail-gpa">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span>
          </div>
        </div>
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
        <div className="readiness-rail real-readiness">
          <div className="readiness-heading">Readiness</div>
          <div className="readiness-overall">
            <span className="readiness-state">{readiness}</span>
            <span className="readiness-pct-label">overall profile</span>
          </div>
          <div className="readiness-marks">
            <div className={`readiness-mark${dashboard.completeness.academics.ready_for_academic_features ? ' readiness-mark--ready' : ''}`}>
              <span className="readiness-mark-name">Academic</span>
              <span className="readiness-mark-status">{dashboard.completeness.academics.ready_for_academic_features ? 'Ready' : 'Incomplete'}</span>
            </div>
            <div className={`readiness-mark${dashboard.completeness.career.ready_for_career_features ? ' readiness-mark--ready' : ''}`}>
              <span className="readiness-mark-name">Career</span>
              <span className="readiness-mark-status">{dashboard.completeness.career.ready_for_career_features ? 'Ready' : 'Incomplete'}</span>
            </div>
          </div>
        </div>
        <div className="rail-footer">
          <button type="button" className="rail-logout" onClick={() => { void handleLogout(); }}>Logout</button>
        </div>
      </aside>

      <div className="stage">
        <header className="topbar">
          <button type="button" className="topbar-menu" onClick={() => setRailOpen(true)} aria-label="Open navigation" aria-expanded={railOpen}>
            <span className="topbar-menu-icon" aria-hidden="true"><span /></span>
          </button>
          <h2 className="topbar-title">{NAV_ITEMS.find((item) => item.key === activeSection)?.label}</h2>
        </header>
        <main className="stage-main">
          <div className="stage-inner">
            {/* Above the section content and inside the normal flow: it is an
                acknowledgement, not an interruption, so nothing overlays,
                blocks, or steals focus. Outside the section switch so changing
                tabs does not re-mount (and re-announce) it. */}
            <DashboardSuccessNotice />

            {activeSection === 'overview' && (
              <div className="stage-section">
                <ChatPanel />
                <div className="overview-header">
                  <h1 className="overview-name">{displayName}</h1>
                  <div className="overview-vitals">
                    <span>{major ?? 'Major not provided'}</span>
                    <span className="overview-vitals-sep" aria-hidden="true">·</span>
                    <span>{dashboard.institutionName ?? 'Institution not provided'}</span>
                  </div>
                </div>
                <div className="overview-stats">
                  <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                  <div className="overview-stat"><span className="overview-stat-value">{dashboard.courses.length}</span><span className="overview-stat-label">Confirmed Courses</span></div>
                  <div className="overview-stat"><span className="overview-stat-value readiness-state">{readiness}</span><span className="overview-stat-label">Profile Status</span></div>
                </div>
                <div className="overview-grid">
                  <section className="overview-block">
                    <div className="overview-block-title">Academic readiness</div>
                    <p>{dashboard.completeness.academics.transcript_data_present ? `${String(dashboard.courses.length)} confirmed courses across ${String(dashboard.terms.length)} terms.` : 'No confirmed transcript data yet.'}</p>
                    {!dashboard.completeness.academics.transcript_data_present && <Link to="/transcript" className="btn btn-primary btn-sm">Upload transcript</Link>}
                  </section>
                  <section className="overview-block">
                    <div className="overview-block-title">Career readiness</div>
                    <p>{dashboard.career.confirmed ? `${String(dashboard.career.target_roles.length)} target roles and ${String(dashboard.career.skills.technical.length + dashboard.career.skills.soft.length)} skills confirmed.` : 'No confirmed career profile yet.'}</p>
                    {!dashboard.career.confirmed && <Link to="/resume" className="btn btn-primary btn-sm">Upload resume</Link>}
                  </section>
                </div>
              </div>
            )}

            {activeSection === 'academic' && (
              <div className="stage-section">
                <h2 className="academic-section-heading">Academic Record</h2>
                {!dashboard.courses.length ? (
                  <div className="real-empty"><h3>Add your academic history</h3><p>Upload and confirm your transcript to see courses and GPA here.</p><Link to="/transcript" className="btn btn-primary btn-sm">Upload transcript</Link></div>
                ) : (
                  <>
                    <div className="overview-stats">
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.projectedGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Projected GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.earnedHours}</span><span className="overview-stat-label">Earned Hours</span></div>
                    </div>
                    {/* The flat all-courses list is replaced by the term view:
                        one term at a time, chosen from a dropdown that opens on
                        the upcoming term. The GPA/hours stats above stay
                        cumulative and unfiltered -- they are the whole record,
                        and scoping them to one term would quietly change what
                        "Official GPA" means. */}
                    {accessToken
                      ? <TermPlanner accessToken={accessToken} courses={dashboard.courses} />
                      : (
                        <div className="real-course-table" role="table" aria-label="Confirmed courses">
                          {dashboard.courses.map((course) => (
                            <div className="real-course-row" role="row" key={course.id}>
                              <span role="cell"><strong>{course.course_code}</strong><small>{course.title ?? 'Untitled course'}</small></span>
                              <span role="cell">{course.credit_hours} credits</span>
                              <span role="cell">{course.letter_grade ?? 'In progress'}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    {dashboard.repeatExclusions.length > 0 && <p className="real-note">{dashboard.repeatExclusions.length} course attempt(s) excluded from GPA by the institution repeat policy.</p>}
                  </>
                )}
              </div>
            )}

            {activeSection === 'career' && (
              <div className="stage-section">
                {!dashboard.career.confirmed ? (
                  <>
                    <h2 className="career-section-heading">Career Profile</h2>
                    <div className="real-empty"><h3>Build your career profile</h3><p>Upload and confirm your resume before career facts appear here.</p><Link to="/resume" className="btn btn-primary btn-sm">Upload resume</Link></div>
                  </>
                ) : (
                  <>
                    {/* Analyses first, profile second -- matching the demo
                        dashboard's Career tab, which already orders it this
                        way. The three panels are unchanged.

                        An earlier revision put the profile on top so the tab
                        would not open on three bare "Run analysis" buttons.
                        Each panel now carries its own title ("Readiness Check
                        (GAP)" and so on), so the tab still says what it is
                        without a section heading standing in for them.

                        "Career Profile" travels DOWN with the profile rather
                        than staying at the top: it describes the record, not
                        the analyses, and CareerSummary deliberately renders no
                        heading of its own on the grounds that this <h2> labels
                        it. Leaving it above the panels broke that. Its
                        existing border-bottom also supplies the division
                        between the two halves, which is why
                        .career-profile-block draws no rule of its own. */}
                    <GapAnalysisPanel />
                    <FitAnalysisPanel />
                    <ShiftAnalysisPanel />
                    <div className="career-profile-block">
                      <h2 className="career-section-heading">Career Profile</h2>
                      <CareerProfile career={dashboard.career} />
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
      {profileSaved && <div className="profile-save-notice" role="status">Profile saved. Your guidance now uses the latest details.<button type="button" aria-label="Dismiss profile saved message" onClick={() => setProfileSaved(false)}>×</button></div>}
      {profileRequest && <ProfileCompletionModal request={profileRequest} onClose={() => setProfileRequest(null)} onComplete={() => { setProfileRequest(null); setProfileSaved(true); }} />}
    </div></ProfileCompletionContext.Provider>
  );
}
