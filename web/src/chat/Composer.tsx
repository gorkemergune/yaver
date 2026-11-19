import { useEffect, useRef, type KeyboardEvent, type SubmitEvent } from "react";

import { MicIcon, SendIcon } from "../components/icons";
import { tr } from "../i18n/tr";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
}

export function Composer({ value, onChange, onSend, busy }: Props) {
  const area = useRef<HTMLTextAreaElement>(null);

  // Grow with the text up to ~6 lines.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${String(Math.min(el.scrollHeight, 160))}px`;
  }, [value]);

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    onSend();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends on desktop; on phones the return key inserts a line (no physical Shift).
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && window.matchMedia("(pointer: fine)").matches) {
      event.preventDefault();
      onSend();
    }
  }

  return (
    <form onSubmit={submit} className="flex items-end gap-2 border-t border-slate-200 bg-white/90 p-2 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      {/* Faz 2: voice input (Whisper). Reserved now so the layout doesn't move later. */}
      <button
        type="button"
        disabled
        title={tr.chat.micSoon}
        aria-label={tr.chat.micSoon}
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-slate-400 disabled:cursor-not-allowed dark:text-slate-500"
      >
        <MicIcon />
      </button>
      <textarea
        ref={area}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        onKeyDown={onKeyDown}
        placeholder={busy ? tr.chat.sending : tr.chat.inputPlaceholder}
        rows={1}
        enterKeyHint="send"
        className="max-h-40 min-h-11 flex-1 resize-none rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-base outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900"
      />
      <button
        type="submit"
        disabled={busy || !value.trim()}
        aria-label={tr.chat.send}
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <SendIcon width={18} height={18} />
      </button>
    </form>
  );
}
