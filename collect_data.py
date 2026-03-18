#!/usr/bin/env python3
"""
Strategy (MSTR) Bitcoin Purchase Tracker
Scrapes bitbo.io/treasuries/microstrategy for purchase history.
Outputs strategy_btc_seed.json for Chart.js dashboard.

Source: https://bitbo.io/treasuries/microstrategy/
Table columns: Date | BTC Purchased | Amount | Total Bitcoin | Total Dollars
"""

import json
import re
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser

URL = "https://bitbo.io/treasuries/microstrategy/"
OUTPUT = "strategy_btc_seed.json"
USER_AGENT = "HerdVibe/1.0 (contact@herdvibe.com)"


class TableParser(HTMLParser):
    """Extract all <table> data from HTML."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.cur_table = []
        self.cur_row = []
        self.cur_cell = ""
        self.in_table = False
        self.in_row = False
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.cur_table = []
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.cur_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.cur_cell = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            self.cur_row.append(self.cur_cell.strip())
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.cur_row:
                self.cur_table.append(self.cur_row)
        elif tag == "table" and self.in_table:
            self.in_table = False
            if self.cur_table:
                self.tables.append(self.cur_table)

    def handle_data(self, data):
        if self.in_cell:
            self.cur_cell += data


def fetch(url):
    """Fetch URL content."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError) as e:
        print(f"ERROR fetching {url}: {e}")
        sys.exit(1)


def parse_date(s):
    """Parse date string like '3/16/2026' or '03/19/2024' or '4/1/2024 - 5/1/2024' → 'YYYY-MM-DD'."""
    s = s.strip()
    # Handle date ranges — take the last date
    if " - " in s:
        s = s.split(" - ")[-1].strip()
    # Remove leading zeros and parse
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_num(s):
    """Parse number: '22,337' → 22337, '$1.568B' → 1568000000, '-704' → -704."""
    s = s.strip().replace(",", "").replace("**", "")
    if not s or s == "--":
        return 0

    # Handle $XXB / $XXM format
    m = re.match(r"\$?([\d.]+)\s*(B|M|T)?", s, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        unit = (m.group(2) or "").upper()
        if unit == "T":
            val *= 1_000_000_000_000
        elif unit == "B":
            val *= 1_000_000_000
        elif unit == "M":
            val *= 1_000_000
        return val

    # Plain number
    try:
        return float(s.replace("$", ""))
    except ValueError:
        return 0


def find_purchase_table(tables):
    """Find the table with purchase history (has 'Date' and 'BTC Purchased' headers)."""
    for table in tables:
        if len(table) < 2:
            continue
        header = " ".join(table[0]).lower()
        if "date" in header and ("btc" in header or "purchased" in header):
            return table
    # Fallback: find largest table with 5 columns
    for table in tables:
        if len(table) > 5 and all(len(r) >= 4 for r in table[1:3]):
            return table
    return None


def main():
    print("=" * 55)
    print("Strategy BTC Tracker — bitbo.io scraper")
    print("=" * 55)

    html = fetch(URL)
    print(f"Fetched {len(html):,} bytes from bitbo.io")

    parser = TableParser()
    parser.feed(html)
    print(f"Found {len(parser.tables)} tables")

    table = find_purchase_table(parser.tables)
    if not table:
        print("ERROR: Could not find purchase history table")
        sys.exit(1)

    # Skip header row(s)
    start = 0
    for i, row in enumerate(table):
        if any("date" in c.lower() for c in row):
            start = i + 1
            break

    purchases = []
    for row in table[start:]:
        if len(row) < 4:
            continue

        date_str = row[0].replace("**", "").strip()
        date = parse_date(date_str)
        if not date:
            continue

        btc = parse_num(row[1])
        amount = parse_num(row[2])        # Purchase amount USD
        cum_btc = parse_num(row[3])        # Total Bitcoin after purchase
        # row[4] if exists = Total Dollars cumulative (not needed for per-purchase)

        if btc == 0:
            continue

        avg_price = amount / btc if btc > 0 and amount > 0 else 0

        purchases.append({
            "date": date,
            "btc": int(btc),
            "avg_price": round(avg_price),
            "total_usd": int(amount),
            "cumulative_btc": int(cum_btc),
            "funding": "atm"  # Default; most recent are ATM
        })

    # Sort oldest first
    purchases.sort(key=lambda x: x["date"])

    # Fix funding type for known early purchases
    funding_map = {
        "2020-08-11": "cash", "2020-09-14": "cash", "2020-12-04": "cash",
        "2020-12-21": "convertible_notes",
        "2021-01-22": "cash", "2021-02-02": "cash",
        "2021-02-24": "convertible_notes",
        "2021-03-01": "cash", "2021-03-05": "cash", "2021-03-12": "cash",
        "2021-04-05": "cash", "2021-05-13": "cash", "2021-05-18": "cash",
        "2021-06-21": "notes",
        "2022-01-31": "cash", "2022-04-05": "loan",
        "2022-06-28": "cash", "2022-09-20": "cash",
        "2022-12-22": "cash", "2022-12-24": "cash",
        "2023-03-27": "cash", "2023-04-05": "cash", "2023-07-31": "cash",
        "2023-11-01": "cash",
        "2024-02-06": "cash", "2024-05-01": "cash", "2024-08-01": "cash",
        "2024-09-20": "notes",
        "2025-02-10": "atm_preferred", "2025-02-24": "atm_preferred",
        "2025-06-23": "cash",
        "2025-08-11": "cash",
        "2025-10-13": "cash", "2025-10-20": "cash", "2025-10-27": "cash",
        "2025-11-03": "cash", "2025-11-10": "cash",
        "2025-12-01": "cash", "2025-12-31": "cash",
    }
    for p in purchases:
        if p["date"] in funding_map:
            p["funding"] = funding_map[p["date"]]

    if not purchases:
        print("ERROR: No purchases parsed")
        sys.exit(1)

    last = purchases[-1]
    total_btc = last["cumulative_btc"]
    total_cost = sum(p["total_usd"] for p in purchases)
    avg_cost = total_cost / total_btc if total_btc > 0 else 0

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "bitbo.io/treasuries/microstrategy (BitcoinTreasuries.com)",
        "entity": "Strategy Inc (MSTR)",
        "cik": "0001050446",
        "summary": {
            "total_btc": total_btc,
            "total_cost_usd": total_cost,
            "avg_cost_per_btc": round(avg_cost),
            "total_purchase_events": len(purchases)
        },
        "purchases": purchases
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Parsed {len(purchases)} purchases")
    print(f"   Total BTC: {total_btc:,}")
    print(f"   Total cost: ${total_cost:,.0f}")
    print(f"   Avg cost: ${avg_cost:,.0f}/BTC")
    print(f"   Output: {OUTPUT}")
    print("=" * 55)


if __name__ == "__main__":
    main()
