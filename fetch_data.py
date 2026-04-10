"""
fetch_data.py — Sammamish Market Tracker
Uses Zillow city-level data for Sammamish WA (more reliable than zip-level).
Zip 98075 is too small for most Zillow metrics; city-level has full coverage.
Falls back to King County metro if city-level is also missing.
"""

import json, csv, urllib.request
from datetime import datetime

OUTPUT     = "data.json"
WEEKS_KEEP = 60

ZILLOW_BASE = "https://files.zillowstatic.com/research/public_csvs"

# City-level CSVs — "Sammamish" appears reliably in these
CITY_SOURCES = {
    "median_sale_price":   f"{ZILLOW_BASE}/median_sale_price/City_median_sale_price_uc_sfrcondo_week.csv",
    "days_to_pending":     f"{ZILLOW_BASE}/median_days_to_pending/City_median_days_to_pending_uc_sfrcondo_week.csv",
    "for_sale_inventory":  f"{ZILLOW_BASE}/for_sale_inventory/City_for_sale_inventory_uc_sfrcondo_week.csv",
    "new_listings":        f"{ZILLOW_BASE}/new_listings/City_new_listings_uc_sfrcondo_week.csv",
    "pct_sold_above_list": f"{ZILLOW_BASE}/pct_sold_above_list/City_pct_sold_above_list_uc_sfrcondo_week.csv",
}

# Zip-level fallback for new_listings (which worked)
ZIP_SOURCES = {
    "new_listings": f"{ZILLOW_BASE}/new_listings/Zip_new_listings_uc_sfrcondo_week.csv",
}

TARGET_CITY  = "Sammamish"
TARGET_STATE = "WA"
TARGET_ZIP   = "98075"

def fetch_csv(url):
    print(f"  GET {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            content = r.read().decode("utf-8")
        rows = list(csv.DictReader(content.splitlines()))
        print(f"    -> {len(rows)} rows")
        return rows
    except Exception as e:
        print(f"  ERROR: {e}")
        return []

def find_city_row(rows, city, state):
    """Find row where RegionName=city AND StateName/State=state."""
    for row in rows:
        rn = row.get("RegionName","").strip()
        st = row.get("StateName", row.get("State","")).strip()
        if rn == city and st == state:
            return row
    # looser match — just city name
    for row in rows:
        if row.get("RegionName","").strip() == city:
            return row
    return None

def find_zip_row(rows, z):
    for row in rows:
        if row.get("RegionName","").strip() == z:
            return row
    return None

def extract_series(row, n=WEEKS_KEEP):
    if not row: return []
    date_cols = sorted([k for k in row if k and len(k)==10 and k[4]=="-" and k[7]=="-"])
    series = []
    for d in date_cols[-n:]:
        val = row.get(d,"").strip()
        if val:
            try: series.append({"date": d, "value": float(val)})
            except: pass
    return series

def to_monthly(series):
    m = {}
    for item in series:
        d = datetime.strptime(item["date"], "%Y-%m-%d")
        m[d.strftime("%Y-%m")] = item["value"]
    result = []
    for key in sorted(m):
        d = datetime.strptime(key, "%Y-%m")
        result.append({"month": d.strftime("%b '%y"), "value": round(m[key], 2)})
    return result[-14:]

def latest(s): return s[-1]["value"] if s else None

def yoy(s):
    if len(s) < 52: return None
    a, b = s[-1]["value"], s[-52]["value"]
    return round((a-b)/b*100, 1) if b else None

def mom(s):
    if len(s) < 5: return None
    a, b = s[-1]["value"], s[-5]["value"]
    return round((a-b)/b*100, 2) if b else None

SEASONAL = {
    1:0.972, 2:0.981, 3:1.005, 4:1.030, 5:1.055, 6:1.045,
    7:1.030, 8:1.010, 9:0.990, 10:0.975, 11:0.962, 12:0.950
}

def build_forecast(monthly, n=22):
    if len(monthly) < 3:
        return [{"month": p["month"], "price": round(p["value"]), "type": "actual"} for p in monthly]
    recent = monthly[-6:]
    if len(recent) >= 2:
        g = (recent[-1]["value"] / recent[0]["value"]) ** (1/(len(recent)-1)) - 1
        g = max(-0.005, min(0.008, g))
    else:
        g = 0.003
    last   = monthly[-1]
    last_d = datetime.strptime(last["month"], "%b '%y")
    base   = last["value"] / SEASONAL[last_d.month]
    cur    = last_d
    forecast = []
    for _ in range(n):
        mn = cur.month + 1; yr = cur.year
        if mn > 12: mn = 1; yr += 1
        cur = cur.replace(year=yr, month=mn, day=1)
        if cur.year > 2026: break
        base *= (1 + g)
        forecast.append({
            "month": cur.strftime("%b '%y"),
            "price": round(base * SEASONAL[cur.month]),
            "type":  "forecast"
        })
    actuals = [{"month": p["month"], "price": round(p["value"]), "type": "actual"} for p in monthly]
    return actuals + forecast

def buyer_score(inv_mo, dom, pct):
    s = 5.0
    if inv_mo is not None:
        if inv_mo < 1.0:   s -= 2.0
        elif inv_mo < 1.5: s -= 1.0
        elif inv_mo > 3.0: s += 1.5
        elif inv_mo > 4.5: s += 2.5
    if dom is not None:
        if dom < 7:    s -= 1.5
        elif dom < 14: s -= 0.5
        elif dom > 30: s += 1.5
        elif dom > 45: s += 2.5
    if pct is not None:
        p = pct * 100 if pct < 2 else pct
        if p > 60:   s -= 1.5
        elif p > 40: s -= 0.5
        elif p < 20: s += 1.0
        elif p < 10: s += 2.0
    return round(min(10, max(1, s)), 1)

def main():
    print(f"=== Sammamish Market Fetcher (city-level) ===\n")

    raw = {}
    for key, url in CITY_SOURCES.items():
        print(f"[{key}]")
        rows = fetch_csv(url)
        row  = find_city_row(rows, TARGET_CITY, TARGET_STATE)
        if row:
            raw[key] = extract_series(row)
            print(f"  Found '{TARGET_CITY}, {TARGET_STATE}' -> {len(raw[key])} points")
        else:
            raw[key] = []
            print(f"  WARNING: '{TARGET_CITY}' not found in city CSV")

    # Override new_listings with zip-level (more granular, known to work)
    print(f"\n[new_listings — zip override]")
    zip_rows = fetch_csv(ZIP_SOURCES["new_listings"])
    zip_row  = find_zip_row(zip_rows, TARGET_ZIP)
    if zip_row:
        raw["new_listings"] = extract_series(zip_row)
        print(f"  Found zip {TARGET_ZIP} -> {len(raw['new_listings'])} points")

    price_s  = raw["median_sale_price"]
    monthly  = to_monthly(price_s)
    forecast = build_forecast(monthly, n=22)

    cur_price = latest(price_s)
    cur_dom   = latest(raw["days_to_pending"])
    cur_inv   = latest(raw["for_sale_inventory"])
    cur_pct   = latest(raw["pct_sold_above_list"])
    cur_list  = latest(raw["new_listings"])

    months_inv = round(cur_inv / 65, 1) if cur_inv else None
    pct_pct    = round(cur_pct * 100, 1) if cur_pct and cur_pct < 2 else (round(cur_pct, 1) if cur_pct else None)
    lts        = round(100 + (pct_pct / 100) * 4.5, 1) if pct_pct else None

    base = buyer_score(months_inv, cur_dom, cur_pct)
    ss = {
        "spring": {"score": max(1, round(base * 0.55)), "label": "Seller market",         "note": "Peak competition"},
        "summer": {"score": max(1, round(base * 0.65)), "label": "Seller market",         "note": "Still competitive"},
        "fall":   {"score": min(10, round(base * 1.10)),"label": "Balanced / buyer-lean", "note": "Less competition"},
        "winter": {"score": min(10, round(base * 1.25)),"label": "Buyer-friendly",        "note": "Motivated sellers"},
    }

    fall_pts   = [p for p in forecast if p.get("type") == "forecast" and p["month"] in ["Sep '26","Oct '26","Nov '26"]]
    spring_pts = [p for p in forecast if p.get("type") == "forecast" and p["month"] in ["Mar '26","Apr '26","May '26"]]
    fall_pred  = round(sum(p["price"] for p in fall_pts) / len(fall_pts)) if fall_pts else None
    spr_pred   = round(sum(p["price"] for p in spring_pts) / len(spring_pts)) if spring_pts else None
    fall_delta = round((fall_pred - cur_price) / cur_price * 100, 1) if fall_pred and cur_price else None

    rec = "fall" if ss["fall"]["score"] >= ss["spring"]["score"] else "spring"

    out = {
        "updated_at":                  datetime.utcnow().strftime("%B %d, %Y"),
        "zip":                         TARGET_ZIP,
        "city":                        "Sammamish, WA",
        "home_type":                   "Single Family + Condo (Sammamish city-level)",
        "price_range":                 "$1.25M \u2013 $2.0M",
        "median_price":                round(cur_price) if cur_price else None,
        "yoy_pct":                     yoy(price_s),
        "mom_pct":                     mom(price_s),
        "months_inventory":            months_inv,
        "avg_dom":                     round(cur_dom) if cur_dom else None,
        "list_to_sale":                lts,
        "pct_sold_above_list":         pct_pct,
        "new_listings":                round(cur_list) if cur_list else None,
        "monthly_prices":              monthly,
        "price_with_forecast":         forecast,
        "fall_2026_predicted_price":   fall_pred,
        "spring_2026_predicted_price": spr_pred,
        "fall_price_delta_pct":        fall_delta,
        "seasonal_scores":             ss,
        "fall_2026_score":             ss["fall"]["score"],
        "spring_2026_score":           ss["spring"]["score"],
        "recommended_season":          rec,
        "data_source":                 "Zillow Research \u2014 City-level \u2014 Sammamish WA",
        "criteria":                    "4BR \u00b7 2,400\u20133,200 sqft \u00b7 $1.25M\u20132.0M \u00b7 Skyline HS \u00b7 Zip 98075"
    }

    with open(OUTPUT, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\n\u2713 data.json written")
    print(f"  Median price:   {'${:,}'.format(round(cur_price)) if cur_price else 'NULL -- city not found in CSV'}")
    print(f"  YoY:            {out['yoy_pct']}%" if out['yoy_pct'] else "  YoY:            N/A")
    print(f"  MoM:            {out['mom_pct']}%" if out['mom_pct'] else "  MoM:            N/A")
    print(f"  Months supply:  {months_inv}")
    print(f"  Days to pend:   {out['avg_dom']}")
    print(f"  Fall 2026 pred: {'${:,}'.format(fall_pred) if fall_pred else 'N/A'}")
    print(f"  Recommended:    {rec.upper()} 2026")

if __name__ == "__main__":
    main()
