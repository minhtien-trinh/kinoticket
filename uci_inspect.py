#!/usr/bin/env python3
"""
Analysiert uci_dump/page.html und leitet die Selektoren fuer die
Vorstellungszeiten her.

    pip install beautifulsoup4
    python uci_inspect.py
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

DUMP = Path("uci_dump/page.html")
FILM = "Odyssee"
TIME_RE = re.compile(r"^\s*\d{1,2}[:.]\d{2}\s*$")


def desc(el) -> str:
    """Tag + Klassen + relevante Attribute in Kurzform."""
    cls = ".".join(el.get("class", []))
    attrs = {k: v for k, v in el.attrs.items()
             if k.startswith("data-") or k in ("href", "id", "itemprop", "datetime")}
    attr_s = " ".join(f'{k}="{str(v)[:45]}"' for k, v in list(attrs.items())[:5])
    return f"<{el.name}{'.' + cls if cls else ''}> {attr_s}".strip()


def main() -> None:
    if not DUMP.exists():
        raise SystemExit(f"{DUMP} fehlt. Erst uci_discover2.py laufen lassen.")

    soup = BeautifulSoup(DUMP.read_text(encoding="utf-8"), "html.parser")

    # 1. Wo taucht der Film auf?
    print("=" * 70)
    print(f"1. Fundstellen '{FILM}'")
    print("=" * 70)
    treffer = [el for el in soup.find_all(string=re.compile(FILM, re.I))
               if el.parent.name not in ("script", "style", "title")]
    print(f"{len(treffer)} Textknoten gefunden\n")

    for i, node in enumerate(treffer[:4]):
        print(f"--- Fundstelle {i + 1}: {node.strip()[:70]!r}")
        el = node.parent
        for lvl in range(6):
            print(f"    {'  ' * lvl}^ {desc(el)}")
            if el.parent is None or el.parent.name == "body":
                break
            el = el.parent
        print()

    # 2. Wie sehen Uhrzeit-Elemente aus?
    print("=" * 70)
    print("2. Elemente, deren Text nur eine Uhrzeit ist")
    print("=" * 70)
    zeiten = [el for el in soup.find_all(["a", "span", "div", "button", "li", "time"])
              if el.string and TIME_RE.match(el.string)]
    print(f"{len(zeiten)} Kandidaten\n")

    muster = Counter(desc(el) for el in zeiten)
    for m, n in muster.most_common(8):
        print(f"  {n:>4}x  {m}")

    if zeiten:
        print("\n--- Beispiel-Uhrzeit im Kontext (3 Ebenen hoch):")
        el = zeiten[0]
        print(el.prettify()[:400])
        for lvl in range(3):
            el = el.parent
            if el is None:
                break
            print(f"  {'  ' * lvl}^ {desc(el)}")

    # 3. Container-Kandidaten
    print("\n" + "=" * 70)
    print("3. Haeufige Klassen mit film/movie/performance/show im Namen")
    print("=" * 70)
    klassen = Counter()
    for el in soup.find_all(class_=True):
        for c in el.get("class", []):
            if re.search(r"film|movie|perform|show|vorstell|spielplan|program|session", c, re.I):
                klassen[f"{el.name}.{c}"] += 1
    for k, n in klassen.most_common(20):
        print(f"  {n:>4}x  {k}")


if __name__ == "__main__":
    main()
