#!/usr/bin/env python3
"""
Strategy (MSTR) mNAV Calculator
- Updates BTC_USD.csv and MSTR_USD.csv from yfinance daily
- Calculates mNAV from CSVs + capital structure
- Outputs strategy_mnav.json
"""

import json, csv, os, sys
from datetime import datetime, timedelta

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    print("⚠️  yfinance not installed")
    HAS_YF = False

BTC_CSV = "BTC_USD.csv"
MSTR_CSV = "MSTR_USD.csv"
OUTPUT = "strategy_mnav.json"

# ─── Capital Structure (date, debt_M, preferred_notional_M, cash_M) ───
CAPITAL_STRUCTURE = [
    ("2020-08-01", 0, 0, 50),       # Cash after BTC purchases
    ("2020-09-14", 0, 0, 50),
    ("2020-12-21", 650, 0, 10),      # Convertible notes issued, cash used for BTC
    ("2021-02-24", 1700, 0, 10),
    ("2021-06-21", 2200, 0, 10),
    ("2022-04-05", 2400, 0, 10),
    ("2023-01-01", 2200, 0, 45),
    ("2024-03-01", 3400, 0, 45),
    ("2024-09-20", 4200, 0, 45),
    ("2024-11-25", 7200, 0, 50),
    ("2025-01-01", 7200, 875, 50),
    ("2025-02-10", 7200, 1750, 50),
    ("2025-06-01", 7200, 2000, 100),
    ("2025-07-01", 7200, 2200, 500),
    ("2025-10-01", 8200, 2200, 1500),
    ("2025-12-01", 8200, 2200, 2250),
    ("2026-01-01", 8200, 2500, 2250),
    ("2026-03-01", 8200, 3500, 2250),
]

# ─── BTC Holdings (date, cumulative_btc) ───
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

# ─── Shares Outstanding (ALL split-adjusted to post-Aug 2024 10:1 split) ───
# yfinance returns split-adjusted prices, so shares must also be split-adjusted
SHARES_OUTSTANDING = [
    ("2020-08-01", 99_400_000),    # 9.94M × 10
    ("2021-01-01", 103_400_000),   # 10.34M × 10
    ("2021-09-13", 113_600_000),   # 11.36M × 10
    ("2022-01-01", 114_300_000),   # 11.43M × 10
    ("2023-01-01", 116_300_000),   # 11.63M × 10
    ("2024-01-01", 142_300_000),   # 14.23M × 10
    ("2024-08-08", 167_800_000),   # Post split (same number)
    ("2024-09-13", 167_800_000),
    ("2024-11-11", 198_000_000),
    ("2024-11-18", 210_000_000),
    ("2024-11-25", 225_000_000),
    ("2024-12-09", 240_000_000),
    ("2024-12-31", 246_000_000),
    ("2025-01-21", 256_000_000),
    ("2025-03-31", 268_000_000),
    ("2025-05-12", 275_000_000),
    ("2025-07-29", 285_000_000),
    ("2025-09-01", 288_000_000),
    ("2025-12-01", 293_000_000),
    ("2026-01-12", 303_000_000),
    ("2026-01-20", 313_000_000),
    ("2026-02-01", 316_000_000),
    ("2026-03-01", 320_000_000),
    ("2026-03-16", 325_000_000),
]


def get_stepped(history, date_str):
    """Get most recent value. Works with (date, val) and (date, v1, v2, v3)."""
    val = history[0][1] if len(history[0]) == 2 else history[0][1:]
    for item in history:
        if date_str >= item[0]:
            val = item[1] if len(item) == 2 else item[1:]
        else:
            break
    return val


def load_csv(path):
    """Load Date→Close from CSV."""
    prices = {}
    if not os.path.exists(path):
        return prices
    with open(path, 'r') as f:
        for row in csv.DictReader(f):
            try:
                prices[row['Date']] = float(row['Close'])
            except (ValueError, KeyError):
                continue
    return prices


def save_csv(path, prices_dict):
    """Save prices dict {date: close} to CSV."""
    rows = sorted(prices_dict.items())
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Date', 'Close'])
        for date, close in rows:
            w.writerow([date, round(close, 2)])


def update_csv_from_yfinance(ticker, csv_path):
    """Fetch latest prices from yfinance and merge into CSV."""
    if not HAS_YF:
        return load_csv(csv_path)

    existing = load_csv(csv_path)
    
    # Find the last date in CSV, fetch from there
    if existing:
        last_date = max(existing.keys())
        start = (datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
        print(f"  {csv_path}: updating from {start} (had {len(existing)} days)")
    else:
        start = "2020-08-01"
        print(f"  {csv_path}: fresh download from {start}")

    try:
        data = yf.Ticker(ticker).history(start=start, auto_adjust=True)
        new_count = 0
        for idx, row in data.iterrows():
            ds = idx.strftime("%Y-%m-%d")
            if ds not in existing or ds >= last_date if existing else True:
                existing[ds] = float(row['Close'])
                new_count += 1
        print(f"  {csv_path}: +{new_count} new days, total {len(existing)}")
    except Exception as e:
        print(f"  yfinance error for {ticker}: {e}")

    save_csv(csv_path, existing)
    return existing


def main():
    print("=" * 55)
    print("Strategy mNAV Calculator")
    print("=" * 55)

    # Update CSVs from yfinance
    print("\nUpdating price CSVs...")
    btc_prices = update_csv_from_yfinance("BTC-USD", BTC_CSV)
    mstr_prices = update_csv_from_yfinance("MSTR", MSTR_CSV)

    if not btc_prices:
        print("ERROR: No BTC prices"); sys.exit(1)
    if not mstr_prices:
        print("ERROR: No MSTR prices"); sys.exit(1)

    # Generate daily mNAV
    print("\nCalculating daily mNAV...")
    start = datetime(2020, 8, 11)
    end = datetime.utcnow()
    
    daily = []
    cur = start

    while cur <= end:
        ds = cur.strftime("%Y-%m-%d")
        
        bp = btc_prices.get(ds)
        mp = mstr_prices.get(ds)

        if bp and mp:
            bh = get_stepped(BTC_HOLDINGS, ds)
            sh = get_stepped(SHARES_OUTSTANDING, ds)
            cap = get_stepped(CAPITAL_STRUCTURE, ds)
            debt, pref, cash = cap[0], cap[1], cap[2]

            mcap = mp * sh
            ev = mcap + debt * 1e6 + pref * 1e6 - cash * 1e6
            bval = bh * bp
            mnav = ev / bval if bval > 0 else None

            if mnav and mnav > 0:
                daily.append({
                    "date": ds,
                    "btc_price": round(bp, 2),
                    "mstr_price": round(mp, 2),
                    "mnav": round(mnav, 3),
                    "btc_held": bh,
                    "shares": sh,
                })

        cur += timedelta(days=1)

    # Output
    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "BTC & MSTR prices: yfinance (CSV cached), mNAV: calculated",
        "current": daily[-1] if daily else None,
        "weekly": daily,
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    mnav_vals = [w['mnav'] for w in daily]
    print(f"\n✅ {len(daily)} daily entries")
    if daily:
        print(f"   mNAV range: {min(mnav_vals):.2f}x - {max(mnav_vals):.2f}x")
        l = daily[-1]
        print(f"   Latest: {l['date']} mNAV={l['mnav']}x BTC=${l['btc_price']:,.0f} MSTR=${l['mstr_price']:,.2f}")
    print(f"   Output: {OUTPUT}")
    print("=" * 55)


if __name__ == "__main__":
    main()
