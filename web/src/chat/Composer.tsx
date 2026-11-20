import { useEffect, useRef, useState, type ClipboardEvent, type KeyboardEvent, type SubmitEvent } from "react";

import { attachableFiles } from "../api/uploads";
import { MicIcon, PaperclipIcon, SendIcon, XIcon } from "../components/icons";
import { TypingDots } from "../design/parts";
import { tr } from "../i18n/tr";
import { ImageStrip, type PendingImage } from "./ImageStrip";
import { useVoice } from "./useVoice";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  images: PendingImage[];
  onAddFiles: (files: File[]) => void;
  onRemoveImage: (id: string) => void;
  onVoiceText: (text: string) => void;
  onVoiceError: (code: string) => void;
  /** Full width of its container (the office), not the chat's centred column. */
  wide?: boolean;
}

export function Composer({
  value,
  onChange,
  onSend,
  busy,
  images,
  onAddFiles,
  onRemoveImage,
  onVoiceText,
  onVoiceError,
  wide = false,
}: Props) {
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const voice = useVoice(onVoiceText, onVoiceError);
  const pressedAt = useRef(0);
  const [held, setHeld] = useState(true); // false: tap mode (tap again to send)
  const canSend = !busy && (value.trim().length > 0 || images.length > 0);

  // Grow with the text up to ~6 lines.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${String(Math.min(el.scrollHeight, 160))}px`;
  }, [value]);

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (canSend) onSend();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends on desktop; on phones the return key inserts a line (no physical Shift).
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && window.matchMedia("(pointer: fine)").matches) {
      event.preventDefault();
      if (canSend) onSend();
    }
  }

  // Ctrl+V of a screenshot: the image is attached, text pastes as usual.
  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = attachableFiles(event.clipboardData.files);
    if (files.length > 0) {
      event.preventDefault();
      onAddFiles(files);
    }
  }

  return (
    <form
      onSubmit={submit}
      className={`yv-glass rounded-3xl ${wide ? "w-full" : "mx-2 mb-2 md:mx-auto md:mb-3 md:w-full md:max-w-2xl"}`}
    >
      <ImageStrip images={images} onRemove={onRemoveImage} />
      <div className="flex items-end gap-1 p-2">
        {/* Push-to-talk: hold and release to send; a short tap records until the next tap. */}
        <button
          type="button"
          disabled={busy || voice.state === "transcribing"}
          title={tr.voice.hold}
          aria-label={voice.state === "recording" ? tr.voice.stop : tr.voice.hold}
          aria-pressed={voice.state === "recording"}
          onPointerDown={(event) => {
            event.preventDefault();
            if (voice.state === "recording") {
              voice.stop(true); // tap mode: second tap sends
              return;
            }
            pressedAt.current = performance.now();
            setHeld(true);
            void voice.start();
          }}
          onPointerUp={() => {
            if (voice.state !== "recording" && performance.now() - pressedAt.current > 600) return;
            if (performance.now() - pressedAt.current < 350) {
              setHeld(false); // a tap: keep recording
              return;
            }
            if (held) voice.stop(true);
          }}
          onPointerCancel={() => {
            voice.stop(false);
          }}
          className={`flex h-11 w-10 shrink-0 touch-none select-none items-center justify-center rounded-full transition-colors disabled:opacity-40 ${
            voice.state === "recording"
              ? "bg-rose-500 text-white shadow-[0_0_0_6px_rgba(244,63,94,0.25)]"
              : "text-slate-500 hover:bg-white/60 hover:text-indigo-600 dark:text-slate-400 dark:hover:bg-white/10"
          }`}
        >
          {voice.state === "transcribing" ? <TypingDots color="currentColor" /> : <MicIcon />}
        </button>
        {/* accept="image/*" (+ PDF): iPhone offers camera, photo library and files */}
        <input
          ref={picker}
          type="file"
          accept="image/*,.heic,.heif,application/pdf,.pdf"
          multiple
          hidden
          onChange={(event) => {
            onAddFiles(attachableFiles(event.target.files));
            event.target.value = ""; // the same file can be picked again
          }}
        />
        <button
          type="button"
          onClick={() => picker.current?.click()}
          disabled={busy}
          title={tr.chat.attach}
          aria-label={tr.chat.attach}
          className="flex h-11 w-10 shrink-0 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 hover:text-indigo-600 disabled:opacity-40 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          <PaperclipIcon />
        </button>
        {voice.state === "recording" ? (
          <div className="flex min-h-11 flex-1 items-center gap-3 rounded-2xl bg-rose-500/10 px-3" role="status">
            <span className="flex h-8 flex-1 items-center gap-[3px]" aria-hidden>
              {voice.levels.map((level, index) => (
                <span
                  key={index}
                  className="w-[3px] flex-1 rounded-full bg-rose-500 transition-[height] duration-75"
                  style={{ height: `${String(Math.max(8, level * 100))}%` }}
                />
              ))}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-rose-600 dark:text-rose-300">
              0:{String(voice.seconds).padStart(2, "0")} · {held ? tr.voice.release : tr.voice.tapToSend}
            </span>
            <button
              type="button"
              onClick={() => {
                voice.stop(false);
              }}
              aria-label={tr.voice.cancel}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-rose-600 hover:bg-rose-500/15 dark:text-rose-300"
            >
              <XIcon width={16} height={16} />
            </button>
          </div>
        ) : (
          <textarea
          ref={area}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder={voice.state === "transcribing" ? tr.voice.transcribing : busy ? tr.chat.sending : tr.chat.inputPlaceholder}
          rows={1}
          enterKeyHint="send"
          className="max-h-40 min-h-11 flex-1 resize-none rounded-2xl border border-transparent bg-white/70 px-4 py-2.5 text-base outline-none placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-500/20 dark:bg-white/5 dark:placeholder:text-slate-500"
        />
        )}
        <button
          type="submit"
          disabled={!canSend}
          aria-label={tr.chat.send}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-[0_8px_20px_-8px_rgba(99,102,241,0.9)] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SendIcon width={18} height={18} />
        </button>
      </div>
    </form>
  );
}
