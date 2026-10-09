"""Settings categories keep everyday controls easy to reach and search global."""

import unittest
import os
from pathlib import Path

import test_gui
from testing_support import FakeConfig, _get_qapp_or_skip


class SettingsCategoryTests(unittest.TestCase):
    _window = test_gui.SettingsNavigationTests._window

    def setUp(self):
        _get_qapp_or_skip(self)
        self.window = self._window(FakeConfig())
        self.groups = {
            title: group for group, _content, title in self.window._settings_group_specs
        }

    def test_general_opens_with_everyday_preferences(self):
        self.assertEqual(self.window._settings_active_category, "General")
        self.assertTrue(self.window.settings_category_buttons["General"].isChecked())
        self.assertEqual(
            {title for title, group in self.groups.items() if not group.isHidden()},
            {"Appearance and language", "Window and tray"},
        )

    def test_categories_reach_every_settings_group(self):
        reached = set()
        for category, _description, titles in self.window._SETTINGS_CATEGORIES:
            self.window.settings_category_buttons[category].click()
            visible = {
                title for title, group in self.groups.items() if not group.isHidden()
            }
            self.assertEqual(visible, set(titles))
            self.assertEqual(self.window.settings_category_heading.text(), category)
            reached.update(visible)
        self.assertEqual(reached, set(self.groups))

    def test_search_crosses_categories_and_preserves_unsaved_changes(self):
        window = self.window
        window.settings_category_buttons["Folders"].click()
        window.cfg_dl_path.setText("C:/Downloads/Review")
        window.settings_filter.setText("private token")
        self.assertFalse(self.groups["Connection"].isHidden())
        self.assertFalse(window.cfg_token.isHidden())
        self.assertTrue(self.groups["Storage"].isHidden())
        self.assertEqual(window.settings_category_heading.text(), "Search results")
        window.settings_filter.clear()
        self.assertFalse(self.groups["Storage"].isHidden())
        self.assertTrue(self.groups["Connection"].isHidden())
        self.assertEqual(window.cfg_dl_path.text(), "C:/Downloads/Review")
        self.assertEqual(window.settings_status.text(), "Unsaved changes")

    def test_category_selection_clears_search_and_empty_state(self):
        window = self.window
        window.settings_filter.setText("no-such-setting-123")
        self.assertFalse(window.settings_filter_empty.isHidden())
        window.settings_category_buttons["Maintenance"].click()
        self.assertEqual(window.settings_filter.text(), "")
        self.assertTrue(window.settings_filter_empty.isHidden())
        self.assertFalse(self.groups["Import and export"].isHidden())
        self.assertFalse(self.groups["Maintenance"].isHidden())

    def test_invalid_field_is_revealed_after_leaving_its_category(self):
        window = self.window
        window.settings_category_buttons["Connection"].click()
        window.cfg_site_profiles.setPlainText("{not valid JSON")
        window.settings_category_buttons["General"].click()
        window.settings_filter.setText("theme")
        window.btn_save.click()
        self.assertEqual(window._settings_active_category, "Connection")
        self.assertEqual(window.settings_filter.text(), "")
        self.assertFalse(self.groups["Site profiles"].isHidden())
        self.assertEqual(window.cfg_site_profiles.toPlainText(), "{not valid JSON")
        self.assertEqual(window.cfg_site_profiles.property("state"), "error")

    def test_folder_repair_opens_the_folder_control(self):
        window = self.window
        window.settings_filter.setText("theme")
        window._preflight_actions["output-folder"] = "choose-output-folder"
        window._run_preflight_action("output-folder")
        self.assertEqual(window._settings_active_category, "Folders")
        self.assertEqual(window.settings_filter.text(), "")
        self.assertFalse(self.groups["Storage"].isHidden())
        self.assertFalse(window.cfg_dl_path.isHidden())
        self.assertEqual(
            window.settings_status.text(),
            "Choose a download folder this machine can write to.",
        )

    def test_narrow_window_uses_category_picker_without_sideways_scroll(self):
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        previous_font = app.font()
        self.addCleanup(app.setFont, previous_font)
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
            app.setFont(QFont("Segoe UI", 9))
        window = self.window
        window.resize(900, 620)
        window._nav_click("Settings")
        window.show()
        QApplication.processEvents()
        self.assertTrue(window.settings_category_picker.isVisible())
        self.assertFalse(window.settings_category_buttons["General"].isVisible())
        for category in window.settings_category_buttons:
            window._select_settings_category(category)
            QApplication.processEvents()
            self.assertEqual(window.settings_scroll.horizontalScrollBar().maximum(), 0,
                             category)
