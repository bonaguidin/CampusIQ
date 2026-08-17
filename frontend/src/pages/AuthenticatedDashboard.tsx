import { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { analyzeFit, analyzeGap, analyzeShift } from '../api/analysis';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import { ChatPanel } from '../components/ChatPanel';
import { GuidedTour } from '../components/GuidedTour';
import { DashboardSuccessNotice } from '../components/DashboardSuccessNotice';
import { CareerSnapshotPanel } from '../components/CareerSnapshotPanel';
import { CourseDiscoveryPanel } from '../components/CourseDiscoveryPanel';
import { FitAnalysisPanel } from '../components/FitAnalysisPanel';
import { GapAnalysisPanel } from '../components/GapAnalysisPanel';
import { ShiftAnalysisPanel } from '../components/ShiftAnalysisPanel';
import { TermPlanner } from '../components/TermPlanner';
import { CareerProfile, type CareerFieldFocus } from '../components/career/CareerProfile';
import { ProfileChecklist } from '../components/career/ProfileChecklist';
import { ProfileCompletionContext, type ProfileFieldRequest } from '../components/profile/ProfileCompletionContext';
import { buildDashboardViewModel } from '../data/dashboardViewModel';
import { missingChecklistFields } from '../lib/profileChecklist';

type NavSection = 'overview' | 'academic' | 'career';

const NAV_ITEMS: Array<{ key: NavSection; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'academic', label: 'Academic' },
  { key: 'career', label: 'Career' },
];

type CareerSubTab = 'snapshot' | 'gap' | 'fit' | 'shift' | 'profile';

const CAREER_SUB_TABS: Array<{ key: CareerSubTab; label: string }> = [
  { key: 'snapshot', label: 'Snapshot' },
  { key: 'gap', label: 'Readiness' },
  { key: 'fit', label: 'Role Fit' },
  { key: 'shift', label: 'Trend Guidance' },
  { key: 'profile', label: 'Profile' },
];

// First-run tour is remembered per user (localStorage), so it auto-shows once
// and the "?" button replays it on demand. A profile field could hold this
// later; localStorage keeps it demo-simple with no migration.
const TOUR_SEEN_PREFIX = 'gradusiq_tour_seen_';

export function AuthenticatedDashboard() {
  const { studentAccount, signOutSession, session, slug, reloadStudentProfile } = useAuth();
  const tourSeenKey = session?.user?.id ? `${TOUR_SEEN_PREFIX}${session.user.id}` : null;
  const [tourOpen, setTourOpen] = useState<boolean>(() =>
    tourSeenKey ? localStorage.getItem(tourSeenKey) !== '1' : false,
  );
  // The term view reads planned_courses and the catalog through the session
  // bearer token. Absent one, the section falls back to the flat course list
  // below rather than rendering an empty planner.
  const accessToken = session?.access_token ?? null;
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState<NavSection>('overview');
  const [careerSubTab, setCareerSubTab] = useState<CareerSubTab>('snapshot');
  const [railOpen, setRailOpen] = useState(false);
  const [fieldFocus, setFieldFocus] = useState<CareerFieldFocus | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);
  // Lifted out of GapAnalysisPanel/FitAnalysisPanel/ShiftAnalysisPanel (each
  // still owns its own internal useAnalysisRun by default) so the Snapshot
  // sub-tab can read the exact same run state its full-panel sibling shows —
  // one run, reflected in both places, instead of a second independent fetch.
  const gapRun = useAnalysisRun(() => analyzeGap({ slug, accessToken }));
  const fitRun = useAnalysisRun(() => analyzeFit({ slug, accessToken }));
  const shiftRun = useAnalysisRun(() => analyzeShift({ slug, accessToken }));
  const canonical = studentAccount.profile?.intelligence_profile;
  const dashboard = useMemo(
    () => (canonical ? buildDashboardViewModel(canonical) : null),
    [canonical],
  );
  // Computed from the profile in hand, not from a skipped analysis: the
  // checklist has to be right before anything has been run, which is the whole
  // reason it is not built out of the panels' own missing_fields.
  const missingDetails = useMemo(
    () => (canonical ? missingChecklistFields(canonical) : []),
    [canonical],
  );

  /**
   * Send the student to the field, wherever they asked from.
   *
   * The one handler behind both entry points -- the checklist and a skipped
   * analysis's per-gap link -- so the two cannot answer the same request
   * differently. Switching to the Career tab first is what makes it work from
   * anywhere: the field only exists on that tab, and the request is worthless
   * if it lands on a section that does not render it.
   */
  const requestField = useCallback((request: ProfileFieldRequest) => {
    setActiveSection('career');
    // The field only renders inside CareerProfile, which now lives on the
    // Profile sub-tab rather than directly on the Career section — so a
    // skipped-analysis "Add this" link has to land the student there too,
    // not just on whichever Career sub-tab happened to be open.
    setCareerSubTab('profile');
    setRailOpen(false);
    // A new object every time, so asking twice for the same field works.
    setFieldFocus({ path: request.path, nonce: Date.now() });
  }, []);

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

  function handleTourClose() {
    setTourOpen(false);
    if (tourSeenKey) localStorage.setItem(tourSeenKey, '1');
  }

  // The tour ends on these; each marks the tour seen (via onClose) then routes.
  const tourEndActions = [
    { label: 'Add transcript', onClick: () => { void navigate('/transcript'); } },
    { label: 'Add resume', onClick: () => { void navigate('/resume'); } },
  ];

  return (
    <ProfileCompletionContext.Provider value={requestField}><div className="shell" data-dashboard-source="authenticated">
      {/* First-run onboarding tour — carousel that walks the tabs and ends on
          the transcript/resume upload CTAs. */}
      {tourOpen && (
        <GuidedTour
          onNavigate={setActiveSection}
          onClose={handleTourClose}
          endActions={tourEndActions}
        />
      )}
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
          <button
            type="button"
            className="topbar-help"
            onClick={() => setTourOpen(true)}
            aria-label="Replay the new-user tour"
            title="Take the tour"
          >
            ?
          </button>
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
                    {/* Above the sub-tab row, because it is the answer to the
                        question the analyses ask, and it applies regardless of
                        which sub-tab is open. Sticky rather than fixed: it
                        settles at the top of the scroll container and covers
                        nothing, which is the whole difference between it and
                        the modal it replaces. */}
                    <ProfileChecklist
                      missing={missingDetails}
                      onJump={(field, trigger) => { requestField({ path: field.path, trigger }); }}
                    />

                    {/* Second-level tab row, same pattern as AcademicSnapshot's
                        .academic-tabs (useState + role="tablist" + underline
                        indicator) -- kept as a sibling set of CSS classes
                        rather than sharing AcademicSnapshot's, since Academic
                        and Career are independent sections that happen to
                        agree on a visual language, not one shared component. */}
                    <div className="career-tabs" role="tablist" aria-label="Career views">
                      {CAREER_SUB_TABS.map(({ key, label }) => (
                        <button
                          key={key}
                          type="button"
                          role="tab"
                          id={`career-tab-${key}`}
                          aria-selected={careerSubTab === key}
                          aria-controls={`career-panel-${key}`}
                          className={`career-tab${careerSubTab === key ? ' career-tab--active' : ''}`}
                          onClick={() => setCareerSubTab(key)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>

                    {/* Every sub-tab's content stays mounted at all times and
                        is hidden with CSS rather than conditional JSX. GAP/
                        FIT/SHIFT each hold their run result in local state
                        (useAnalysisRun, lifted here for GAP/FIT/SHIFT so
                        Snapshot can share it) -- unmounting on tab switch
                        would throw that state away and force a re-run. */}
                    <div
                      role="tabpanel"
                      id="career-panel-snapshot"
                      aria-labelledby="career-tab-snapshot"
                      className={`career-subtab-panel${careerSubTab === 'snapshot' ? '' : ' career-subtab-panel--hidden'}`}
                    >
                      <CareerSnapshotPanel
                        gap={gapRun}
                        fit={fitRun}
                        shift={shiftRun}
                        onViewFull={setCareerSubTab}
                      />
                    </div>

                    <div
                      role="tabpanel"
                      id="career-panel-gap"
                      aria-labelledby="career-tab-gap"
                      className={`career-subtab-panel${careerSubTab === 'gap' ? '' : ' career-subtab-panel--hidden'}`}
                    >
                      <GapAnalysisPanel run={gapRun} />
                    </div>

                    <div
                      role="tabpanel"
                      id="career-panel-fit"
                      aria-labelledby="career-tab-fit"
                      className={`career-subtab-panel${careerSubTab === 'fit' ? '' : ' career-subtab-panel--hidden'}`}
                    >
                      <FitAnalysisPanel run={fitRun} />
                    </div>

                    <div
                      role="tabpanel"
                      id="career-panel-shift"
                      aria-labelledby="career-tab-shift"
                      className={`career-subtab-panel${careerSubTab === 'shift' ? '' : ' career-subtab-panel--hidden'}`}
                    >
                      <ShiftAnalysisPanel run={shiftRun} />
                    </div>

                    <div
                      role="tabpanel"
                      id="career-panel-profile"
                      aria-labelledby="career-tab-profile"
                      className={`career-subtab-panel${careerSubTab === 'profile' ? '' : ' career-subtab-panel--hidden'}`}
                    >
                      {/* Natural next action after fit/gaps/trends: given what
                          the student now understands about the role, which
                          actual courses at their school build toward it. Kept
                          grouped with CareerProfile on the Profile sub-tab, as
                          it was on the single-page layout. */}
                      <CourseDiscoveryPanel targetRoles={dashboard.career.target_roles} />
                      <div className="career-profile-block">
                        <h2 className="career-section-heading">Career Profile</h2>
                        {/* Graduation and the majors are academic record, not
                            career record, so they arrive as props rather than
                            being dug out of the profile by the career component.
                            All three were already on the view model and simply
                            unread -- nothing new is fetched to render them. */}
                        <CareerProfile
                          career={dashboard.career}
                          details={{
                            expectedGraduation: dashboard.expectedGraduation,
                            majorCurrent: dashboard.majorCurrent,
                            majorIntended: dashboard.majorIntended,
                          }}
                          // Each field PATCHes only its own keys and then
                          // reloads, so the page re-renders from the server's
                          // answer rather than from what the editor hoped it
                          // wrote. Without a token there is nothing to save
                          // with, so the profile stays read-only rather than
                          // growing buttons that cannot work.
                          editing={
                            accessToken
                              ? {
                                  accessToken,
                                  onSaved: async () => {
                                    await reloadStudentProfile();
                                    setProfileSaved(true);
                                  },
                                }
                              : null
                          }
                          focus={fieldFocus}
                        />
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
      {profileSaved && <div className="profile-save-notice" role="status">Profile saved. Your guidance now uses the latest details.<button type="button" aria-label="Dismiss profile saved message" onClick={() => setProfileSaved(false)}>×</button></div>}
    </div></ProfileCompletionContext.Provider>
  );
}
