import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const BACKENDS = ['auto', 'argos', 'deepl'];
const BACKEND_LABELS = ['Auto (DeepL if key set)', 'Offline (Argos)', 'DeepL'];

// The two global hotkeys live as GNOME custom keybindings (created by
// install.sh); the prefs UI edits their accelerator in place.
const KB_SCHEMA = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding';
const KB_BASE = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/';

// Config-driven UI translation (mirrors extension.js): the interface language
// is a zenbuji config setting, not the system locale, so `_` is rebound from
// config before the window is built. Japanese maps the English msgid -> ja;
// missing keys (and English) fall through to the msgid unchanged.
const UI_JA = {
    'Auto (DeepL if key set)': '自動（キーがあれば DeepL）',
    'Offline (Argos)': 'オフライン（Argos）',
    'DeepL': 'DeepL',
    'Translation': '翻訳',
    'Stored in the zenbuji config, shared with the CLI, popup, and file-manager surfaces.':
        'zenbuji の設定に保存され、CLI・ポップアップ・ファイルマネージャーと共有されます。',
    'Backend': 'バックエンド',
    'DeepL API key': 'DeepL API キー',
    'Verify DeepL key': 'DeepL キーを確認',
    'Checks the key above and shows remaining quota.': '上記のキーを確認し、残りの利用量を表示します。',
    'Verify': '確認',
    'Checking…': '確認中…',
    'characters used': '文字使用',
    'check failed': '確認に失敗しました',
    'English': '英語',
    'German': 'ドイツ語',
    'Languages': '翻訳言語',
    'Which translations to show, in order.': '表示する翻訳とその順序。',
    'History': '履歴',
    'Keep recent lookups': '最近の検索を保存',
    'Show them in the top-bar “Recent” menu.': 'トップバーの「履歴」メニューに表示します。',
    'Clear history': '履歴を消去',
    'Clear': '消去',
    'Cleared.': '消去しました。',
    'Advanced': '詳細設定',
    'Selection hotkey': '選択ホットキー',
    'Super+J is a GNOME custom shortcut (Settings ▸ Keyboard). Re-bind it there or with dconf.':
        'Super+J は GNOME のカスタムショートカットです（設定 ▸ キーボード）。そこか dconf で変更できます。',
    'Screen-region OCR': '画面領域 OCR',
    'Super+Shift+J (or the top-bar “Look up screen region”) reads on-screen Japanese via OCR. Needs the full (non---light) install for the OCR model.':
        'Super+Shift+J（またはトップバーの「画面領域を調べる」）で画面上の日本語を OCR で読み取ります。OCR モデルにはフル（--light でない）インストールが必要です。',
    'zenbuji command': 'zenbuji コマンド',
    'Could not read zenbuji config — check the command in Advanced.':
        'zenbuji の設定を読み込めませんでした — 詳細設定のコマンドを確認してください。',
    'Build a local dictionary': 'ローカル辞書を作成',
    'Cache DeepL translations and reuse them (saves quota); browse them in the Dictionary window.':
        'DeepL 翻訳をキャッシュして再利用します（クォータ節約）。辞書ウィンドウで閲覧できます。',
    'Popup': 'ポップアップ',
    'Close when it loses focus': 'フォーカスを失ったら閉じる',
    'Dismiss the popup automatically when you click elsewhere.':
        '他の場所をクリックすると自動的に閉じます。',
    'Shortcuts': 'ショートカット',
    'Click a shortcut to change it. These are GNOME custom keybindings.':
        'ショートカットをクリックして変更します（GNOME のカスタムキーバインド）。',
    'Look up selection': '選択テキストを調べる',
    'Look up screen region (OCR)': '画面領域を調べる（OCR）',
    'Needs the full (non---light) install for the OCR model.':
        'OCR モデルにはフル（--light でない）インストールが必要です。',
    'Disabled': '無効',
    'Type the new shortcut…  (Esc cancel · Backspace clear)':
        '新しいショートカットを入力…  (Esc で取消 · Backspace で消去)',
    'Run install.sh to create this shortcut.':
        'このショートカットを作成するには install.sh を実行してください。',
    'Interface': 'インターフェース',
    'Interface language': '表示言語',
    'Language of the popup, menu, and this settings window.': 'ポップアップ・メニュー・この設定画面の言語。',
    'Reopen settings to see this window in the new language.':
        '新しい言語でこの画面を表示するには設定を開き直してください。',
};
let _ = s => s;

/* Read the UI language from the shared zenbuji config file, synchronously, so
 * the window can be built in the right language before the CLI is queried. */
function readUiLang() {
    try {
        const path = GLib.build_filenamev(
            [GLib.get_user_config_dir(), 'zenbuji', 'config.json']);
        const [ok, bytes] = GLib.file_get_contents(path);
        if (!ok)
            return 'en';
        const cfg = JSON.parse(new TextDecoder().decode(bytes)) || {};
        return cfg.ui_language === 'ja' ? 'ja' : 'en';
    } catch (_e) {
        return 'en';
    }
}

export default class ZenbujiPrefs extends ExtensionPreferences {
    /* Resolve the CLI command from the same gsetting the extension uses. */
    _cliArgv(settings, args) {
        const cmd = settings.get_string('zenbuji-command') || 'zenbuji';
        const base = cmd.split(' ').filter(s => s.length > 0);
        return [...base, ...args];
    }

    /* Run `zenbuji <args>`; call cb(parsedJsonOrNull, errString). */
    _runCli(settings, args, cb) {
        try {
            const proc = new Gio.Subprocess({
                argv: this._cliArgv(settings, args),
                flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            });
            proc.init(null);
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    const [, stdout, stderr] = p.communicate_utf8_finish(res);
                    let data = null;
                    try {
                        data = JSON.parse(stdout);
                    } catch (_e) {
                        // Non-JSON output (e.g. a plain "saved" line) — fine.
                    }
                    cb(data, p.get_exit_status() === 0 ? null : (stderr || 'failed'));
                } catch (e) {
                    cb(null, `${e}`);
                }
            });
        } catch (e) {
            cb(null, `${e}`);
        }
    }

    _setConfig(settings, args) {
        this._runCli(settings, ['config', ...args], () => {});
    }

    /* A row whose suffix shows the current accelerator of a GNOME custom
     * keybinding and lets the user re-capture it. `slug` is the keybinding's
     * dconf folder name (created by install.sh). */
    _makeShortcutRow(title, subtitle, slug) {
        let kb = null;
        try {
            kb = Gio.Settings.new_with_path(KB_SCHEMA, KB_BASE + slug + '/');
        } catch (_e) {
            kb = null;
        }
        const row = new Adw.ActionRow({title, subtitle});
        const label = new Gtk.ShortcutLabel({
            valign: Gtk.Align.CENTER,
            disabled_text: _('Disabled'),
        });
        const btn = new Gtk.Button({valign: Gtk.Align.CENTER, child: label});
        btn.add_css_class('flat');
        const refresh = () =>
            label.set_accelerator(kb ? (kb.get_string('binding') || '') : '');
        if (kb) {
            refresh();
            btn.connect('clicked',
                () => this._captureShortcut(row, subtitle, btn, label, kb, refresh));
        } else {
            row.set_subtitle(_('Run install.sh to create this shortcut.'));
            btn.set_sensitive(false);
        }
        row.add_suffix(btn);
        row.set_activatable_widget(btn);
        return row;
    }

    /* Grab the next key combo and write it to the keybinding. Esc cancels,
     * Backspace clears (disables) the shortcut. */
    _captureShortcut(row, baseSubtitle, btn, label, kb, refresh) {
        const win = row.get_root();
        if (!win)
            return;
        btn.set_sensitive(false);
        label.set_accelerator('');
        row.set_subtitle(_('Type the new shortcut…  (Esc cancel · Backspace clear)'));

        const ctl = new Gtk.EventControllerKey();
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE);
        const finish = (accel) => {
            win.remove_controller(ctl);
            btn.set_sensitive(true);
            row.set_subtitle(baseSubtitle || '');
            if (accel !== null)
                kb.set_string('binding', accel);
            refresh();
        };
        const LONE_MODS = [
            Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
            Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R,
            Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift,
        ];
        ctl.connect('key-pressed', (_c, keyval, _code, state) => {
            const mods = state & Gtk.accelerator_get_default_mod_mask();
            if (keyval === Gdk.KEY_Escape && mods === 0) {
                finish(null);          // cancel, keep current
                return Gdk.EVENT_STOP;
            }
            if (keyval === Gdk.KEY_BackSpace && mods === 0) {
                finish('');            // clear / disable
                return Gdk.EVENT_STOP;
            }
            if (LONE_MODS.includes(keyval))
                return Gdk.EVENT_STOP;  // wait for a non-modifier key
            if (!Gtk.accelerator_valid(keyval, mods))
                return Gdk.EVENT_STOP;
            finish(Gtk.accelerator_name(keyval, mods));
            return Gdk.EVENT_STOP;
        });
        win.add_controller(ctl);
    }

    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const uiLang = readUiLang();
        _ = (s) => (uiLang === 'ja' && UI_JA[s]) ? UI_JA[s] : s;
        let loading = true;  // suppress write-backs while we apply fetched values

        const page = new Adw.PreferencesPage();
        window.add(page);

        // --- Interface ---------------------------------------------------- //
        const UI_LANGS = ['en', 'ja'];
        const ifaceGroup = new Adw.PreferencesGroup({title: _('Interface')});
        page.add(ifaceGroup);

        const uiLangRow = new Adw.ComboRow({
            title: _('Interface language'),
            subtitle: _('Language of the popup, menu, and this settings window.'),
            // Language names shown in their own script, not translated.
            model: Gtk.StringList.new(['English', '日本語']),
            selected: UI_LANGS.indexOf(uiLang) >= 0 ? UI_LANGS.indexOf(uiLang) : 0,
        });
        uiLangRow.connect('notify::selected', () => {
            if (loading)
                return;
            this._setConfig(settings, ['--ui-language', UI_LANGS[uiLangRow.selected]]);
            uiLangRow.set_subtitle(
                _('Reopen settings to see this window in the new language.'));
        });
        ifaceGroup.add(uiLangRow);

        // --- Translation -------------------------------------------------- //
        const trGroup = new Adw.PreferencesGroup({
            title: _('Translation'),
            description: _('Stored in the zenbuji config, shared with the CLI, ' +
                'popup, and file-manager surfaces.'),
        });
        page.add(trGroup);

        const backendRow = new Adw.ComboRow({
            title: _('Backend'),
            model: Gtk.StringList.new(BACKEND_LABELS.map(s => _(s))),
        });
        backendRow.connect('notify::selected', () => {
            if (loading)
                return;
            this._setConfig(settings, ['--backend', BACKENDS[backendRow.selected]]);
        });
        trGroup.add(backendRow);

        const keyRow = new Adw.PasswordEntryRow({
            title: _('DeepL API key'),
            // Without the apply button, the `apply` signal never fires (Enter
            // only emits `entry-activated`), so the key would never save.
            show_apply_button: true,
        });
        keyRow.connect('apply', () => {
            this._setConfig(settings, ['--deepl-key', keyRow.get_text().trim()]);
        });
        trGroup.add(keyRow);

        const verifyRow = new Adw.ActionRow({
            title: _('Verify DeepL key'),
            subtitle: _('Checks the key above and shows remaining quota.'),
        });
        const verifyBtn = new Gtk.Button({
            label: _('Verify'),
            valign: Gtk.Align.CENTER,
        });
        verifyBtn.connect('clicked', () => {
            verifyRow.set_subtitle(_('Checking…'));
            this._runCli(settings, ['usage', '--json', '--key', keyRow.get_text().trim()],
                (data) => {
                    if (data && data.ok) {
                        const used = data.used.toLocaleString();
                        const limit = data.limit.toLocaleString();
                        verifyRow.set_subtitle(`✓ ${used} / ${limit} ${_('characters used')}`);
                    } else {
                        const msg = (data && data.error) || _('check failed');
                        verifyRow.set_subtitle(`✗ ${msg}`);
                    }
                });
        });
        verifyRow.add_suffix(verifyBtn);
        verifyRow.set_activatable_widget(verifyBtn);
        trGroup.add(verifyRow);

        const dictRow = new Adw.SwitchRow({
            title: _('Build a local dictionary'),
            subtitle: _('Cache DeepL translations and reuse them (saves quota); ' +
                'browse them in the Dictionary window.'),
        });
        dictRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings, ['--dictionary', dictRow.get_active() ? 'on' : 'off']);
        });
        trGroup.add(dictRow);

        const enRow = new Adw.SwitchRow({title: _('English')});
        const deRow = new Adw.SwitchRow({title: _('German')});
        const applyLangs = () => {
            if (loading)
                return;
            const langs = [];
            if (enRow.get_active())
                langs.push('en');
            if (deRow.get_active())
                langs.push('de');
            this._setConfig(settings, ['--lang', langs.join(',') || 'en']);
        };
        enRow.connect('notify::active', applyLangs);
        deRow.connect('notify::active', applyLangs);

        const langGroup = new Adw.PreferencesGroup({
            title: _('Languages'),
            description: _('Which translations to show, in order.'),
        });
        langGroup.add(enRow);
        langGroup.add(deRow);
        page.add(langGroup);

        // --- History ------------------------------------------------------ //
        const histGroup = new Adw.PreferencesGroup({title: _('History')});
        page.add(histGroup);

        const histRow = new Adw.SwitchRow({
            title: _('Keep recent lookups'),
            subtitle: _('Show them in the top-bar “Recent” menu.'),
        });
        histRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings, ['--history', histRow.get_active() ? 'on' : 'off']);
        });
        histGroup.add(histRow);

        const clearRow = new Adw.ActionRow({title: _('Clear history')});
        const clearBtn = new Gtk.Button({
            label: _('Clear'),
            valign: Gtk.Align.CENTER,
            css_classes: ['destructive-action'],
        });
        clearBtn.connect('clicked', () => {
            this._setConfig(settings, ['--clear-history']);
            clearRow.set_subtitle(_('Cleared.'));
        });
        clearRow.add_suffix(clearBtn);
        clearRow.set_activatable_widget(clearBtn);
        histGroup.add(clearRow);

        // --- Popup -------------------------------------------------------- //
        const popupGroup = new Adw.PreferencesGroup({title: _('Popup')});
        page.add(popupGroup);

        const closeRow = new Adw.SwitchRow({
            title: _('Close when it loses focus'),
            subtitle: _('Dismiss the popup automatically when you click elsewhere.'),
        });
        closeRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings,
                ['--popup-close-on-focus-loss', closeRow.get_active() ? 'on' : 'off']);
        });
        popupGroup.add(closeRow);

        // --- Shortcuts ---------------------------------------------------- //
        const scGroup = new Adw.PreferencesGroup({
            title: _('Shortcuts'),
            description: _('Click a shortcut to change it. These are GNOME custom keybindings.'),
        });
        page.add(scGroup);
        scGroup.add(this._makeShortcutRow(_('Look up selection'), '', 'zenbuji'));
        scGroup.add(this._makeShortcutRow(_('Look up screen region (OCR)'),
            _('Needs the full (non---light) install for the OCR model.'), 'zenbuji-ocr'));

        // --- Advanced ----------------------------------------------------- //
        const advGroup = new Adw.PreferencesGroup({title: _('Advanced')});
        page.add(advGroup);

        const cmdRow = new Adw.EntryRow({
            title: _('zenbuji command'),
            text: settings.get_string('zenbuji-command'),
            show_apply_button: true,
        });
        cmdRow.connect('apply', () => {
            settings.set_string('zenbuji-command', cmdRow.get_text().trim() || 'zenbuji');
        });
        advGroup.add(cmdRow);

        // --- Load current config asynchronously, then enable write-backs. -- //
        this._runCli(settings, ['config', '--json'], (cfg, err) => {
            if (cfg) {
                const bIdx = BACKENDS.indexOf(cfg.backend);
                backendRow.selected = bIdx >= 0 ? bIdx : 0;
                keyRow.set_text(cfg.deepl_api_key || '');
                const langs = cfg.languages || ['en', 'de'];
                enRow.set_active(langs.includes('en'));
                deRow.set_active(langs.includes('de'));
                histRow.set_active(cfg.history !== false);
                closeRow.set_active(cfg.popup_close_on_focus_loss !== false);
                dictRow.set_active(cfg.dictionary !== false);
            } else if (err) {
                trGroup.set_description(
                    _('Could not read zenbuji config — check the command in Advanced.'));
            }
            loading = false;
        });
    }
}
