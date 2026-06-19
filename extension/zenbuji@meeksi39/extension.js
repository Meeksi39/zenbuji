/* zenbuji — GNOME Shell extension
 *
 * Top-bar menu: type or paste Japanese text and get furigana + EN/DE inline.
 * Global hotkey: look up the current PRIMARY selection in a popup window.
 *
 * All language processing happens in the `zenbuji` Python CLI; this extension
 * only spawns it and renders the JSON it prints.
 */

import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Target-language section labels, shown in the interface language.
const LANG_NAMES_BY_UI = {
    en: {en: 'English', de: 'Deutsch', ja: '日本語'},
    ja: {en: '英語', de: 'ドイツ語', ja: '日本語'},
};

// Interface strings, by language. The UI language is a zenbuji config setting
// (config.json), so translation is config-driven rather than locale-driven:
// `_` is rebound when the extension enables. Japanese maps English msgid->ja;
// missing keys (and English) fall through to the msgid.
const UI_JA = {
    'Type or paste Japanese…': '日本語を入力または貼り付け…',
    'Recent': '履歴',
    'No recent lookups': '履歴はありません',
    'Look up current selection': '選択テキストを調べる',
    'Look up screen region (OCR)': '画面領域を調べる（OCR）',
    'Add screen region to dictionary (OCR)': '画面領域を辞書に追加（OCR）',
    'Dictionary': '辞書',
    'Practice (SRS)': '練習（SRS）',
    'Statistics': '統計',
    'Game helper': 'ゲームヘルパー',
    'Start VOICEVOX': 'VOICEVOX を起動',
    'Starting VOICEVOX…': 'VOICEVOX を起動中…',
    'Settings…': '設定…',
    'Looking up…': '検索中…',
};
let _ = s => s;

function runJson(argv, callback) {
    try {
        const proc = new Gio.Subprocess({
            argv,
            flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
        });
        proc.init(null);
        proc.communicate_utf8_async(null, null, (p, res) => {
            try {
                const [, stdout, stderr] = p.communicate_utf8_finish(res);
                if (p.get_exit_status() !== 0) {
                    callback(null, stderr || 'zenbuji failed');
                    return;
                }
                callback(JSON.parse(stdout), null);
            } catch (e) {
                callback(null, `${e}`);
            }
        });
    } catch (e) {
        callback(null, `${e}`);
    }
}

const ZenbujiIndicator = GObject.registerClass(
class ZenbujiIndicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.0, 'zenbuji');
        this._extension = extension;

        this.add_child(new St.Label({
            text: '振',
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-weight: 700;',
        }));

        // --- Input row ---------------------------------------------------- //
        const entryItem = new PopupMenu.PopupBaseMenuItem({
            activate: false,
            reactive: true,
            can_focus: false,
        });
        this._entry = new St.Entry({
            hint_text: _('Type or paste Japanese…'),
            can_focus: true,
            x_expand: true,
            style_class: 'zenbuji-entry',
        });
        this._entry.clutter_text.connect('activate', () => this._lookupEntry());
        entryItem.add_child(this._entry);
        this.menu.addMenuItem(entryItem);

        // --- Result area -------------------------------------------------- //
        this._resultSection = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._resultSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // --- Recent lookups ----------------------------------------------- //
        this._recentSub = new PopupMenu.PopupSubMenuMenuItem(_('Recent'));
        this.menu.addMenuItem(this._recentSub);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const selItem = new PopupMenu.PopupMenuItem(_('Look up current selection'));
        selItem.connect('activate', () => this._extension.lookupSelection());
        this.menu.addMenuItem(selItem);

        const ocrItem = new PopupMenu.PopupMenuItem(_('Look up screen region (OCR)'));
        ocrItem.connect('activate', () => this._extension.lookupRegion());
        this.menu.addMenuItem(ocrItem);

        const ocrAddItem = new PopupMenu.PopupMenuItem(_('Add screen region to dictionary (OCR)'));
        ocrAddItem.connect('activate', () => this._extension.addRegion());
        this.menu.addMenuItem(ocrAddItem);

        const dictItem = new PopupMenu.PopupMenuItem(_('Dictionary'));
        dictItem.connect('activate', () => this._extension.openDictionary());
        this.menu.addMenuItem(dictItem);

        const learnItem = new PopupMenu.PopupMenuItem(_('Practice (SRS)'));
        learnItem.connect('activate', () => this._extension.openLearning());
        this.menu.addMenuItem(learnItem);

        const statsItem = new PopupMenu.PopupMenuItem(_('Statistics'));
        statsItem.connect('activate', () => this._extension.openStatistics());
        this.menu.addMenuItem(statsItem);

        const gameItem = new PopupMenu.PopupMenuItem(_('Game helper'));
        gameItem.connect('activate', () => this._extension.openGame());
        this.menu.addMenuItem(gameItem);

        if (this._extension.voicevoxAvailable()) {
            const vvItem = new PopupMenu.PopupMenuItem(_('Start VOICEVOX'));
            vvItem.connect('activate', () => this._extension.startVoicevox(true));
            this.menu.addMenuItem(vvItem);
        }

        const prefsItem = new PopupMenu.PopupMenuItem(_('Settings…'));
        prefsItem.connect('activate', () => this._extension.openPreferences());
        this.menu.addMenuItem(prefsItem);

        // Focus the entry when the menu opens.
        this.menu.connect('open-state-changed', (_m, open) => {
            if (open) {
                this._clearResult();
                this._populateRecent();
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
                    global.stage.set_key_focus(this._entry.clutter_text);
                    return GLib.SOURCE_REMOVE;
                });
            }
        });
    }

    _clearResult() {
        this._resultSection.removeAll();
    }

    _populateRecent() {
        const menu = this._recentSub.menu;
        menu.removeAll();
        const history = this._extension.readHistory();
        if (!history.length) {
            const empty = new PopupMenu.PopupMenuItem(_('No recent lookups'));
            empty.sensitive = false;
            menu.addMenuItem(empty);
            return;
        }
        for (const entry of history) {
            const item = new PopupMenu.PopupMenuItem(entry.text || '');
            if (entry.reading && entry.reading !== entry.text) {
                item.label.text = `${entry.text}（${entry.reading}）`;
            }
            item.connect('activate', () => this._extension.lookupText(entry.text || ''));
            menu.addMenuItem(item);
        }
    }

    _addInfo(text, style) {
        const item = new PopupMenu.PopupMenuItem('');
        item.label.clutter_text.set_line_wrap(true);
        item.label.text = text;
        if (style)
            item.label.set_style(style);
        item.sensitive = false;
        this._resultSection.addMenuItem(item);
    }

    _lookupEntry() {
        const text = this._entry.get_text().trim();
        if (!text)
            return;
        this._clearResult();
        this._addInfo(_('Looking up…'), 'opacity: 0.6;');
        const cmd = this._extension.cliArgv(['read', '--json', text]);
        runJson(cmd, (data, err) => {
            this._clearResult();
            if (err) {
                this._addInfo(`⚠ ${err}`, 'opacity: 0.7; font-size: 11px;');
                return;
            }
            this._renderResult(data);
        });
    }

    _renderResult(data) {
        if (data.reading && data.reading !== data.text)
            this._addInfo(data.reading, 'font-size: 15px; opacity: 0.8;');

        const langs = this._extension.getLanguages();
        const names = LANG_NAMES_BY_UI[this._extension.uiLang()] || LANG_NAMES_BY_UI.en;
        for (const lang of langs) {
            const val = data.translations ? data.translations[lang] : null;
            this._addInfo(`${names[lang] || lang}:`,
                'font-weight: 700; font-size: 11px; opacity: 0.6;');
            this._addInfo(val || '—', 'font-size: 14px; padding-bottom: 4px;');
        }
        for (const note of (data.notes || []))
            this._addInfo(note, 'font-size: 10px; font-style: italic; opacity: 0.5;');
    }
});

export default class ZenbujiExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        const lang = this.uiLang();
        _ = (s) => (lang === 'ja' && UI_JA[s]) ? UI_JA[s] : s;
        this._indicator = new ZenbujiIndicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        // If VOICEVOX is the chosen TTS engine, make sure its local service is
        // running so the first read-aloud doesn't fall back to the system voice.
        this._maybeStartVoicevox();
        // The global selection hotkey (Super+J) is a GNOME custom keybinding set
        // up by install.sh — it works without the extension and avoids a
        // double-binding conflict, so it is intentionally not registered here.

        // Keep a fullscreen game alive when a zenbuji popup appears over it (see
        // _onWindowCreated). Without the extension enabled the popup is just a
        // normal focus-stealing window, so this is a best-effort enhancement.
        this._windowCreatedId = global.display.connect(
            'window-created', this._onWindowCreated.bind(this));
    }

    disable() {
        if (this._windowCreatedId) {
            global.display.disconnect(this._windowCreatedId);
            this._windowCreatedId = null;
        }
        this._indicator?.destroy();
        this._indicator = null;
        this._settings = null;
    }

    // The id GTK sets on the popup / dictionary / practice windows (Wayland),
    // matching the Adw.Application id used by the CLI.
    static APP_ID = 'com.meeksi39.zenbuji';

    _findFullscreenWindow() {
        // A Proton/Wine fullscreen window is still in the tab list (and still
        // reports fullscreen) even after it minimises itself on focus loss.
        const wins = global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null);
        for (const w of wins) {
            try {
                if (w.is_fullscreen())
                    return w;
            } catch (_e) { /* window vanished */ }
        }
        return null;
    }

    _isZenbujiWindow(win) {
        try {
            if (win.get_gtk_application_id?.() === ZenbujiExtension.APP_ID)
                return true;
        } catch (_e) { /* not a GTK/Wayland window */ }
        try {
            return win.get_wm_class?.() === ZenbujiExtension.APP_ID;
        } catch (_e) {
            return false;
        }
    }

    // A zenbuji window (popup/dictionary/practice) just appeared. If a fullscreen
    // window is underneath — typically a Proton/Wine game, which minimises itself
    // the moment it loses focus — move the popup onto a different monitor (so the
    // game stays visible) and hand focus back to the game so it isn't left
    // minimised. The popup stays on top but unfocused; OCR popups don't
    // close-on-focus-loss, so the result remains readable while you keep playing.
    _onWindowCreated(_display, win) {
        if (!this._isZenbujiWindow(win))
            return;

        const game = this._findFullscreenWindow();
        if (!game)
            return; // ordinary desktop use — let the popup behave normally

        const gameMonitor = game.get_monitor();

        const reposition = () => {
            try {
                const nMonitors = global.display.get_n_monitors();
                if (nMonitors > 1) {
                    let target = -1;
                    for (let i = 0; i < nMonitors; i++) {
                        if (i !== gameMonitor) { target = i; break; }
                    }
                    if (target >= 0 && win.get_monitor() !== target)
                        win.move_to_monitor(target);
                }
                win.make_above();
                if (game.minimized)
                    game.unminimize();
                game.activate(global.get_current_time());
            } catch (e) {
                logError(e, 'zenbuji: repositioning popup over fullscreen window');
            }
        };

        // Restore the game once more when the popup is dismissed, in case the
        // user focused the popup (to correct OCR text) and the game minimised
        // itself again.
        win.connect('unmanaged', () => {
            try {
                if (game.minimized)
                    game.unminimize();
                game.activate(global.get_current_time());
            } catch (_e) { /* game closed in the meantime */ }
        });

        const actor = win.get_compositor_private();
        if (actor) {
            const id = actor.connect('first-frame', () => {
                actor.disconnect(id);
                reposition();
            });
        } else {
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
                reposition();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    cliArgv(args) {
        const cmd = this._settings.get_string('zenbuji-command') || 'zenbuji';
        // Allow a space-separated command (e.g. a wrapper with flags).
        const base = cmd.split(' ').filter(s => s.length > 0);
        return [...base, ...args];
    }

    // Read the canonical CLI config file directly (no Python startup needed).
    _readConfig() {
        try {
            const path = GLib.build_filenamev(
                [GLib.get_user_config_dir(), 'zenbuji', 'config.json']);
            const [ok, bytes] = GLib.file_get_contents(path);
            if (!ok)
                return {};
            return JSON.parse(new TextDecoder().decode(bytes)) || {};
        } catch (_e) {
            return {};
        }
    }

    // Recent lookups recorded by the CLI in its data dir.
    readHistory() {
        try {
            const path = GLib.build_filenamev(
                [GLib.get_user_data_dir(), 'zenbuji', 'history.json']);
            const [ok, bytes] = GLib.file_get_contents(path);
            if (!ok)
                return [];
            const data = JSON.parse(new TextDecoder().decode(bytes));
            return Array.isArray(data) ? data : [];
        } catch (_e) {
            return [];
        }
    }

    getLanguages() {
        const langs = this._readConfig().languages;
        return Array.isArray(langs) && langs.length ? langs : ['en', 'de'];
    }

    uiLang() {
        return this._readConfig().ui_language === 'ja' ? 'ja' : 'en';
    }

    lookupSelection() {
        this._spawnPopup(['popup', '--selection']);
    }

    lookupText(text) {
        if (!text)
            return;
        this._spawnPopup(['popup', text]);
    }

    lookupRegion() {
        this._spawnPopup(['popup', '--ocr']);
    }

    // Same screen-region OCR, but no popup: translate, store in the dictionary,
    // and read the word aloud — all in the background.
    addRegion() {
        this._spawnPopup(['add', '--ocr', '--speak']);
    }

    openDictionary() {
        this._spawnPopup(['dict']);
    }

    openLearning() {
        this._spawnPopup(['learn']);
    }

    openStatistics() {
        this._spawnPopup(['stats']);
    }

    openGame() {
        this._spawnPopup(['game']);
    }

    _spawnPopup(args) {
        try {
            const proc = new Gio.Subprocess({
                argv: this.cliArgv(args),
                flags: Gio.SubprocessFlags.STDERR_PIPE,
            });
            proc.init(null);
        } catch (e) {
            Main.notify('zenbuji', `${e}`);
        }
    }

    // The Quadlet unit ./install.sh --voicevox writes; its presence means the
    // user has set the VOICEVOX engine up as a systemd --user service.
    _voicevoxUnitPath() {
        return GLib.build_filenamev(
            [GLib.get_user_config_dir(), 'containers', 'systemd', 'voicevox.container']);
    }

    voicevoxAvailable() {
        try {
            return GLib.file_test(this._voicevoxUnitPath(), GLib.FileTest.EXISTS);
        } catch (_e) {
            return false;
        }
    }

    // Start the VOICEVOX service (no-op if already running). With notify=true,
    // confirm to the user — used by the menu item; the auto-start on enable is
    // silent.
    startVoicevox(notify = false) {
        try {
            const proc = new Gio.Subprocess({
                argv: ['systemctl', '--user', 'start', 'voicevox.service'],
                flags: Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE,
            });
            proc.init(null);
            if (notify)
                Main.notify('zenbuji', _('Starting VOICEVOX…'));
        } catch (e) {
            Main.notify('zenbuji', `${e}`);
        }
    }

    _maybeStartVoicevox() {
        try {
            const engine = this._readConfig().tts_engine || 'auto';
            if ((engine === 'voicevox' || engine === 'auto') && this.voicevoxAvailable())
                this.startVoicevox(false);
        } catch (_e) { /* best effort — never block enable() */ }
    }
}
