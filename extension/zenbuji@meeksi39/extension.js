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
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

const LANG_NAMES = {en: 'English', de: 'Deutsch', ja: '日本語'};

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

        const selItem = new PopupMenu.PopupMenuItem(_('Look up current selection'));
        selItem.connect('activate', () => this._extension.lookupSelection());
        this.menu.addMenuItem(selItem);

        const prefsItem = new PopupMenu.PopupMenuItem(_('Settings…'));
        prefsItem.connect('activate', () => this._extension.openPreferences());
        this.menu.addMenuItem(prefsItem);

        // Focus the entry when the menu opens.
        this.menu.connect('open-state-changed', (_m, open) => {
            if (open) {
                this._clearResult();
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
        for (const lang of langs) {
            const val = data.translations ? data.translations[lang] : null;
            this._addInfo(`${LANG_NAMES[lang] || lang}:`,
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
        this._indicator = new ZenbujiIndicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        Main.wm.addKeybinding(
            'lookup-selection',
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            () => this.lookupSelection()
        );
    }

    disable() {
        Main.wm.removeKeybinding('lookup-selection');
        this._indicator?.destroy();
        this._indicator = null;
        this._settings = null;
    }

    cliArgv(args) {
        const cmd = this._settings.get_string('zenbuji-command') || 'zenbuji';
        // Allow a space-separated command (e.g. a wrapper with flags).
        const base = cmd.split(' ').filter(s => s.length > 0);
        return [...base, ...args];
    }

    getLanguages() {
        // The CLI owns the canonical config; default to en/de for the menu.
        return ['en', 'de'];
    }

    lookupSelection() {
        try {
            const proc = new Gio.Subprocess({
                argv: this.cliArgv(['popup', '--selection']),
                flags: Gio.SubprocessFlags.STDERR_PIPE,
            });
            proc.init(null);
        } catch (e) {
            Main.notify('zenbuji', `${e}`);
        }
    }
}
