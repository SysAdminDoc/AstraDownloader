"""Dropdown indicators remain visible after applying the application theme."""

import unittest

import astra_downloader as ad

try:
    from .gui_support import ChoiceBox
    from .testing_support import _get_qapp_or_skip
except ImportError:
    from gui_support import ChoiceBox
    from testing_support import _get_qapp_or_skip


class ChoiceBoxAffordanceTests(unittest.TestCase):
    def test_indicator_paints_in_both_themes_and_layout_directions(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionComboBox

        app = _get_qapp_or_skip(self)
        old_sheet = app.styleSheet()
        self.addCleanup(app.setStyleSheet, old_sheet)
        self.addCleanup(ad.apply_application_theme, getattr(app, "_astra_theme_setting", "system"))
        for theme in ("dark", "light"):
            ad.apply_application_theme(theme)
            for direction in (
                Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft,
            ):
                for enabled in (True, False):
                    with self.subTest(theme=theme, direction=direction, enabled=enabled):
                        combo = ChoiceBox()
                        combo.addItems(["First", "Second"])
                        combo.resize(240, 40)
                        combo.setLayoutDirection(direction)
                        combo.setEnabled(enabled)
                        combo.show()
                        QApplication.processEvents()
                        option = QStyleOptionComboBox()
                        combo.initStyleOption(option)
                        arrow = combo.style().subControlRect(
                            QStyle.ComplexControl.CC_ComboBox, option,
                            QStyle.SubControl.SC_ComboBoxArrow, combo,
                        )
                        pixels = combo.grab().toImage()
                        cx, cy = arrow.center().x(), arrow.center().y()
                        colors = {
                            pixels.pixelColor(x, y).rgba()
                            for y in range(cy - 6, cy + 7)
                            for x in range(cx - 6, cx + 7)
                        }
                        self.assertGreater(len(colors), 2, "dropdown arrow region is blank")
                        self.assertEqual(
                            arrow.center().x() < combo.width() // 2,
                            direction == Qt.LayoutDirection.RightToLeft,
                        )
                        combo.hide()
                        combo.deleteLater()

    def test_selection_and_native_accessibility_are_preserved(self):
        from PySide6.QtGui import QAccessible
        from PySide6.QtWidgets import QComboBox

        _get_qapp_or_skip(self)
        combo = ChoiceBox()
        combo.setAccessibleName("Download format")
        combo.addItem("MP4", "mp4")
        combo.addItem("MP3", "mp3")
        combo.setCurrentIndex(1)
        self.assertIsInstance(combo, QComboBox)
        self.assertEqual(combo.currentData(), "mp3")
        interface = QAccessible.queryAccessibleInterface(combo)
        self.assertEqual(interface.role(), QAccessible.Role.ComboBox)
        self.assertEqual(interface.text(QAccessible.Text.Name), "Download format")
