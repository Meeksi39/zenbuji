// zenbuji caption capture — background event page.
//
// Owns the long-lived native-messaging port to the zenbuji host, batches the
// caption lines the content script sends, and reflects the on/off toggle to the
// content scripts + the toolbar badge.
//
// The Firefox MV3 event page can be unloaded when idle, which drops the port. We
// don't fight it: ensurePort() reconnects lazily on the next flush (losing at
// most one ~4s batch), and the on/off state lives in storage so a fresh page —
// or a freshly injected content script — picks it back up.

const HOST = "com.meeksi39.zenbuji_capture";
const FLUSH_MS = 4000;
const MAX_BUFFER = 20;

let port = null;
let buffer = [];
let session = 0;
let enabled = false;
let flushTimer = null;

function ensurePort() {
  if (port) return port;
  port = browser.runtime.connectNative(HOST);
  port.onMessage.addListener((reply) => {
    // The host reports a running "new words waiting" count — show it on the badge.
    if (reply && typeof reply.new === "number") {
      browser.action.setBadgeText({ text: reply.new ? String(reply.new) : "" });
    }
  });
  port.onDisconnect.addListener(() => {
    port = null; // reconnect lazily on the next flush
  });
  return port;
}

function flush() {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (!buffer.length) return;
  const lines = buffer.map((b) => b.line);
  const meta = buffer[buffer.length - 1];
  buffer = [];
  try {
    ensurePort().postMessage({
      type: "capture",
      lines,
      title: meta.title,
      url: meta.url,
    });
    session += lines.length;
  } catch (e) {
    console.warn("[zenbuji] native host post failed:", e);
    port = null; // force a reconnect next time
  }
}

function scheduleFlush() {
  if (!flushTimer) flushTimer = setTimeout(flush, FLUSH_MS);
}

function broadcastEnabled() {
  browser.tabs.query({ url: "*://*.youtube.com/*" }).then((tabs) => {
    for (const t of tabs) {
      browser.tabs
        .sendMessage(t.id, { kind: "setEnabled", enabled })
        .catch(() => {});
    }
  });
}

browser.runtime.onMessage.addListener((msg) => {
  if (!msg) return;
  switch (msg.kind) {
    case "line":
      buffer.push({ line: msg.line, title: msg.title, url: msg.url });
      if (buffer.length >= MAX_BUFFER) flush();
      else scheduleFlush();
      return;
    case "queryEnabled":
      return Promise.resolve({ enabled });
    case "getStatus":
      return Promise.resolve({ enabled, session });
    case "setEnabled":
      enabled = !!msg.enabled;
      browser.storage.local.set({ enabled });
      if (!enabled) flush(); // ship whatever's buffered before going quiet
      broadcastEnabled();
      return Promise.resolve({ enabled });
  }
});

browser.storage.local.get("enabled").then((r) => {
  enabled = !!r.enabled;
});
