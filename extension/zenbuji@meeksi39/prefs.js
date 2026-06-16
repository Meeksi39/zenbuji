import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gio from 'gi://Gio';

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

        // Keybinding (shown as editable text — '<Super>j' style).
        const shortcutRow = new Adw.EntryRow({
            title: _('Selection lookup shortcut'),
            text: (settings.get_strv('lookup-selection')[0]) || '',
        });
        shortcutRow.connect('apply', () => {
            const val = shortcutRow.get_text().trim();
            settings.set_strv('lookup-selection', val ? [val] : []);
        });
        group.add(shortcutRow);

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
