import Adw from 'gi://Adw';

import {ExtensionPreferences, gettext as _} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class ZenbujiPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        const page = new Adw.PreferencesPage();
        const group = new Adw.PreferencesGroup({
            title: _('zenbuji'),
            description: _('Furigana + EN/DE lookup. Translation backend and ' +
                'languages are configured with the CLI: zenbuji config --help'),
        });
        page.add(group);

        const hintRow = new Adw.ActionRow({
            title: _('Selection hotkey'),
            subtitle: _('Super+J is a GNOME custom shortcut (Settings ▸ Keyboard). ' +
                'Re-bind it there or with dconf.'),
        });
        group.add(hintRow);

        const cmdRow = new Adw.EntryRow({
            title: _('zenbuji command'),
            text: settings.get_string('zenbuji-command'),
        });
        cmdRow.connect('apply', () => {
            settings.set_string('zenbuji-command', cmdRow.get_text().trim() || 'zenbuji');
        });
        group.add(cmdRow);

        window.add(page);
    }
}
