import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { INSTITUTIONS, todayIso, validateSignupForm } from '../lib/signupRules.mjs';

/**
 * Account creation. Deliberately does NOT navigate to /dashboard on success:
 * this project requires email confirmation (mailer_autoconfirm is false,
 * verified against the live auth settings), so signUp() returns
 * `session: null` and there is no session to gate anything with yet. The
 * students row is created later, on the first confirmed login, from the
 * metadata attached here -- see lib/studentAccount.ts.
 */
export function SignUpPage() {
  const { signUpWithPassword } = useAuth();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [institutionId, setInstitutionId] = useState<string>(INSTITUTIONS[0].id);
  const [dateOfBirth, setDateOfBirth] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    // Every client-side rule, including the age gate, runs before any network
    // call. An underage or malformed submission never reaches signUp().
    const problem = validateSignupForm(
      { name, email, password, institutionId, dateOfBirth },
      todayIso(),
    );
    if (problem) {
      setError(problem);
      return;
    }

    setSubmitting(true);
    try {
      await signUpWithPassword(email.trim(), password, {
        name: name.trim(),
        institution_id: institutionId,
        date_of_birth: dateOfBirth,
      });
      setSentTo(email.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-up failed.');
    } finally {
      setSubmitting(false);
    }
  }

  if (sentTo) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Check your email</p>
          </div>

          <div className="login-form">
            <p>
              We sent a confirmation link to <strong>{sentTo}</strong>. Open it to activate your
              account, then sign in — your profile is set up on that first sign-in.
            </p>
          </div>

          <p className="login-note">
            <Link to="/login">Back to sign in</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="login-bg">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">Create your student account</p>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          className="login-form"
        >
          <div className="form-group">
            <label htmlFor="signup-name" className="form-label">
              Full name
            </label>
            <input
              id="signup-name"
              type="text"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
              autoComplete="name"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="signup-email" className="form-label">
              Email
            </label>
            <input
              id="signup-email"
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
              autoComplete="email"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="signup-password" className="form-label">
              Password
            </label>
            <input
              id="signup-password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              autoComplete="new-password"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="signup-dob" className="form-label">
              Date of birth
            </label>
            <input
              id="signup-dob"
              type="date"
              className="form-input"
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
              disabled={submitting}
              max={todayIso()}
              autoComplete="bday"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="signup-institution" className="form-label">
              Institution
            </label>
            <select
              id="signup-institution"
              className="form-select"
              value={institutionId}
              onChange={(e) => setInstitutionId(e.target.value)}
              disabled={submitting}
            >
              {INSTITUTIONS.map((institution) => (
                <option key={institution.id} value={institution.id}>
                  {institution.name}
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
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Creating account…
              </span>
            ) : (
              'Create account'
            )}
          </button>
        </form>

        <p className="login-note">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
