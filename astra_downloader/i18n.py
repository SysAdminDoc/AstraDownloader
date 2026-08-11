"""Qt translation loading and locale normalization for Astra Downloader."""

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QLocale, QTranslator, Qt


SUPPORTED_LOCALES = (
    "ar",
    "de",
    "en",
    "es",
    "fr",
    "it",
    "ja",
    "ko",
    "pt_BR",
    "ru",
    "zh_CN",
)

# Catalogues below this floor remain shipped so an older configuration can
# still load its requested locale, but they are not presented as finished
# choices to new users. English is the reference locale and therefore does
# not need a translated catalogue to qualify.
COMPANION_LOCALE_MIN_COVERAGE = 0.80
ADVERTISED_LOCALES = ("de", "en")


def normalize_companion_locale(value, system_locale=None):
    """Resolve a configured/system locale onto a bundled catalogue."""
    requested = str(value or "system").strip().replace("-", "_")
    follows_system = requested.lower() == "system"
    if follows_system:
        requested = str(
            system_locale
            or os.environ.get("ASTRA_COMPANION_LANGUAGE")
            or QLocale.system().name()
        ).strip().replace("-", "_")
    exact = next(
        (locale for locale in SUPPORTED_LOCALES if locale.lower() == requested.lower()),
        None,
    )
    if exact:
        return exact if not follows_system or exact in ADVERTISED_LOCALES else "en"
    language = requested.split("_", 1)[0].lower()
    resolved = next(
        (
            locale
            for locale in SUPPORTED_LOCALES
            if locale.split("_", 1)[0].lower() == language
        ),
        "en",
    )
    return resolved if not follows_system or resolved in ADVERTISED_LOCALES else "en"


def companion_translations_dir():
    """Return the source or PyInstaller extraction directory for `.qm` files."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "translations"
    return Path(__file__).resolve().parent / "translations"


def install_companion_translator(app, configured_locale="system"):
    """Install the selected Qt catalogue and return its retained translator."""
    locale = normalize_companion_locale(configured_locale)
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft
        if locale == "ar"
        else Qt.LayoutDirection.LeftToRight
    )
    app.setProperty("astraLocale", locale)
    if locale == "en":
        return None
    translator = QTranslator(app)
    catalog = companion_translations_dir() / f"astra_downloader_{locale}.qm"
    if not translator.load(str(catalog)):
        return None
    app.installTranslator(translator)
    return translator


__all__ = (
    "SUPPORTED_LOCALES",
    "COMPANION_LOCALE_MIN_COVERAGE",
    "ADVERTISED_LOCALES",
    "companion_translations_dir",
    "install_companion_translator",
    "normalize_companion_locale",
)
