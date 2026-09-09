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
MIN_SCHOOL_YEAR = 2025
MAX_SCHOOL_YEAR = 2029
MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12,
}
MONTH_RE = "|".join(MONTHS)


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
    req = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 schoolvakanties-calendar"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")
    p = TextExtractor()
    p.feed(raw)
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text


def school_year_date(day, month_name, explicit_year, school_year_start):
    month = MONTHS[month_name.lower()]
    if explicit_year:
        year = int(explicit_year)
    else:
        year = school_year_start if month >= 9 else school_year_start + 1
    return date(year, month, int(day))


def parse_vacation_line(line, school_year_start):
    m = re.search(r"\bvan\s+(.+?)\s+tot en met\s+(.+)$", line, re.IGNORECASE)
    if not m:
        return None

    start_text, end_text = m.groups()

    # End dates on Vlaanderen.be always provide month and year; ignore any
    # parenthetical note that follows the date.
    end_match = re.search(
        rf"(\d{{1,2}})\s+({MONTH_RE})\s+(\d{{4}})\b",
        end_text,
        re.IGNORECASE,
    )
    if not end_match:
        return None
    end_day, end_month, end_year = end_match.groups()

    # Some rows omit the month (and year) on the start date, e.g.
    # 'van maandag 16 tot en met zondag 22 februari 2026'. In that case the
    # start date uses the same month as the end date.
    start_match = re.search(
        rf"(\d{{1,2}})(?:\s+({MONTH_RE}))?(?:\s+(\d{{4}}))?\s*$",
        start_text,
        re.IGNORECASE,
    )
    if not start_match:
        return None
    start_day, start_month, start_year = start_match.groups()
    if not start_month:
        start_month = end_month

    start = school_year_date(start_day, start_month, start_year, school_year_start)
    end = date(int(end_year), MONTHS[end_month.lower()], int(end_day)) + timedelta(days=1)
    return start, end


def extract_events(text):
    heading = re.compile(r"(?:Schoolvakanties|Schooljaar)\s+(\d{4})-(\d{4})")
    headings = list(heading.finditer(text))
    events = []

    for i, h in enumerate(headings):
        school_year_start = int(h.group(1))
        if not (MIN_SCHOOL_YEAR <= school_year_start <= MAX_SCHOOL_YEAR):
            continue

        end_pos = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[h.end():end_pos]

        for name in VACATIONS:
            line_match = re.search(
                rf"{re.escape(name)}:\s*([^\n]+)",
                block,
                re.IGNORECASE,
            )
            if not line_match:
                continue
            parsed = parse_vacation_line(line_match.group(1), school_year_start)
            if parsed:
                start, end = parsed
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
        uid = uuid5(
            NAMESPACE_URL,
            f"https://www.vlaanderen.be/schoolvakanties/{name}/{start.isoformat()}",
        )
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
    expected = (MAX_SCHOOL_YEAR - MIN_SCHOOL_YEAR + 1) * len(VACATIONS)
    if len(events) != expected:
        raise RuntimeError(
            f"Found {len(events)} school-vacation events; expected exactly {expected}. "
            "Refusing to overwrite the ICS file."
        )
    content = make_ics(events)
    OUTPUT.write_text(content, encoding="utf-8", newline="")
    print(f"Wrote {len(events)} vacation events to {OUTPUT}")
    for name, start, end in events:
        print(f"{name}: {start} -> {end - timedelta(days=1)}")


if __name__ == "__main__":
    main()
