import { useQueryClient } from "@tanstack/react-query";
import { useState, type SyntheticEvent } from "react";

import { login } from "../api/auth";
import { tr } from "../i18n/tr";
import { Backdrop } from "./Backdrop";

/** Shown instead of the app when APP_PASSWORD is set and this browser has no session. */
export function LoginView() {
  const client = useQueryClient();
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: SyntheticEvent): Promise<void> => {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    const result = await login(password);
    setBusy(false);
    if (result.ok) {
      setPassword("");
      await client.invalidateQueries(); // everything that failed with 401 loads now
      return;
    }
    setError(
      result.error === "too_many_attempts"
        ? tr.login.tooMany(Math.ceil((result.retryAfter ?? 60) / 60))
        : result.error === "wrong_password"
          ? tr.login.wrong
          : tr.login.network,
    );
    if (result.error === "wrong_password") setPassword("");
  };

  return (
    <div className="flex min-h-dvh items-center justify-center px-4 py-10">
      <Backdrop />
      <form
        onSubmit={(event) => void submit(event)}
        className="yv-glass yv-rise w-full max-w-sm rounded-[2rem] px-6 pb-7 pt-8 text-center shadow-xl shadow-indigo-950/10"
      >
        <img src="/favicon.svg" alt="" className="mx-auto h-16 w-16 drop-shadow-[0_8px_24px_rgba(129,140,248,0.45)]" />
        <h1 className="font-grotesk yv-name-gradient mt-4 text-4xl font-semibold tracking-tight">{tr.appName}</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{tr.login.subtitle}</p>

        <label htmlFor="password" className="sr-only">
          {tr.login.password}
        </label>
        <div className="yv-inset mt-6 flex items-center rounded-2xl pr-1 focus-within:ring-2 focus-within:ring-indigo-400/60">
          <input
            id="password"
            type={visible ? "text" : "password"}
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setError(null);
            }}
            placeholder={tr.login.password}
            aria-invalid={error !== null}
            aria-describedby={error ? "login-error" : undefined}
            className="min-h-12 min-w-0 flex-1 bg-transparent px-4 text-base outline-none placeholder:text-slate-400"
          />
          <button
            type="button"
            onClick={() => {
              setVisible((value) => !value);
            }}
            className="rounded-xl px-3 py-2 text-xs font-medium text-slate-500 hover:bg-white/60 dark:text-slate-400 dark:hover:bg-white/10"
          >
            {visible ? tr.login.hide : tr.login.show}
          </button>
        </div>

        <p id="login-error" role="alert" className="mt-2 min-h-5 text-sm text-rose-600 dark:text-rose-400">
          {error}
        </p>

        <button
          type="submit"
          disabled={!password || busy}
          className="mt-2 min-h-12 w-full rounded-2xl bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500 font-semibold text-white shadow-lg shadow-indigo-500/25 transition-opacity hover:opacity-95 disabled:opacity-50"
        >
          {busy ? tr.login.busy : tr.login.submit}
        </button>
        <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">{tr.login.hint}</p>
      </form>
    </div>
  );
}
