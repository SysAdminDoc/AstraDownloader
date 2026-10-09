"""Pairing disclosure and subscription entry retain their working controls."""

from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
import pytest

import astra_downloader as ad
from testing_support import FakeConfig, FakeHistory, _retire_test_window


@pytest.fixture
def pairing_window(qapp):
    config = FakeConfig()
    history = FakeHistory()
    manager = ad.DownloadManager(config, history)
    with patch.object(ad.MainWindow, "_start_instance_command_listener"), \
            patch.object(ad.MainWindow, "_start_readiness_probe"), \
            patch.object(ad.MainWindow, "_load_site_catalog_extractors"), \
            patch.object(ad.MainWindow, "_refresh_tools_status"), \
            patch.object(ad.MainWindow, "_open_extension_pairing") as pair_extension, \
            patch.object(ad.MainWindow, "_open_userscript_pairing") as pair_userscript, \
            patch.object(ad.MainWindow, "_add_subscription") as add_subscription, \
            patch.object(ad.QSystemTrayIcon, "show"):
        window = ad.MainWindow(config, manager, history)
        window.resize(1120, 760)
        window.show()
        for timer in (window.update_timer, window.cleanup_timer, window.tools_status_timer):
            timer.stop()
        QApplication.processEvents()
        yield window, pair_extension, pair_userscript, add_subscription
        _retire_test_window(window)


@pytest.mark.parametrize("size", [(900, 620), (1120, 760)])
def test_pairing_actions_work_while_technical_details_are_collapsed(pairing_window, size):
    window, pair_extension, pair_userscript, _ = pairing_window
    window.resize(*size)
    window._nav_click("Browser extension")
    QApplication.processEvents()
    assert window.extension_details.isHidden()
    assert window.btn_startstop.isVisible()
    assert window.btn_allow_extension_pairing.isVisible()
    assert window.btn_pair_userscript.isVisible()
    window.btn_allow_extension_pairing.click()
    window.btn_pair_userscript.click()
    pair_extension.assert_called_once()
    pair_userscript.assert_called_once()
    window.btn_extension_details.click()
    QApplication.processEvents()
    assert window.cfg_native_chrome_ids.isVisible()
    assert window.btn_register_chrome_host.isVisible()
    assert window.dash_endpoint.isVisible()
    assert window.stat_port.isVisible()
    assert window.extension_page_scroll.horizontalScrollBar().maximum() == 0
    window._append_log("Pairing layout test")
    assert window.log_text.isVisible()
    window.btn_extension_details.click()
    assert window.extension_details.isHidden()
    assert window.btn_allow_extension_pairing.isVisible()


def test_subscription_link_and_interval_stay_available_at_minimum_size(pairing_window):
    window, _, _, add_subscription = pairing_window
    window.resize(900, 620)
    window._nav_click("Subscriptions")
    QApplication.processEvents()
    for control in (window.subscription_url, window.subscription_interval,
                    window.btn_add_subscription, window.subscription_search,
                    window.subscription_status_filter):
        assert control.isVisible()
        top_left = control.mapTo(window, QPoint(0, 0))
        assert window.rect().contains(top_left)
        assert window.rect().contains(top_left + QPoint(control.width() - 1, control.height() - 1))
    window.subscription_url.setText("https://www.youtube.com/@example")
    window.subscription_url.returnPressed.emit()
    add_subscription.assert_called_once()
    assert window.subscription_interval.value() == 60
