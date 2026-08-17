#!/usr/bin/env python3
"""
UCI Showtime Watcher, final.

Ueberwacht Vorstellungen eines Films im UCI Berlin East Side Gallery und
meldet neue Termine per E-Mail (SMTP) und optional per ntfy.sh Push.

Setup:
    pip install playwright beautifulsoup4 requests
    playwright install chromium

Termine ansehen, ohne etwas zu speichern oder zu melden:
    python uci_watcher_final.py --dump --baseline

Normaler Lauf, meldet nur neue IMAX-OV/OmU-Termine:
    python uci_watcher_final.py

Umgebungsvariablen:
    STATE_PATH   Pfad zur seen.json (Standard: ~/.cache/uci_watcher/seen.json)
    SMTP_USER    Gmail-Adresse, von der gesendet wird
    SMTP_PASS    Google App-Passwort, NICHT das normale Passwort
    MAIL_TO      Empfaengeradresse
    NTFY_TOPIC   optional, zusaetzlicher Push
    FILM_ID      UCI-Film-ID (Standard: 407923, Die Odyssee)
    FILTER_MODE  imax-ov | ov | alle
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://www.uci-kinowelt.de"
CINEMA_URL = f"{BASE}/home/berlin-east-side-gallery"
FILM_ID = os.environ.get("FILM_ID", "407923")      # Die Odyssee
FILM_TITLE = os.environ.get("FILM_TITLE", "Die Odyssee")

STATE_FILE = Path(
    os.environ.get("STATE_PATH", Path.home() / ".cache" / "uci_watcher" / "seen.json")
)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
POLL_INTERVAL = 30 * 60

# SMTP, fuer den Mailversand aus GitHub Actions heraus
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
MAIL_TO = os.environ.get("MAIL_TO")

VERSION_LABELS = {
    "2d": "2D", "3d": "3D", "ov": "OV", "omu": "OmU",
    "isens": "iSense", "imax": "IMAX", "4dx": "4DX", "dbox": "D-BOX",
}


def matches_filter(s: "Showtime", modus: str) -> bool:
    """OV und OmU sind beide englischer Originalton, OmU nur mit dt. Untertiteln."""
    englisch = "OV" in s.version or "OmU" in s.version
    if modus == "imax-ov":
        return englisch and "IMAX" in s.version
    if modus == "ov":
        return englisch
    return True


@dataclass(frozen=True)
class Showtime:
    performance_id: str
    datum: str        # ISO, YYYY-MM-DD
    uhrzeit: str
    version: str
    url: str

    @property
    def wochentag(self) -> str:
        tage = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        return tage[datetime.strptime(self.datum, "%Y-%m-%d").weekday()]

    def __str__(self) -> str:
        d = datetime.strptime(self.datum, "%Y-%m-%d").strftime("%d.%m.")
        return f"{self.wochentag} {d} {self.uhrzeit}  {self.version}"


def parse_badges(html: str) -> list[Showtime]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Showtime] = []

    for a in soup.select("a.badge-performance"):
        href = a.get("href", "")
        datum = a.get("data-date", "")
        zeit = a.get("data-time", "")
        if not (href and datum and zeit):
            continue

        pid = href.rstrip("/").split("/")[-1]
        flags = [f for f in a.get("data-version", "").split("|") if f]
        version = " ".join(VERSION_LABELS.get(f, f) for f in flags if f in VERSION_LABELS)

        out.append(
            Showtime(
                performance_id=pid,
                datum=f"{datum[0:4]}-{datum[4:6]}-{datum[6:8]}",
                uhrzeit=zeit,
                version=version or "-",
                url=href if href.startswith("http") else BASE + href,
            )
        )
    return out


def fetch(dump: bool = False) -> list[Showtime]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="de-DE", timezone_id="Europe/Berlin")
        page = ctx.new_page()

        page.goto(CINEMA_URL, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.click("#onetrust-accept-btn-handler", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2500)

        # Von der Film-Card zur Detailseite, dort gehoeren alle Badges dem Film
        detail = page.evaluate(
            """(fid) => {
                const slide = document.querySelector(`[data-slide-filmid="${fid}"]`);
                const a = slide?.querySelector('a[href]');
                return a ? a.href : null;
            }""",
            FILM_ID,
        )

        if detail:
            page.goto(detail, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2500)
            for _ in range(4):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(600)
            html = page.content()
            quelle = detail
        else:
            print("Keine Detailseite gefunden, nutze Startseite.", file=sys.stderr)
            html = page.content()
            quelle = CINEMA_URL

        browser.close()

    if dump:
        Path("uci_detail.html").write_text(html, encoding="utf-8")
        print(f"Quelle: {quelle}\nHTML gedumpt: uci_detail.html")

    return parse_badges(html)


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def send_mail(neue: list[Showtime], betreff: str) -> None:
    if not (SMTP_USER and SMTP_PASS and MAIL_TO):
        print("SMTP nicht konfiguriert, keine Mail verschickt.", file=sys.stderr)
        return

    zeilen = [
        f"{s}\n    Tickets: {s.url}"
        for s in sorted(neue, key=lambda s: (s.datum, s.uhrzeit))
    ]
    body = (
        f"Neue Vorstellungen fuer {FILM_TITLE} im UCI Berlin East Side Gallery:\n\n"
        + "\n\n".join(zeilen)
        + "\n\n--\nAutomatisch erzeugt vom UCI Showtime Watcher."
    )

    msg = EmailMessage()
    msg["Subject"] = betreff
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg.set_content(body)

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as srv:
                srv.login(SMTP_USER, SMTP_PASS)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as srv:
                srv.starttls()
                srv.login(SMTP_USER, SMTP_PASS)
                srv.send_message(msg)
        print(f"Mail an {MAIL_TO} verschickt.", flush=True)
    except Exception as exc:
        # Nicht abbrechen: der State soll trotzdem geschrieben werden? Nein,
        # lieber lautstark scheitern, damit der naechste Lauf es erneut meldet.
        raise RuntimeError(f"Mailversand fehlgeschlagen: {exc}") from exc


def notify(neue: list[Showtime]) -> None:
    text = "\n".join(str(s) for s in sorted(neue, key=lambda s: (s.datum, s.uhrzeit)))
    print(f"[NEU] {FILM_TITLE}, {len(neue)} Vorstellung(en)\n{text}", flush=True)

    betreff = f"{len(neue)} neue Vorstellung(en): {FILM_TITLE}"
    send_mail(neue, betreff)

    if not NTFY_TOPIC:
        return
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=text.encode("utf-8"),
        headers={
            "Title": f"Neue Vorstellungen: {FILM_TITLE}".encode("utf-8"),
            "Tags": "clapper",
            "Click": neue[0].url,
            "Priority": "high",
        },
        timeout=10,
    )


def check_once(modus: str = "alle", dump: bool = False, baseline: bool = False) -> None:
    try:
        alle = fetch(dump=dump)
    except Exception as exc:
        print(f"Abruf fehlgeschlagen: {exc}", file=sys.stderr)
        sys.exit(1)

    if not alle:
        # Leeres Ergebnis heisst fast immer kaputter Scrape, nicht "Film ausgelaufen".
        # Kein State-Update, sonst gilt spaeter alles als neu.
        print("Keine Vorstellungen gefunden, Seitenstruktur pruefen.", file=sys.stderr)
        sys.exit(1)

    aktuell = [s for s in alle if matches_filter(s, modus)]
    print(f"{len(alle)} Vorstellungen gesamt, {len(aktuell)} nach Filter '{modus}'.", flush=True)

    if dump:
        print(f"\n{len(alle)} Vorstellungen (* = trifft Filter '{modus}'):")
        for s in sorted(alle, key=lambda s: (s.datum, s.uhrzeit)):
            mark = "*" if matches_filter(s, modus) else " "
            print(f" {mark} {s}  {s.performance_id}")

    state = load_state()
    neue = [s for s in aktuell if s.performance_id not in state]

    if baseline:
        # Alles als gesehen markieren, ohne zu benachrichtigen.
        state.update({s.performance_id: asdict(s) for s in aktuell})
        save_state(state)
        print(f"Baseline gesetzt: {len(state)} Vorstellungen als gesehen markiert.")
        return

    if neue:
        # Erst melden, dann speichern. Schlaegt die Mail fehl, bleibt der State
        # unveraendert und der naechste Lauf versucht es erneut.
        notify(neue)
        state.update({s.performance_id: asdict(s) for s in neue})
        save_state(state)
    else:
        print(f"Keine Aenderung ({len(aktuell)} bekannte Vorstellungen).", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="HTML sichern und alle Termine listen")
    ap.add_argument(
        "--filter",
        choices=["imax-ov", "ov", "alle"],
        default=os.environ.get("FILTER_MODE", "imax-ov"),
        help="welche Vorstellungen melden (Standard: imax-ov)",
    )
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="aktuelle Termine als gesehen markieren, ohne zu benachrichtigen",
    )
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=POLL_INTERVAL)
    args = ap.parse_args()

    if not args.loop:
        check_once(args.filter, args.dump, args.baseline)
        return

    while True:
        check_once(args.filter, args.dump, args.baseline)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
