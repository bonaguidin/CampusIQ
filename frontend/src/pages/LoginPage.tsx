import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

const DEMO_STUDENTS = [
  { name: 'Jordan Reyes',  slug: 'jordanReyes'  },
  { name: 'Ethan Brooks',  slug: 'ethanBrooks'  },
  { name: 'Marcus Webb',   slug: 'marcusWebb'   },
  { name: 'Priya Nair',    slug: 'priyaNair'    },
  { name: 'Sofia Ramirez', slug: 'sofiaRamirez' },
] as const;

export function LoginPage() {
  const { login, loading, profile } = useAuth();
  const navigate = useNavigate();
  const [selectedSlug, setSelectedSlug] = useState<string>(DEMO_STUDENTS[0].slug);
  const [error, setError] = useState<string | null>(null);

  // Wait for React to flush the profile state before navigating
  useEffect(() => {
    if (profile && !loading) {
      void navigate('/dashboard');
    }
  }, [profile, loading, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await login(selectedSlug);
    } catch {
      setError('Failed to load student profile. Please try again.');
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card">
        {/* Header — serif product name on white */}
        <div className="login-header">
          <h1 className="login-logo">Campus IQ</h1>
          <p className="login-subtitle">Texas A&amp;M University</p>
        </div>

        <form
          onSubmit={(e) => { void handleSubmit(e); }}
          className="login-form"
        >
          <div className="form-group">
            <label htmlFor="student-select" className="form-label">
              Student profile
            </label>
            <select
              id="student-select"
              className="form-select"
              value={selectedSlug}
              onChange={(e) => setSelectedSlug(e.target.value)}
              disabled={loading}
            >
              {DEMO_STUDENTS.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          {error && (
            <p className="login-error" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-full"
            disabled={loading}
            aria-busy={loading}
          >
            {loading ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Loading…
              </span>
            ) : (
              'Enter Dashboard'
            )}
          </button>
        </form>

        <p className="login-note">Demo mode — select a student profile to explore</p>
      </div>
    </div>
  );
}
