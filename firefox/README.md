# zenbuji caption capture (Firefox)

A little sidecar I made so watching anime/YouTube with Japanese subs quietly
*does something*: while it's on, it reads the captions as they go by and sends
them to zenbuji, which keeps the words I don't already know. Next time I open the
dictionary (`zenbuji dict`), the new ones are waiting there to add — and nothing
gets translated until I actually decide to keep a word, so it never eats my DeepL
quota in the background.

It captures only **content words** (nouns, verbs, adjectives) — particles and
punctuation are dropped and verbs are folded to their dictionary form (食べた →
食べる) on the zenbuji side, so one word is one entry.

## Setup

The extension talks to zenbuji over Firefox's *native messaging*, so the host has
to be registered first — `./install.sh` does that for you (it writes the host
manifest to `~/.mozilla/native-messaging-hosts/` and a small wrapper into
`~/.local/bin/`). Make sure you've run the installer once.

Then load the extension itself — it's not signed, so it goes in as a temporary
add-on (this is the easy path for personal use; you'll redo it after a Firefox
restart):

1. Open `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on…**
3. Pick `firefox/zenbuji-capture/manifest.json` from this repo

You should see a 振 toolbar button appear, and the add-on's id should read
`zenbuji-capture@meeksi39` (a random id instead means the native host won't match
— check that the manifest's `allowed_extensions` lines up).

## Using it

Click the toolbar button → **Start capturing**, then play a video with Japanese
captions turned on. The badge counts what's been sent. Open `zenbuji dict` to see
the new words and add the ones you want. Toggle it off when you're done.

## If it's not capturing

- **CC actually on?** It scrapes the on-screen caption text, so the captions have
  to be visible.
- **Badge stays empty / nothing in `~/.local/share/zenbuji/captured.json`?** The
  native host probably isn't connecting. Re-run `./install.sh`, confirm
  `~/.local/bin/zenbuji-native-host` is executable, and that the manifest at
  `~/.mozilla/native-messaging-hosts/com.meeksi39.zenbuji_capture.json` points at
  it. (Flatpak Firefox uses `~/.var/app/org.mozilla.firefox/.mozilla/…` — the
  installer copies it there too.)
- **A `console.warn` about no caption segments** (in the page console) means
  YouTube likely renamed the caption DOM — the selectors to fix are right at the
  top of `content.js`.

## Want it to stick around?

Temporary add-ons vanish when Firefox restarts. For a permanent unsigned install
you need Developer Edition / Nightly with `xpinstall.signatures.required=false`,
or sign it through addons.mozilla.org. The fixed extension id keeps the native
host matching either way.
