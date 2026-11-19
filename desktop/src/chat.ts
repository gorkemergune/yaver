import { api, type ChatResponse, type Team } from "./api";
import { conversationStore, errorMessage, helpers, speakerOf } from "./chat/model";
import { tr } from "./i18n/tr";

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function byId<T extends HTMLElement>(id: string, type: new () => T): T {
  const node = document.getElementById(id);
  if (!(node instanceof type)) throw new Error(`#${id} missing`);
  return node;
}

// Static, trusted markup only.
const ICONS = {
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
};

type View = "chat" | "settings";

const messages = byId("messages", HTMLOListElement);
const composer = byId("composer", HTMLFormElement);
const input = byId("input", HTMLTextAreaElement);
const send = byId("send", HTMLButtonElement);
const actions = byId("actions", HTMLElement);

const conversation = conversationStore(globalThis.localStorage);
let team: Team | null = null;
let busy = false;
let view: View = "chat";

// ---- header -------------------------------------------------------------------------

function iconButton(icon: string, label: string, onClick: () => void): HTMLButtonElement {
  const button = el("button", "icon-btn");
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = icon;
  button.addEventListener("click", onClick);
  return button;
}

const viewButtons = new Map<View, HTMLButtonElement>();

function showView(next: View): void {
  view = next;
  for (const name of ["chat", "settings"] as const) {
    byId(`view-${name}`, HTMLElement).hidden = name !== next;
    viewButtons.get(name)?.setAttribute("aria-pressed", String(name === next));
  }
  if (next === "chat") input.focus();
  if (next === "settings") void loadSettings();
}

function toggleView(target: View): void {
  showView(view === target ? "chat" : target);
}

const newChatButton = iconButton(ICONS.plus, tr.header.newChat, () => {
  if (busy) return;
  conversation.set(null);
  renderEmpty();
  showView("chat");
});
const settingsButton = iconButton(ICONS.gear, tr.header.settings, () => {
  toggleView("settings");
});
viewButtons.set("settings", settingsButton);
actions.append(
  newChatButton,
  settingsButton,
  iconButton(ICONS.close, tr.header.close, () => void api.hideChat()),
);

// ---- messages -----------------------------------------------------------------------

function scrollToEnd(): void {
  messages.scrollTop = messages.scrollHeight;
}

function renderEmpty(): void {
  messages.replaceChildren();
  const empty = el("li", "empty");
  empty.append(el("strong", undefined, tr.chat.emptyTitle), tr.chat.emptyHint);
  messages.append(empty);
}

function clearEmpty(): void {
  messages.querySelector(".empty")?.remove();
}

function addUser(text: string): void {
  clearEmpty();
  const item = el("li", "msg user");
  item.append(el("div", "bubble", text));
  messages.append(item);
  scrollToEnd();
}

function addPending(): HTMLLIElement {
  const item = el("li", "msg assistant pending");
  item.append(el("div", "bubble", tr.chat.thinking));
  messages.append(item);
  scrollToEnd();
  return item;
}

function tag(name: string, color: string, helper = false): HTMLSpanElement {
  const node = el("span", helper ? "tag helper" : "tag", name);
  node.style.background = color;
  return node;
}

function undoLine(reply: ChatResponse): HTMLElement | null {
  const id = reply.change_set_id;
  const count = reply.changes.length;
  if (!id || count === 0) return null;
  const line = el("div", "change-line", tr.chat.changes(count));
  const button = el("button", "link-btn", tr.chat.undo);
  button.type = "button";
  button.addEventListener("click", () => {
    button.disabled = true;
    button.textContent = tr.chat.undoing;
    api.undo(id).then(
      () => {
        button.textContent = tr.chat.undone;
      },
      (error: unknown) => {
        button.disabled = false;
        button.textContent = tr.chat.undo;
        button.title = `${tr.chat.undoFailed}: ${errorMessage(error)}`;
      },
    );
  });
  line.append(button);
  return line;
}

function fillReply(item: HTMLLIElement, reply: ChatResponse): void {
  item.className = "msg assistant";
  const speaker = speakerOf(team, reply);
  const who = el("div", "who");
  who.append(tag(speaker.name, speaker.color));
  for (const helper of helpers(team, reply)) who.append(tag(helper.name, helper.color, true));
  const children: HTMLElement[] = [who, el("div", "bubble", reply.reply)];
  const undo = undoLine(reply);
  if (undo) children.push(undo);
  item.replaceChildren(...children);
  scrollToEnd();
}

function fillError(item: HTMLLIElement, error: unknown): void {
  item.className = "msg error";
  item.replaceChildren(el("div", "bubble", errorMessage(error)));
  scrollToEnd();
}

// ---- sending ------------------------------------------------------------------------

function setBusy(value: boolean): void {
  busy = value;
  send.disabled = value;
  newChatButton.disabled = value;
}

async function submit(): Promise<void> {
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  autosize();
  setBusy(true);
  addUser(text);
  const pending = addPending();
  try {
    const reply = await api.chat(text, conversation.get());
    conversation.set(reply.conversation_id);
    fillReply(pending, reply);
  } catch (error) {
    fillError(pending, error);
  } finally {
    setBusy(false);
    input.focus();
  }
}

function autosize(): void {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  void submit();
});

input.addEventListener("keydown", (event) => {
  // Enter sends, Shift+Enter is a new line; IME composition keeps Enter for itself.
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void submit();
  }
});
input.addEventListener("input", autosize);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") void api.hideChat();
});

// ---- settings -----------------------------------------------------------------------

const settingsForm = byId("settings-form", HTMLFormElement);
const apiUrl = byId("api-url", HTMLInputElement);
const apiUrlHint = byId("api-url-hint", HTMLElement);
const apiUrlEnv = byId("api-url-env", HTMLElement);
const saveUrl = byId("save-url", HTMLButtonElement);
const testUrl = byId("test-url", HTMLButtonElement);
const settingsStatus = byId("settings-status", HTMLElement);

function setStatus(text: string, kind: "ok" | "err" | "" = ""): void {
  settingsStatus.textContent = text;
  settingsStatus.className = kind ? `status ${kind}` : "status";
}

async function loadSettings(): Promise<void> {
  setStatus("");
  const settings = await api.settings();
  apiUrl.value = settings.api_url;
  apiUrlHint.textContent = tr.settings.apiUrlHint(settings.default_api_url);
  apiUrlEnv.hidden = !settings.api_url_from_env;
}

async function refreshTeam(): Promise<Team> {
  team = await api.team();
  return team;
}

settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveUrl.disabled = true;
  api
    .setApiUrl(apiUrl.value)
    .then((normalized) => {
      apiUrl.value = normalized;
      setStatus(tr.settings.saved, "ok");
      void refreshTeam().catch(() => undefined);
    })
    .catch((error: unknown) => {
      setStatus(errorMessage(error), "err");
    })
    .finally(() => {
      saveUrl.disabled = false;
    });
});

testUrl.addEventListener("click", () => {
  testUrl.disabled = true;
  setStatus(tr.settings.testing);
  refreshTeam()
    .then((loaded) => {
      const names = [loaded.coordinator, ...loaded.agents].map((m) => m.name).join(", ");
      setStatus(tr.settings.connected(names), "ok");
    })
    .catch((error: unknown) => {
      setStatus(errorMessage(error), "err");
    })
    .finally(() => {
      testUrl.disabled = false;
    });
});

// ---- start --------------------------------------------------------------------------

function init(): void {
  document.title = tr.appName;
  input.placeholder = tr.chat.placeholder;
  send.textContent = tr.chat.send;
  byId("api-url-label", HTMLElement).textContent = tr.settings.apiUrl;
  apiUrlEnv.textContent = tr.settings.apiUrlFromEnv;
  saveUrl.textContent = tr.settings.save;
  testUrl.textContent = tr.settings.test;
  renderEmpty();
  showView("chat");
  // Names/colors are nice to have; the chat works without them.
  void refreshTeam().catch(() => undefined);
  // Focus the input each time the panel is opened from the logo.
  window.addEventListener("focus", () => {
    if (view === "chat") input.focus();
  });
}

init();
