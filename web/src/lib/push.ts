/**
 * Web Push in the browser: service worker (public/sw.js), permission, subscription.
 * iPhone: only works in the app added to the home screen (Safari → Paylaş → Ana Ekrana Ekle),
 * iOS 16.4+.
 */
import { apiGet, apiPost } from "../api/client";

export type PushState =
  | "unsupported" // no service worker / PushManager (plain http from a phone, old browser)
  | "ios-browser" // iPhone Safari tab: add to home screen first
  | "server-off" // no VAPID keys on the server
  | "denied" // notifications blocked for this site
  | "off"
  | "on";

interface PushKey {
  enabled: boolean;
  public_key: string | null;
  subscriptions: number;
}

/** VAPID public key (base64url) -> the bytes PushManager wants. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export function isIosBrowserTab(nav: Navigator = navigator): boolean {
  const ios = /iPhone|iPad|iPod/.test(nav.userAgent);
  const standalone =
    (nav as Navigator & { standalone?: boolean }).standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches;
  return ios && !standalone;
}

function supported(): boolean {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** Registers the service worker once (main.tsx); quietly does nothing where unsupported. */
export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration("/");
  return existing ?? navigator.serviceWorker.register("/sw.js");
}

export async function pushState(): Promise<PushState> {
  if (isIosBrowserTab()) return "ios-browser";
  if (!supported()) return "unsupported";
  const key = await apiGet<PushKey>("/push/key");
  if (!key.enabled) return "server-off";
  if (Notification.permission === "denied") return "denied";
  const subscription = await (
    await registration()
  ).pushManager.getSubscription();
  return subscription ? "on" : "off";
}

/** Asks for permission (must run from a click), subscribes, tells the server. */
export async function enablePush(): Promise<PushState> {
  const key = await apiGet<PushKey>("/push/key");
  if (!key.enabled || !key.public_key) return "server-off";
  const permission = await Notification.requestPermission();
  if (permission !== "granted")
    return permission === "denied" ? "denied" : "off";
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const subscription =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(key.public_key),
    }));
  await apiPost("/push/subscribe", subscription.toJSON());
  return "on";
}

export async function disablePush(): Promise<PushState> {
  const subscription = await (
    await registration()
  ).pushManager.getSubscription();
  if (subscription) {
    await apiPost("/push/unsubscribe", { endpoint: subscription.endpoint });
    await subscription.unsubscribe();
  }
  return "off";
}

export async function sendTestPush(): Promise<{
  sent: number;
  removed: number;
  failed: number;
}> {
  return apiPost("/push/test");
}
