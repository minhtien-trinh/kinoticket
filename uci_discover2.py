#!/usr/bin/env python3
"""
UCI Discovery v2: klickt zuerst das OneTrust-Consent-Banner weg,
loggt danach ALLE Requests (nicht nur JSON) und dumpt das gerenderte HTML.

    pip install playwright
    playwright install chromium

    python uci_discover2.py            # headless
    python uci_discover2.py --show     # sichtbarer Browser, zum Mitschauen
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

CINEMA_URL = "https://www.uci-kinowelt.de/home/berlin-east-side-gallery"
FILM = "Odyssee"
OUT = Path("uci_dump")

STATIC = re.compile(r"\.(png|jpe?g|webp|svg|gif|woff2?|ttf|css|ico|mp4)(\?|$)", re.I)
NOISE = re.compile(r"onetrust|cookielaw|googletagmanager|google-analytics|doubleclick|facebook", re.I)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="Browser sichtbar starten")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    calls: list[tuple[int, str, str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.show)
        ctx = browser.new_context(locale="de-DE", timezone_id="Europe/Berlin")
        page = ctx.new_page()

        def on_response(resp):
            url = resp.url
            if STATIC.search(url) or NOISE.search(url):
                return
            ct = resp.headers.get("content-type", "").split(";")[0]
            try:
                size = len(resp.body())
            except Exception:
                size = -1
            calls.append((size, resp.request.method, ct, url))

            if "json" in ct and size > 200:
                try:
                    body = resp.text()
                except Exception:
                    return
                if FILM.lower() in body.lower():
                    print(f"\n>>> TREFFER {url}")
                    fn = OUT / f"hit_{abs(hash(url))}.json"
                    fn.write_text(body, encoding="utf-8")
                    print(f"    gespeichert: {fn}")

        page.on("response", on_response)
        page.goto(CINEMA_URL, wait_until="domcontentloaded", timeout=60_000)

        # 1. Consent-Banner akzeptieren, sonst bootet die App nicht weiter
        for sel in ("#onetrust-accept-btn-handler",
                    "button:has-text('Alle akzeptieren')",
                    "button:has-text('Akzeptieren')"):
            try:
                page.click(sel, timeout=5000)
                print(f"Consent geklickt: {sel}")
                break
            except Exception:
                continue
        else:
            print("Kein Consent-Banner gefunden (evtl. schon weg).")

        # 2. Lazy Loading triggern
        page.wait_for_timeout(3000)
        for _ in range(6):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(800)
        page.wait_for_timeout(4000)

        html = page.content()
        (OUT / "page.html").write_text(html, encoding="utf-8")
        browser.close()

    print("\n--- Requests (ohne Assets/Tracking) ---")
    for size, method, ct, url in sorted(calls, key=lambda t: -t[0])[:40]:
        print(f"{size:>8} B  {method:<5} {ct:<28} {url[:110]}")

    print(f"\nHTML gedumpt: {OUT / 'page.html'} ({len(html)} Zeichen)")
    print(f"Titel '{FILM}' im HTML enthalten: {FILM.lower() in html.lower()}")

    for marker in ("__NEXT_DATA__", "__INITIAL_STATE__", "__NUXT__", "application/ld+json"):
        if marker in html:
            print(f"State-Blob gefunden: {marker}")


if __name__ == "__main__":
    main()
