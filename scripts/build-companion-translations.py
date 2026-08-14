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
        "Theme":
            "Erscheinungsbild",
        "System default":
            "Systemstandard",
        "Dark":
            "Dunkel",
        "Light":
            "Hell",
        "System default follows the operating system appearance.":
            "Der Systemstandard folgt dem Erscheinungsbild des Betriebssystems.",
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
        "(Using SponsorBlock)":
            "(Using SponsorBlock)",
        "SponsorBlock data and API are licensed CC BY-NC-SA 4.0; Astra Downloader is MIT.":
            "Daten und API von SponsorBlock stehen unter CC BY-NC-SA 4.0; Astra Downloader steht unter MIT.",
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
        "Profile":
            "Profil",
        "Site profiles":
            "Site-Profile",
        "Site profile":
            "Site-Profil",
        "Site profile summary":
            "Zusammenfassung des Site-Profils",
        "Automatic site profile":
            "Automatisches Site-Profil",
        "No profile (one-off)":
            "Kein Profil (einmalig)",
        "No site profile for this download.":
            "Kein Site-Profil für diesen Download.",
        "Named site profiles":
            "Benannte Site-Profile",
        'Example: [{"Name":"YouTube archive","Domain":"youtube.com","VideoFormat":"mp4","Quality":"1080"}]':
            'Beispiel: [{"Name":"YouTube archive","Domain":"youtube.com","VideoFormat":"mp4","Quality":"1080"}]',
        "One JSON object per profile. Match a domain automatically, or choose a profile for one download in the paste box. Supported defaults include format, quality, proxy, impersonation and request pacing; do not put cookies or passwords here.":
            "Ein JSON-Objekt pro Profil. Ordnen Sie automatisch eine Domain zu oder wählen Sie ein Profil für einen einzelnen Download im Eingabefeld. Unterstützte Vorgaben umfassen Format, Qualität, Proxy, Impersonation und Anfragepausen; speichern Sie hier keine Cookies oder Passwörter.",
        "Automatic matching is on; no profile matches this link.":
            "Die automatische Zuordnung ist aktiv; kein Profil passt zu diesem Link.",
        "Using site profile: {name}.":
            "Site-Profil wird verwendet: {name}.",
        "Reveal":
            "Anzeigen",
        "Copy":
            "Kopieren",
        "Regenerate":
            "Neu erzeugen",
        "Storage":
            "Speicherort",
        "Filename template preview":
            "Vorschau der Dateinamensvorlage",
        "Use Windows-safe filenames":
            "Windows-sichere Dateinamen verwenden",
        "Ask yt-dlp to replace characters and names that Windows cannot store.":
            "yt-dlp soll Zeichen und Namen ersetzen, die Windows nicht speichern kann.",
        "Browse":
            "Durchsuchen",
        "Confirm folder":
            "Ordner bestätigen",
        "Open extension pairing":
            "Erweiterungskopplung öffnen",
        "Post-processing":
            "Nachbearbeitung",
        "Write info JSON sidecar":
            "Info-JSON als Begleitdatei schreiben",
        "Write media-server NFO sidecar":
            "NFO-Begleitdatei für Medienserver schreiben",
        "Write Kodi/Jellyfin-compatible NFO metadata beside downloaded media and create tvshow.nfo and season.nfo for channel folders.":
            "Kodi/Jellyfin-kompatible NFO-Metadaten neben heruntergeladenen Medien schreiben und tvshow.nfo sowie season.nfo für Kanäle erstellen.",
        "Write description sidecar":
            "Beschreibung als Begleitdatei schreiben",
        "Write thumbnail sidecar":
            "Vorschaubild als Begleitdatei schreiben",
        "Split chapters into files":
            "Kapitel in einzelne Dateien aufteilen",
        "Start live streams from the beginning":
            "Livestreams von Anfang an starten",
        "Live-video retry interval":
            "Intervall für Live-Video-Wiederholungen",
        " seconds":
            " Sekunden",
        "Archive output":
            "Archiv-Ausgabe",
        "Optional sidecars, chapter splitting and live-event controls. These do not change the existing embed options.":
            "Optionale Begleitdateien, Kapitelaufteilung und Live-Ereignissteuerung. Die bestehenden Einbettungsoptionen bleiben unverändert.",
        "0 disables live-event retries; otherwise yt-dlp retries at this interval within a bounded wait window.":
            "0 deaktiviert Wiederholungen für Live-Ereignisse; andernfalls versucht yt-dlp innerhalb eines begrenzten Wartefensters in diesem Intervall erneut.",
        "Preview unavailable until the template is valid.":
            "Die Vorschau ist verfügbar, sobald die Vorlage gültig ist.",
        "The template preview uses a reserved Windows name.":
            "Die Vorlagenvorschau verwendet einen reservierten Windows-Namen.",
        "The rendered template path is too long for Windows.":
            "Der gerenderte Vorlagenpfad ist für Windows zu lang.",
        "Reserved Windows name in preview: {name}.":
            "Reservierter Windows-Name in der Vorschau: {name}.",
        "Rendered path is {length} characters; Windows maximum is {maximum}.":
            "Der gerenderte Pfad hat {length} Zeichen; das Windows-Maximum ist {maximum}.",
        "Preview: {path} ({length} characters).":
            "Vorschau: {path} ({length} Zeichen).",
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
        "No server events yet":
            "Noch keine Serverereignisse",
        "Start the local API or pair the browser extension to see recent activity here.":
            "Starten Sie die lokale API oder koppeln Sie die Browsererweiterung, um hier aktuelle Aktivitäten zu sehen.",
        "Download a video":
            "Video herunterladen",
        "Paste a link from almost any site — YouTube, Reddit, X, TikTok, Vimeo, Instagram, Twitch and hundreds more.":
            "Fügen Sie einen Link von fast jeder Website ein — YouTube, Reddit, X, TikTok, Vimeo, Instagram, Twitch und Hunderte mehr.",
        "Welcome to Astra Downloader":
            "Willkommen bei Astra Downloader",
        "Confirm where finished videos should go. You can change this later in Settings.":
            "Bestätigen Sie, wohin fertige Videos gespeichert werden. Sie können dies später in den Einstellungen ändern.",
        "This choice is saved once for this install.":
            "Diese Auswahl wird für diese Installation einmalig gespeichert.",
        "First-run download folder":
            "Downloadordner beim ersten Start",
        "First-run setup status":
            "Einrichtungsstatus beim ersten Start",
        "When setup finishes, pair Astra Deck from the local extension page.":
            "Wenn die Einrichtung abgeschlossen ist, koppeln Sie Astra Deck über die lokale Erweiterungsseite.",
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
        "From link":
            "Aus Link",
        "Use the timestamp in the pasted link as the clip start.":
            "Den Zeitstempel des eingefügten Links als Clipstart verwenden.",
        "Last 30 s":
            "Letzte 30 s",
        "Download only the last 30 seconds using yt-dlp.":
            "Nur die letzten 30 Sekunden mit yt-dlp herunterladen.",
        "Clip ranges are unavailable for this SABR-only link.":
            "Clipbereiche sind für diesen SABR-only-Link nicht verfügbar.",
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
        "Generate local subtitles when no track exists":
            "Lokale Untertitel erzeugen, wenn keine Spur vorhanden ist",
        "After a video download, use the locally provisioned Whisper model to write an SRT sidecar only when yt-dlp found no subtitle track.":
            "Nach einem Videodownload das lokal bereitgestellte Whisper-Modell verwenden, um nur dann eine SRT-Begleitdatei zu schreiben, wenn yt-dlp keine Untertitelspur gefunden hat.",
        "Uses the bundled multilingual Whisper model and the first language in Subtitle languages. Setup downloads the model when this option is enabled.":
            "Verwendet das gebündelte mehrsprachige Whisper-Modell und die erste Sprache unter Untertitelsprachen. Beim Aktivieren dieser Option lädt die Einrichtung das Modell herunter.",
        "Ready":
            "Bereit",
        "Local transcription is enabled and the pinned Whisper model is ready.":
            "Lokale Transkription ist aktiviert und das festgelegte Whisper-Modell ist bereit.",
        "Local transcription is enabled and the pinned Whisper model and runtime are ready.":
            "Lokale Transkription ist aktiviert und das festgelegte Whisper-Modell sowie die Laufzeit sind bereit.",
        "Repair needed":
            "Reparatur erforderlich",
        "The local Whisper model is present but incomplete or damaged. Run setup to fetch it again.":
            "Das lokale Whisper-Modell ist vorhanden, aber unvollständig oder beschädigt. Führen Sie die Einrichtung erneut aus, um es abzurufen.",
        "The local Whisper model or whisper.cpp runtime is incomplete or damaged. Run setup to fetch it again.":
            "Das lokale Whisper-Modell oder die whisper.cpp-Laufzeit ist unvollständig oder beschädigt. Führen Sie die Einrichtung erneut aus, um sie abzurufen.",
        "Run setup to provision the local Whisper model before downloading.":
            "Führen Sie die Einrichtung aus, um das lokale Whisper-Modell vor dem Download bereitzustellen.",
        "Run setup to provision the local Whisper model and whisper.cpp runtime before downloading.":
            "Führen Sie die Einrichtung aus, um das lokale Whisper-Modell und die whisper.cpp-Laufzeit vor dem Download bereitzustellen.",
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
        "Force IP version":
            "IP-Version erzwingen",
        "Use IPv4 or IPv6 for every request. Off uses the system route.":
            "IPv4 oder IPv6 für jede Anfrage verwenden. Aus nutzt die Systemroute.",
        "IPv4":
            "IPv4",
        "IPv6":
            "IPv6",
        "Source address":
            "Quelladresse",
        "Bind requests to a local IPv4 or IPv6 address. Blank uses the system route.":
            "Anfragen an eine lokale IPv4- oder IPv6-Adresse binden. Leer nutzt die Systemroute.",
        "Geo X-Forwarded-For":
            "Geo-X-Forwarded-For",
        "Country code (US) or CIDR block for geo verification. Blank leaves it off.":
            "Ländercode (US) oder CIDR-Block für die Geoprüfung. Leer lässt die Option aus.",
        "Geo verification proxy":
            "Proxy für Geoprüfung",
        "Optional HTTP(S) or SOCKS proxy used only for region checks.":
            "Optionaler HTTP(S)- oder SOCKS-Proxy nur für Regionsprüfungen.",
        "Enter a local IPv4 or IPv6 address, or leave this blank.":
            "Geben Sie eine lokale IPv4- oder IPv6-Adresse ein oder lassen Sie das Feld leer.",
        "Enter a two-letter country code or CIDR block, or leave this blank.":
            "Geben Sie einen zweistelligen Ländercode oder CIDR-Block ein oder lassen Sie das Feld leer.",
        "Enter an http, https, or socks proxy URL, or leave this blank.":
            "Geben Sie eine http-, https- oder socks-Proxy-URL ein oder lassen Sie das Feld leer.",
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
        "Subscriptions are unavailable in this session.":
            "Abonnements sind in dieser Sitzung nicht verfügbar.",
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
        "Output file name":
            "Name der Ausgabedatei",
        "Output file name status":
            "Status des Ausgabedateinamens",
        "Leave empty to use the video title":
            "Leer lassen, um den Videotitel zu verwenden",
        "Name the saved file. The extension is added for you. Applies to a single link.":
            "Benennt die gespeicherte Datei. Die Dateiendung wird automatisch "
            "ergänzt. Gilt für einen einzelnen Link.",
        "A saved file name applies to a single link only.":
            "Ein gespeicherter Dateiname gilt nur für einen einzelnen Link.",
        "Saves as {name}.<ext>":
            "Wird als {name}.<ext> gespeichert",
        "Trimmed to {name}.<ext>":
            "Gekürzt auf {name}.<ext>",
        "Use the proxy Windows is configured with":
            "Den von Windows konfigurierten Proxy verwenden",
        "Use the system proxy":
            "Systemproxy verwenden",
        "Detected system proxy":
            "Erkannter Systemproxy",
        "Reads the proxy from Windows Internet Settings. A proxy typed above always wins.":
            "Liest den Proxy aus den Windows-Internetoptionen. Ein oben "
            "eingetragener Proxy hat immer Vorrang.",
        "A proxy is typed above, so it is used and the system proxy is ignored.":
            "Oben ist ein Proxy eingetragen; dieser wird verwendet und der "
            "Systemproxy ignoriert.",
        "Downloads connect directly.":
            "Downloads verbinden sich direkt.",
        "Windows reports no proxy, so downloads connect directly.":
            "Windows meldet keinen Proxy; Downloads verbinden sich direkt.",
        "Windows reports {proxy}.":
            "Windows meldet {proxy}.",
        "That name cannot be used. Remove any folder separators, drive letters, %, or reserved device names such as CON.":
            "Dieser Name kann nicht verwendet werden. Entfernen Sie "
            "Ordnertrennzeichen, Laufwerksbuchstaben, %, oder reservierte "
            "Gerätenamen wie CON.",
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
        "Put .part, .f### and .ytdl files beside the output and keep them for diagnosis. Off by default: they use a private temporary folder and are removed after the download reaches a terminal state.":
            "Die .part-, .f###- und .ytdl-Dateien neben der Ausgabe ablegen und zur Diagnose behalten. Standardmäßig deaktiviert: Sie werden in einem privaten temporären Ordner verwendet und entfernt, sobald der Download einen Endstatus erreicht.",
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
        "Plugin-based proof-of-origin providers are disabled. Downloads use the verified token-exempt YouTube client chain.":
            "Pluginbasierte Proof-of-Origin-Anbieter sind deaktiviert. Downloads verwenden die verifizierte tokenfreie YouTube-Clientkette.",
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
        "Preparing transcription model...":
            "Transkriptionsmodell wird vorbereitet…",
        "{label} status indicator: {value}":
            "{label} Statusindikator: {value}",
        "{label} status: {value}":
            "{label} Status: {value}",
        "Required":
            "Erforderlich",
        "The local transcription model is missing or damaged.":
            "Das lokale Transkriptionsmodell fehlt oder ist beschädigt.",
        "Run setup with local subtitle generation enabled, then retry the download.":
            "Führen Sie die Einrichtung mit aktivierter lokaler Untertitelerzeugung aus und wiederholen Sie den Download.",
        "Run setup with local subtitle generation enabled, then retry subtitle generation on this completed media.":
            "Führen Sie die Einrichtung mit aktivierter lokaler Untertitelerzeugung aus und wiederholen Sie die Untertitelerzeugung für diese abgeschlossenen Medien.",
        "run-setup":
            "Einrichtung ausführen",
        "run-setup-and-retry-subtitles":
            "Einrichtung ausführen und Untertitel erneut erzeugen",
        "Local subtitle generation failed after the media downloaded.":
            "Die lokale Untertitelerzeugung ist nach dem Mediendownload fehlgeschlagen.",
        "Check the ffmpeg and local transcription model readiness rows, then retry the download.":
            "Prüfen Sie die Bereitschaftszeilen für ffmpeg und das lokale Transkriptionsmodell und wiederholen Sie den Download.",
        "The local transcription runtime is missing or cannot produce SRT output.":
            "Die lokale Transkriptionslaufzeit fehlt oder kann keine SRT-Ausgabe erzeugen.",
        "Local subtitle generation exceeded its time limit.":
            "Die lokale Untertitelerzeugung hat das Zeitlimit überschritten.",
        "Retry subtitle generation on the completed media. If it times out again, use a shorter recording or a faster machine.":
            "Versuchen Sie die Untertitelerzeugung für die abgeschlossenen Medien erneut. Wenn sie erneut das Zeitlimit überschreitet, verwenden Sie eine kürzere Aufnahme oder einen schnelleren Computer.",
        "Check the local transcription readiness rows, then retry subtitles without downloading the media again.":
            "Prüfen Sie die Bereitschaftszeilen für die lokale Transkription und versuchen Sie die Untertitel erneut, ohne die Medien erneut herunterzuladen.",
        "retry-subtitles":
            "Untertitel erneut erzeugen",
        "Retry subtitles":
            "Untertitel erneut erzeugen",
        "Generate subtitles again without downloading the media.":
            "Untertitel erneut erzeugen, ohne die Medien erneut herunterzuladen.",
        "retry":
            "Erneut versuchen",
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
        "YouTube requires a proof-of-origin token for this video, and the plugin-free client chain cannot supply one.":
            "YouTube benötigt für dieses Video ein Proof-of-Origin-Token, das die pluginfreie Clientkette nicht bereitstellen kann.",
        "Retry with a stored site sign-in, or try again later if YouTube makes a token-exempt format available.":
            "Versuchen Sie es mit einer gespeicherten Website-Anmeldung erneut oder später, falls YouTube ein tokenfreies Format bereitstellt.",
        "The YouTube proof-of-origin token path is unavailable for this video.":
            "Der Proof-of-Origin-Tokenpfad von YouTube ist für dieses Video nicht verfügbar.",
        "The plugin-based provider path is disabled. Retry with a stored site sign-in or later.":
            "Der pluginbasierte Anbieterpfad ist deaktiviert. Versuchen Sie es mit einer gespeicherten Website-Anmeldung oder später erneut.",
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
        "The live video did not start within the allowed wait window.":
            "Das Live-Video hat innerhalb des zulässigen Wartefensters nicht begonnen.",
        "Retry when the scheduled event is expected to start, or choose a shorter retry interval for live-event waiting.":
            "Versuchen Sie es erneut, wenn das geplante Ereignis beginnen soll, oder wählen Sie ein kürzeres Wiederholungsintervall für das Warten auf Live-Ereignisse.",
        "retry-live-video":
            "retry-live-video",
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
        "The site says this media is unavailable in your region.":
            "Die Website meldet, dass dieses Medium in Ihrer Region nicht verfügbar ist.",
        "Set `--xff` to a two-letter country code or CIDR block in Settings for geo verification. If that path is still blocked, add a `--geo-verification-proxy` there, then retry.":
            "Setzen Sie `--xff` in den Einstellungen auf einen zweistelligen Ländercode oder CIDR-Block für die Geoprüfung. Wenn dieser Weg weiterhin blockiert ist, fügen Sie dort einen `--geo-verification-proxy` hinzu und versuchen Sie es erneut.",
        "configure-geo-and-retry":
            "configure-geo-and-retry",
        "Set a browser to imitate in Settings — this is the usual remedy for a Cloudflare or TLS-fingerprint block. A stored sign-in for the site also helps. If a dual-stack route is returning the 403, try `--force-ipv4` in Settings.":
            "Stellen Sie in den Einstellungen einen Browser zur Nachahmung ein — dies ist das übliche Mittel gegen eine Cloudflare- oder TLS-Fingerprint-Sperre. Eine gespeicherte Anmeldung für die Website hilft ebenfalls. Wenn eine Dual-Stack-Route den 403 verursacht, versuchen Sie `--force-ipv4` in den Einstellungen.",
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
        "Could not prepare the defaults undo snapshot. Nothing changed; check disk permissions and retry.":
            "Der Rückgängig-Schnappschuss für die Standards konnte nicht vorbereitet werden. Nichts wurde geändert; prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
        "Could not prepare the import undo snapshot. Nothing changed; check disk permissions and retry.":
            "Der Rückgängig-Schnappschuss für den Import konnte nicht vorbereitet werden. Nichts wurde geändert; prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
        "Could not restore the previous settings. The Undo snapshot is still available; check disk permissions and retry.":
            "Die vorherigen Einstellungen konnten nicht wiederhergestellt werden. Der Rückgängig-Schnappschuss ist weiterhin verfügbar; prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
        "No Restore defaults action is available to undo.":
            "Keine Aktion zum Wiederherstellen der Standards verfügbar.",
        "Restore the settings from before Restore defaults was used.":
            "Die Einstellungen vor dem Zurücksetzen auf Standards wiederherstellen.",
        "Restore the sign-in removed by the last action.":
            "Die durch die letzte Aktion entfernte Anmeldung wiederherstellen.",
        "Restore the subscription removed by the last action.":
            "Das durch die letzte Aktion entfernte Abonnement wiederherstellen.",
        "Settings from before Restore defaults were restored.":
            "Die Einstellungen vor dem Zurücksetzen auf Standards wurden wiederhergestellt.",
        "Settings were restored, but the Undo record could not be updated on disk.":
            "Die Einstellungen wurden wiederhergestellt, aber der Rückgängig-Eintrag konnte nicht auf der Festplatte aktualisiert werden.",
        "The Undo record is still available; clear it before closing.":
            "Der Rückgängig-Eintrag ist weiterhin verfügbar; löschen Sie ihn vor dem Schließen.",
        "The import stopped before all subscriptions were added.":
            "Der Import wurde beendet, bevor alle Abonnements hinzugefügt wurden.",
        "The import was only partly applied because its Undo snapshot could not be saved.":
            "Der Import wurde nur teilweise angewendet, weil sein Rückgängig-Schnappschuss nicht gespeichert werden konnte.",
        "Undo defaults":
            "Standards rückgängig",
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


# These entries were added when the extractor began following Qt setters and
# constant picker loops. Keep the German catalogue complete so the advertised
# locale remains a genuinely translated build rather than an English fallback.
CATALOGS["de"].update({
    "yt-dlp freshness": "Aktualität von yt-dlp",
    "FFmpeg security and filters": "FFmpeg-Sicherheit und Filter",
    "Stored sign-in expiry": "Ablauf gespeicherter Anmeldungen",
    "Anonymous GitHub API budget": "Anonymes GitHub-API-Budget",
    "Proof-of-origin token provider": "Proof-of-Origin-Token-Anbieter",
    "refresh-ytdlp": "yt-dlp aktualisieren",
    "provision-runtime": "Laufzeit bereitstellen",
    "refresh-sign-in": "Anmeldung aktualisieren",
    "retry-github": "GitHub erneut versuchen",
    "use-sign-in": "Anmeldung verwenden",
    "Checking": "Wird geprüft",
    "Pre-flight": "Vorabprüfung",
    "Checks known download failure causes before a job starts. Each row names the remedy.":
        "Prüft bekannte Downloadfehler, bevor ein Auftrag startet. Jede Zeile nennt die Lösung.",
    "GitHub's anonymous budget is exhausted; retry after its reset.":
        "Das anonyme GitHub-Budget ist erschöpft; versuchen Sie es nach dem Zurücksetzen erneut.",
    "{action} for {label}": "{action} für {label}",
    "Format": "Format",
    "Quality": "Qualität",
    "Duration": "Dauer",
    "{count} {noun} rejected for {reasons} different reasons. First: {first}":
        "{count} {noun} aus {reasons} verschiedenen Gründen abgelehnt. Zuerst: {first}",
    "{label}: {value}": "{label}: {value}",
    "●  {status}": "●  {status}",
    "link": "Link",
    "links": "Links",
    "{count} {noun} rejected: {reason}":
        "{count} {noun} abgelehnt: {reason}",
    "Downloads {kind} in {languages}{format}, without the video. Change this under Settings, Post-processing.":
        "Lädt {kind} in {languages}{format} ohne Video herunter. Ändern Sie das unter Einstellungen, Nachbearbeitung.",
    "{signed_in} {site} — {count} {stored}.":
        "{signed_in} {site} — {count} {stored}.",
    "{label} could not be read and was set aside as {backup}. Restore puts the original back and reloads it.":
        "{label} konnte nicht gelesen werden und wurde als {backup} beiseitegelegt. Die Wiederherstellung legt das Original zurück und lädt es neu.",
    "Exported {settings} settings and {subscriptions} subscriptions.":
        "{settings} Einstellungen und {subscriptions} Abonnements exportiert.",
    "Imported {count} changed settings":
        "{count} geänderte Einstellungen importiert",
    "Download history cleared. Downloaded files were not removed.":
        "Downloadverlauf gelöscht. Heruntergeladene Dateien wurden nicht entfernt.",
    "Restored {count} download history {entry_label}.":
        "{count} Einträge des Downloadverlaufs wiederhergestellt.",
    "entry": "Eintrag",
    "entries": "Einträge",
    "Link copied.": "Link kopiert.",
    "Error copied.": "Fehler kopiert.",
    "Link ready. Check the options, then choose Download.":
        "Link bereit. Prüfen Sie die Optionen und wählen Sie dann Herunterladen.",
    "yt-dlp {yt}    •    ffmpeg {ffmpeg}":
        "yt-dlp {yt}    •    ffmpeg {ffmpeg}",
    "Show Astra Downloader": "Astra Downloader anzeigen",
    "Open Downloads Folder": "Downloads-Ordner öffnen",
    "Quit Astra Downloader": "Astra Downloader beenden",
    "{app} - {status}": "{app} – {status}",
    "MP3": "MP3",
    "M4A": "M4A",
    "Opus": "Opus",
    "FLAC": "FLAC",
    "WAV": "WAV",
    "MP4": "MP4",
    "MKV": "MKV",
    "WebM": "WebM",
    "Failed": "Fehlgeschlagen",
    "Cancelled": "Abgebrochen",
    "Nothing downloaded": "Nichts heruntergeladen",
    "All subscriptions": "Alle Abonnements",
    "Disabled": "Deaktiviert",
    "Needs attention": "Aufmerksamkeit erforderlich",
    "All sign-ins": "Alle Anmeldungen",
    "Stored and valid": "Gespeichert und gültig",
    "Expired": "Abgelaufen",
    "Missing on disk": "Auf Datenträger nicht vorhanden",
    "Creator, else auto-generated": "Vom Ersteller, sonst automatisch erzeugt",
    "Creator only": "Nur vom Ersteller",
    "Auto-generated only": "Nur automatisch erzeugt",
    "Same as source": "Wie Quelle",
    "SRT": "SRT",
    "WebVTT": "WebVTT",
    "ASS": "ASS",
    "LRC": "LRC",
    "creator subtitles, falling back to auto-generated":
        "Untertitel vom Ersteller, sonst automatisch erzeugte",
    "as {format}": "als {format}",
    "Confirm your download folder before adding a download.":
        "Bestätigen Sie den Downloadordner, bevor Sie einen Download hinzufügen.",
    "Paste a video link first.": "Fügen Sie zuerst einen Videolink ein.",
    "Save this download to": "Diesen Download speichern unter",
    "Search title or filename": "Titel oder Dateiname suchen",
    "{total} configured · {archived} archived · {queued} queued":
        "{total} konfiguriert · {archived} archiviert · {queued} eingereiht",
    "{signed_in} {site} — {stored}": "{signed_in} {site} — {stored}",
    "Select the exported cookies.txt": "Exportierte cookies.txt auswählen",
    "Added {title}. The first scan is scheduled now.":
        "{title} hinzugefügt. Der erste Scan ist jetzt geplant.",
    "Same as video folder": "Wie Videoordner",
    "Deno": "Deno",
    "Node 22+": "Node 22+",
    "QuickJS": "QuickJS",
    "Your server token was regenerated, so the browser extension needs pairing again.":
        "Ihr Servertoken wurde neu erzeugt. Die Browsererweiterung muss erneut gekoppelt werden.",
    "{total} / {limit} jobs": "{total} / {limit} Aufträge",
    "Export Settings": "Einstellungen exportieren",
    "Import Settings": "Einstellungen importieren",
    "No filtered history rows are available to export.":
        "Keine gefilterten Verlaufseinträge zum Exportieren vorhanden.",
    "Export Download History": "Downloadverlauf exportieren",
    "Exported {count} filtered history row(s) to {path}":
        "{count} gefilterte Verlaufseinträge nach {path} exportiert",
    "Download history is already clear.": "Der Downloadverlauf ist bereits leer.",
    "Could not prepare the history undo snapshot. The existing history was preserved; check disk permissions and retry.":
        "Der Rückgängig-Schnappschuss für den Verlauf konnte nicht vorbereitet werden. Der vorhandene Verlauf blieb erhalten. Prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
    "Could not clear download history. The existing history was preserved; check disk permissions and retry.":
        "Der Downloadverlauf konnte nicht gelöscht werden. Der vorhandene Verlauf blieb erhalten. Prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
    "No cleared history entries to restore.":
        "Keine gelöschten Verlaufseinträge zum Wiederherstellen vorhanden.",
    "Could not restore download history. The Undo snapshot is still available; check disk permissions and retry.":
        "Der Downloadverlauf konnte nicht wiederhergestellt werden. Der Rückgängig-Schnappschuss ist noch verfügbar. Prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
    "Retry queued: {title}": "Erneuter Versuch eingereiht: {title}",
    "Download resumed.": "Download fortgesetzt.",
    "Checking…": "Wird geprüft …",
    "Check yt-dlp Update": "yt-dlp-Update prüfen",
    "Select Folder": "Ordner auswählen",
    "Copied video link staged. Review the options, then choose Add to queue.":
        "Kopierter Videolink vorgemerkt. Prüfen Sie die Optionen und wählen Sie Zur Warteschlange hinzufügen.",
    "Endpoint copied.": "Endpunkt kopiert.",
    "Review Diagnostics": "Diagnose prüfen",
    "Save diagnostics": "Diagnose speichern",
    "Copy to Clipboard": "In Zwischenablage kopieren",
    "{name} {page}": "{name} {page}",
    "{open_label} {name}": "{open_label} {name}",
    "Clip ranges apply to a single link. Remove the extra links or clear the clip range.":
        "Clipbereiche gelten für einen einzelnen Link. Entfernen Sie die zusätzlichen Links oder löschen Sie den Clipbereich.",
    "Queued {id}{suffix}.": "{id}{suffix} eingereiht.",
    "Queued {count} downloads.": "{count} Downloads eingereiht.",
    "{label}: {path}": "{label}: {path}",
    "{label} {title}": "{label} {title}",
    "Every {minutes} min · next scan {next_scan}":
        "Alle {minutes} Min. · nächster Scan {next_scan}",
    "{browser} — {warning}": "{browser} — {warning}",
    "{count} {discarded}": "{count} {discarded}",
    "That cookie file is too large to be a browser export.":
        "Diese Cookie-Datei ist zu groß für einen Browserexport.",
    "{label}: {error}": "{label}: {error}",
    "Start the local companion before adding a subscription.":
        "Starten Sie den lokalen Begleiter, bevor Sie ein Abonnement hinzufügen.",
    "{label}: {language}": "{label}: {language}",
    "{label} could not be restored. Its backup is at {backup}.":
        "{label} konnte nicht wiederhergestellt werden. Die Sicherung befindet sich unter {backup}.",
    "Destination confirmed: {folder}. Setup can continue in the background.":
        "Ziel bestätigt: {folder}. Die Einrichtung kann im Hintergrund fortgesetzt werden.",
    "Confirm a folder before your first download.":
        "Bestätigen Sie vor dem ersten Download einen Ordner.",
    "The download folder validator is unavailable. Check the log and retry.":
        "Die Prüfung des Downloadordners ist nicht verfügbar. Prüfen Sie das Protokoll und versuchen Sie es erneut.",
    "Could not save the download folder. Check disk permissions and retry.":
        "Der Downloadordner konnte nicht gespeichert werden. Prüfen Sie die Berechtigungen und versuchen Sie es erneut.",
    "Next: {action}": "Nächster Schritt: {action}",
    "ETA {eta}": "Restzeit {eta}",
    "Preparing download": "Download wird vorbereitet",
    "{count} stored sign-ins are listed by site only — add them again after importing.":
        "{count} gespeicherte Anmeldungen sind nur nach Website aufgeführt — fügen Sie sie nach dem Import erneut hinzu.",
    "{added} subscriptions added, {skipped} already present":
        "{added} Abonnements hinzugefügt, {skipped} bereits vorhanden",
    "sign-ins still needed for {sites}": "Anmeldungen weiterhin erforderlich für {sites}",
    "not carried: {settings}": "nicht übernommen: {settings}",
    "{start}–{end} of {filtered} filtered · {total} retained":
        "{start}–{end} von {filtered} gefiltert · {total} behalten",
    "0 of {filtered} filtered · {total} retained":
        "0 von {filtered} gefiltert · {total} behalten",
    "{start}–{end} of {filtered} filtered · {total} retained · limit {limit}":
        "{start}–{end} von {filtered} gefiltert · {total} behalten · Limit {limit}",
    "0 of {filtered} filtered · {total} retained · limit {limit}":
        "0 von {filtered} gefiltert · {total} behalten · Limit {limit}",
    "History retention": "Verlaufsaufbewahrung",
    "Maximum number of download records to keep locally. Files are never deleted.":
        "Maximale Anzahl lokaler Downloadaufzeichnungen. Dateien werden nie gelöscht.",
    " entries": " Einträge",
    "Subscription archive": "Abonnementarchiv",
    "yt-dlp {version} is ready.": "yt-dlp {version} ist bereit.",
    "{quality}p": "{quality}p",
    "Video link staged. Open Downloads to review it before adding it to the queue.":
        "Videolink vorgemerkt. Öffnen Sie Downloads, um ihn vor dem Einreihen zu prüfen.",
    "ffmpeg refresh complete.": "ffmpeg-Aktualisierung abgeschlossen.",
    "Setup complete.": "Einrichtung abgeschlossen.",
    "ffmpeg refresh failed. The previous copy is still installed.":
        "Die ffmpeg-Aktualisierung ist fehlgeschlagen. Die vorherige Version ist weiterhin installiert.",
    "Setup failed. Check the log for details.":
        "Die Einrichtung ist fehlgeschlagen. Details finden Sie im Protokoll.",
    "mp3": "mp3",
    "m4a": "m4a",
    "opus": "opus",
    "flac": "flac",
    "wav": "wav",
    "mp4": "mp4",
    "mkv": "mkv",
    "webm": "webm",
    "—": "—",
    "{target} (unavailable)": "{target} (nicht verfügbar)",
    "creator subtitles only": "nur Untertitel vom Ersteller",
    "auto-generated subtitles only": "nur automatisch erzeugte Untertitel",
    "Saving to {path}.": "Speichern unter {path}.",
    "Could not read stored sign-ins: {error}":
        "Gespeicherte Anmeldungen konnten nicht gelesen werden: {error}",
    "{count} {auth} · {from_label} {source} · {state}":
        "{count} {auth} · {from_label} {source} · {state}",
    "Could not read that file: {error}": "Datei konnte nicht gelesen werden: {error}",
    "{removed} {site}.": "{removed} {site}.",
    "Download complete": "Download abgeschlossen",
    "Could not write the bundle: {error}":
        "Das Paket konnte nicht geschrieben werden: {error}",
    "Could not read that bundle: {error}":
        "Das Paket konnte nicht gelesen werden: {error}",
    "Could not export download history: {error}":
        "Downloadverlauf konnte nicht exportiert werden: {error}",
    "Still running in the tray so Astra Deck can keep sending downloads.":
        "Läuft weiterhin im Infobereich, damit Astra Deck Downloads senden kann.",
    "{label} {date}": "{label} {date}",
    "for an accurate ffmpeg clip": "für einen präzisen ffmpeg-Clip",
    "for a yt-dlp clip": "für einen yt-dlp-Clip",
    "Pause between subtitle requests": "Pause zwischen Untertitelanfragen",
    "Seconds between subtitle-track requests. Helps avoid subtitle rate limits; 0 disables it.":
        "Sekunden zwischen Anfragen für Untertitelspuren. Hilft, Ratenbegrenzungen für Untertitel zu vermeiden; 0 deaktiviert die Pause.",
    # Playlist staging, pipeline steps, command inspector and the Deno
    # security floor (2026-08-14).
    "{count} videos": "{count} Videos",
    "Copy command": "Befehl kopieren",
    "Close": "Schließen",
    "Review Playlist": "Playlist überprüfen",
    "(untitled playlist)": "(unbenannte Playlist)",
    "Select all": "Alle auswählen",
    "Deselect all": "Alle abwählen",
    "Invert": "Umkehren",
    "Download selected": "Auswahl herunterladen",
    "{selected} of {total} selected": "{selected} von {total} ausgewählt",
    "Download selected ({count})": "Auswahl herunterladen ({count})",
    "yt-dlp Command": "yt-dlp-Befehl",
    "Scanning playlist items...": "Playlist-Einträge werden gelesen...",
    "(untitled)": "(ohne Titel)",
    "View yt-dlp command": "yt-dlp-Befehl anzeigen",
    "Command for {title}": "Befehl für {title}",
    "This is the exact command line executed for this job with credentials, tokens, and cookie paths redacted.":
        "Dies ist die exakte Befehlszeile dieses Auftrags; Zugangsdaten, Token und Cookie-Pfade sind geschwärzt.",
    "No command recorded.": "Kein Befehl aufgezeichnet.",
    "Paste a playlist link first.": "Zuerst einen Playlist-Link einfügen.",
    "Enter a playlist URL to review.": "Zum Überprüfen eine Playlist-URL eingeben.",
    "Security floor": "Sicherheitsuntergrenze",
    "Fetching metadata": "Metadaten werden abgerufen",
    "Could not preview playlist.": "Playlist-Vorschau nicht möglich.",
    "No playlist items selected.": "Keine Playlist-Einträge ausgewählt.",
    "Queued {count} items from playlist.": "{count} Einträge aus der Playlist eingereiht.",
    "Runtime floor": "Laufzeituntergrenze",
    "Embedding metadata": "Metadaten werden eingebettet",
    "{runtime} {version} is below the security floor {floor}; update it before downloading.":
        "{runtime} {version} liegt unter der Sicherheitsuntergrenze {floor}; vor dem Herunterladen aktualisieren.",
    "Generating subtitles": "Untertitel werden erzeugt",
    "required": "erforderlich",
    "{runtime} {version} is below the runtime floor {floor}; update it before downloading.":
        "{runtime} {version} liegt unter der Laufzeituntergrenze {floor}; vor dem Herunterladen aktualisieren.",
    "Review playlist": "Playlist überprüfen",
    "Preview and select videos in this playlist before downloading.":
        "Videos dieser Playlist vor dem Herunterladen ansehen und auswählen.",
    "The configured Deno runtime is below Astra Downloader's security floor.":
        "Die konfigurierte Deno-Laufzeit liegt unter der Sicherheitsuntergrenze von Astra Downloader.",
    "Update Deno to the security floor shown in the readiness panel, then retry.":
        "Deno auf die im Bereitschaftsbereich angezeigte Sicherheitsuntergrenze aktualisieren und erneut versuchen.",
})


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
