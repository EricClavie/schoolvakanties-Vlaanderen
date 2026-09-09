#!/usr/bin/env python3
import html
import re
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

SOURCE_URL = "https://www.vlaanderen.be/onderwijs-en-vorming/wat-mag-en-moet-op-school/schoolvakanties-vrije-dagen-en-afwezigheden/schoolvakanties"
OUTPUT = Path("schoolvakanties_vlaanderen_2026-2030.ics")
VACATIONS = ("Herfstvakantie", "Kerstvakantie", "Krokusvakantie", "Paasvakantie", "Zomervakantie")
MIN_START_YEAR = 2026
MAX_START_YEAR = 2030
MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12,
}

class TextExtractor(HTMLParser):
    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "div"}
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS:
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in self.BLOCKS:
            self.parts.append("\n")
    def handle_data(self, data):
        self.parts.append(data)


def page_text():
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0 schoolvakanties-calendar"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")
    p = TextExtractor()
    p.feed(raw)
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text


def parse_date(day, month, year):
    return date(int(year), MONTHS[month.lower()], int(day))


def extract_events(text):
    heading = re.compile(r"(?:Schoolvakanties|Schooljaar)\s+(\d{4})-(\d{4})")
    headings = list(heading.finditer(text))
    events = []
    for i, h in enumerate(headings):
        end_pos = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[h.end():end_pos]
        for name in VACATIONS:
            # Match only within the same line as the vacation label. This avoids
            # accidentally consuming dates belonging to another vacation.
            pat = re.compile(
                rf"{re.escape(name)}:\s+van\s+[^\n]*?(\d{{1,2}})\s+([A-Za-zÀ-ÿ]+)(?:\s+(\d{{4}}))?\s+tot en met\s+[^\n]*?(\d{{1,2}})\s+([A-Za-zÀ-ÿ]+)\s+(\d{{4}})",
                re.IGNORECASE,
            )
            m = pat.search(block)
            if not m:
                continue
            d1, m1, y1, d2, m2, y2 = m.groups()
            y2 = int(y2)
            if y1:
                y1 = int(y1)
            else:
                y1 = y2 - 1 if MONTHS[m1.lower()] > MONTHS[m2.lower()] else y2
            start = parse_date(d1, m1, y1)
            end = parse_date(d2, m2, y2) + timedelta(days=1)
            if MIN_START_YEAR <= start.year <= MAX_START_YEAR:
                events.append((name, start, end))
    unique = {(name, start, end) for name, start, end in events}
    return sorted(unique, key=lambda x: (x[1], x[0]))


def ics_escape(value):
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def make_ics(events):
    stamp = date.today().strftime("%Y%m%d") + "T000000Z"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//EricClavie//Vlaamse schoolvakanties//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Schoolvakanties Vlaanderen",
        "X-WR-CALDESC:Vlaamse schoolvakanties, automatisch bijgewerkt vanaf Vlaanderen.be",
    ]
    for name, start, end in events:
        uid = uuid5(NAMESPACE_URL, f"https://www.vlaanderen.be/schoolvakanties/{name}/{start.isoformat()}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@schoolvakanties-vlaanderen",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            f"SUMMARY:{ics_escape(name)}",
            "TRANSP:TRANSPARENT",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    text = page_text()
    events = extract_events(text)
    expected = (MAX_START_YEAR - MIN_START_YEAR + 1) * len(VACATIONS)
    if len(events) != expected:
        raise RuntimeError(f"Found {len(events)} school-vacation events; expected exactly {expected}. Refusing to overwrite the ICS file.")
    content = make_ics(events)
    OUTPUT.write_text(content, encoding="utf-8", newline="")
    print(f"Wrote {len(events)} vacation events to {OUTPUT}")
    for name, start, end in events:
        print(f"{name}: {start} -> {end - timedelta(days=1)}")

if __name__ == "__main__":
    main()
