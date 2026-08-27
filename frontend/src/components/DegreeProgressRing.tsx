const SIZE = 56;
const STROKE = 5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The stat row's 4th item -- a ring of satisfied-vs-total requirement groups
 * (leaf nodes only, see requirementProgress.mjs), with the "X of Y" detail
 * line the mockup calls for underneath. `total === 0` (no program evaluated
 * yet, or a program with no requirements) renders the same dash the other
 * three stats show for missing data, rather than a 0%-full or empty ring
 * that would read as "0 satisfied" instead of "not available."
 */
export function DegreeProgressRing({ satisfied, total }: { satisfied: number; total: number }) {
  if (total === 0) {
    return (
      <div className="overview-stat overview-stat--ring">
        <span className="overview-stat-value">—</span>
        <span className="overview-stat-label">Degree Progress</span>
      </div>
    );
  }

  const pct = Math.round((satisfied / total) * 100);
  const offset = CIRCUMFERENCE * (1 - satisfied / total);

  return (
    <div className="overview-stat overview-stat--ring">
      <svg
        className="degree-progress-ring"
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`${String(satisfied)} of ${String(total)} requirement groups satisfied`}
      >
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          strokeWidth={STROKE}
          className="degree-progress-ring-track"
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          strokeWidth={STROKE}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          className="degree-progress-ring-fill"
        />
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" className="degree-progress-ring-pct">
          {pct}%
        </text>
      </svg>
      <span className="overview-stat-label">Degree Progress</span>
      <span className="overview-stat-detail">{satisfied} of {total} requirement groups satisfied</span>
    </div>
  );
}
