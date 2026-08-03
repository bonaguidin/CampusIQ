import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import './GuidedTour.css';

// ── Types ────────────────────────────────────────────────────────────────────

export type TourSection = 'overview' | 'academic' | 'career';

interface TourStep {
  /** Dashboard tab this step walks the viewer to. */
  section: TourSection;
  /** Small mono eyebrow — the tab / context label. */
  eyebrow: string;
  /** Serif display headline. */
  title: string;
  /** Body copy explaining what lives on this tab. */
  body: ReactNode;
}

// ── Tour Script ──────────────────────────────────────────────────────────────
// Weighted toward Career (FIT/GAP/SHIFT) — the core of the product — and ends
// there so the demo lands on the strongest feature.

const TOUR_STEPS: TourStep[] = [
  {
    section: 'overview',
    eyebrow: 'Welcome',
    title: 'Welcome to GradusIQ',
    body: (
      <>
        Your AI career and academic companion. This quick tour walks through the
        three main areas of a student profile. Take it now, or{' '}
        <strong>skip</strong> and reopen it anytime from the{' '}
        <strong>?</strong> button up top.
      </>
    ),
  },
  {
    section: 'overview',
    eyebrow: 'Overview',
    title: 'Your snapshot at a glance',
    body: (
      <>
        Name, GPA, major, university and expected graduation — plus{' '}
        <strong>Feature Readiness</strong> and{' '}
        <strong>Profile Completeness</strong> so you know what to fill in next.
        At the top, chat with the assistant about your career and academic
        details.
      </>
    ),
  },
  {
    section: 'academic',
    eyebrow: 'Academic',
    title: 'Your academic record',
    body: (
      <>
        Grades in each class and your professors&rsquo; comments on your
        coursework. <strong>AI Analysis</strong> reads the grades and comments
        for patterns, and <strong>Exam Topics</strong> breaks performance down by
        subject.
      </>
    ),
  },
  {
    section: 'career',
    eyebrow: 'Career · the core',
    title: 'GAP, FIT & SHIFT',
    body: (
      <>
        The heart of GradusIQ. <strong>GAP</strong> is a readiness check against
        your target roles — your score, what&rsquo;s missing, and what to do
        next. <strong>FIT</strong> shows how well your profile matches each
        role and why. <strong>SHIFT</strong> shows how those roles are evolving
        and adjacent paths worth exploring. Below sits your own data —
        experience, projects, certifications, interests and target roles.
      </>
    ),
  },
];

// ── Component ────────────────────────────────────────────────────────────────

interface GuidedTourProps {
  /** Switch the underlying dashboard tab as the tour advances. */
  onNavigate: (section: TourSection) => void;
  /** Called when the tour ends. `completed` is true only on Finish. */
  onClose: (completed: boolean) => void;
}

export function GuidedTour({ onNavigate, onClose }: GuidedTourProps) {
  const [index, setIndex] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);

  const step = TOUR_STEPS[index];
  const isFirst = index === 0;
  const isLast = index === TOUR_STEPS.length - 1;

  // Drive the underlying tab whenever the step changes, and move focus to the
  // card so keyboard users follow along.
  useEffect(() => {
    onNavigate(step.section);
    cardRef.current?.focus();
  }, [index, step.section, onNavigate]);

  // Escape skips the tour.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  function next() {
    if (isLast) {
      onClose(true);
    } else {
      setIndex((i) => i + 1);
    }
  }

  function back() {
    setIndex((i) => Math.max(0, i - 1));
  }

  return (
    <div className="tour-overlay" role="presentation">
      <div
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        tabIndex={-1}
        ref={cardRef}
      >
        <div className="tour-eyebrow">{step.eyebrow}</div>
        <h2 className="tour-title" id="tour-title">
          {step.title}
        </h2>
        <p className="tour-body" id="tour-body">
          {step.body}
        </p>

        <div className="tour-footer">
          {/* Progress dots */}
          <div className="tour-dots" aria-hidden="true">
            {TOUR_STEPS.map((_, i) => (
              <span
                key={i}
                className={`tour-dot${i === index ? ' tour-dot--active' : ''}`}
              />
            ))}
          </div>

          <div className="tour-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm tour-skip"
              onClick={() => onClose(false)}
            >
              Skip tour
            </button>
            {!isFirst && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={back}
              >
                Back
              </button>
            )}
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={next}
            >
              {isLast ? 'Finish' : 'Next'}
            </button>
          </div>
        </div>

        <div className="tour-step-count" aria-live="polite">
          Step {index + 1} of {TOUR_STEPS.length}
        </div>
      </div>
    </div>
  );
}
