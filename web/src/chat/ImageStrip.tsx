import { useState } from "react";

import { XIcon } from "../components/icons";
import { tr } from "../i18n/tr";

export interface PendingImage {
  id: string;
  file: File;
  url: string; // object URL for the preview
}

/** Thumbnails under the input before sending; each can be removed. */
export function ImageStrip({ images, onRemove }: { images: PendingImage[]; onRemove: (id: string) => void }) {
  if (images.length === 0) return null;
  return (
    <ul className="flex gap-2 overflow-x-auto px-2 pt-2" aria-label={tr.chat.attachedImages}>
      {images.map((image) => (
        <li key={image.id} className="relative shrink-0">
          <Thumb url={image.url} name={image.file.name} className="h-16 w-16" />
          <button
            type="button"
            onClick={() => {
              onRemove(image.id);
            }}
            aria-label={tr.chat.removeImage}
            className="absolute -right-1.5 -top-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-slate-900/80 text-white shadow hover:bg-slate-900"
          >
            <XIcon width={14} height={14} />
          </button>
        </li>
      ))}
    </ul>
  );
}

/** An image, or a labelled tile when the browser can't show it (HEIC on desktop Chrome). */
export function Thumb({ url, name, className }: { url: string; name: string; className: string }) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <div
        className={`${className} flex items-center justify-center rounded-xl bg-slate-200 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300`}
        title={name}
      >
        {name.split(".").pop()?.toUpperCase() ?? tr.chat.image}
      </div>
    );
  }
  return (
    <img
      src={url}
      alt={name}
      onError={() => {
        setBroken(true);
      }}
      className={`${className} rounded-xl object-cover ring-1 ring-black/5 dark:ring-white/10`}
    />
  );
}
