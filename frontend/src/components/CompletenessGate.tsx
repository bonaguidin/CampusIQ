import type { ProfileCompleteness } from '../types/student';

interface CompletenessGateProps {
  completeness: ProfileCompleteness;
}

const FEATURES = [
  { key: 'FIT' as const, label: 'FIT', subtitle: 'Role Explorer' },
  { key: 'GAP' as const, label: 'GAP', subtitle: 'Readiness Check' },
  { key: 'SHIFT' as const, label: 'SHIFT', subtitle: 'Trend Guidance' },
];

function ProgressBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  return (
    <div className="progress-row">
      <span className="progress-label">{label}</span>
      <div
        className="progress-bar"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${pct}%`}
      >
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="progress-pct">{pct}%</span>
    </div>
  );
}

export function CompletenessGate({ completeness }: CompletenessGateProps) {
  return (
    <div className="completeness-gate card">
      <div className="completeness-features">
        {FEATURES.map(({ key, label, subtitle }) => {
          const feature = completeness.by_feature?.[key];
          const ready = feature?.ready ?? false;
          return (
            <div
              key={key}
              className={`feature-badge ${ready ? 'feature-ready' : 'feature-not-ready'}`}
              aria-label={`${label}: ${ready ? 'ready' : 'not ready'}`}
            >
              <span className="feature-label">{label}</span>
              <span className="feature-subtitle">{subtitle}</span>
              <span className={`feature-status ${ready ? 'status-ready' : 'status-pending'}`}>
                {ready ? 'Ready' : 'Incomplete'}
              </span>
            </div>
          );
        })}
      </div>

      <div className="completeness-progress">
        <ProgressBar value={completeness.academic ?? 0} label="Academic" />
        <ProgressBar value={completeness.career ?? 0} label="Career" />
      </div>
    </div>
  );
}
