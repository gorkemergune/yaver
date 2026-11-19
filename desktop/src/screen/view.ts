// Screen-time view of the panel: today's total, limits, apps. Read-only, like the web UI.
import { api } from "../api";
import { tr } from "../i18n/tr";
import { fill, fmtDay, fmtDuration, limitState, topApps, type ScreenSummary } from "./model";

const MAX_APPS = 10;
const REFRESH_MS = 30_000;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function bar(share: number, state = ""): HTMLElement {
  const track = el("div", "bar-track");
  const value = el("div", state ? `bar-fill ${state}` : "bar-fill");
  value.style.width = `${(share * 100).toFixed(1)}%`;
  track.append(value);
  return track;
}

function render(root: HTMLElement, summary: ScreenSummary): void {
  const t = tr.screen;
  const children: HTMLElement[] = [];

  const head = el("div", "screen-head");
  head.append(el("span", "screen-day", fmtDay(summary.date)), el("strong", "screen-total", fmtDuration(summary.total_seconds)));
  children.push(head);

  if (!summary.supported) children.push(el("p", "hint", t.unsupported));
  else if (!summary.tracking) children.push(el("p", "hint warn", t.paused));

  if (summary.limits.length > 0) {
    children.push(el("h3", undefined, t.limits));
    const list = el("ul", "rows");
    for (const limit of summary.limits) {
      const state = limitState(limit.used_seconds, limit.limit_seconds);
      const row = el("li", "row-item");
      const line = el("div", "row-line");
      line.append(
        el("span", "row-name", limit.name),
        el("span", `row-value ${state}`, t.usedOf(fmtDuration(limit.used_seconds), fmtDuration(limit.limit_seconds))),
      );
      row.append(line, bar(fill(limit.used_seconds, limit.limit_seconds), state));
      list.append(row);
    }
    children.push(list);
  }

  children.push(el("h3", undefined, t.apps));
  if (summary.apps.length === 0) {
    children.push(el("p", "hint", t.empty));
  } else {
    const list = el("ul", "rows");
    const top = summary.apps[0]?.seconds ?? 0;
    for (const app of topApps(summary.apps, MAX_APPS, t.other)) {
      const row = el("li", "row-item");
      row.title = app.exe;
      const line = el("div", "row-line");
      line.append(el("span", "row-name", app.name), el("span", "row-value", fmtDuration(app.seconds)));
      row.append(line, bar(fill(app.seconds, top)));
      list.append(row);
    }
    children.push(list);
  }

  const foot = el("div", "screen-foot");
  foot.append(el("p", "hint", summary.limits.length > 0 ? t.limitsHint : t.noLimitsHint));
  if (summary.config_error) foot.append(el("p", "hint warn", t.configError(summary.config_error)));
  const open = el("button", "link-btn", t.openConfig);
  open.type = "button";
  open.title = summary.config_path;
  open.addEventListener("click", () => void api.openConfigFolder());
  foot.append(open, el("p", "hint", t.localOnly));
  children.push(foot);

  root.replaceChildren(...children);
}

/** Loads now and every 30 s until `stop()` (called when the view is left). */
export function startScreenView(root: HTMLElement): { stop(): void } {
  let alive = true;
  const load = () => {
    api.screenTime().then(
      (summary) => {
        if (alive) render(root, summary);
      },
      () => {
        if (alive) root.replaceChildren(el("p", "hint warn", tr.screen.loadFailed));
      },
    );
  };
  load();
  const timer = window.setInterval(load, REFRESH_MS);
  return {
    stop() {
      alive = false;
      window.clearInterval(timer);
    },
  };
}
