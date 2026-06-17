import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const BACKENDS = ['auto', 'argos', 'deepl'];
const BACKEND_LABELS = ['Auto (DeepL if key set)', 'Offline (Argos)', 'DeepL'];
const TTS_ENGINES = ['auto', 'voicevox', 'system', 'command', 'off'];
const TTS_ENGINE_LABELS = ['Auto (VOICEVOX if running)', 'VOICEVOX',
    'System (spd-say / espeak)', 'Custom command', 'Off'];

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
    'Translation length limit': '翻訳の文字数上限',
    'Maximum characters sent to translate in one lookup.':
        '1回の翻訳で送信する最大文字数。',
    'Build a local dictionary': 'ローカル辞書を作成',
    'Cache DeepL translations and reuse them (saves quota); browse them in the Dictionary window.':
        'DeepL 翻訳をキャッシュして再利用します（クォータ節約）。辞書ウィンドウで閲覧できます。',
    'Also store offline translations': 'オフライン翻訳も保存',
    'Cache Argos (offline) translations in the dictionary too, not just DeepL — lets you build a practice deck without a key.':
        'DeepL だけでなく Argos（オフライン）翻訳も辞書にキャッシュします。キーなしで練習用の単語帳を作れます。',
    'Speech': '音声',
    'Read words aloud': '単語を読み上げる',
    'Speak the reading after an OCR/silent add, and via the 🔊 buttons.':
        'OCR・サイレント追加の後、および 🔊 ボタンで読みを読み上げます。',
    'Read aloud after a lookup': '検索後に読み上げる',
    'Speak the reading automatically when you look up a word (Super+J).':
        '単語を調べたとき（Super+J）に自動的に読みを読み上げます。',
    'Also speak the English translation': '英語訳も読み上げる',
    'After a background OCR add, read the English meaning too (英語で…).':
        'バックグラウンドの OCR 追加の後、英語の意味も読み上げます（英語で…）。',
    'Read selection aloud': '選択を読み上げる',
    'Voice engine': '音声エンジン',
    'VOICEVOX gives natural Japanese; auto falls back to the system voice.':
        'VOICEVOX は自然な日本語音声です。auto は利用できない場合システム音声に切り替えます。',
    'Auto (VOICEVOX if running)': '自動（VOICEVOX が動作中なら使用）',
    'VOICEVOX': 'VOICEVOX',
    'System (spd-say / espeak)': 'システム（spd-say / espeak）',
    'Custom command': 'カスタムコマンド',
    'Off': 'オフ',
    'Voice': '音声（話者）',
    'Default (Zundamon)': '既定（ずんだもん）',
    'Start the VOICEVOX engine: ./install.sh --voicevox':
        'VOICEVOX エンジンを起動してください: ./install.sh --voicevox',
    'Test voice': '音声をテスト',
    'Speak a sample with the current engine and voice.':
        '現在のエンジンと話者でサンプルを読み上げます。',
    'Test': 'テスト',
    'Text-to-speech command': '音声合成コマンド',
    'Used only when the engine is "Custom command". Use {text} as the placeholder.':
        'エンジンが「カスタムコマンド」のときのみ使用。{text} をプレースホルダーに使用します。',
    'Add screen region to dictionary (OCR)': '画面領域を辞書に追加（OCR）',
    'Popup': 'ポップアップ',
    'Close when it loses focus': 'フォーカスを失ったら閉じる',
    'Dismiss the popup automatically when you click elsewhere.':
        '他の場所をクリックすると自動的に閉じます。',
    'Learning': '学習',
    'Show translation as a hint': '翻訳をヒントとして表示',
    'Show the meaning during practice (test only the reading).':
        '練習中に意味を表示します（読みのみ出題）。',
    'Open once a day on login': 'ログイン時に1日1回開く',
    'Automatically start a practice round after you log in.':
        'ログイン後に練習を自動的に開始します。',
    'Practice (SRS)': '練習（SRS）',
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

        const cacheOfflineRow = new Adw.SwitchRow({
            title: _('Also store offline translations'),
            subtitle: _('Cache Argos (offline) translations in the dictionary too, ' +
                'not just DeepL — lets you build a practice deck without a key.'),
        });
        cacheOfflineRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings,
                ['--cache-offline', cacheOfflineRow.get_active() ? 'on' : 'off']);
        });
        trGroup.add(cacheOfflineRow);

        const charRow = new Adw.SpinRow({
            title: _('Translation length limit'),
            subtitle: _('Maximum characters sent to translate in one lookup.'),
            adjustment: new Gtk.Adjustment({
                lower: 10, upper: 2000, step_increment: 10, page_increment: 50,
            }),
        });
        charRow.get_adjustment().connect('value-changed', () => {
            if (loading)
                return;
            this._setConfig(settings,
                ['--translation-char-limit', String(charRow.get_value())]);
        });
        trGroup.add(charRow);

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

        // --- Speech ------------------------------------------------------- //
        const speechGroup = new Adw.PreferencesGroup({title: _('Speech')});
        page.add(speechGroup);

        const ttsRow = new Adw.SwitchRow({
            title: _('Read words aloud'),
            subtitle: _('Speak the reading after an OCR/silent add, and via the 🔊 buttons.'),
        });
        ttsRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings, ['--tts', ttsRow.get_active() ? 'on' : 'off']);
        });
        speechGroup.add(ttsRow);

        const ttsLookupRow = new Adw.SwitchRow({
            title: _('Read aloud after a lookup'),
            subtitle: _('Speak the reading automatically when you look up a word (Super+J).'),
        });
        ttsLookupRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings,
                ['--tts-on-lookup', ttsLookupRow.get_active() ? 'on' : 'off']);
        });
        speechGroup.add(ttsLookupRow);

        const ttsAddTrRow = new Adw.SwitchRow({
            title: _('Also speak the English translation'),
            subtitle: _('After a background OCR add, read the English meaning too (英語で…).'),
        });
        ttsAddTrRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings,
                ['--tts-add-translation', ttsAddTrRow.get_active() ? 'on' : 'off']);
        });
        speechGroup.add(ttsAddTrRow);

        const engineRow = new Adw.ComboRow({
            title: _('Voice engine'),
            subtitle: _('VOICEVOX gives natural Japanese; auto falls back to the system voice.'),
            model: Gtk.StringList.new(TTS_ENGINE_LABELS.map(s => _(s))),
        });
        speechGroup.add(engineRow);

        // VOICEVOX speaker picker — populated from `zenbuji voices --json` once
        // the config has loaded (so we can preselect the saved speaker).
        let voiceIds = [];
        let voiceLoading = false;
        const voiceRow = new Adw.ComboRow({
            title: _('Voice'),
            model: Gtk.StringList.new([_('Default (Zundamon)')]),
        });
        voiceRow.connect('notify::selected', () => {
            if (loading || voiceLoading)
                return;
            const id = voiceIds[voiceRow.selected];
            if (id !== undefined)
                this._setConfig(settings, ['--voicevox-speaker', String(id)]);
        });
        speechGroup.add(voiceRow);

        const usesVoicevox = e => e === 'auto' || e === 'voicevox';
        engineRow.connect('notify::selected', () => {
            if (loading)
                return;
            const engine = TTS_ENGINES[engineRow.selected];
            this._setConfig(settings, ['--tts-engine', engine]);
            voiceRow.set_sensitive(usesVoicevox(engine));
            ttsCmdRow.set_sensitive(engine === 'command');
        });

        const testRow = new Adw.ActionRow({
            title: _('Test voice'),
            subtitle: _('Speak a sample with the current engine and voice.'),
        });
        const testBtn = new Gtk.Button({label: _('Test'), valign: Gtk.Align.CENTER});
        testBtn.connect('clicked', () => {
            this._runCli(settings, ['speak', 'こんにちは、日本語'], () => {});
        });
        testRow.add_suffix(testBtn);
        testRow.activatable_widget = testBtn;
        speechGroup.add(testRow);

        const ttsCmdRow = new Adw.EntryRow({
            title: _('Text-to-speech command'),
            show_apply_button: true,
        });
        ttsCmdRow.set_tooltip_text(
            _('Used only when the engine is "Custom command". Use {text} as the placeholder.'));
        ttsCmdRow.connect('apply', () => {
            this._setConfig(settings, ['--tts-command', ttsCmdRow.get_text().trim()]);
        });
        speechGroup.add(ttsCmdRow);

        // --- Learning ----------------------------------------------------- //
        const learnGroup = new Adw.PreferencesGroup({title: _('Learning')});
        page.add(learnGroup);

        const learnHintRow = new Adw.SwitchRow({
            title: _('Show translation as a hint'),
            subtitle: _('Show the meaning during practice (test only the reading).'),
        });
        learnHintRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings,
                ['--learn-show-translation', learnHintRow.get_active() ? 'on' : 'off']);
        });
        learnGroup.add(learnHintRow);

        const learnLoginRow = new Adw.SwitchRow({
            title: _('Open once a day on login'),
            subtitle: _('Automatically start a practice round after you log in.'),
        });
        learnLoginRow.connect('notify::active', () => {
            if (loading)
                return;
            this._setConfig(settings,
                ['--learn-on-login', learnLoginRow.get_active() ? 'on' : 'off']);
        });
        learnGroup.add(learnLoginRow);

        // --- Shortcuts ---------------------------------------------------- //
        const scGroup = new Adw.PreferencesGroup({
            title: _('Shortcuts'),
            description: _('Click a shortcut to change it. These are GNOME custom keybindings.'),
        });
        page.add(scGroup);
        scGroup.add(this._makeShortcutRow(_('Look up selection'), '', 'zenbuji'));
        scGroup.add(this._makeShortcutRow(_('Look up screen region (OCR)'),
            _('Needs the full (non---light) install for the OCR model.'), 'zenbuji-ocr'));
        scGroup.add(this._makeShortcutRow(_('Add screen region to dictionary (OCR)'),
            '', 'zenbuji-ocr-add'));
        scGroup.add(this._makeShortcutRow(_('Read selection aloud'),
            '', 'zenbuji-speak'));
        scGroup.add(this._makeShortcutRow(_('Practice (SRS)'), '', 'zenbuji-learn'));

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
                cacheOfflineRow.set_active(cfg.cache_offline === true);
                ttsRow.set_active(cfg.tts === true);
                ttsLookupRow.set_active(cfg.tts_on_lookup === true);
                ttsAddTrRow.set_active(cfg.tts_add_translation === true);
                ttsCmdRow.set_text(cfg.tts_command || '');
                const engIdx = TTS_ENGINES.indexOf(cfg.tts_engine || 'auto');
                engineRow.selected = engIdx >= 0 ? engIdx : 0;
                const engine = TTS_ENGINES[engineRow.selected];
                ttsCmdRow.set_sensitive(engine === 'command');
                voiceRow.set_sensitive(usesVoicevox(engine));
                // Populate the voice list from the running VOICEVOX engine and
                // preselect the saved speaker (defaults to 3 / Zundamon).
                const wantSpeaker = cfg.voicevox_speaker !== undefined
                    ? cfg.voicevox_speaker : 3;
                this._runCli(settings, ['voices', '--json'], (voices) => {
                    voiceLoading = true;
                    if (voices && voices.length) {
                        voiceIds = voices.map(v => v.id);
                        const list = new Gtk.StringList();
                        voices.forEach(v => list.append(`${v.name} — ${v.style}`));
                        voiceRow.set_model(list);
                        const idx = voiceIds.indexOf(wantSpeaker);
                        voiceRow.selected = idx >= 0 ? idx : 0;
                    } else {
                        voiceRow.set_subtitle(
                            _('Start the VOICEVOX engine: ./install.sh --voicevox'));
                        voiceRow.set_sensitive(false);
                    }
                    voiceLoading = false;
                });
                charRow.set_value(cfg.translation_char_limit || 200);
                learnHintRow.set_active(cfg.learn_show_translation !== false);
                learnLoginRow.set_active(cfg.learn_on_login === true);
            } else if (err) {
                trGroup.set_description(
                    _('Could not read zenbuji config — check the command in Advanced.'));
            }
            loading = false;
        });
    }
}
