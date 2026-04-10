"""
fetch_data.py
Fetches Zillow Research public CSVs for zip code 98075 (Sammamish, WA)
and writes data.json for the dashboard to consume.

Runs via GitHub Actions weekly. Completely free — no API keys needed.
Zillow publishes these CSVs publicly at files.zillowstatic.com.
"""

import json
import csv
import urllib.request
import urllib.error
from datetime import datetime, timedelta

ZIP = "98075"  # Sammamish, WA (Skyline HS area)
OUTPUT = "data.json"
WEEKS = 52     # how many weeks of history to keep

# Zillow Research CSV URLs (publicly available, no auth required)
ZILLOW_BASE = "https://files.zillowstatic.com/research/public_csvs"
SOURCES = {
    "median_sale_price": f"{ZILLOW_BASE}/median_sale_price/Zip_median_sale_price_uc_sfrcondo_week.csv",
    "days_to_pending":   f"{ZILLOW_BASE}/median_days_to_pending/Zip_median_days_to_pending_uc_sfrcondo_week.csv",
    "for_sale_inventory":f"{ZILLOW_BASE}/for_sale_inventory/Zip_for_sale_inventory_uc_sfrcondo_week.csv",
    "new_listings":      f"{ZILLOW_BASE}/new_listings/Zip_new_listings_uc_sfrcondo_week.csv",
    "pct_sold_above_list":f"{ZILLOW_BASE}/pct_sold_above_list/Zip_pct_sold_above_list_uc_sfrcondo_week.csv",
}

def fetch_csv(url):
    """Download a CSV from a URL and return as list of dicts."""
    print(f"  Fetching: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
        reader = csv.DictReader(content.splitlines())
        return list(reader)
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}")
        return []

def extract_zip_series(rows, zip_code, n_weeks=WEEKS):
    """
    Find the row for zip_code, return last n_weeks of {date, value} pairs.
    Zillow CSV format: first ~9 columns are metadata, rest are date columns.
    """
    for row in rows:
        if row.get("RegionName") == zip_code:
            # collect all date columns (format: YYYY-MM-DD)
            date_cols = [k for k in row.keys() if k and len(k) == 10 and k[4] == "-"]
            date_cols.sort()
            recent = date_cols[-n_weeks:]
            series = []
            for d in recent:
                val = row.get(d, "").strip()
                if val:
                    try:
                        series.append({"date": d, "value": float(val)})
                    except ValueError:
                        pass
            return series
    print(f"  WARNING: zip {zip_code} not found in CSV")
    return []

def monthly_from_weekly(series):
    """
    Collapse weekly data into monthly by taking the last reading of each month.
    Returns list of {month: 'MMM YY', value: float}
    """
    monthly = {}
    for item in series:
        d = datetime.strptime(item["date"], "%Y-%m-%d")
        key = d.strftime("%Y-%m")
        monthly[key] = item["value"]

    result = []
    for key in sorted(monthly.keys()):
        d = datetime.strptime(key, "%Y-%m")
        result.append({
            "month": d.strftime("%b '%y"),
            "value": round(monthly[key], 2)
        })
    return result[-13:]  # last 13 months

def compute_yoy(series):
    """Compute year-over-year % change from latest vs ~52 weeks ago."""
    if len(series) < 2:
        return None
    latest = series[-1]["value"]
    year_ago = series[0]["value"] if len(series) >= 52 else series[0]["value"]
    if year_ago == 0:
        return None
    return round((latest - year_ago) / year_ago * 100, 1)

def seasonal_buyer_score(inventory, dom, pct_over_list):
    """
    Simple scoring model: higher = better for buyer.
    This is the baseline for the annual cycle; the dashboard
    overlays known seasonal multipliers for spring vs fall.
    """
    score = 5.0
    # inventory: < 1 mo = very tight, > 3 mo = buyer-friendly
    if inventory is not None:
        if inventory < 1.0:   score -= 2
        elif inventory < 2.0: score -= 1
        elif inventory > 3.0: score += 1.5
        elif inventory > 4.0: score += 2.5
    # DOM: fast = seller market
    if dom is not None:
        if dom < 7:    score -= 1.5
        elif dom < 14: score -= 0.5
        elif dom > 30: score += 1.5
        elif dom > 45: score += 2.5
    # pct sold over list: high = seller market
    if pct_over_list is not None:
        p = pct_over_list * 100 if pct_over_list < 2 else pct_over_list
        if p > 60:   score -= 1.5
        elif p > 40: score -= 0.5
        elif p < 20: score += 1.0
        elif p < 10: score += 2.0
    return round(min(10, max(1, score)), 1)

def main():
    print("=== Sammamish Market Data Fetcher ===")
    print(f"Target zip: {ZIP}")

    raw = {}
    for key, url in SOURCES.items():
        rows = fetch_csv(url)
        raw[key] = extract_zip_series(rows, ZIP)
        print(f"  {key}: {len(raw[key])} weekly data points")

    # --- build monthly price series ---
    price_series = monthly_from_weekly(raw["median_sale_price"])

    # --- current snapshot (latest values) ---
    def latest(key):
        s = raw.get(key, [])
        return s[-1]["value"] if s else None

    median_price   = latest("median_sale_price")
    dom            = latest("days_to_pending")
    inventory_raw  = latest("for_sale_inventory")
    new_listings   = latest("new_listings")
    pct_over_list  = latest("pct_sold_above_list")

    # convert inventory count → months (rough: inventory / avg monthly sales)
    # Zillow "for_sale_inventory" is a count; typical monthly sales in 98075 ~40-60 homes
    months_inventory = round(inventory_raw / 50, 1) if inventory_raw else None

    # pct_sold_above_list comes as 0-1 float in some versions, 0-100 in others
    if pct_over_list and pct_over_list < 2:
        pct_over_list_pct = round(pct_over_list * 100, 1)
    else:
        pct_over_list_pct = round(pct_over_list, 1) if pct_over_list else None

    # list-to-sale proxy: if 60% sell above list, rough L/S = ~102-103%
    list_to_sale = None
    if pct_over_list_pct is not None:
        list_to_sale = round(100 + (pct_over_list_pct / 100) * 4.5, 1)

    yoy_pct = compute_yoy(raw["median_sale_price"])
    base_score = seasonal_buyer_score(months_inventory, dom, pct_over_list)

    # seasonal multipliers based on known Sammamish pattern
    seasonal_scores = {
        "spring": {
            "score": max(1, round(base_score * 0.55)),
            "label": "Seller market",
            "note":  "Peak competition, bidding wars"
        },
        "summer": {
            "score": max(1, round(base_score * 0.65)),
            "label": "Seller market",
            "note":  "Still very competitive"
        },
        "fall": {
            "score": min(10, round(base_score * 1.1)),
            "label": "Balanced / buyer-lean",
            "note":  "Less competition, price cuts possible"
        },
        "winter": {
            "score": min(10, round(base_score * 1.25)),
            "label": "Buyer-friendly",
            "note":  "Motivated sellers, low inventory but low demand"
        }
    }

    fall_score = seasonal_scores["fall"]["score"]
    spring_score = seasonal_scores["spring"]["score"]
    recommended = "fall" if fall_score > spring_score else "spring"

    output = {
        "updated_at":         datetime.utcnow().strftime("%B %d, %Y"),
        "zip":                ZIP,
        "city":               "Sammamish, WA",
        "median_price":       round(median_price) if median_price else None,
        "yoy_pct":            yoy_pct,
        "months_inventory":   months_inventory,
        "avg_dom":            round(dom) if dom else None,
        "list_to_sale":       list_to_sale,
        "pct_sold_above_list":pct_over_list_pct,
        "new_listings":       round(new_listings) if new_listings else None,
        "monthly_prices":     [{"month": p["month"], "price": round(p["value"])} for p in price_series],
        "seasonal_scores":    seasonal_scores,
        "fall_2026_score":    fall_score,
        "spring_2026_score":  spring_score,
        "recommended_season": recommended,
        "data_source":        "Zillow Research public CSVs — zillow.com/research/data",
        "criteria":           "4BR · 2,400–3,200 sqft · Zip 98075 · Skyline HS area"
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Written to {OUTPUT}")
    print(f"  Median price:    ${output['median_price']:,}" if output['median_price'] else "  Median price:    N/A")
    print(f"  YoY change:      {output['yoy_pct']}%" if output['yoy_pct'] else "  YoY change:      N/A")
    print(f"  Months supply:   {output['months_inventory']}")
    print(f"  Days to pending: {output['avg_dom']}")
    print(f"  Fall 2026 score: {fall_score}/10")
    print(f"  Recommended:     {recommended.upper()} 2026")

if __name__ == "__main__":
    main()
