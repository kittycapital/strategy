#!/usr/bin/env python3
"""
Strategy (MSTR) mNAV Calculator + BTC/MSTR Price History
Uses: BTC_USD.csv (local) + yfinance (MSTR price/shares)
Outputs: strategy_mnav.json for dashboard charts.

mNAV = Enterprise Value / BTC Value
EV = Market Cap + Total Debt + Preferred Equity - Cash
BTC Value = BTC Holdings × BTC Price
"""

import json
import csv
import sys
import os
from datetime import datetime, timedelta

# ─── Try importing yfinance ───
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    print("⚠️  yfinance not installed, using seed data only")
    HAS_YF = False

# ─── Config ───
BTC_CSV = "BTC_USD.csv"
OUTPUT = "strategy_mnav.json"

# Strategy capital structure (updated periodically from 10-K/10-Q)
# These are stepped values - update when new filings come out
CAPITAL_STRUCTURE = [
    # (from_date, debt_M, preferred_notional_M, cash_M)
    ("2020-08-01", 0, 0, 600),
    ("2020-12-21", 650, 0, 60),       # First convertible notes
    ("2021-02-24", 1700, 0, 60),      # More converts
    ("2021-06-21", 2200, 0, 60),
    ("2022-04-05", 2400, 0, 50),      # Silvergate loan
    ("2023-01-01", 2200, 0, 50),      # Paid off Silvergate
    ("2024-03-01", 3400, 0, 50),
    ("2024-09-20", 4200, 0, 50),
    ("2024-11-25", 7200, 0, 100),     # Massive converts
    ("2025-01-01", 7200, 875, 100),   # STRK preferred added
    ("2025-02-10", 7200, 1750, 200),  # STRK + STRF
    ("2025-06-01", 7200, 2000, 500),  # STRD added
    ("2025-07-01", 7200, 2200, 1000), # STRC added
    ("2025-10-01", 8200, 2200, 2000),
    ("2025-12-01", 8200, 2200, 2250),
    ("2026-01-01", 8200, 2500, 2250), # More STRC
    ("2026-03-01", 8200, 3500, 2250), # STRC ramp-up
]

# BTC holdings history (from our seed data - cumulative at key dates)
BTC_HOLDINGS = [
    ("2020-08-11", 21454), ("2020-09-14", 38250), ("2020-12-04", 40824),
    ("2020-12-21", 70470), ("2021-02-24", 90531), ("2021-06-21", 105085),
    ("2021-09-13", 114042), ("2021-11-28", 121044), ("2021-12-30", 124391),
    ("2022-01-31", 125051), ("2022-04-05", 129218), ("2022-06-28", 129699),
    ("2022-09-20", 130000), ("2022-12-24", 132500), ("2023-03-27", 138955),
    ("2023-06-27", 152333), ("2023-09-24", 158245), ("2023-11-30", 174530),
    ("2023-12-27", 189150), ("2024-02-26", 193000), ("2024-03-19", 214246),
    ("2024-06-20", 226331), ("2024-09-13", 244800), ("2024-09-20", 252220),
    ("2024-11-11", 279420), ("2024-11-18", 331200), ("2024-11-25", 386700),
    ("2024-12-02", 402100), ("2024-12-09", 423650), ("2024-12-16", 439000),
    ("2024-12-23", 444262), ("2024-12-30", 446400),
    ("2025-01-06", 447470), ("2025-01-13", 450000), ("2025-01-21", 461000),
    ("2025-01-27", 471107), ("2025-02-10", 478740), ("2025-02-24", 499096),
    ("2025-03-17", 499226), ("2025-03-24", 506137), ("2025-03-31", 528185),
    ("2025-04-14", 531644), ("2025-04-21", 538200), ("2025-04-28", 553555),
    ("2025-05-05", 555450), ("2025-05-12", 568840), ("2025-05-19", 576230),
    ("2025-05-26", 580250), ("2025-06-16", 592100), ("2025-06-30", 597325),
    ("2025-07-14", 601550), ("2025-07-21", 607770), ("2025-07-29", 628791),
    ("2025-09-08", 638460), ("2025-09-22", 639835), ("2025-10-27", 640808),
    ("2025-11-17", 649870), ("2025-12-01", 650000), ("2025-12-08", 660624),
    ("2025-12-15", 671268), ("2025-12-29", 672497),
    ("2026-01-05", 673783), ("2026-01-12", 687410), ("2026-01-20", 709715),
    ("2026-01-26", 712647), ("2026-02-02", 713502), ("2026-02-09", 714644),
    ("2026-02-17", 717131), ("2026-02-23", 717722), ("2026-03-02", 720737),
    ("2026-03-09", 738731), ("2026-03-16", 761068),
]

# Shares outstanding history (approximate, from 10-Q/10-K)
SHARES_OUTSTANDING = [
    ("2020-08-01", 9940000),    # Pre-split era, class A + B
    ("2021-01-01", 10340000),
    ("2021-09-13", 11360000),   # After ATM sales
    ("2022-01-01", 11430000),
    ("2023-01-01", 11630000),
    ("2024-01-01", 14230000),
    ("2024-09-13", 16780000),   # ATM acceleration
    ("2024-11-11", 198000000),  # Post 10:1 stock split Aug 2024 + massive ATM
    ("2024-11-18", 210000000),
    ("2024-11-25", 225000000),
    ("2024-12-09", 240000000),
    ("2024-12-31", 246000000),
    ("2025-01-21", 256000000),
    ("2025-02-01", 260000000),
    ("2025-03-31", 268000000),
    ("2025-05-12", 275000000),
    ("2025-06-16", 279000000),
    ("2025-07-29", 285000000),
    ("2025-09-01", 288000000),
    ("2025-12-01", 293000000),
    ("2026-01-12", 303000000),
    ("2026-01-20", 313000000),
    ("2026-02-01", 316000000),
    ("2026-03-01", 320000000),
    ("2026-03-16", 325000000),
]


def get_stepped_value(history, date_str):
    """Get the most recent value from a stepped history list."""
    val = history[0][1]
    for d, v in history:
        if date_str >= d:
            val = v
        else:
            break
    return val


def load_btc_csv():
    """Load BTC prices from CSV."""
    prices = {}
    with open(BTC_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                prices[row['Date']] = float(row['Close'])
            except (ValueError, KeyError):
                continue
    return prices


def fetch_mstr_yfinance(start_date="2020-08-01"):
    """Fetch MSTR daily close prices from yfinance."""
    if not HAS_YF:
        return {}
    
    print("Fetching MSTR data from yfinance...")
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(start=start_date, auto_adjust=True)
        prices = {}
        for idx, row in hist.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            prices[date_str] = float(row['Close'])
        print(f"  Got {len(prices)} MSTR price points")
        
        # Also try to get current shares outstanding
        info = mstr.info
        shares = info.get('sharesOutstanding', None)
        if shares:
            print(f"  Current shares outstanding: {shares:,.0f}")
        
        return prices
    except Exception as e:
        print(f"  yfinance error: {e}")
        return {}


def calculate_mnav(date_str, btc_price, mstr_price, btc_held, shares, debt_m, pref_m, cash_m):
    """Calculate mNAV for a given date."""
    if not btc_price or not mstr_price or not btc_held or not shares:
        return None
    
    market_cap = mstr_price * shares
    ev = market_cap + (debt_m * 1e6) + (pref_m * 1e6) - (cash_m * 1e6)
    btc_value = btc_held * btc_price
    
    if btc_value <= 0:
        return None
    
    return ev / btc_value


def main():
    print("=" * 55)
    print("Strategy mNAV Calculator")
    print("=" * 55)

    # Load BTC prices
    btc_prices = load_btc_csv()
    print(f"BTC prices loaded: {len(btc_prices)} days")

    # Fetch MSTR prices
    mstr_prices = fetch_mstr_yfinance()

    # If no yfinance, try loading existing output for MSTR prices
    if not mstr_prices and os.path.exists(OUTPUT):
        print("Loading existing mNAV data for MSTR prices...")
        with open(OUTPUT) as f:
            existing = json.load(f)
        for pt in existing.get("daily", []):
            if pt.get("mstr_price"):
                mstr_prices[pt["date"]] = pt["mstr_price"]
        print(f"  Recovered {len(mstr_prices)} MSTR prices from existing data")

    # Generate daily mNAV from 2020-08-11 onwards
    start = datetime(2020, 8, 11)
    end = datetime.utcnow()
    
    daily = []
    weekly = []  # Sampled weekly for lighter JSON
    
    current = start
    last_week = None
    
    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        
        btc_price = btc_prices.get(ds)
        mstr_price = mstr_prices.get(ds)
        btc_held = get_stepped_value(BTC_HOLDINGS, ds)
        shares = get_stepped_value(SHARES_OUTSTANDING, ds)
        
        cap = get_stepped_value(CAPITAL_STRUCTURE, ds)
        debt_m = cap if isinstance(cap, (int, float)) else 0
        # Re-fetch from tuple
        for d, debt, pref, cash in CAPITAL_STRUCTURE:
            if ds >= d:
                debt_m, pref_m, cash_m = debt, pref, cash
        
        mnav = None
        if btc_price and mstr_price:
            mnav = calculate_mnav(ds, btc_price, mstr_price, btc_held, shares, debt_m, pref_m, cash_m)
        
        btc_per_share = btc_held / shares if shares else None
        
        entry = {
            "date": ds,
            "btc_price": round(btc_price, 2) if btc_price else None,
            "mstr_price": round(mstr_price, 2) if mstr_price else None,
            "mnav": round(mnav, 4) if mnav else None,
            "btc_held": btc_held,
            "shares": shares,
            "btc_per_share": round(btc_per_share, 8) if btc_per_share else None,
        }
        
        daily.append(entry)
        
        # Weekly sample (every Monday or first available)
        week_key = current.strftime("%Y-W%W")
        if week_key != last_week and (btc_price or mstr_price):
            weekly.append(entry)
            last_week = week_key
        
        current += timedelta(days=1)

    # Filter to only entries with data
    daily_with_data = [d for d in daily if d["btc_price"] or d["mstr_price"]]
    weekly_with_data = [d for d in weekly if d["btc_price"]]

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "BTC: CSV/CoinGecko, MSTR: yfinance, mNAV: calculated",
        "current": daily_with_data[-1] if daily_with_data else None,
        "weekly": weekly_with_data,
        "daily": daily_with_data,
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    # Stats
    mnav_entries = [d for d in daily_with_data if d["mnav"]]
    print(f"\n✅ Generated {len(daily_with_data)} daily entries")
    print(f"   {len(mnav_entries)} entries with mNAV")
    print(f"   {len(weekly_with_data)} weekly samples")
    if mnav_entries:
        latest = mnav_entries[-1]
        print(f"   Latest mNAV: {latest['mnav']}x ({latest['date']})")
        print(f"   Latest BTC: ${latest['btc_price']:,.0f}")
        print(f"   Latest MSTR: ${latest['mstr_price']:,.2f}")
    print(f"   Output: {OUTPUT}")
    print("=" * 55)


if __name__ == "__main__":
    main()
