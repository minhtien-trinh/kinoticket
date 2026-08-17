#!/usr/bin/env python3
"""
UCI Showtime Watcher: ueberwacht Vorstellungen eines Films im UCI Berlin East Side Gallery.

Warum Playwright statt requests: uci-kinowelt.de setzt Bot-Detection ein,
plain requests bekommt 403. Ein echter Browser-Context kommt durch.

Setup:
    pip install playwright
    playwright install chromium

Schritt 1 (einmalig): JSON-Endpoint finden
    python uci_watcher.py --discover

Schritt 2: ueberwachen
    python uci_watcher.py                 # einmaliger Check, fuer cron
    python uci_watcher.py --loop
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

CINEMA_URL = "https://www.uci-kinowelt.de/home/berlin-east-side-gallery"
FILM = os.environ.get("FILM_TITLE", "Die Odyssee")
STATE_FILE = Path.home() / ".cache" / "uci_watcher" / "seen.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
POLL_INTERVAL = 30 * 60


@dataclass(frozen=True)
class Showtime:
    film: str
    datum: str
    uhrzeit: str
    saal: str = ""
    format: str = ""
    link: str = ""

    @property
    def key(self) -> str:
        raw = f"{self.film}|{self.datum}|{self.uhrzeit}|{self.saal}|{self.format}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def __str__(self) -> str:
        return " ".join(x for x in (self.datum, self.uhrzeit, self.format, self.saal) if x)


# ---------------------------------------------------------------------------
# Discovery: zeigt alle JSON-Responses, die die Seite laedt
# ---------------------------------------------------------------------------
def discover() -> None:
    treffer: list[tuple[str, int]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="de-DE")

        def on_response(resp):
            ct = resp.headers.get("content-type", "")
            if "json" not in ct or resp.status != 200:
                return
            try:
                body = resp.text()
            except Exception:
                return
            treffer.append((resp.url, len(body)))
            # Heuristik: Endpoints, die den Filmtitel enthalten, sind die richtigen
            if FILM.lower() in body.lower():
                print(f"\n>>> TREFFER: {resp.url}")
                print(body[:1500])

        page.on("response", on_response)
        page.goto(CINEMA_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)
        browser.close()

    print("\n--- Alle JSON-Responses ---")
    for url, size in sorted(treffer, key=lambda t: -t[1]):
        print(f"{size:>8} B  {url}")


# ---------------------------------------------------------------------------
# Extraktion: liest die Vorstellungen aus der gerenderten Seite
# Fallback, falls du keinen sauberen JSON-Endpoint findest.
# ---------------------------------------------------------------------------
JS_EXTRACT = """
() => {
  const out = [];
  // Selektoren nach --discover bzw. DevTools-Inspektion anpassen
  document.querySelectorAll('[data-testid="movie-card"], .movie-row').forEach(card => {
    const titel = card.querySelector('h2, h3, .movie-title')?.innerText?.trim() || '';
    card.querySelectorAll('a[href*="/vorstellung"], button[data-time], .performance').forEach(s => {
      out.push({
        film: titel,
        datum: s.getAttribute('data-date') || '',
        uhrzeit: (s.getAttribute('data-time') || s.innerText || '').trim(),
        saal: s.getAttribute('data-auditorium') || '',
        format: s.getAttribute('data-format') || '',
        link: s.getAttribute('href') || ''
      });
    });
  });
  return out;
}
"""


def fetch_showtimes() -> list[Showtime]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="de-DE", timezone_id="Europe/Berlin")
        page.goto(CINEMA_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)
        raw = page.evaluate(JS_EXTRACT)
        browser.close()

    alle = [Showtime(**item) for item in raw if item.get("film")]
    return [s for s in alle if FILM.lower() in s.film.lower()]


# ---------------------------------------------------------------------------


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def notify(neue: list[Showtime]) -> None:
    text = "\n".join(str(s) for s in neue)
    print(f"[NEU] {FILM}, {len(neue)} Vorstellung(en)\n{text}", flush=True)

    if NTFY_TOPIC:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=text.encode("utf-8"),
            headers={
                "Title": f"Neue Vorstellungen: {FILM}".encode("utf-8"),
                "Tags": "clapper",
                "Click": CINEMA_URL,
                "Priority": "high",
            },
            timeout=10,
        )


def check_once() -> None:
    try:
        aktuell = fetch_showtimes()
    except Exception as exc:
        print(f"Abruf fehlgeschlagen: {exc}", file=sys.stderr)
        return

    if not aktuell:
        print(f"Nichts geparst. Selektoren pruefen oder {FILM} laeuft dort nicht.", file=sys.stderr)
        return

    state = load_state()
    neue = [s for s in aktuell if s.key not in state]

    if neue:
        notify(neue)
        state.update({s.key: asdict(s) for s in neue})
        save_state(state)
    else:
        print(f"Keine Aenderung ({len(aktuell)} bekannte Vorstellungen).", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="JSON-Endpoints auflisten")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=POLL_INTERVAL)
    args = ap.parse_args()

    if args.discover:
        discover()
        return

    if not args.loop:
        check_once()
        return

    while True:
        check_once()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
