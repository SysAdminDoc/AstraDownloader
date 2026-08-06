#!/usr/bin/env python3
"""Generate Qt Linguist sources and compile companion translation catalogues."""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "astra_downloader" / "translations"
# The strings to translate are EXTRACTED from the GUI, never listed by hand.
#
# They used to be a hand-written tuple of 21 entries against a window that
# shows 138, because nothing connected the tuple to the code: every string
# added after the tuple was written simply never reached a translator, and
# the catalogues still reported themselves complete.
try:
    from extract_companion_strings import extract_all
except ImportError:  # Running from the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from extract_companion_strings import extract_all

SOURCE_STRINGS = tuple(extract_all())

CATALOGS = {
    "ar": {
        "Sign-ins": "تسجيلات الدخول",
        "Browser extension": "امتداد المتصفح",
        "Download": "تنزيل",
        "History": "السجل",
        "Settings": "الإعدادات",
    },
    "de": {
        "Extension server":
            "Erweiterungsserver",
        "Stopped":
            "Gestoppt",
        "Server offline":
            "Server offline",
        "Local only · token required":
            "Nur lokal · Token erforderlich",
        "Start server":
            "Server starten",
        "Copy endpoint":
            "Endpunkt kopieren",
        "Open folder":
            "Ordner öffnen",
        "Active":
            "Aktiv",
        "In progress":
            "Läuft",
        "Completed":
            "Abgeschlossen",
        "This session":
            "Diese Sitzung",
        "Uptime":
            "Laufzeit",
        "Since launch":
            "Seit dem Start",
        "Port":
            "Port",
        "Local API":
            "Lokale API",
        "Clear":
            "Leeren",
        "Review diagnostics":
            "Diagnose prüfen",
        "Download":
            "Herunterladen",
        "Save to":
            "Speichern unter",
        "Restore":
            "Wiederherstellen",
        "Dismiss":
            "Ausblenden",
        "0 / 200 jobs":
            "0 / 200 Aufträge",
        "Pause intake":
            "Annahme pausieren",
        "Clear history":
            "Verlauf löschen",
        "Undo clear":
            "Löschen rückgängig",
        "Export filtered":
            "Gefilterte exportieren",
        "0 of 0 retained":
            "0 von 0 behalten",
        "Previous":
            "Zurück",
        "Next":
            "Weiter",
        "New subscription":
            "Neues Abonnement",
        "Every":
            "Alle",
        "Add subscription":
            "Abonnement hinzufügen",
        "Subscriptions are ready when the local companion is running.":
            "Abonnements sind verfügbar, sobald die lokale Anwendung läuft.",
        "Read from browser":
            "Aus dem Browser lesen",
        "Import cookies.txt":
            "cookies.txt importieren",
        "Connection":
            "Verbindung",
        "Reveal":
            "Anzeigen",
        "Copy":
            "Kopieren",
        "Regenerate":
            "Neu erzeugen",
        "Storage":
            "Speicherort",
        "Browse":
            "Durchsuchen",
        "Post-processing":
            "Nachbearbeitung",
        "Format preferences":
            "Formatwünsche",
        "Preferred video codec":
            "Bevorzugter Videocodec",
        "Preferred audio codec":
            "Bevorzugter Audiocodec",
        "Preferred frame rate":
            "Bevorzugte Bildrate",
        "Playlist limits":
            "Playlist-Grenzen",
        "Maximum items":
            "Maximale Anzahl",
        "Stop after this many items from one playlist. 0 takes all of them.":
            "Nach so vielen Einträgen einer Playlist stoppen. 0 nimmt alle.",
        "Shortest item (seconds)":
            "Kürzester Eintrag (Sekunden)",
        "Skip items shorter than this, which is how a channel's shorts are left behind. 0 takes any length.":
            "Kürzere Einträge überspringen — so bleiben die Shorts eines Kanals außen vor. 0 nimmt jede Länge.",
        "Longest item (seconds)":
            "Längster Eintrag (Sekunden)",
        "Skip items longer than this, which is how multi-hour streams are left behind. 0 takes any length.":
            "Längere Einträge überspringen — so bleiben mehrstündige Streams außen vor. 0 nimmt jede Länge.",
        "Performance":
            "Leistung",
        "Tray behavior":
            "Infobereich",
        "Maintenance":
            "Wartung",
        "Checking installed tools…":
            "Installierte Werkzeuge werden geprüft…",
        "Check for yt-dlp updates":
            "Nach yt-dlp-Updates suchen",
        "Reinstall ffmpeg":
            "ffmpeg neu installieren",
        "Export settings":
            "Einstellungen exportieren",
        "Import settings":
            "Einstellungen importieren",
        "Save changes":
            "Änderungen speichern",
        "Review the redacted support payload":
            "Bereinigte Supportdaten prüfen",
        "Paths, URLs, tokens, cookie-shaped values, and opaque identifiers are removed. Only copy this payload if you are comfortable sharing what remains.":
            "Pfade, URLs, Token, cookieähnliche Werte und undurchsichtige Kennungen werden entfernt. Kopieren Sie diese Daten nur, wenn Sie mit der Weitergabe des Rests einverstanden sind.",
        "Browser extension":
            "Browser-Erweiterung",
        "Astra Downloader runs a local API so the Astra Deck browser extension can send downloads straight from a page. Downloading by pasting a link never needs this server.":
            "Astra Downloader betreibt eine lokale API, damit die Astra-Deck-Browsererweiterung Downloads direkt von einer Seite senden kann. Zum Herunterladen per eingefügtem Link wird dieser Server nie benötigt.",
        "Pairing":
            "Kopplung",
        "The extension finds this server on its own once it is running. Requests are accepted from this machine only and must carry the session token.":
            "Die Erweiterung findet diesen Server selbst, sobald er läuft. Anfragen werden nur von diesem Computer angenommen und müssen das Sitzungstoken enthalten.",
        "Server log":
            "Serverprotokoll",
        "Download a video":
            "Video herunterladen",
        "Paste a link from almost any site — YouTube, Reddit, X, TikTok, Vimeo, Instagram, Twitch and hundreds more.":
            "Fügen Sie einen Link von fast jeder Website ein — YouTube, Reddit, X, TikTok, Vimeo, Instagram, Twitch und Hunderte mehr.",
        "Paste a video link, or several at once":
            "Videolink einfügen, auch mehrere auf einmal",
        "Video":
            "Video",
        "Audio":
            "Audio",
        "Subtitles":
            "Untertitel",
        "Clip from":
            "Ausschnitt von",
        "to":
            "bis",
        "Clip ranges apply to a single link.":
            "Ausschnitte gelten nur für einen einzelnen Link.",
        "History":
            "Verlauf",
        "All statuses":
            "Alle Status",
        "Complete":
            "Abgeschlossen",
        "All formats":
            "Alle Formate",
        "Newest first":
            "Neueste zuerst",
        "Oldest first":
            "Älteste zuerst",
        "Saved from":
            "Gespeichert ab",
        "through":
            "bis",
        "File":
            "Datei",
        "Subscriptions":
            "Abonnements",
        "Watch YouTube channels or playlists on a schedule and queue only new uploads.":
            "YouTube-Kanäle oder Playlists nach Zeitplan beobachten und nur neue Uploads einreihen.",
        "Scan now":
            "Jetzt prüfen",
        "Remove":
            "Entfernen",
        "Sign-ins":
            "Anmeldungen",
        "Add a site sign-in":
            "Website-Anmeldung hinzufügen",
        "Site address you signed in to — x.com, instagram.com, vimeo.com":
            "Adresse der Website, bei der Sie angemeldet sind — x.com, instagram.com, vimeo.com",
        "Profile (optional)":
            "Profil (optional)",
        "Import this site's cookies to unblock the download waiting on it.":
            "Cookies dieser Website importieren, um den wartenden Download freizugeben.",
        "Reading cookies from the browser…":
            "Cookies werden aus dem Browser gelesen…",
        "Settings":
            "Einstellungen",
        "Local API port":
            "Lokaler API-Port",
        "Default 9751. Change only for custom clients.":
            "Standard 9751. Nur für eigene Clients ändern.",
        "Private token":
            "Privates Token",
        "Authorizes extension requests on this computer.":
            "Autorisiert Anfragen der Erweiterung auf diesem Computer.",
        "Video download folder":
            "Ordner für Videodownloads",
        "Default destination for video downloads.":
            "Standardziel für Videodownloads.",
        "Audio download folder":
            "Ordner für Audiodownloads",
        "Leave blank to use the video folder.":
            "Leer lassen, um den Videoordner zu verwenden.",
        "Filename template":
            "Dateinamenvorlage",
        "Optional yt-dlp output template, relative to the folder above (e.g. %(uploader)s/%(title)s.%(ext)s). Must keep %(ext)s. Title and channel fields are length-bounded on save so long titles cannot overrun the maximum path length. Blank uses the default.":
            "Optionale yt-dlp-Ausgabevorlage, relativ zum Ordner oben (z. B. %(uploader)s/%(title)s.%(ext)s). %(ext)s muss erhalten bleiben. Titel- und Kanalfelder werden beim Speichern in der Länge begrenzt, damit lange Titel die maximale Pfadlänge nicht überschreiten. Leer verwendet den Standard.",
        "Embed metadata":
            "Metadaten einbetten",
        "Embed thumbnail":
            "Vorschaubild einbetten",
        "Embed chapters":
            "Kapitel einbetten",
        "Download subtitles":
            "Untertitel herunterladen",
        "Keep intermediate files":
            "Zwischendateien behalten",
        "Tracks":
            "Spuren",
        "Save as":
            "Speichern als",
        "Subtitle languages":
            "Untertitelsprachen",
        "Use SponsorBlock segments":
            "SponsorBlock-Segmente verwenden",
        "Action":
            "Aktion",
        "Remove segments":
            "Segmente entfernen",
        "Mark segments":
            "Segmente markieren",
        "With nothing ticked, every category is acted on.":
            "Ohne Auswahl werden alle Kategorien berücksichtigt.",
        "Preferences, not requirements: a link that has none of these still downloads. The MP4 container overrides them, because an editor-safe file is the point of choosing MP4.":
            "Wünsche, keine Bedingungen: Ein Link ohne diese Eigenschaften wird trotzdem heruntergeladen. Der MP4-Container hat Vorrang, denn eine schnittsichere Datei ist der Sinn von MP4.",
        "These apply when you paste a playlist or channel. A single video is never filtered by them.":
            "Gilt beim Einfügen einer Playlist oder eines Kanals. Ein einzelnes Video wird dadurch nie gefiltert.",
        "Uploaded after":
            "Hochgeladen nach",
        "A date as YYYYMMDD, or a relative one such as today-30days. Empty takes any date.":
            "Ein Datum als JJJJMMTT oder relativ wie today-30days. Leer bedeutet jedes Datum.",
        "Concurrent fragments":
            "Gleichzeitige Fragmente",
        "More can improve fast connections.":
            "Mehr kann schnelle Verbindungen beschleunigen.",
        "Simultaneous downloads":
            "Gleichzeitige Downloads",
        "How many downloads run at once.":
            "Wie viele Downloads gleichzeitig laufen.",
        "Download retries":
            "Download-Wiederholungen",
        "Retry attempts on transient network errors.":
            "Wiederholungsversuche bei vorübergehenden Netzwerkfehlern.",
        "Rate limit":
            "Geschwindigkeitsbegrenzung",
        "Optional, such as 500K or 2M.":
            "Optional, etwa 500K oder 2M.",
        "Throttle floor":
            "Drosselungsschwelle",
        "Below this rate the server is assumed to be throttling and the video is re-extracted. Empty disables it.":
            "Unterhalb dieser Rate wird eine Drosselung durch den Server angenommen und das Video neu ausgelesen. Leer deaktiviert dies.",
        "Socket timeout":
            "Socket-Zeitlimit",
        "Seconds before a stalled connection is abandoned. 0 uses yt-dlp's own default.":
            "Sekunden, bevor eine hängende Verbindung abgebrochen wird. 0 verwendet den Standard von yt-dlp.",
        "Extractor retries":
            "Extractor-Wiederholungen",
        "Retries while reading the page, before any transfer starts. 0 uses yt-dlp's own default.":
            "Wiederholungen beim Lesen der Seite, bevor eine Übertragung beginnt. 0 verwendet den Standard von yt-dlp.",
        "Verify formats before downloading":
            "Formate vor dem Herunterladen prüfen",
        "Pause between downloads":
            "Pause zwischen Downloads",
        "Seconds to wait before each download. A bandwidth cap does not prevent an HTTP 429; spacing the requests does. 0 disables it.":
            "Wartezeit in Sekunden vor jedem Download. Eine Bandbreitenbegrenzung verhindert keinen HTTP 429, zeitliche Abstände schon. 0 deaktiviert dies.",
        "Longest pause":
            "Längste Pause",
        "Upper bound when the pause is randomised. Ignored below the pause above.":
            "Obergrenze, wenn die Pause zufällig gewählt wird. Wird ignoriert, wenn sie unter der Pause oben liegt.",
        "Pause between requests":
            "Pause zwischen Anfragen",
        "Seconds between the data requests inside one download.":
            "Sekunden zwischen den Datenanfragen innerhalb eines Downloads.",
        "Max file size":
            "Maximale Dateigröße",
        "Skip anything larger. 0 means no limit.":
            "Größeres überspringen. 0 bedeutet keine Begrenzung.",
        "Proxy":
            "Proxy",
        "Optional HTTP(S) or SOCKS proxy.":
            "Optionaler HTTP(S)- oder SOCKS-Proxy.",
        "Imitate a browser":
            "Browser nachahmen",
        "Sends a real browser's TLS fingerprint. The usual fix for a site that returns 403, though it can itself trigger rate limiting.":
            "Sendet den TLS-Fingerabdruck eines echten Browsers. Die übliche Lösung bei einer Website, die 403 zurückgibt, kann aber selbst eine Ratenbegrenzung auslösen.",
        "Off":
            "Aus",
        "JavaScript runtime":
            "JavaScript-Laufzeitumgebung",
        "Auto prefers Deno, then Node 22+, then the QuickJS runtime the app downloads for itself (2 MB).":
            "Automatisch bevorzugt Deno, dann Node 22+, dann die QuickJS-Laufzeitumgebung, die die App selbst herunterlädt (2 MB).",
        "Auto":
            "Automatisch",
        "yt-dlp update channel":
            "yt-dlp-Updatekanal",
        "Nightly ships same-day YouTube fixes; stable lags by weeks.":
            "Nightly liefert YouTube-Korrekturen am selben Tag, Stable hinkt Wochen hinterher.",
        "Nightly (recommended)":
            "Nightly (empfohlen)",
        "Stable":
            "Stabil",
        "Language":
            "Sprache",
        "Companion language":
            "Sprache der Anwendung",
        "Language changes apply the next time Astra Downloader starts.":
            "Sprachänderungen gelten beim nächsten Start von Astra Downloader.",
        "Keep yt-dlp up to date automatically":
            "yt-dlp automatisch aktuell halten",
        "Checks at most once every 12 hours - when the server starts and when the download queue goes idle.":
            "Prüft höchstens alle 12 Stunden – beim Serverstart und wenn die Warteschlange leer läuft.",
        "Close to the system tray":
            "In den Infobereich schließen",
        "Start minimized to the tray":
            "Minimiert im Infobereich starten",
        "Notify when a download finishes (while minimized)":
            "Benachrichtigen, wenn ein Download fertig ist (wenn minimiert)",
        "Stage copied video links for review":
            "Kopierte Videolinks zur Prüfung vormerken",
        "Installed tools":
            "Installierte Werkzeuge",
        "Move this install to another machine, or recover from a config you cannot open. The bundle carries settings and subscriptions. Stored sign-ins are listed by site but never exported — cookies stay on this machine.":
            "Diese Installation auf einen anderen Computer übertragen oder eine nicht mehr lesbare Konfiguration wiederherstellen. Das Paket enthält Einstellungen und Abonnements. Gespeicherte Anmeldungen werden nur nach Website aufgeführt, aber nie exportiert — Cookies bleiben auf diesem Computer.",
        "Cancel":
            "Abbrechen",
        "Play":
            "Abspielen",
        "Show in folder":
            "Im Ordner anzeigen",
        "Copy link":
            "Link kopieren",
        "Download again":
            "Erneut herunterladen",
        "Saved":
            "Gespeichert",
        "Best":
            "Beste",
        "Status":
            "Status",
        "Subscriptions unavailable":
            "Abonnements nicht verfügbar",
        "Start the Astra Downloader companion to manage scheduled channel scans.":
            "Starten Sie Astra Downloader, um geplante Kanalprüfungen zu verwalten.",
        "No scheduled subscriptions":
            "Keine geplanten Abonnements",
        "Add a YouTube channel or playlist above. New uploads will be queued on its interval.":
            "Fügen Sie oben einen YouTube-Kanal oder eine Playlist hinzu. Neue Uploads werden im eingestellten Intervall eingereiht.",
        "Store a signed-in session so private or members-only videos download. Cookies stay on this PC and are only ever sent to the site they came from.":
            "Eine angemeldete Sitzung speichern, damit private oder mitgliederexklusive Videos heruntergeladen werden können. Cookies bleiben auf diesem PC und werden nur an die Website gesendet, von der sie stammen.",
        "Read from":
            "Lesen aus",
        "Chrome, Edge, and Brave 127+ encrypt their cookie store, so reading them from outside the browser usually fails — export a cookies.txt file from the browser and import that instead. Firefox can normally be read directly.":
            "Chrome, Edge und Brave 127+ verschlüsseln ihren Cookie-Speicher, sodass das Lesen von außerhalb des Browsers meist fehlschlägt — exportieren Sie stattdessen eine cookies.txt aus dem Browser und importieren Sie diese. Firefox lässt sich normalerweise direkt lesen.",
        "Expired — sign in again to refresh it":
            "Abgelaufen — melden Sie sich erneut an, um sie zu erneuern",
        "Signed in to":
            "Angemeldet bei",
        "cookies stored":
            "Cookies gespeichert",
        "Site sign-ins are unavailable in this session.":
            "Website-Anmeldungen sind in dieser Sitzung nicht verfügbar.",
        "Up":
            "Hoch",
        "Down":
            "Runter",
        "Resume":
            "Fortsetzen",
        "Add sign-in":
            "Anmeldung hinzufügen",
        "No downloads yet":
            "Noch keine Downloads",
        "Completed downloads will appear here.":
            "Abgeschlossene Downloads erscheinen hier.",
        "View download queue":
            "Download-Warteschlange anzeigen",
        "No matching downloads":
            "Keine passenden Downloads",
        "Adjust the search, status, format, or saved-date filters.":
            "Passen Sie die Filter für Suche, Status, Format oder Speicherdatum an.",
        "Show":
            "Anzeigen",
        "No stored sign-ins":
            "Keine gespeicherten Anmeldungen",
        "Add one above for any site that only serves video to signed-in viewers. YouTube downloads use the browser extension instead and need nothing here.":
            "Fügen Sie oben eine für jede Website hinzu, die Videos nur angemeldeten Nutzern zeigt. YouTube-Downloads verwenden stattdessen die Browsererweiterung und benötigen hier nichts.",
        "Missing on disk — import it again":
            "Auf dem Datenträger nicht gefunden — erneut importieren",
        "cookies for other sites were discarded.":
            "Cookies anderer Websites wurden verworfen.",
        "No preference":
            "Keine Bevorzugung",
        "Retry":
            "Wiederholen",
        "Nothing downloading yet":
            "Es lädt noch nichts",
        "Paste a video link above to start. Downloads sent from the Astra Deck browser extension land here too.":
            "Fügen Sie oben einen Videolink ein, um zu beginnen. Downloads aus der Astra-Deck-Browsererweiterung erscheinen ebenfalls hier.",
        "Paste a link":
            "Link einfügen",
        "This link tops out at {height}p.":
            "Dieser Link bietet höchstens {height}p.",
        "page":
            "Seite",
        "Open":
            "Öffnen",
        "Session cookies — valid until the site signs you out":
            "Sitzungscookies — gültig, bis die Website Sie abmeldet",
        "Removed the stored sign-in for":
            "Gespeicherte Anmeldung entfernt für",
        "from":
            "von",
        "unknown":
            "unbekannt",
        "First cookie expires":
            "Erstes Cookie läuft ab",
        "cookie":
            "Cookie",
        "cookies":
            "Cookies",
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
