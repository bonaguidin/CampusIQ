import { useAuth } from '../auth/useAuth';
import { useNavigate } from 'react-router-dom';
import type { StudentBlock } from '../types/student';

interface ProfileHeaderProps {
  student: StudentBlock;
  gpa: number;
}

function gpaClass(gpa: number): string {
  if (gpa >= 3.5) return 'gpa-green';
  if (gpa >= 3.0) return 'gpa-blue';
  if (gpa >= 2.5) return 'gpa-amber';
  return 'gpa-red';
}

function safeGpa(value: unknown): number | null {
  return typeof value === 'number' && !isNaN(value) ? value : null;
}

function graduationYear(expected: string): string {
  if (!expected) return '';
  return expected.slice(0, 4);
}

export function ProfileHeader({ student, gpa }: ProfileHeaderProps) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const gpaValue = safeGpa(gpa);

  function handleLogout() {
    logout();
    navigate('/login');
  }

  return (
    <header className="profile-header">
      <div className="profile-header-inner">
        <div className="profile-info">
          <h1 className="profile-name">{student?.name ?? '—'}</h1>
          <div className="profile-meta">
            <span className="profile-major">{student?.major_current ?? '—'}</span>
            <span className="classification-badge">{student?.classification ?? '—'}</span>
            {gpaValue !== null && (
              <span className={`gpa-pill ${gpaClass(gpaValue)}`}>
                GPA {gpaValue.toFixed(2)}
              </span>
            )}
          </div>
          <p className="profile-institution">
            {student?.institution ?? '—'}
            {student?.expected_graduation
              ? ` · Expected ${graduationYear(student.expected_graduation)}`
              : ''}
          </p>
        </div>

        <button
          type="button"
          className="btn btn-ghost"
          onClick={handleLogout}
          aria-label="Logout"
        >
          Logout
        </button>
      </div>
    </header>
  );
}
