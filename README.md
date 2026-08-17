# UCI Showtime Watcher

Überwacht **Die Odyssee** im UCI Berlin East Side Gallery und schickt eine
E-Mail, sobald neue **IMAX OV/OmU**-Vorstellungen erscheinen. Läuft stündlich
als GitHub Action, kein eigener Rechner nötig.

## Setup

### 1. Repo anlegen und pushen

```bash
git init
git add .
git commit -m "UCI Showtime Watcher"
git branch -M main
git remote add origin https://github.com/<DEIN-USER>/kinoticket.git
git push -u origin main
```

Repo **public** anlegen: private Repos haben nur 2000 Actions-Freiminuten pro
Monat, stündlich wäre das knapp. Öffentlich ist unbegrenzt, und `state/seen.json`
enthält nur Kino-Termine.

### 2. Gmail App-Passwort erzeugen

Das normale Google-Passwort funktioniert für SMTP nicht.

1. 2-Faktor-Authentifizierung aktivieren: <https://myaccount.google.com/security>
2. App-Passwort erzeugen: <https://myaccount.google.com/apppasswords>
3. Name z. B. `uci-watcher`, das 16-stellige Passwort kopieren.

### 3. Secrets hinterlegen

Repo → **Settings** → **Secrets and variables** → **Actions** → *New repository secret*:

| Name        | Wert                                     |
|-------------|------------------------------------------|
| `SMTP_USER` | deine Gmail-Adresse (Absender)           |
| `SMTP_PASS` | das App-Passwort aus Schritt 2           |
| `MAIL_TO`   | `trinhmt3@gmail.com`                     |

### 4. Testen

Repo → **Actions** → *UCI Showtime Watcher* → **Run workflow**.

Der Lauf sollte grün sein und `Keine Aenderung` melden, weil `state/seen.json`
bereits die aktuellen 72 Vorstellungen als Baseline enthält.

Um den Mailversand zu testen, lokal eine bekannte IMAX-OV-Vorstellung aus
`state/seen.json` löschen, committen und den Workflow erneut starten. Dann muss
eine Mail ankommen.

## Lokal ausführen

```bash
pip install -r requirements.txt
playwright install chromium

# Alle Termine ansehen, * markiert Treffer
STATE_PATH=$PWD/state/seen.json python uci_watcher_final.py --dump --baseline

# Normaler Lauf
STATE_PATH=$PWD/state/seen.json python uci_watcher_final.py
```

## Konfiguration

Alles über Umgebungsvariablen, im Workflow unter `env:` gesetzt:

| Variable      | Standard                           | Bedeutung                          |
|---------------|------------------------------------|------------------------------------|
| `FILTER_MODE` | `imax-ov`                          | `imax-ov`, `ov` oder `alle`        |
| `FILM_ID`     | `407923`                           | UCI-Film-ID                        |
| `FILM_TITLE`  | `Die Odyssee`                      | nur für Betreff und Ausgabe        |
| `STATE_PATH`  | `~/.cache/uci_watcher/seen.json`   | wo die gesehenen Termine liegen    |
| `NTFY_TOPIC`  | –                                  | optionaler Push zusätzlich zur Mail|

`imax-ov` trifft sowohl `IMAX OV` als auch `IMAX OmU`, beide sind englischer
Originalton, OmU zusätzlich mit deutschen Untertiteln.

## Wie es funktioniert

`state/seen.json` merkt sich jede bereits gemeldete `performance_id`. Nach
jedem Lauf committet die Action die Datei zurück ins Repo, dadurch überlebt der
Zustand den Container. Gemeldet wird nur, was noch nicht in der Datei steht.

Findet der Scraper **null** Vorstellungen, bricht der Lauf mit Fehler ab und
schreibt den State *nicht* fort. Sonst würde eine kaputte Seitenstruktur den
Speicher leeren und beim nächsten Lauf alles als neu gelten.

## Grenzen

- **Cron ist unpünktlich.** GitHub verzögert geplante Läufe je nach Last um 5
  bis 20 Minuten, gelegentlich fällt einer aus. Für ein wöchentlich
  veröffentlichtes Programm irrelevant, für Minuten-genaues Ticketing nicht.
- **60-Tage-Regel.** Ohne Repo-Aktivität deaktiviert GitHub geplante Workflows.
  `keepalive.yml` committet deshalb monatlich einen Zeitstempel.
- **Der Scraper hängt am HTML.** Baut UCI die Seite um, greift der Selektor
  `a.badge-performance` ins Leere. Der Lauf schlägt dann fehl statt still zu
  schweigen, du siehst es also in der Actions-Übersicht.
