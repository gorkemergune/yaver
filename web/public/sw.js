// Yaver service worker: Web Push only (no offline cache, so a new build is never stale).
// Payload from backend/app/services/push.py: {title, body, url, tag}.

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Yaver";
  const options = {
    body: data.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/badge-96.png",
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    data: { url: data.url || "/#/chat" },
  };
  event.waitUntil(
    Promise.all([
      self.registration.showNotification(title, options),
      // An open app refreshes its chat right away (and tests can see the push arrived).
      self.clients
        .matchAll({ type: "window", includeUncontrolled: true })
        .then((clients) => clients.forEach((client) => client.postMessage({ type: "push", title, ...options }))),
    ]),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/#/chat", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const open = clients.find((client) => new URL(client.url).origin === self.location.origin);
      if (open) {
        return open.focus().then((client) => (client && "navigate" in client ? client.navigate(url) : client));
      }
      return self.clients.openWindow(url);
    }),
  );
});
