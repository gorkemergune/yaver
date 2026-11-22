import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { api, type ChatResponse, type Team } from "./api";
import { conversationStore, errorMessage, helpers, needsKey, speakerOf } from "./chat/model";
import { tr } from "./i18n/tr";
import { startScreenView } from "./screen/view";

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
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
};

const VIEWS = ["chat", "screen", "settings", "key"] as const;
type View = (typeof VIEWS)[number];

function isView(value: unknown): value is View {
  return VIEWS.includes(value as View);
}

const messages = byId("messages", HTMLOListElement);
const composer = byId("composer", HTMLFormElement);
const input = byId("input", HTMLTextAreaElement);
const send = byId("send", HTMLButtonElement);
const actions = byId("actions", HTMLElement);

const conversation = conversationStore(globalThis.localStorage);
let team: Team | null = null;
let busy = false;
let view: View = "chat";
let screenView: { stop(): void } | null = null;

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
  screenView?.stop();
  screenView = null;
  for (const name of VIEWS) {
    byId(`view-${name}`, HTMLElement).hidden = name !== next;
    viewButtons.get(name)?.setAttribute("aria-pressed", String(name === next));
  }
  if (next === "chat") input.focus();
  if (next === "settings") void loadSettings();
  if (next === "screen") screenView = startScreenView(byId("view-screen", HTMLElement));
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
const screenButton = iconButton(ICONS.clock, tr.header.screen, () => {
  toggleView("screen");
});
const settingsButton = iconButton(ICONS.gear, tr.header.settings, () => {
  toggleView("settings");
});
viewButtons.set("screen", screenButton);
viewButtons.set("settings", settingsButton);
actions.append(
  newChatButton,
  screenButton,
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

/** 👎 "Hatalı" under an answer: a short note, then POST /api/bug-reports (via Rust). */
function reportLine(report: { messageId: number | null; userText: string; replyText: string; error: string | null }): HTMLElement {
  const line = el("div", "report-line");
  const open = el("button", "link-btn report-btn", `👎 ${tr.bugs.button}`);
  open.type = "button";
  open.title = tr.bugs.buttonHint;
  open.addEventListener("click", () => {
    const note = el("textarea", "report-note");
    note.rows = 2;
    note.maxLength = 2000;
    note.placeholder = tr.bugs.placeholder;
    const save = el("button", "link-btn", tr.bugs.send);
    save.type = "button";
    const cancel = el("button", "link-btn", tr.bugs.cancel);
    cancel.type = "button";
    cancel.addEventListener("click", () => {
      line.replaceChildren(open);
    });
    save.addEventListener("click", () => {
      save.disabled = true;
      save.textContent = tr.bugs.sending;
      api.reportBug({ ...report, note: note.value.trim() }).then(
        (saved) => {
          line.replaceChildren(el("span", "report-done", tr.bugs.sent(saved.id)));
        },
        (error: unknown) => {
          save.disabled = false;
          save.textContent = tr.bugs.send;
          save.title = `${tr.bugs.failed}: ${errorMessage(error)}`;
        },
      );
    });
    line.replaceChildren(note, save, cancel);
    note.focus();
  });
  line.append(open);
  return line;
}

function fillReply(item: HTMLLIElement, reply: ChatResponse, asked: string): void {
  item.className = "msg assistant";
  const speaker = speakerOf(team, reply);
  const who = el("div", "who");
  who.append(tag(speaker.name, speaker.color));
  for (const helper of helpers(team, reply)) who.append(tag(helper.name, helper.color, true));
  const children: HTMLElement[] = [who, el("div", "bubble", reply.reply)];
  const undo = undoLine(reply);
  if (undo) children.push(undo);
  children.push(reportLine({ messageId: reply.message_id ?? null, userText: asked, replyText: reply.reply, error: null }));
  item.replaceChildren(...children);
  scrollToEnd();
}

function fillError(item: HTMLLIElement, error: unknown, asked: string): void {
  item.className = "msg error";
  const text = errorMessage(error);
  item.replaceChildren(el("div", "bubble", text), reportLine({ messageId: null, userText: asked, replyText: "", error: text }));
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
    fillReply(pending, reply, text);
  } catch (error) {
    if (needsKey(error)) {
      // not a red error: the message goes back to the input, the key screen says what to do
      pending.remove();
      messages.lastElementChild?.remove(); // the user's bubble
      if (!messages.children.length) renderEmpty();
      input.value = text;
      autosize();
      unsent = text;
      askForKey(error);
    } else {
      fillError(pending, error, text);
    }
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
const testConnection = byId("test-connection", HTMLButtonElement);
const settingsStatus = byId("settings-status", HTMLElement);
const loginForm = byId("login-form", HTMLFormElement);
const password = byId("password", HTMLInputElement);
const loginButton = byId("login-button", HTMLButtonElement);
const logoutButton = byId("logout-button", HTMLButtonElement);
const loginStatus = byId("login-status", HTMLElement);
const autostart = byId("autostart", HTMLInputElement);
const autostartStatus = byId("autostart-status", HTMLElement);

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
  autostart.checked = settings.autostart;
  byId("app-version", HTMLElement).textContent = tr.settings.version(settings.version);
  autostartStatus.textContent = "";
  logoutButton.hidden = !settings.logged_in;
  loginStatus.textContent = "";
  if (keyWanted) {
    // the server refused us: say why, whichever of the two openers ran last
    setLoginStatus(tr.settings.keyNeeded, "err");
    password.focus();
  }
}

function setLoginStatus(text: string, kind: "ok" | "err" | "" = ""): void {
  loginStatus.textContent = text;
  loginStatus.className = kind ? `status ${kind}` : "status";
}

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!password.value) return;
  loginButton.disabled = true;
  api
    .useDeviceKey(password.value)
    .then(() => {
      keyWanted = false;
      password.value = "";
      logoutButton.hidden = false;
      setLoginStatus(unsent ? tr.settings.resend : tr.settings.loggedIn, "ok");
      if (unsent) {
        unsent = null;
        window.setTimeout(() => {
          showView("chat");
        }, 1200);
      }
      void refreshTeam().catch(() => undefined);
    })
    .catch((error: unknown) => {
      setLoginStatus(errorMessage(error), "err");
    })
    .finally(() => {
      loginButton.disabled = false;
    });
});

logoutButton.addEventListener("click", () => {
  void api.logout().then(() => {
    logoutButton.hidden = true;
    setLoginStatus(tr.settings.loggedOut, "ok");
  });
});

autostart.addEventListener("change", () => {
  autostart.disabled = true;
  api
    .setAutostart(autostart.checked)
    .then((enabled) => {
      autostart.checked = enabled;
      autostartStatus.textContent = "";
    })
    .catch(() => {
      autostart.checked = !autostart.checked;
      autostartStatus.textContent = tr.settings.autostartFailed;
      autostartStatus.className = "status err";
    })
    .finally(() => {
      autostart.disabled = false;
    });
});

/** The server wants a device key (first start, revoked key) until one is saved. */
let keyWanted = false;
/** A message the server refused for want of a key: back in the input until it is sent. */
let unsent: string | null = null;

const keyKept = byId("key-kept", HTMLElement);
const keyWhy = byId("key-why", HTMLElement);

/** The key screen (not a red error): what a device key is, where to get one, a button to
 *  the settings. */
function askForKey(error?: unknown): void {
  keyWanted = true;
  const revoked = (error as { code?: string } | undefined)?.code === "device_key_invalid";
  keyWhy.textContent = revoked ? tr.key.invalid : tr.key.why;
  keyKept.hidden = !unsent;
  showView("key");
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

// "Bağlantıyı test et": the address in use with the key typed in the field (before saving
// it) or the saved one; the answer says which.
testConnection.addEventListener("click", () => {
  testConnection.disabled = true;
  setLoginStatus(tr.settings.testing);
  const typed = password.value.trim();
  api
    .testConnection(typed || null)
    .then((report) => {
      const names = report.names.join(", ");
      if (report.typed_key) setLoginStatus(tr.settings.typedKeyOk, "ok");
      else if (report.with_key) setLoginStatus(tr.settings.connectedWithKey(names), "ok");
      else setLoginStatus(tr.settings.connectedNoKey(names), "ok");
      if (!report.typed_key) void refreshTeam().catch(() => undefined);
    })
    .catch((error: unknown) => {
      const code = (error as { code?: string } | null)?.code;
      setLoginStatus(code === "login_required" ? tr.settings.reachedNeedsKey : errorMessage(error), "err");
    })
    .finally(() => {
      testConnection.disabled = false;
    });
});

byId("key-go", HTMLButtonElement).addEventListener("click", () => {
  showView("settings");
});
byId("key-later", HTMLButtonElement).addEventListener("click", () => {
  showView("chat");
});

// ---- start --------------------------------------------------------------------------

function init(): void {
  document.title = tr.appName;
  input.placeholder = tr.chat.placeholder;
  send.textContent = tr.chat.send;
  byId("api-url-label", HTMLElement).textContent = tr.settings.apiUrl;
  apiUrlEnv.textContent = tr.settings.apiUrlFromEnv;
  saveUrl.textContent = tr.settings.save;
  testConnection.textContent = tr.settings.test;
  byId("key-title", HTMLElement).textContent = tr.key.title;
  keyWhy.textContent = tr.key.why;
  keyKept.textContent = tr.key.kept;
  byId("key-steps", HTMLOListElement).replaceChildren(...tr.key.steps.map((step) => el("li", undefined, step)));
  byId("key-go", HTMLButtonElement).textContent = tr.key.go;
  byId("key-later", HTMLButtonElement).textContent = tr.key.later;
  byId("password-label", HTMLElement).textContent = tr.settings.password;
  byId("password-hint", HTMLElement).textContent = tr.settings.passwordHint;
  loginButton.textContent = tr.settings.login;
  logoutButton.textContent = tr.settings.logout;
  byId("autostart-label", HTMLElement).textContent = tr.settings.autostart;
  byId("autostart-hint", HTMLElement).textContent = tr.settings.autostartHint;
  renderEmpty();
  showView("chat");
  // Names/colors are nice to have; the chat works without them. A server that wants a key
  // (first start, revoked key): the settings page asks for one.
  void refreshTeam().catch((error: unknown) => {
    if (needsKey(error)) askForKey(error);
  });
  // A limit warning clicked: open on the screen-time view.
  void getCurrentWebviewWindow().listen<string>("show_view", (event) => {
    if (isView(event.payload)) showView(event.payload);
  });
  // Focus the input each time the panel is opened from the logo.
  window.addEventListener("focus", () => {
    if (view === "chat") input.focus();
  });
}

init();
