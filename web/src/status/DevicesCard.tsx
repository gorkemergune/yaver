import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { apiDelete, apiGet, apiPost } from "../api/client";
import type { DeviceKeyView } from "../api/types";
import { tr } from "../i18n/tr";
import { Card } from "./Card";

const KEY = ["devices"] as const;
const t = tr.devices;

const when = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : t.never;

/** Device keys: the desktop app and the Siri shortcut log in with one (shown once). */
export function DevicesCard() {
  const client = useQueryClient();
  const devices = useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => apiGet<{ devices: DeviceKeyView[] }>("/devices", { signal }),
  });
  const [name, setName] = useState("");
  const [made, setMade] = useState<{ name: string; key: string } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const button = "rounded-full px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50";

  async function create(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const label = name.trim();
    if (!label) return;
    try {
      const result = await apiPost<DeviceKeyView & { key: string }>("/devices", { name: label });
      setMade({ name: result.name, key: result.key });
      setName("");
      setNote(null);
      void client.invalidateQueries({ queryKey: KEY });
    } catch {
      setNote(t.failed);
    }
  }

  async function revoke(device: DeviceKeyView) {
    if (!window.confirm(t.revokeConfirm(device.name))) return;
    try {
      await apiDelete(`/devices/${String(device.id)}`);
      void client.invalidateQueries({ queryKey: KEY });
    } catch {
      setNote(t.failed);
    }
  }

  const active = devices.data?.devices.filter((d) => !d.revoked) ?? [];
  return (
    <Card title={t.title}>
      <p className="text-sm text-slate-600 dark:text-slate-300">{t.what}</p>
      {made && (
        <div className="mt-3 rounded-xl border border-amber-400/50 bg-amber-50/70 p-3 text-sm dark:bg-amber-400/10">
          <p className="font-medium">{t.madeTitle(made.name)}</p>
          <code className="yv-inset mt-2 block break-all rounded-lg px-3 py-2 text-xs">{made.key}</code>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={`${button} bg-gradient-to-r from-indigo-500 to-fuchsia-500 text-white`}
              onClick={() => {
                navigator.clipboard.writeText(made.key).then(
                  () => {
                    setNote(t.copied);
                  },
                  () => {
                    setNote(t.copyFailed);
                  },
                );
              }}
            >
              {t.copy}
            </button>
            <button type="button" className={`${button} yv-glass`} onClick={() => { setMade(null); }}>
              {t.done}
            </button>
          </div>
          <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">{t.onlyOnce}</p>
        </div>
      )}
      <form onSubmit={(event) => void create(event)} className="mt-3 flex gap-2">
        <label htmlFor="device-name" className="sr-only">
          {t.name}
        </label>
        <input
          id="device-name"
          value={name}
          maxLength={100}
          onChange={(event) => {
            setName(event.target.value);
          }}
          placeholder={t.namePlaceholder}
          className="yv-inset h-10 min-w-0 flex-auto rounded-full px-4 text-sm outline-none"
        />
        <button type="submit" disabled={!name.trim()} className={`${button} bg-gradient-to-r from-indigo-500 to-fuchsia-500 text-white`}>
          {t.create}
        </button>
      </form>
      {note && <p className="mt-2 text-xs text-slate-500">{note}</p>}
      {active.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {active.map((device) => (
            <li key={device.id} className="yv-inset flex items-center gap-3 rounded-xl px-3 py-2 text-sm">
              <span className="min-w-0 flex-auto">
                <span className="font-medium">{device.name}</span>{" "}
                <code className="text-xs text-slate-500">{device.prefix}…</code>
                <span className="block text-xs text-slate-500">{t.lastUsed(when(device.last_used_at))}</span>
              </span>
              <button
                type="button"
                className="rounded-full px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-500/10 dark:text-rose-400"
                onClick={() => void revoke(device)}
              >
                {t.revoke}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
