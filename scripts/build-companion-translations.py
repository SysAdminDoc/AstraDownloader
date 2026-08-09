#!/usr/bin/env python3
"""Generate Qt Linguist sources and compile companion translation catalogues."""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "astra_downloader" / "translations"
# The strings to translate are EXTRACTED from the companion sources, never
# listed by hand.
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
        "Undo remove":
            "Entfernen rückgängig",
        "Undo import":
            "Import rückgängig",
        "Restore the subscription removed in this session.":
            "In dieser Sitzung entferntes Abonnement wiederherstellen.",
        "Restore the sign-in removed in this session.":
            "In dieser Sitzung entfernte Anmeldung wiederherstellen.",
        "The sign-in was restored.":
            "Die Anmeldung wurde wiederhergestellt.",
        "The subscription was restored.":
            "Das Abonnement wurde wiederhergestellt.",
        "Restore settings and subscriptions changed by the last import.":
            "Durch den letzten Import geänderte Einstellungen und Abonnements wiederherstellen.",
        "Could not restore the imported settings. The Undo snapshot is still available; check disk space and permissions, then retry.":
            "Die importierten Einstellungen konnten nicht wiederhergestellt werden. Der Rückgängig-Schnappschuss ist weiterhin verfügbar; prüfen Sie Speicherplatz und Berechtigungen und versuchen Sie es erneut.",
        "No sign-in removal is available to undo.":
            "Keine entfernte Anmeldung zum Wiederherstellen verfügbar.",
        "Subscription removed. Downloaded files were not deleted.":
            "Abonnement entfernt. Heruntergeladene Dateien wurden nicht gelöscht.",
        "No subscription removal is available to undo.":
            "Kein entferntes Abonnement zum Wiederherstellen verfügbar.",
        "No settings import is available to undo.":
            "Kein Einstellungen-Import zum Rückgängigmachen verfügbar.",
        "Settings were restored, but some imported subscriptions remain.":
            "Einstellungen wurden wiederhergestellt, aber einige importierte Abonnements sind noch vorhanden.",
        "Settings import undone.":
            "Einstellungen-Import rückgängig gemacht.",
        "Could not restore the stored sign-in.":
            "Die gespeicherte Anmeldung konnte nicht wiederhergestellt werden.",
        "Could not restore the subscription.":
            "Das Abonnement konnte nicht wiederhergestellt werden.",
        "Closing now will cancel {count} active downloads.":
            "Beim Schließen werden {count} aktive Downloads abgebrochen.",
        "Find a setting":
            "Einstellung suchen",
        "Filter settings":
            "Einstellungen filtern",
        "Search settings by name or group":
            "Einstellungen nach Name oder Gruppe durchsuchen",
        "No settings match this search.":
            "Keine Einstellungen entsprechen dieser Suche.",
        "Language":
            "Sprache",
        "Language changes apply after restarting Astra Downloader.":
            "Sprachänderungen werden nach einem Neustart von Astra Downloader angewendet.",
        "Import and export":
            "Import und Export",
        "Restore defaults":
            "Standards wiederherstellen",
        "Restore the editable settings to their shipped defaults.":
            "Bearbeitbare Einstellungen auf die mitgelieferten Standards zurücksetzen.",
        "Settings already use their defaults.":
            "Die Einstellungen verwenden bereits ihre Standards.",
        "Could not restore defaults. Nothing changed; check disk permissions and retry.":
            "Standards konnten nicht wiederhergestellt werden. Nichts wurde geändert; prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
        "SponsorBlock categories":
            "SponsorBlock-Kategorien",
        "Restored defaults for {count} settings: {names}.":
            "Standards für {count} Einstellungen wiederhergestellt: {names}.",
        "Settings restored and server restarted.":
            "Einstellungen wiederhergestellt und Server neu gestartet.",
        "Settings restored. Restart Astra Downloader to apply the language.":
            "Einstellungen wiederhergestellt. Starten Sie Astra Downloader neu, um die Sprache anzuwenden.",
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
        "One-link video password":
            "Videopasswort für einen Link",
        "Video password — one link only (optional)":
            "Videopasswort — nur ein Link (optional)",
        "For a single protected link. Stored site credentials live under Sign-ins.":
            "Für einen einzelnen geschützten Link. Gespeicherte Zugangsdaten finden Sie unter Anmeldungen.",
        "Video passwords are available for a single link only.":
            "Videopasswörter sind nur für einen einzelnen Link verfügbar.",
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
        "Store a signed-in session so private or members-only videos download. Cookies or stored credentials stay on this PC and are only ever sent to the site they belong to.":
            "Eine angemeldete Sitzung speichern, damit private oder mitgliederexklusive Videos heruntergeladen werden können. Cookies oder gespeicherte Zugangsdaten bleiben auf diesem PC und werden nur an die zugehörige Website gesendet.",
        "Read from":
            "Lesen aus",
        "Chromium browsers such as Chrome, Edge, Brave, Opera, Vivaldi, and Chromium 127+ encrypt their cookie store, so reading them from outside the browser usually fails — export a cookies.txt file or use username/password instead. Firefox can normally be read directly.":
            "Chromium-Browser wie Chrome, Edge, Brave, Opera, Vivaldi und Chromium 127+ verschlüsseln ihren Cookie-Speicher, sodass das Lesen von außerhalb des Browsers meist fehlschlägt — exportieren Sie eine cookies.txt oder verwenden Sie stattdessen Benutzername/Passwort. Firefox lässt sich normalerweise direkt lesen.",
        "likely unreadable on Windows 127+":
            "unter Windows 127+ wahrscheinlich nicht lesbar",
        "Site sign-in username":
            "Benutzername der Website-Anmeldung",
        "Username or email":
            "Benutzername oder E-Mail",
        "Site sign-in password":
            "Passwort der Website-Anmeldung",
        "Password":
            "Passwort",
        "Store username/password":
            "Benutzername/Passwort speichern",
        "username/password stored securely.":
            "Benutzername/Passwort sicher gespeichert.",
        "Username/password — stored securely":
            "Benutzername/Passwort — sicher gespeichert",
        "cookie session expired":
            "Cookie-Sitzung abgelaufen",
        "cookies + username/password":
            "Cookies + Benutzername/Passwort",
        "username/password":
            "Benutzername/Passwort",
        "Import this site's cookies or store its username/password to unblock the download waiting on it.":
            "Importieren Sie die Cookies dieser Website oder speichern Sie Benutzername/Passwort, um den wartenden Download freizugeben.",
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
        "Removed?":
            "Entfernt?",
        "Reveal log file":
            "Protokolldatei anzeigen",
        "Limited":
            "Eingeschränkt",
        "Maximum playlist items":
            "Maximale Playlist-Einträge",
        "Shortest playlist item in seconds":
            "Kürzestes Playlist-Element in Sekunden",
        "Longest playlist item in seconds":
            "Längstes Playlist-Element in Sekunden",
        "Unsaved changes":
            "Ungespeicherte Änderungen",
        "Checking yt-dlp. The verified current copy stays available until the update passes.":
            "yt-dlp wird geprüft. Die verifizierte aktuelle Kopie bleibt erhalten, bis das Update erfolgreich ist.",
        "yt-dlp update failed. The previous working copy was kept; check the log for details.":
            "Das yt-dlp-Update ist fehlgeschlagen. Die vorherige funktionierende Kopie wurde beibehalten; prüfen Sie das Protokoll.",
        "Refreshing ffmpeg. The current verified copy stays available until replacement succeeds.":
            "ffmpeg wird aktualisiert. Die aktuelle verifizierte Kopie bleibt verfügbar, bis der Ersatz erfolgreich ist.",
        "Token copied. It will clear from the clipboard in 60 seconds if unchanged.":
            "Token kopiert. Es wird in 60 Sekunden aus der Zwischenablage gelöscht, falls es unverändert bleibt.",
        "New token ready. Save settings to apply it.":
            "Neues Token bereit. Speichern Sie die Einstellungen, um es anzuwenden.",
        "Server status indicator: Stopped":
            "Indikator für Serverstatus: Gestoppt",
        "Server status: Stopped":
            "Serverstatus: Gestoppt",
        "Companion pages":
            "Companion-Seiten",
        "Missing":
            "Fehlt",
        "Supported":
            "Unterstützt",
        "The installed yt-dlp streams SABR formats through fallback clients. Updates flip this automatically once native support ships.":
            "Das installierte yt-dlp streamt SABR-Formate über Fallback-Clients. Updates schalten dies automatisch um, sobald native Unterstützung verfügbar ist.",
        "Update":
            "Aktualisieren",
        "Proof-of-origin provider is running but out of date. Downloads use the web client with PO tokens.":
            "Der Proof-of-Origin-Anbieter läuft, ist aber veraltet. Downloads verwenden den Webclient mit PO-Tokens.",
        "Extension server status indicator: Offline":
            "Indikator für Erweiterungsserverstatus: Offline",
        "Review the redacted support payload before copying it.":
            "Redigierte Support-Nutzdaten vor dem Kopieren prüfen.",
        "Open the persisted server log in File Explorer.":
            "Gespeichertes Serverprotokoll im Datei-Explorer öffnen.",
        "Recent local companion events. Use Clear to remove visible entries.":
            "Aktuelle lokale Companion-Ereignisse. Mit „Leeren“ sichtbare Einträge entfernen.",
        "Video URL":
            "Video-URL",
        "Download type":
            "Downloadtyp",
        "Download format":
            "Downloadformat",
        "Download quality":
            "Downloadqualität",
        "Send this download somewhere other than the default folder.":
            "Diesen Download in einem anderen Ordner als dem Standardordner speichern.",
        "Clip start timestamp":
            "Startzeit des Clips",
        "Clip end timestamp":
            "Endzeit des Clips",
        "Subtitle request summary":
            "Zusammenfassung der Untertitelanforderung",
        "Quick download status":
            "Status des Schnell-Downloads",
        "Download tool setup status":
            "Status der Download-Tool-Einrichtung",
        "Download tool setup progress":
            "Fortschritt der Download-Tool-Einrichtung",
        "Storage problem":
            "Speicherproblem",
        "Quarantined state file":
            "In Quarantäne verschobene Zustandsdatei",
        "Running and pending downloads stored in the durable queue.":
            "Laufende und ausstehende Downloads in der dauerhaften Warteschlange.",
        "Pause starting pending downloads. Downloads already running will continue.":
            "Starten ausstehender Downloads pausieren. Bereits laufende Downloads werden fortgesetzt.",
        "Remove saved history entries. Downloaded files are not deleted.":
            "Gespeicherte Verlaufseinträge entfernen. Heruntergeladene Dateien werden nicht gelöscht.",
        "Restore the history entries cleared in this session.":
            "In dieser Sitzung gelöschte Verlaufseinträge wiederherstellen.",
        "Export every row matching the current filters as CSV.":
            "Alle Zeilen, die den aktuellen Filtern entsprechen, als CSV exportieren.",
        "Search download history":
            "Downloadverlauf durchsuchen",
        "History status":
            "Verlaufsstatus",
        "History format":
            "Verlaufsformat",
        "History sort order":
            "Sortierreihenfolge des Verlaufs",
        "History start date":
            "Startdatum des Verlaufs",
        "History end date":
            "Enddatum des Verlaufs",
        "History status message":
            "Statusmeldung des Verlaufs",
        "Subscription channel or playlist URL":
            "URL des Abonnementkanals oder der Playlist",
        "Subscription scan interval in minutes":
            "Scanintervall des Abonnements in Minuten",
        "Search subscriptions":
            "Abonnements durchsuchen",
        "Search title, URL, or error":
            "Titel, URL oder Fehler durchsuchen",
        "Subscription status":
            "Abonnementstatus",
        "Site address for the sign-in":
            "Adresse der Website für die Anmeldung",
        "Browser to read cookies from":
            "Browser zum Lesen von Cookies",
        "Browser profile name or path":
            "Name oder Pfad des Browserprofils",
        "Site sign-in status":
            "Status der Website-Anmeldung",
        "Search stored sign-ins":
            "Gespeicherte Anmeldungen durchsuchen",
        "Search site or source":
            "Website oder Quelle durchsuchen",
        "Stored sign-in status":
            "Status der gespeicherten Anmeldung",
        "Test":
            "Test",
        "Testing the stored sign-in…":
            "Gespeicherte Anmeldung wird getestet…",
        "Private API token":
            "Privates API-Token",
        "Reveal private token":
            "Privates Token anzeigen",
        "Fetch subtitle tracks and embed them in the file. The Subtitles download type fetches them without the video.":
            "Untertitelspuren abrufen und in die Datei einbetten. Der Downloadtyp „Untertitel“ ruft sie ohne das Video ab.",
        "Put .part, .f### and .ytdl files beside the output and keep them for diagnosis. Off by default: they use a private temporary folder and are removed after a successful download.":
            "Die .part-, .f###- und .ytdl-Dateien neben der Ausgabe ablegen und zur Diagnose behalten. Standardmäßig deaktiviert: Sie werden in einem privaten temporären Ordner verwendet und nach erfolgreichem Download entfernt.",
        "Subtitle tracks":
            "Untertitelspuren",
        "Subtitle format":
            "Untertitelformat",
        "SponsorBlock action":
            "SponsorBlock-Aktion",
        "Playlist uploaded after":
            "Playlist hochgeladen nach",
        "Socket timeout in seconds":
            "Socket-Timeout in Sekunden",
        "Check that a chosen format can actually be downloaded before committing to it. Costs an extra request per candidate format.":
            "Prüfen, ob ein ausgewähltes Format tatsächlich heruntergeladen werden kann, bevor es übernommen wird. Verursacht eine zusätzliche Anfrage pro Kandidatenformat.",
        "Pause between downloads in seconds":
            "Pause zwischen Downloads in Sekunden",
        "Longest pause in seconds":
            "Längste Pause in Sekunden",
        "Pacing jitter":
            "Pacing-Jitter",
        "Randomise host wait times and yt-dlp pacing by ± this percentage. 0 keeps fixed timing.":
            "Host-Wartezeiten und yt-dlp-Pacing um diesen Prozentsatz zufällig variieren. 0 verwendet feste Zeiten.",
        "Pacing jitter percentage":
            "Pacing-Jitter in Prozent",
        "Pause between requests in seconds":
            "Pause zwischen Anfragen in Sekunden",
        "Max file size in megabytes":
            "Maximale Dateigröße in Megabyte",
        "No limit":
            "Keine Begrenzung",
        "Checking installed yt-dlp…":
            "Installierte yt-dlp-Version wird geprüft…",
        "Watch clipboard changes for video links from any supported site. Matching links fill the Quick download field but are never downloaded until you confirm.":
            "Zwischenablage auf Videolinks von unterstützten Websites überwachen. Passende Links füllen das Schnell-Download-Feld, werden aber erst nach Ihrer Bestätigung heruntergeladen.",
        "Off by default. Clipboard content that does not look like a video link is ignored, and a matching link is staged without starting a download.":
            "Standardmäßig deaktiviert. Zwischenablageinhalte, die nicht wie ein Videolink aussehen, werden ignoriert; passende Links werden bereitgestellt, ohne einen Download zu starten.",
        "Installed tools status":
            "Status der installierten Tools",
        "Check for a yt-dlp update. Active downloads must finish first.":
            "Nach einem yt-dlp-Update suchen. Aktive Downloads müssen zuerst abgeschlossen werden.",
        "Download a fresh ffmpeg and verify its checksum. The installed copy stays in place until the replacement verifies.":
            "Frisches ffmpeg herunterladen und Prüfsumme verifizieren. Die installierte Kopie bleibt erhalten, bis der Ersatz verifiziert ist.",
        "Write settings and subscriptions to a JSON bundle.":
            "Einstellungen und Abonnements in ein JSON-Bundle schreiben.",
        "Read a bundle written by Export settings and apply it.":
            "Ein von „Einstellungen exportieren“ geschriebenes Bundle lesen und anwenden.",
        "Settings status":
            "Einstellungsstatus",
        "Starting":
            "Wird gestartet",
        "Could not save the imported settings. Check disk space and permissions, then retry.":
            "Importierte Einstellungen konnten nicht gespeichert werden. Prüfen Sie Speicherplatz und Berechtigungen und versuchen Sie es erneut.",
        "Loading history…":
            "Verlauf wird geladen…",
        "Copy error":
            "Fehler kopieren",
        "Install yt-dlp before checking for updates.":
            "Installieren Sie yt-dlp, bevor Sie nach Updates suchen.",
        "Wait for active downloads to finish before updating yt-dlp.":
            "Warten Sie, bis aktive Downloads abgeschlossen sind, bevor Sie yt-dlp aktualisieren.",
        "Setup is already running.":
            "Die Einrichtung läuft bereits.",
        "Wait for active downloads to finish before refreshing ffmpeg.":
            "Warten Sie, bis aktive Downloads abgeschlossen sind, bevor Sie ffmpeg aktualisieren.",
        "Choose a valid local video download folder.":
            "Wählen Sie einen gültigen lokalen Video-Downloadordner.",
        "Choose a valid local audio download folder.":
            "Wählen Sie einen gültigen lokalen Audio-Downloadordner.",
        "Enter one or more language codes, such as en or en,es.":
            "Geben Sie einen oder mehrere Sprachcodes ein, z. B. en oder en,es.",
        "Use a rate such as 500K or 2M, or leave this blank.":
            "Verwenden Sie eine Rate wie 500K oder 2M oder lassen Sie das Feld leer.",
        "Enter an http, https, or socks proxy URL.":
            "Geben Sie eine HTTP-, HTTPS- oder SOCKS-Proxy-URL ein.",
        "The private API token cannot be empty.":
            "Das private API-Token darf nicht leer sein.",
        "Keep %(ext)s and use only safe yt-dlp fields such as %(title)s, %(id)s, %(uploader)s — no absolute paths or '..'.":
            "Behalten Sie %(ext)s bei und verwenden Sie nur sichere yt-dlp-Felder wie %(title)s, %(id)s, %(uploader)s — keine absoluten Pfade oder '..'.",
        "Check the highlighted fields before saving.":
            "Prüfen Sie die markierten Felder vor dem Speichern.",
        "Could not save settings. Nothing changed; check disk permissions and retry.":
            "Einstellungen konnten nicht gespeichert werden. Nichts wurde geändert; prüfen Sie die Schreibrechte und versuchen Sie es erneut.",
        "Settings saved and server restarted.":
            "Einstellungen gespeichert und Server neu gestartet.",
        "Looking up available formats…":
            "Verfügbare Formate werden gesucht…",
        "Copied token cleared from the clipboard.":
            "Kopiertes Token wurde aus der Zwischenablage entfernt.",
        "Redacted diagnostics preview":
            "Vorschau der redigierten Diagnosedaten",
        "Installing required download tools...":
            "Erforderliche Download-Tools werden installiert…",
        "Setting Up":
            "Einrichtung",
        "Unavailable":
            "Nicht verfügbar",
        "Downloads use the web client with proof-of-origin tokens.":
            "Downloads verwenden den Webclient mit Proof-of-Origin-Tokens.",
        "Fallback":
            "Fallback",
        "No proof-of-origin provider is running. Downloads fall back to the token-exempt tv and android_vr clients.":
            "Kein Proof-of-Origin-Anbieter läuft. Downloads fallen auf die tokenfreien tv- und android_vr-Clients zurück.",
        "Run a bounded metadata-only sign-in test.":
            "Begrenzten Metadaten-Test der Anmeldung ausführen.",
        "Test passed":
            "Test bestanden",
        "Subscription scan started. This row will update when it finishes.":
            "Abonnement-Scan gestartet. Diese Zeile wird aktualisiert, sobald er abgeschlossen ist.",
        "Server status indicator: Starting":
            "Indikator für Serverstatus: Wird gestartet",
        "Server status: Starting":
            "Serverstatus: Wird gestartet",
        "Starting server":
            "Server wird gestartet",
        "Checking local ports and preparing the API":
            "Lokale Ports werden geprüft und die API wird vorbereitet",
        "Extension server status indicator: Starting":
            "Indikator für Erweiterungsserverstatus: Wird gestartet",
        "Starting server…":
            "Server wird gestartet…",
        "Running":
            "Läuft",
        "Resume pending downloads explicitly. Items needing sign-in remain paused.":
            "Ausstehende Downloads explizit fortsetzen. Elemente, die eine Anmeldung benötigen, bleiben pausiert.",
        "History unavailable":
            "Verlauf nicht verfügbar",
        "Could not read download history. The unreadable file was set aside; restore it from the state notice or inspect diagnostics.":
            "Downloadverlauf konnte nicht gelesen werden. Die unlesbare Datei wurde beiseitegelegt; stellen Sie sie aus dem Status-Hinweis wieder her oder prüfen Sie die Diagnose.",
        "Settings saved. Restart Astra Downloader to apply the language.":
            "Einstellungen gespeichert. Starten Sie Astra Downloader neu, um die Sprache anzuwenden.",
        "Settings saved.":
            "Einstellungen gespeichert.",
        "Hide":
            "Ausblenden",
        "Hide private token":
            "Privates Token ausblenden",
        "Server error":
            "Serverfehler",
        "Server status: Error":
            "Serverstatus: Fehler",
        "Server status indicator: Error":
            "Indikator für Serverstatus: Fehler",
        "Extension server status indicator: Error":
            "Indikator für Erweiterungsserverstatus: Fehler",
        "Server failed to start. Check the log for details.":
            "Serverstart fehlgeschlagen. Prüfen Sie das Protokoll auf Details.",
        "Installing yt-dlp...":
            "yt-dlp wird installiert…",
        "{label} status indicator: {value}":
            "{label} Statusindikator: {value}",
        "{label} status: {value}":
            "{label} Status: {value}",
        "Required":
            "Erforderlich",
        "Optional":
            "Optional",
        "No subscriptions match these filters":
            "Keine Abonnements entsprechen diesen Filtern",
        "Try a different search or choose All subscriptions.":
            "Versuchen Sie es mit einer anderen Suche oder wählen Sie „Alle Abonnements“.",
        "No sign-ins match these filters":
            "Keine Anmeldungen entsprechen diesen Filtern",
        "Try a different search or choose All sign-ins.":
            "Versuchen Sie es mit einer anderen Suche oder wählen Sie „Alle Anmeldungen“.",
        "Stored sign-in test passed.":
            "Test der gespeicherten Anmeldung bestanden.",
        "Server status indicator: Running":
            "Indikator für Serverstatus: Läuft",
        "Server status: Running":
            "Serverstatus: Läuft",
        "Server online":
            "Server online",
        "Local only · ready for Astra Deck":
            "Nur lokal · bereit für Astra Deck",
        "Extension server status indicator: Online":
            "Indikator für Erweiterungsserverstatus: Online",
        "Stop server":
            "Server stoppen",
        "Local only · start before downloading":
            "Nur lokal · vor dem Download starten",
        "{title} status: {status}":
            "{title} Status: {status}",
        "Move this pending download earlier.":
            "Diesen ausstehenden Download nach oben verschieben.",
        "Move this pending download later.":
            "Diesen ausstehenden Download nach unten verschieben.",
        "Resume this download.":
            "Diesen Download fortsetzen.",
        "Store this site's signed-in session so the download can run.":
            "Gespeicherte Anmeldung für diese Website ablegen, damit der Download ausgeführt werden kann.",
        "History could not be read":
            "Verlauf konnte nicht gelesen werden",
        "Astra Downloader kept the unreadable history aside instead of showing an empty list.":
            "Astra Downloader hat den unlesbaren Verlauf beiseitegelegt, statt eine leere Liste anzuzeigen.",
        "Open diagnostics":
            "Diagnose öffnen",
        "Settings status: {message}":
            "Einstellungsstatus: {message}",
        "Installing ffmpeg...":
            "ffmpeg wird installiert…",
        "This download goes to {path}. Click to use the default folder again.":
            "Dieser Download wird in {path} gespeichert. Klicken Sie, um wieder den Standardordner zu verwenden.",
        "{shown} of {total} shown":
            "{shown} von {total} angezeigt",
        "Enable subscription":
            "Abonnement aktivieren",
        "Every {minutes} min · scanning now…":
            "Alle {minutes} Min. · Scan läuft…",
        "Test failed":
            "Test fehlgeschlagen",
        "Subtitle language":
            "Untertitelsprache",
        "{title} progress":
            "{title} Fortschritt",
        "{progress} percent complete":
            "{progress} Prozent abgeschlossen",
        "Could not read download history: {error}":
            "Downloadverlauf konnte nicht gelesen werden: {error}",
        "No current message":
            "Keine aktuelle Meldung",
        "Port {configured} was unavailable at startup; bound to fallback port {port} for this session. Restart to retry {configured}.":
            "Port {configured} war beim Start nicht verfügbar; für diese Sitzung wurde auf Port {port} ausgewichen. Starten Sie neu, um {configured} erneut zu versuchen.",
        "Registering shortcuts and protocols...":
            "Verknüpfungen und Protokolle werden registriert…",
        "Finishing setup...":
            "Einrichtung wird abgeschlossen…",
        "This host is paused — retry in {duration}.":
            "Dieser Host ist pausiert — erneut versuchen in {duration}.",
        "Host paused · retry in {duration}":
            "Host pausiert · erneut versuchen in {duration}",
        "YouTube requires a PO token for this video. Start the PO-token provider, then retry the download.":
            "YouTube benötigt für dieses Video ein PO-Token. Starten Sie den PO-Token-Anbieter und versuchen Sie den Download erneut.",
        "Start bgutil-ytdlp-pot-provider on 127.0.0.1:4416 and retry.":
            "Starten Sie bgutil-ytdlp-pot-provider auf 127.0.0.1:4416 und versuchen Sie es erneut.",
        "start-po-token-provider":
            "start-po-token-provider",
        "The PO-token provider is reachable but looks stale or failed to issue a usable token.":
            "Der PO-Token-Anbieter ist erreichbar, wirkt aber veraltet oder konnte kein nutzbares Token ausstellen.",
        "Update or restart bgutil-ytdlp-pot-provider, then retry.":
            "Aktualisieren oder starten Sie bgutil-ytdlp-pot-provider neu und versuchen Sie es erneut.",
        "update-po-token-provider":
            "update-po-token-provider",
        "This video only exposes SABR-limited formats that this yt-dlp path cannot download yet.":
            "Dieses Video bietet nur SABR-beschränkte Formate, die dieser yt-dlp-Pfad noch nicht herunterladen kann.",
        "Clip ranges, the bandwidth cap and concurrent fragments do not apply to SABR streams and were ignored. Update yt-dlp when SABR support lands, or retry after YouTube exposes standard formats.":
            "Clipbereiche, Bandbreitenbegrenzung und gleichzeitige Fragmente gelten nicht für SABR-Streams und wurden ignoriert. Aktualisieren Sie yt-dlp, sobald SABR-Unterstützung verfügbar ist, oder versuchen Sie es erneut, nachdem YouTube Standardformate anbietet.",
        "update-ytdlp-or-retry-later":
            "update-ytdlp-or-retry-later",
        "yt-dlp needs the Deno JavaScript runtime to solve recent YouTube signature challenges.":
            "yt-dlp benötigt die Deno-JavaScript-Laufzeit, um aktuelle YouTube-Signatur-Herausforderungen zu lösen.",
        "Install Deno with winget install DenoLand.Deno, then restart Astra Downloader.":
            "Installieren Sie Deno mit winget install DenoLand.Deno und starten Sie Astra Downloader anschließend neu.",
        "install-deno":
            "install-deno",
        "The installed Deno runtime is too old for this yt-dlp build to solve recent YouTube signature challenges.":
            "Die installierte Deno-Laufzeit ist für diesen yt-dlp-Build zu alt, um aktuelle YouTube-Signatur-Herausforderungen zu lösen.",
        "Upgrade Deno to 2.3.0 or newer with winget upgrade DenoLand.Deno, then retry.":
            "Führen Sie ein Upgrade auf Deno 2.3.0 oder neuer mit winget upgrade DenoLand.Deno durch und versuchen Sie es erneut.",
        "upgrade-deno":
            "upgrade-deno",
        "yt-dlp needs a configured JavaScript runtime for YouTube challenges.":
            "yt-dlp benötigt eine konfigurierte JavaScript-Laufzeit für YouTube-Herausforderungen.",
        "Provision Deno, or install Node 22+ and select it in companion settings.":
            "Stellen Sie Deno bereit oder installieren Sie Node 22+ und wählen Sie es in den Companion-Einstellungen aus.",
        "configure-javascript-runtime":
            "configure-javascript-runtime",
        "Astra Downloader could not verify the configured JavaScript runtime.":
            "Astra Downloader konnte die konfigurierte JavaScript-Laufzeit nicht verifizieren.",
        "Repair or replace the selected runtime, then retry.":
            "Reparieren oder ersetzen Sie die ausgewählte Laufzeit und versuchen Sie es erneut.",
        "Repair or replace the selected JavaScript runtime, then retry.":
            "Reparieren oder ersetzen Sie die ausgewählte JavaScript-Laufzeit und versuchen Sie es erneut.",
        "repair-javascript-runtime":
            "repair-javascript-runtime",
        "The configured JavaScript runtime is below yt-dlp's supported floor.":
            "Die konfigurierte JavaScript-Laufzeit liegt unter der von yt-dlp unterstützten Mindestversion.",
        "Upgrade to Deno 2.3+ or Node 22+, then retry.":
            "Führen Sie ein Upgrade auf Deno 2.3+ oder Node 22+ durch und versuchen Sie es erneut.",
        "upgrade-javascript-runtime":
            "upgrade-javascript-runtime",
        "The configured runtime could not execute the yt-dlp EJS capability probe.":
            "Die konfigurierte Laufzeit konnte die EJS-Fähigkeitsprüfung von yt-dlp nicht ausführen.",
        "Sign in to confirm YouTube access. Grant browser cookies or open the video while signed in, then retry.":
            "Melden Sie sich an, um den YouTube-Zugriff zu bestätigen. Gewähren Sie Browser-Cookies oder öffnen Sie das Video während der Anmeldung und versuchen Sie es erneut.",
        "Sign in to YouTube in this browser and allow Astra Deck to attach YouTube cookies.":
            "Melden Sie sich in diesem Browser bei YouTube an und erlauben Sie Astra Deck, YouTube-Cookies anzuhängen.",
        "sign-in-and-retry":
            "sign-in-and-retry",
        "ffmpeg is missing, stale, or failed during merge/extract.":
            "ffmpeg fehlt, ist veraltet oder ist beim Zusammenführen/Extrahieren fehlgeschlagen.",
        "Open Astra Downloader and refresh ffmpeg before retrying.":
            "Öffnen Sie Astra Downloader und aktualisieren Sie ffmpeg, bevor Sie es erneut versuchen.",
        "refresh-ffmpeg":
            "refresh-ffmpeg",
        "Astra Downloader could not reach the site or a required provider.":
            "Astra Downloader konnte die Website oder einen erforderlichen Anbieter nicht erreichen.",
        "Check the network, VPN, firewall, and provider process, then retry.":
            "Prüfen Sie Netzwerk, VPN, Firewall und den Anbieterprozess und versuchen Sie es erneut.",
        "check-network-and-retry":
            "check-network-and-retry",
        "Astra Downloader could not create a protected YouTube cookie jar.":
            "Astra Downloader konnte kein geschütztes YouTube-Cookie-Archiv erstellen.",
        "Retry from Astra Deck so fresh cookies can be supplied.":
            "Versuchen Sie es erneut über Astra Deck, damit neue Cookies bereitgestellt werden können.",
        "The site refused the request (HTTP 403).":
            "Die Website hat die Anfrage abgelehnt (HTTP 403).",
        "Set a browser to imitate in Settings — this is the usual remedy for a Cloudflare or TLS-fingerprint block. A stored sign-in for the site also helps.":
            "Stellen Sie in den Einstellungen einen Browser zur Nachahmung ein — dies ist das übliche Mittel gegen eine Cloudflare- oder TLS-Fingerprint-Sperre. Eine gespeicherte Anmeldung für die Website hilft ebenfalls.",
        "impersonate-and-retry":
            "impersonate-and-retry",
        "The site refused further requests for now (HTTP 429).":
            "Die Website hat weitere Anfragen vorerst abgelehnt (HTTP 429).",
        "This site is paused for the rest of its retry window. Raise the request pacing in Settings — a bandwidth cap does not help here — then retry. Other sites can continue downloading.":
            "Diese Website ist für den Rest des Wiederholungsfensters pausiert. Erhöhen Sie in den Einstellungen das Anfrage-Pacing — eine Bandbreitenbegrenzung hilft hier nicht — und versuchen Sie es erneut. Andere Websites können weiter herunterladen.",
        "slow-down-and-retry":
            "slow-down-and-retry",
        "There is not enough free disk space for this download.":
            "Nicht genügend freier Speicherplatz für diesen Download.",
        "Free space on the destination drive, then retry the download.":
            "Geben Sie Speicherplatz auf dem Ziellaufwerk frei und versuchen Sie den Download erneut.",
        "free-disk-space-and-retry":
            "free-disk-space-and-retry",
        "This link only offers SABR streams. {options} do not apply to them and will be ignored.":
            "Dieser Link bietet nur SABR-Streams. {options} gelten für sie nicht und werden ignoriert.",
        "Antivirus software may have removed or truncated it. Add an exclusion for {path} and let setup fetch it again.":
            "Antivirensoftware hat die Datei möglicherweise entfernt oder gekürzt. Fügen Sie eine Ausnahme für {path} hinzu und lassen Sie die Einrichtung sie erneut abrufen.",
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
