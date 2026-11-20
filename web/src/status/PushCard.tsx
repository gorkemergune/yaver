import { useEffect, useState } from "react";

import { tr } from "../i18n/tr";
import { Card } from "./Card";
import {
  disablePush,
  enablePush,
  pushState,
  sendTestPush,
  type PushState,
} from "../lib/push";

/** Notifications switch: briefing, check-in and follow-ups also arrive as Web Push. */
export function PushCard() {
  const [state, setState] = useState<PushState | "loading" | "error">(
    "loading",
  );
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    pushState().then(setState, () => {
      setState("error");
    });
  }, []);

  const run = (action: () => Promise<PushState>): void => {
    setBusy(true);
    setNote(null);
    action()
      .then(setState, () => {
        setNote(tr.push.failed);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const button =
    "rounded-full px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50";
  return (
    <Card title={tr.push.title}>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        {state === "loading"
          ? tr.plan.loading
          : state === "error"
            ? tr.push.failed
            : tr.push.states[state]}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {(state === "off" || state === "denied") && (
          <button
            type="button"
            disabled={busy || state === "denied"}
            onClick={() => {
              run(enablePush);
            }}
            className={`${button} bg-gradient-to-r from-indigo-500 to-fuchsia-500 text-white`}
          >
            {tr.push.enable}
          </button>
        )}
        {state === "on" && (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setNote(null);
                sendTestPush()
                  .then(
                    (result) => {
                      setNote(tr.push.sent(result.sent));
                    },
                    () => {
                      setNote(tr.push.failed);
                    },
                  )
                  .finally(() => {
                    setBusy(false);
                  });
              }}
              className={`${button} bg-indigo-500/10 text-indigo-700 hover:bg-indigo-500/20 dark:text-indigo-300`}
            >
              {tr.push.test}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                run(disablePush);
              }}
              className={`${button} text-slate-600 hover:bg-white/60 dark:text-slate-300 dark:hover:bg-white/10`}
            >
              {tr.push.disable}
            </button>
          </>
        )}
      </div>
      {note && (
        <p
          role="status"
          className="mt-2 text-sm text-slate-500 dark:text-slate-400"
        >
          {note}
        </p>
      )}
    </Card>
  );
}
