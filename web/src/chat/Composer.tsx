import { useEffect, useRef, type ClipboardEvent, type KeyboardEvent, type SubmitEvent } from "react";

import { imageFiles } from "../api/uploads";
import { MicIcon, PaperclipIcon, SendIcon } from "../components/icons";
import { tr } from "../i18n/tr";
import { ImageStrip, type PendingImage } from "./ImageStrip";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  images: PendingImage[];
  onAddFiles: (files: File[]) => void;
  onRemoveImage: (id: string) => void;
}

export function Composer({ value, onChange, onSend, busy, images, onAddFiles, onRemoveImage }: Props) {
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
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
    const files = imageFiles(event.clipboardData.files);
    if (files.length > 0) {
      event.preventDefault();
      onAddFiles(files);
    }
  }

  return (
    <form onSubmit={submit} className="border-t border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <ImageStrip images={images} onRemove={onRemoveImage} />
      <div className="flex items-end gap-1 p-2">
        {/* Faz 2: voice input (Whisper). Reserved now so the layout doesn't move later. */}
        <button
          type="button"
          disabled
          title={tr.chat.micSoon}
          aria-label={tr.chat.micSoon}
          className="flex h-11 w-10 shrink-0 items-center justify-center rounded-full text-slate-400 disabled:cursor-not-allowed dark:text-slate-500"
        >
          <MicIcon />
        </button>
        {/* accept="image/*": iPhone offers camera, photo library and files */}
        <input
          ref={picker}
          type="file"
          accept="image/*,.heic,.heif"
          multiple
          hidden
          onChange={(event) => {
            onAddFiles(imageFiles(event.target.files));
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
        <textarea
          ref={area}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder={busy ? tr.chat.sending : tr.chat.inputPlaceholder}
          rows={1}
          enterKeyHint="send"
          className="max-h-40 min-h-11 flex-1 resize-none rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-base outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label={tr.chat.send}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SendIcon width={18} height={18} />
        </button>
      </div>
    </form>
  );
}
