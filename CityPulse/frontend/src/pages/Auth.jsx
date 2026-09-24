import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { loginAccount, registerAccount } from "../lib/auth";

export function AuthPage({ mode, onAuthenticated }) {
  const isRegister = mode === "register";
  const navigate = useNavigate();
  const location = useLocation();
  const destination = location.state?.from || "/";
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!globalThis.crypto?.subtle) {
    return <main className="auth-page"><section className="auth-card"><h1>Sign-in unavailable</h1>
      <p className="muted">This browser does not support secure local password storage. Try a current browser over localhost or HTTPS.</p>
    </section></main>;
  }

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (isRegister && password !== confirm) return setError("Passwords do not match.");
    setBusy(true);
    try {
      const user = isRegister
        ? await registerAccount(name, password)
        : await loginAccount(name, password);
      onAuthenticated(user);
      navigate(destination, { replace: true });
    } catch (e) {
      setError(e.message || "Could not complete your request.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand"><span className="logo" aria-hidden="true">◉</span><span>CITYPULSE</span></div>
        <p className="auth-eyebrow">CIVIC INTELLIGENCE</p>
        <h1 id="auth-title">{isRegister ? "Create your account" : "Welcome back"}</h1>
        <p className="muted">{isRegister ? "Register to open your CityPulse workspace." : "Sign in to continue to your CityPulse workspace."}</p>

        <form className="auth-form" onSubmit={submit}>
          <label>Name
            <input autoComplete="username" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>Password
            <input type="password" autoComplete={isRegister ? "new-password" : "current-password"} required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {isRegister && (
            <label>Confirm password
              <input type="password" autoComplete="new-password" required minLength={8} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </label>
          )}
          {error && <p className="inline-error" role="alert">{error}</p>}
          <button className="btn primary auth-submit" type="submit" disabled={busy}>{busy ? "Please wait…" : isRegister ? "Create account" : "Sign in"}</button>
        </form>

        <p className="auth-switch">
          {isRegister ? "Already have an account? " : "New to CityPulse? "}
          <Link to={isRegister ? "/login" : "/register"}>{isRegister ? "Sign in" : "Create an account"}</Link>
        </p>
        <p className="auth-note">Frontend demo accounts are saved in this browser only.</p>
      </section>
    </main>
  );
}
