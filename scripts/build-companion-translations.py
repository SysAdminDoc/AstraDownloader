#!/usr/bin/env python3
"""Generate Qt Linguist sources and compile companion translation catalogues."""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "astra_downloader" / "translations"
SOURCE_STRINGS = (
    "Download",
    "History",
    "Sign-ins",
    "Browser extension",
    "Settings",
    "Download a video",
    "Video",
    "Audio",
    "Best",
    "Clip from",
    "to",
    "Pause intake",
    "Nothing downloading yet",
    "Paste a link",
    "Server offline",
    "Local only · start before downloading",
    "Start Server",
    "Stop Server",
    "Tray behavior",
    "Stage copied video links for review",
    "Save changes",
)

CATALOGS = {
    "ar": {
        "Sign-ins": "تسجيلات الدخول",
        "Browser extension": "امتداد المتصفح",
        "Download": "تنزيل",
        "History": "السجل",
        "Settings": "الإعدادات",
    },
    "de": {
        "Sign-ins": "Anmeldungen",
        "Browser extension": "Browser-Erweiterung",
        "Download": "Herunterladen",
        "History": "Verlauf",
        "Settings": "Einstellungen",
        "Video": "Video",
        "Audio": "Audio",
        "Best": "Beste",
        "Clip from": "Clip von",
        "to": "bis",
        "Pause intake": "Annahme pausieren",
        "Nothing downloading yet": "Noch keine Downloads",
        "Paste a link": "Link einfügen",
        "Download a video": "Video herunterladen",
        "Server offline": "Server offline",
        "Local only · start before downloading": (
            "Nur lokal · vor dem Herunterladen starten"
        ),
        "Start Server": "Server starten",
        "Stop Server": "Server stoppen",
        "Tray behavior": "Infobereich",
        "Stage copied video links for review": (
            "Kopierte YouTube-Links zur Prüfung vormerken"
        ),
        "Save changes": "Änderungen speichern",
    },
    "en": {},
    "es": {
        "Sign-ins": "Inicios de sesión",
        "Browser extension": "Extensión del navegador",
        "Download": "Descargar",
        "History": "Historial",
        "Settings": "Configuración",
    },
    "fr": {
        "Sign-ins": "Connexions",
        "Browser extension": "Extension du navigateur",
        "Download": "Télécharger",
        "History": "Historique",
        "Settings": "Paramètres",
    },
    "it": {
        "Sign-ins": "Accessi",
        "Browser extension": "Estensione del browser",
        "Download": "Scarica",
        "History": "Cronologia",
        "Settings": "Impostazioni",
    },
    "ja": {
        "Sign-ins": "サインイン",
        "Browser extension": "ブラウザー拡張機能",
        "Download": "ダウンロード",
        "History": "履歴",
        "Settings": "設定",
    },
    "ko": {
        "Sign-ins": "로그인",
        "Browser extension": "브라우저 확장 프로그램",
        "Download": "다운로드",
        "History": "기록",
        "Settings": "설정",
    },
    "pt_BR": {
        "Sign-ins": "Logins",
        "Browser extension": "Extensão do navegador",
        "Download": "Baixar",
        "History": "Histórico",
        "Settings": "Configurações",
    },
    "ru": {
        "Sign-ins": "Входы",
        "Browser extension": "Расширение браузера",
        "Download": "Скачать",
        "History": "История",
        "Settings": "Настройки",
    },
    "zh_CN": {
        "Sign-ins": "登录",
        "Browser extension": "浏览器扩展",
        "Download": "下载",
        "History": "历史记录",
        "Settings": "设置",
    },
}


def catalogue_coverage():
    """Report how many source strings each catalogue actually declares.

    A missing entry is written out below as its own English source, which is
    what Qt needs to fall back cleanly — but it also makes an untranslated
    catalogue byte-indistinguishable from a finished one, so nothing could
    see that a locale was advertised and empty.

    Coverage counts *declared* keys, not values that differ from English. A
    real translation may coincide with its source — German keeps "Video",
    "Audio" and "Server offline" — and counting differences would report a
    finished catalogue as incomplete.
    """
    known = set(SOURCE_STRINGS)
    report = {}
    for locale, translations in CATALOGS.items():
        declared = sum(1 for source in translations if source in known)
        report[locale] = (declared, len(SOURCE_STRINGS))
    return report


def write_ts(locale, translations):
    root = ET.Element(
        "TS",
        {
            "version": "2.1",
            "language": locale.replace("_", "-"),
            "sourcelanguage": "en",
        },
    )
    context = ET.SubElement(root, "context")
    ET.SubElement(context, "name").text = "AstraDownloader"
    for source in SOURCE_STRINGS:
        message = ET.SubElement(context, "message")
        ET.SubElement(message, "source").text = source
        translation = ET.SubElement(message, "translation")
        translation.text = translations.get(source, source)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    target = OUTPUT_DIR / f"astra_downloader_{locale}.ts"
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target


def find_lrelease():
    for name in ("pyside6-lrelease", "lrelease", "lrelease-qt6"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit(
        "Qt lrelease is required to refresh companion .qm files. "
        "Install the Qt/PySide development tools or retain the reviewed compiled catalogues."
    )


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    compiler = find_lrelease()
    for locale, translations in CATALOGS.items():
        ts_path = write_ts(locale, translations)
        qm_path = ts_path.with_suffix(".qm")
        subprocess.run(
            [compiler, str(ts_path), "-qm", str(qm_path)],
            check=True,
        )
        if not qm_path.exists() or qm_path.stat().st_size < 100:
            raise SystemExit(f"Translation compiler did not produce {qm_path}")
    print(f"Compiled {len(CATALOGS)} companion translation catalogues.")
    for locale, (translated, total) in sorted(catalogue_coverage().items()):
        if locale == "en":
            continue
        note = "" if translated == total else "   <- incomplete"
        print(f"  {locale:>5}: {translated}/{total} strings translated{note}")


if __name__ == "__main__":
    main()
