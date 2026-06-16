import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences, gettext as _} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const BACKENDS = ['auto', 'argos', 'deepl'];
const BACKEND_LABELS = ['Auto (DeepL if key set)', 'Offline (Argos)', 'DeepL'];

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
        let loading = true;  // suppress write-backs while we apply fetched values

        const page = new Adw.PreferencesPage();
        window.add(page);

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
