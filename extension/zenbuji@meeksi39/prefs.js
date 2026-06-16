import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const BACKENDS = ['auto', 'argos', 'deepl'];
const BACKEND_LABELS = ['Auto (DeepL if key set)', 'Offline (Argos)', 'DeepL'];

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

        const keyRow = new Adw.PasswordEntryRow({title: _('DeepL API key')});
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

        // --- Advanced ----------------------------------------------------- //
        const advGroup = new Adw.PreferencesGroup({title: _('Advanced')});
        page.add(advGroup);

        const hintRow = new Adw.ActionRow({
            title: _('Selection hotkey'),
            subtitle: _('Super+J is a GNOME custom shortcut (Settings ▸ Keyboard). ' +
                'Re-bind it there or with dconf.'),
        });
        advGroup.add(hintRow);

        const ocrHintRow = new Adw.ActionRow({
            title: _('Screen-region OCR'),
            subtitle: _('Super+Shift+J (or the top-bar “Look up screen region”) ' +
                'reads on-screen Japanese via OCR. Needs the full (non---light) ' +
                'install for the OCR model.'),
        });
        advGroup.add(ocrHintRow);

        const cmdRow = new Adw.EntryRow({
            title: _('zenbuji command'),
            text: settings.get_string('zenbuji-command'),
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
            } else if (err) {
                trGroup.set_description(
                    _('Could not read zenbuji config — check the command in Advanced.'));
            }
            loading = false;
        });
    }
}
