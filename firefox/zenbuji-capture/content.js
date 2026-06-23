// zenbuji caption capture - content script.
//
// Scrapes the on-screen YouTube caption text and forwards each new line to the
// background page, which batches them and ships them to the native host. Capture
// is opt-in (toggled from the toolbar popup) and only runs while it's enabled.
//
// The caption DOM is the one fragile bit - if YouTube renames these classes, fix
// them here (and only here). See firefox/README.md.

const SEL_CONTAINER = ".ytp-caption-window-container";
const SEL_SEGMENT = ".ytp-caption-segment";

let enabled = false;
let lastLine = "";
let observer = null;
let sawSegment = false;
let warnedEmpty = false;

function currentCaptionText() {
  const segs = document.querySelectorAll(`${SEL_CONTAINER} ${SEL_SEGMENT}`);
  if (segs.length) sawSegment = true;
  return Array.from(segs)
    .map((s) => s.textContent.trim())
    .filter(Boolean)
    .join("")
    .trim();
}

function videoTitle() {
  return document.title.replace(/\s*-\s*YouTube\s*$/, "").trim();
}

function emit(line) {
  if (!enabled || !line || line === lastLine) return;
  lastLine = line; // only fire when the on-screen caption actually changes
  browser.runtime.sendMessage({
    kind: "line",
    line,
    title: videoTitle(),
    url: location.href.split("&")[0],
  });
}

function onMutate() {
  emit(currentCaptionText());
  // Captions clearly on but our selector never matches? Say so once - an early
  // signal that YouTube changed the caption DOM.
  if (enabled && !sawSegment && !warnedEmpty) {
    warnedEmpty = true;
    console.warn(
      "[zenbuji] capturing, but no caption segments matched yet - is CC on? " +
        "(if it is, the YouTube caption selector may have changed)"
    );
  }
}

function startObserver() {
  if (observer) return;
  observer = new MutationObserver(onMutate);
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
}

function stopObserver() {
  if (observer) {
    observer.disconnect();
    observer = null;
  }
}

function setEnabled(on) {
  enabled = on;
  if (on) startObserver();
  else stopObserver();
}

browser.runtime.onMessage.addListener((msg) => {
  if (msg && msg.kind === "setEnabled") setEnabled(!!msg.enabled);
});

// Moving between videos keeps this script alive (YouTube is a SPA) - reset the
// dedup + diagnostics so the next video starts clean.
window.addEventListener("yt-navigate-finish", () => {
  lastLine = "";
  sawSegment = false;
  warnedEmpty = false;
});

// On (re)injection, pick up the persisted on/off state from the background.
browser.runtime
  .sendMessage({ kind: "queryEnabled" })
  .then((r) => setEnabled(!!(r && r.enabled)))
  .catch(() => {});
