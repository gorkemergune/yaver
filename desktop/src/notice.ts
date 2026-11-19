import { invoke } from "@tauri-apps/api/core";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { tr } from "./i18n/tr";

interface Notice {
  title: string;
  body: string;
}

/** The balloon hides itself after a while; the system notification stays in the Action Center. */
const AUTO_HIDE_MS = 20_000;

const box = document.getElementById("notice");
const title = document.getElementById("title");
const body = document.getElementById("body");
const close = document.getElementById("close");
if (!box || !title || !body || !close) throw new Error("notice markup missing");

close.textContent = "×";
close.title = tr.notice.dismiss;
close.setAttribute("aria-label", tr.notice.dismiss);
box.title = tr.notice.open;

let timer: number | undefined;

function render(notice: Notice | null): void {
  if (!notice) return;
  if (title) title.textContent = notice.title;
  if (body) body.textContent = notice.body;
  window.clearTimeout(timer);
  timer = window.setTimeout(() => void invoke("dismiss_notice"), AUTO_HIDE_MS);
}

close.addEventListener("click", (event) => {
  event.stopPropagation();
  void invoke("dismiss_notice");
});
box.addEventListener("click", () => void invoke("open_notice"));

void getCurrentWebviewWindow().listen<Notice>("notice", (event) => {
  render(event.payload);
});
void invoke<Notice | null>("current_notice").then(render);
