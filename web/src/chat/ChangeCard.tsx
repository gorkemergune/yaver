import type { Change } from "../api/types";
import { UndoIcon } from "../components/icons";
import { tr } from "../i18n/tr";
import { describeChange, visibleChanges } from "../lib/changes";

interface Props {
  changes: Change[];
  undone: boolean;
  pending: boolean;
  failed: boolean;
  onUndo: () => void;
}

/** What this message changed, with the single "Geri al" button for all of it. */
export function ChangeCard({ changes, undone, pending, failed, onUndo }: Props) {
  const shown = visibleChanges(changes);
  if (shown.length === 0) return null;
  return (
    <div
      className={`mt-2 rounded-xl border p-3 text-sm ${
        undone
          ? "yv-inset text-slate-400"
          : "border-emerald-300/60 bg-emerald-50/70 dark:border-emerald-400/25 dark:bg-emerald-400/10"
      }`}
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-medium">{tr.changes.title(shown.length)}</span>
        {undone ? (
          <span className="text-xs">{tr.changes.undone}</span>
        ) : (
          <button
            type="button"
            onClick={onUndo}
            disabled={pending}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2.5 text-emerald-800 hover:bg-emerald-100 disabled:opacity-50 dark:text-emerald-300 dark:hover:bg-emerald-900/40"
          >
            <UndoIcon width={16} height={16} />
            {pending ? tr.changes.undoing : tr.changes.undo}
          </button>
        )}
      </div>
      <ul className={`space-y-1 ${undone ? "line-through" : ""}`}>
        {shown.map((change, index) => (
          <li key={`${change.entity}-${String(index)}`}>{describeChange(change)}</li>
        ))}
      </ul>
      {failed && !undone && (
        <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{tr.changes.undoFailed}</p>
      )}
    </div>
  );
}
