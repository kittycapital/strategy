#!/usr/bin/env python3
"""
Strategy (MSTR) Bitcoin Purchase & Stock Issuance Tracker
Fetches 8-K filings from SEC EDGAR and parses BTC purchase + ATM stock sale data.
Outputs JSON for Chart.js dashboard on GitHub Pages.

Data Source: SEC EDGAR free API (no API key required)
  - Submissions API: https://data.sec.gov/submissions/CIK0001050446.json
  - Filing HTML pages: https://www.sec.gov/Archives/edgar/data/1050446/...

CIK for Strategy Inc (MSTR): 0001050446
"""

import json
import re
import sys
import time
import os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser

# ─── Configuration ───────────────────────────────────────────────────
CIK = "0001050446"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/1050446"
USER_AGENT = "HerdVibe/1.0 (contact@herdvibe.com)"  # SEC requires User-Agent
OUTPUT_FILE = "strategy_btc_data.json"
RATE_LIMIT_DELAY = 0.15  # SEC allows 10 req/sec, be conservative

# ─── HTML Table Parser ───────────────────────────────────────────────
class TableParser(HTMLParser):
    """Parse HTML tables from SEC filing pages."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_cell = ""
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell_tag = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.current_table = []
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.cell_tag = tag
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            self.current_row.append(self.current_cell.strip())
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.current_row:
                self.current_table.append(self.current_row)
        elif tag == "table" and self.in_table:
            self.in_table = False
            if self.current_table:
                self.tables.append(self.current_table)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def fetch_url(url, max_retries=3):
    """Fetch URL with proper headers and retry logic."""
    for attempt in range(max_retries):
        try:
            req = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "text/html,application/json"
            })
            with urlopen(req, timeout=30) as resp:
                data = resp.read()
                # Handle gzip if needed
                if resp.headers.get('Content-Encoding') == 'gzip':
                    import gzip
                    data = gzip.decompress(data)
                return data.decode('utf-8', errors='replace')
        except HTTPError as e:
            if e.code == 429:  # Rate limited
                wait = (attempt + 1) * 5
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 404:
                print(f"  404 Not Found: {url}")
                return None
            else:
                print(f"  HTTP {e.code} for {url}, attempt {attempt+1}/{max_retries}")
                time.sleep(2)
        except (URLError, TimeoutError) as e:
            print(f"  Error: {e}, attempt {attempt+1}/{max_retries}")
            time.sleep(2)
    return None


def get_8k_filings():
    """Get list of all 8-K filings from SEC EDGAR Submissions API."""
    print("Fetching MSTR submission history from SEC EDGAR...")
    raw = fetch_url(SUBMISSIONS_URL)
    if not raw:
        print("ERROR: Could not fetch submissions data")
        return []

    data = json.loads(raw)
    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    filings_8k = []
    for i, form in enumerate(forms):
        if form == "8-K":
            acc_no_dashes = accessions[i].replace("-", "")
            doc_url = f"{ARCHIVE_BASE}/{acc_no_dashes}/{primary_docs[i]}"
            filings_8k.append({
                "date": dates[i],
                "accession": accessions[i],
                "url": doc_url
            })

    # Also check additional filing files if entity has >1000 filings
    extra_files = data.get("filings", {}).get("files", [])
    for file_info in extra_files:
        fname = file_info.get("name", "")
        if fname:
            extra_url = f"https://data.sec.gov/submissions/{fname}"
            time.sleep(RATE_LIMIT_DELAY)
            extra_raw = fetch_url(extra_url)
            if extra_raw:
                extra_data = json.loads(extra_raw)
                ex_forms = extra_data.get("form", [])
                ex_dates = extra_data.get("filingDate", [])
                ex_accs = extra_data.get("accessionNumber", [])
                ex_docs = extra_data.get("primaryDocument", [])
                for i, form in enumerate(ex_forms):
                    if form == "8-K":
                        acc_no_dashes = ex_accs[i].replace("-", "")
                        doc_url = f"{ARCHIVE_BASE}/{acc_no_dashes}/{ex_docs[i]}"
                        filings_8k.append({
                            "date": ex_dates[i],
                            "accession": ex_accs[i],
                            "url": doc_url
                        })

    # Sort by date descending
    filings_8k.sort(key=lambda x: x["date"], reverse=True)
    print(f"Found {len(filings_8k)} 8-K filings total")
    return filings_8k


def parse_number(text):
    """Parse a number from text, handling commas, $, ~, etc."""
    if not text:
        return None
    # Remove common non-numeric chars
    cleaned = re.sub(r'[$ ,~\xa0\u200b]', '', text.strip())
    cleaned = cleaned.replace('(', '-').replace(')', '')
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_btc_purchase_data(html_content):
    """
    Extract Bitcoin purchase data from an 8-K filing HTML.
    Strategy's 8-K filings include tables with:
    - Date(s) of purchase
    - Number of bitcoins purchased
    - Aggregate purchase price (USD)
    - Average price per bitcoin (USD)
    """
    if not html_content:
        return None

    # Quick check: does this filing mention bitcoin purchases?
    lower = html_content.lower()
    if 'bitcoin' not in lower:
        return None

    # Check for purchase-related keywords
    purchase_keywords = ['bitcoin purchased', 'btc purchased', 'acquired', 'aggregate purchase price',
                         'average purchase price per bitcoin', 'average price per bitcoin']
    has_purchase_info = any(kw in lower for kw in purchase_keywords)
    if not has_purchase_info:
        return None

    # Parse tables
    parser = TableParser()
    parser.feed(html_content)

    result = {
        "btc_purchases": [],
        "stock_sales": [],
        "total_btc_held": None,
        "total_cost_basis": None
    }

    for table in parser.tables:
        if len(table) < 2:
            continue

        # Check header row for BTC purchase table
        header = ' '.join(table[0]).lower()

        # BTC Purchase table detection
        if ('bitcoin' in header or 'btc' in header) and ('purchase' in header or 'acquired' in header or 'price' in header):
            for row in table[1:]:
                if len(row) >= 3:
                    # Try to find: date, btc amount, aggregate price, avg price
                    btc_amount = None
                    agg_price = None
                    avg_price = None

                    for cell in row:
                        num = parse_number(cell)
                        if num is None:
                            continue
                        # Heuristic: BTC amount is typically < 100,000
                        # Aggregate price is typically > 1,000,000
                        # Average price is typically 10,000 - 200,000
                        if num > 1_000_000 and agg_price is None:
                            agg_price = num
                        elif 5_000 < num < 500_000 and avg_price is None and btc_amount is not None:
                            avg_price = num
                        elif 0 < num < 100_000 and btc_amount is None:
                            btc_amount = num

                    if btc_amount and btc_amount > 0:
                        result["btc_purchases"].append({
                            "btc_amount": btc_amount,
                            "aggregate_price_usd": agg_price,
                            "avg_price_per_btc": avg_price
                        })

        # Stock ATM sale table detection
        if ('share' in header or 'stock' in header) and ('sold' in header or 'sale' in header or 'proceeds' in header or 'issued' in header):
            for row in table[1:]:
                if len(row) >= 2:
                    shares = None
                    proceeds = None
                    for cell in row:
                        num = parse_number(cell)
                        if num is None:
                            continue
                        if num > 1_000_000 and proceeds is None:
                            proceeds = num
                        elif num > 0 and shares is None:
                            shares = num

                    if shares and shares > 0:
                        result["stock_sales"].append({
                            "shares_sold": shares,
                            "proceeds_usd": proceeds
                        })

    # Also try regex extraction from body text as fallback
    if not result["btc_purchases"]:
        # Pattern: "purchased approximately X,XXX bitcoin" or "acquired X,XXX BTC"
        btc_pattern = re.findall(
            r'(?:purchased|acquired)\s+(?:approximately\s+)?([0-9,]+)\s+(?:bitcoin|BTC)',
            html_content, re.IGNORECASE
        )
        price_pattern = re.findall(
            r'(?:aggregate\s+purchase\s+price|total\s+cost)\s+(?:of\s+)?(?:approximately\s+)?\$([0-9,.]+)\s*(million|billion)?',
            html_content, re.IGNORECASE
        )
        avg_pattern = re.findall(
            r'(?:average\s+(?:purchase\s+)?price)\s+(?:of\s+)?(?:approximately\s+)?\$([0-9,.]+)',
            html_content, re.IGNORECASE
        )

        if btc_pattern:
            btc_amt = parse_number(btc_pattern[0])
            agg = None
            avg = None
            if price_pattern:
                val = parse_number(price_pattern[0][0])
                unit = price_pattern[0][1].lower() if price_pattern[0][1] else ''
                if val:
                    if 'billion' in unit:
                        val *= 1_000_000_000
                    elif 'million' in unit:
                        val *= 1_000_000
                    agg = val
            if avg_pattern:
                avg = parse_number(avg_pattern[0])

            if btc_amt:
                result["btc_purchases"].append({
                    "btc_amount": btc_amt,
                    "aggregate_price_usd": agg,
                    "avg_price_per_btc": avg
                })

    # Extract total holdings if mentioned
    total_pattern = re.findall(
        r'(?:total|aggregate)\s+(?:of\s+)?(?:approximately\s+)?([0-9,]+)\s+(?:bitcoin|BTC)',
        html_content, re.IGNORECASE
    )
    if total_pattern:
        result["total_btc_held"] = parse_number(total_pattern[-1])  # Last mention = most recent total

    # Extract stock issuance from ATM text
    atm_shares = re.findall(
        r'sold\s+([0-9,]+)\s+shares?\s+(?:of\s+)?(?:its\s+)?(?:Class\s+A\s+)?(?:common\s+)?stock',
        html_content, re.IGNORECASE
    )
    atm_proceeds = re.findall(
        r'(?:net\s+)?proceeds\s+(?:of\s+)?(?:approximately\s+)?\$([0-9,.]+)\s*(million|billion)?',
        html_content, re.IGNORECASE
    )

    if atm_shares and not result["stock_sales"]:
        shares = parse_number(atm_shares[0])
        proceeds = None
        if atm_proceeds:
            val = parse_number(atm_proceeds[0][0])
            unit = atm_proceeds[0][1].lower() if atm_proceeds[0][1] else ''
            if val:
                if 'billion' in unit:
                    val *= 1_000_000_000
                elif 'million' in unit:
                    val *= 1_000_000
                proceeds = val
        if shares:
            result["stock_sales"].append({
                "shares_sold": shares,
                "proceeds_usd": proceeds
            })

    return result if (result["btc_purchases"] or result["total_btc_held"]) else None


def load_existing_data():
    """Load previously collected data to avoid re-scraping."""
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r') as f:
            return json.load(f)
    return None


def main():
    print("=" * 60)
    print("Strategy (MSTR) Bitcoin Purchase Tracker")
    print("Data Source: SEC EDGAR (free, no API key)")
    print("=" * 60)

    # Load existing data for incremental updates
    existing = load_existing_data()
    known_accessions = set()
    if existing and "filings" in existing:
        known_accessions = {f["accession"] for f in existing["filings"]}
        print(f"Loaded {len(known_accessions)} previously processed filings")

    # Get 8-K filing list
    filings_8k = get_8k_filings()
    if not filings_8k:
        print("No 8-K filings found, using existing data if available")
        if existing:
            return
        sys.exit(1)

    # Filter to BTC-era filings (2020+) and new ones only
    btc_era = [f for f in filings_8k if f["date"] >= "2020-08-01"]
    new_filings = [f for f in btc_era if f["accession"] not in known_accessions]

    print(f"\nBTC-era 8-K filings: {len(btc_era)}")
    print(f"New filings to process: {len(new_filings)}")

    # Process new filings
    results = []
    if existing and "filings" in existing:
        results = existing["filings"]

    for i, filing in enumerate(new_filings):
        print(f"\n[{i+1}/{len(new_filings)}] Processing {filing['date']} - {filing['accession']}")
        time.sleep(RATE_LIMIT_DELAY)

        html = fetch_url(filing["url"])
        if not html:
            print("  Could not fetch filing, skipping")
            continue

        parsed = extract_btc_purchase_data(html)
        if parsed:
            entry = {
                "date": filing["date"],
                "accession": filing["accession"],
                "url": filing["url"],
                **parsed
            }
            results.append(entry)
            btc_sum = sum(p["btc_amount"] for p in parsed["btc_purchases"])
            print(f"  ✓ Found BTC purchase: {btc_sum:,.0f} BTC")
            if parsed["stock_sales"]:
                shares_sum = sum(s["shares_sold"] for s in parsed["stock_sales"])
                print(f"  ✓ Found stock sale: {shares_sum:,.0f} shares")
        else:
            print("  ✗ No BTC purchase data in this filing")

    # Sort results by date
    results.sort(key=lambda x: x["date"])

    # Calculate cumulative totals
    cumulative_btc = 0
    cumulative_cost = 0
    cumulative_shares_sold = 0
    cumulative_proceeds = 0

    for entry in results:
        for p in entry.get("btc_purchases", []):
            cumulative_btc += p.get("btc_amount", 0)
            if p.get("aggregate_price_usd"):
                cumulative_cost += p["aggregate_price_usd"]
        entry["cumulative_btc"] = cumulative_btc
        entry["cumulative_cost_usd"] = cumulative_cost
        entry["avg_cost_basis"] = cumulative_cost / cumulative_btc if cumulative_btc > 0 else 0

        for s in entry.get("stock_sales", []):
            cumulative_shares_sold += s.get("shares_sold", 0)
            if s.get("proceeds_usd"):
                cumulative_proceeds += s["proceeds_usd"]
        entry["cumulative_shares_sold"] = cumulative_shares_sold
        entry["cumulative_proceeds_usd"] = cumulative_proceeds

    # Build output
    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "SEC EDGAR (data.sec.gov)",
        "entity": "Strategy Inc (MSTR)",
        "cik": CIK,
        "summary": {
            "total_btc": cumulative_btc,
            "total_cost_usd": cumulative_cost,
            "avg_cost_per_btc": cumulative_cost / cumulative_btc if cumulative_btc > 0 else 0,
            "total_purchase_events": len(results),
            "total_shares_issued": cumulative_shares_sold,
            "total_atm_proceeds": cumulative_proceeds
        },
        "filings": results
    }

    # Write output
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Output written to {OUTPUT_FILE}")
    print(f"Total BTC purchases tracked: {cumulative_btc:,.0f} BTC")
    print(f"Total cost basis: ${cumulative_cost:,.0f}")
    if cumulative_btc > 0:
        print(f"Average cost: ${cumulative_cost/cumulative_btc:,.2f}/BTC")
    print(f"Total stock shares issued: {cumulative_shares_sold:,.0f}")
    print(f"Total ATM proceeds: ${cumulative_proceeds:,.0f}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
