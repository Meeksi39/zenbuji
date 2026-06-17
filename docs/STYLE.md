# zenbuji visual style guide

How zenbuji's GTK4 surfaces look and feel, so new windows match the existing
ones. The whole UI is built from one shared scaffold (`bin/zenbuji_glass.py`) and
a single stylesheet (`GLASS_CSS` in that file). Reuse those classes — don't
invent per-window styles.

## Principles

- **Frosted glass, Apple-like.** Every window is a translucent rounded card over
  a blurred background (Blur My Shell). Calm, soft, lots of breathing room.
- **One focal point per screen.** Size contrast carries hierarchy (e.g. the huge
  kanji in the quiz; the big stat numbers).
- **Accent-driven, sparing color.** The system accent is *the* color. Everything
  else is the theme foreground at varying opacity. Reserve strong color (red,
  green, level hues) for meaning, never decoration.
- **Pills and soft corners.** Rounded everything; controls read as pills/tiles.
- **Restraint over chrome.** Whitespace and typography first; borders/shadows are
  faint. Minimal emoji (see below).
- **Theme-aware.** Follow the system light/dark scheme and accent color live —
  never hard-code window background colors.

## The window scaffold

`make_glass_window(app, *, title, default_size, resizable, draggable,
close_on_focus_loss)` → `(window, card)` (`zenbuji_glass.py`). It returns a
transparent, headerless window and a `.zenbuji-card` vertical box (spacing 10,
18px padding) to fill. It already handles: light/dark `.zenbuji-card`
variant, Escape-to-close, drag-from-empty-space, and optional focus-loss
dismissal. **Always build new surfaces on this** — never a bare
`Gtk.ApplicationWindow`. Use `application_id="com.meeksi39.zenbuji"` +
`NON_UNIQUE` so windows coexist and the Blur My Shell whitelist matches.

## Color

- **Accent**: use the CSS vars `@accent_color` (vivid, for text/borders/icons)
  and `@accent_bg_color` (for filled buttons). For cairo/Pango where CSS can't
  reach, use the helpers `accent_hex(dark)` and `accent_rgba(dark)`.
- **Foreground washes**: `alpha(currentColor, 0.05–0.16)` for fills, dividers,
  faint tracks. This auto-adapts to light/dark.
- **SRS level palette** (fixed hues, mirrored in CSS `.zenbuji-level-*` and in
  `LEVEL_HEX` in `zenbuji_stats.py`):
  - New `#8a8f96` grey · Learning `#e5a50a` amber · Young `#3584e4` blue ·
    Mature `#2ec27e` green.
- **Status**: correct `#21915c`, wrong `#c0182a`, destructive `#e01b24`.

## Typography (sizes in GLASS_CSS)

| Role | Class | Size/weight |
|---|---|---|
| Window title | `.zenbuji-title` | 17 / 700 |
| Hero kanji (quiz) | `.zenbuji-kanji` | 54 / 700 |
| Big stat number | `.zenbuji-stat-num` (+`-accent`) | 29 / 700 |
| Revealed reading | `.zenbuji-reveal-reading` | 27 / 700 accent |
| Reading (furigana) | `.zenbuji-reading` | 15 accent |
| Translation | `.zenbuji-translation` | 15 |
| Section caption | `.zenbuji-lang-label` | 11 / 700, 0.55 opacity, uppercased in code |
| Caption / stat label | `.zenbuji-stat-label` | 10, letter-spaced |
| Meta / timestamps | `.zenbuji-meta` | 10, 0.5 opacity |

Uppercase section captions in Python (`.upper()`); CSS has no `text-transform`.

## Components

- **Primary button** `.zenbuji-action`: accent-filled with a top-down gradient, a
  real drop shadow + faint accent glow, radius 12, `7px 16px` padding. Deeper
  shadow on hover; settles on `:active`.
- **Secondary button** `.zenbuji-secondary`: translucent `currentColor` fill +
  faint border, same size. Has explicit `:active`/`:checked` (faint fill) so the
  label stays readable.
- **Buttons next to an input must match its height.** Keep padding aligned, or
  set the button `valign=FILL` in a 0-spacing row to fuse them (see the quiz
  combo pill below).
- **Flat icon buttons** `.zenbuji-icon`: neutral (`alpha(currentColor,0.45)`) by
  default, accent on hover — keeps dense rows (dictionary) calm. Destructive uses
  `.zenbuji-icon-danger` (stays red).
- **Text inputs**: default `.zenbuji-card entry` is subtle/translucent (popup,
  dict search). The quiz answer field is the *only* "hero" input —
  `.zenbuji-quiz-input` (larger, near-white, dark text, accent focus ring). Fuse
  a field with a trailing action via `.zenbuji-combo` on the entry +
  `.zenbuji-quiz-go` on the button (squares the seam → one pill).
- **Soft panel** `.zenbuji-panel`: inset rounded group with a faint fill — use to
  cluster related stats (the hero row).
- **Level badge** `.zenbuji-level` + `.zenbuji-level-<level>`: small colored pill.
- **Verdict chip** `.zenbuji-verdict` + `-ok`/`-no`: bold status pill.
- **Hairline** `.zenbuji-hairline` (horizontal) / `.zenbuji-vrule` (vertical):
  1px `alpha(currentColor,0.12)` separators.
- **Progress bar**: add `.zenbuji-quiz-progress` for the slim rounded accent bar.

## Layout & spacing

- Card padding 18px; card box spacing ~10. Section captions get ~18px top margin
  for air between groups.
- Constrain interactive content to a **centered column** (~300–320px) rather than
  stretching edge-to-edge — see `_answer_col()` in `zenbuji_learn.py`. Full-width
  slabs look cheap; centered columns with margin look intentional.
- A little intentional asymmetry beats rigid centering for actions (e.g. the
  fused input+arrow).

## Iconography & emoji

- Prefer **symbolic icons** (`*-symbolic`, e.g. `go-next-symbolic`,
  `audio-volume-high-symbolic`). Verify the name exists in Adwaita before using
  it — a missing name renders blank. No icon for "stats/chart" exists in Adwaita,
  so that's a text label.
- **Minimal emoji.** The only sanctioned glyphs are the ✓/✗ verdict marks and 🔊
  for read-aloud. Don't sprinkle 🔥/📊/⬆ etc. — convey meaning with shape, color,
  and layout instead.

## Charts (cairo)

Draw charts with a `Gtk.DrawingArea` + `set_draw_func` (see `zenbuji_stats.py`):
rounded pills/segments via a local `_rounded_rect`, accent fill from
`accent_rgba(get_dark())`, faint `currentColor` tracks for empty/zero. Connect
`Adw.StyleManager` `notify::dark` → `queue_draw()` so charts re-theme live.

## Motion

Transient flourishes use `Adw.TimedAnimation` fading a `Gtk.Overlay` child
(see `celebrate()` / `_fade_overlay` in `zenbuji_learn.py`). Keep a reference to
the animation so it isn't GC'd mid-play. Short (≤1.3s), ease-out.

## GTK gotchas (learned the hard way)

- **`GLASS_CSS` is a `b"""..."""` byte-string → ASCII only.** No em-dashes/curly
  quotes in CSS comments or it won't import. Use `-` and `'`.
- **Rounding a `Gtk.Picture`/image needs `set_overflow(Gtk.Overflow.HIDDEN)`** —
  `border-radius` alone only rounds the CSS box, not the texture.
- **Unset the window default widget/focus before destroying it.** Destroying the
  current default (e.g. on a phase swap) while the window still points at it is a
  use-after-free → SIGSEGV in `gtk_widget_remove_css_class`. Clear
  `set_default_widget(None)` / `set_focus(None)` *before* removing the children
  (see `clear_phase()` in `zenbuji_learn.py`).
- CSS is installed once at `Gtk.STYLE_PROVIDER_PRIORITY_USER`; the transparent
  window needs the element-qualified `window.zenbuji-window` selector or the
  theme's opaque background wins.

## Adding a new surface — checklist

1. Build it with `make_glass_window`; fill the returned `card`.
2. Reuse the classes above; add a new class to `GLASS_CSS` only for a genuinely
   new component (ASCII-only).
3. Title + section captions follow the type scale; cluster with `.zenbuji-panel`
   and space sections generously.
4. Symbolic icons (verified) or text — not emoji.
5. Localize strings via a per-module `*_STRINGS` table keyed by `ui_language`
   (`en`/`ja`), like the other windows.
6. Launch it and tail `journalctl -f -o cat /usr/bin/gnome-shell`; check both
   light and dark and confirm no CSS parsing errors.
