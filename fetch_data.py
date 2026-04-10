"""
fetch_data.py — Sammamish Market Tracker
Uses Zillow Home Value Index (ZHVI) — their most reliable dataset,
available for every zip code including small ones like 98075.
Also uses Redfin weekly market data as a secondary source.
"""

import json, csv, urllib.request
from datetime import datetime

OUTPUT = "data.json"
TARGET_ZIP   = "98075"
TARGET_CITY  = "Sammamish"
TARGET_STATE = "WA"

ZILLOW_BASE = "https://files.zillowstatic.com/research/public_csvs"

# ZHVI = Zillow Home Value Index, monthly, zip level — very reliable
# mid-tier (35th-65th percentile), smoothed & seasonally adjusted
ZHVI_ZIP_URL = f"{ZILLOW_BASE}/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"

# Also try median sale price at metro/county level for Eastside Seattle
METRO_PRICE_URL = f"{ZILLOW_BASE}/median_sale_price/Metro_median_sale_price_uc_sfrcondo_week.csv"
METRO_DOM_URL   = f"{ZILLOW_BASE}/median_days_to_pending/Metro_median_days_to_pending_uc_sfrcondo_week.csv"
METRO_INV_URL   = f"{ZILLOW_BASE}/for_sale_inventory/Metro_for_sale_inventory_uc_sfrcondo_week.csv"
METRO_PCT_URL   = f"{ZILLOW_BASE}/pct_sold_above_list/Metro_pct_sold_above_list_uc_sfrcondo_week.csv"

# Seattle-Tacoma-Bellevue metro name in Zillow
METRO_NAME = "Seattle-Tacoma-Bellevue, WA"

def fetch_csv(url):
    print(f"  GET {url[:80]}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            content = r.read().decode("utf-8")
        rows = list(csv.DictReader(content.splitlines()))
        print(f"    -> {len(rows)} rows, sample cols: {list(rows[0].keys())[:5] if rows else []}")
        return rows
    except Exception as e:
        print(f"  ERROR: {e}")
        return []

def find_row(rows, key_col, key_val):
    for row in rows:
        if row.get(key_col,"").strip() == key_val:
            return row
    # try partial match
    for row in rows:
        if key_val.lower() in row.get(key_col,"").lower():
            return row
    return None

def find_row_multi(rows, checks):
    """Find row matching multiple column conditions."""
    for row in rows:
        if all(row.get(k,"").strip()==v for k,v in checks.items()):
            return row
    # looser: just first condition
    k0,v0 = list(checks.items())[0]
    return find_row(rows, k0, v0)

def extract_series(row, n=60):
    if not row: return []
    date_cols = sorted([k for k in row if k and len(k)>=7 and
                        (k[4]=="-" or k[4]=="/") and k[:4].isdigit()])
    series = []
    for d in date_cols[-n:]:
        val = row.get(d,"").strip()
        if val:
            try:
                # normalize date to YYYY-MM-DD
                if len(d)==7:  d = d+"-01"
                series.append({"date":d, "value":float(val)})
            except: pass
    return series

def to_monthly(series):
    m = {}
    for item in series:
        try:
            d = datetime.strptime(item["date"][:10], "%Y-%m-%d")
            m[d.strftime("%Y-%m")] = item["value"]
        except: pass
    result = []
    for key in sorted(m):
        d = datetime.strptime(key, "%Y-%m")
        result.append({"month": d.strftime("%b '%y"), "value": round(m[key], 2)})
    return result[-14:]

def latest(s): return s[-1]["value"] if s else None

def yoy(s):
    if len(s) < 52: return None
    a,b = s[-1]["value"], s[-52]["value"]
    return round((a-b)/b*100, 1) if b else None

def yoy_monthly(s):
    """YoY from monthly series (12 months back)."""
    if len(s) < 12: return None
    a,b = s[-1]["value"], s[-13]["value"]
    return round((a-b)/b*100, 1) if b else None

def mom_weekly(s):
    if len(s) < 5: return None
    a,b = s[-1]["value"], s[-5]["value"]
    return round((a-b)/b*100, 2) if b else None

def mom_monthly(s):
    if len(s) < 2: return None
    a,b = s[-1]["value"], s[-2]["value"]
    return round((a-b)/b*100, 2) if b else None

SEASONAL = {
    1:0.972, 2:0.981, 3:1.005, 4:1.030, 5:1.055, 6:1.045,
    7:1.030, 8:1.010, 9:0.990, 10:0.975, 11:0.962, 12:0.950
}

def build_forecast(monthly, n=22):
    if len(monthly) < 3:
        return [{"month":p["month"],"price":round(p["value"]),"type":"actual"} for p in monthly]
    recent = monthly[-6:]
    g = (recent[-1]["value"]/recent[0]["value"])**(1/(len(recent)-1))-1 if len(recent)>=2 else 0.003
    g = max(-0.005, min(0.008, g))
    last   = monthly[-1]
    last_d = datetime.strptime(last["month"], "%b '%y")
    base   = last["value"] / SEASONAL[last_d.month]
    cur    = last_d
    forecast = []
    for _ in range(n):
        mn=cur.month+1; yr=cur.year
        if mn>12: mn=1; yr+=1
        cur=cur.replace(year=yr,month=mn,day=1)
        if cur.year>2026: break
        base *= (1+g)
        forecast.append({"month":cur.strftime("%b '%y"),"price":round(base*SEASONAL[cur.month]),"type":"forecast"})
    actuals=[{"month":p["month"],"price":round(p["value"]),"type":"actual"} for p in monthly]
    return actuals+forecast

def buyer_score(inv_mo, dom, pct):
    s=5.0
    if inv_mo is not None:
        if inv_mo<1.0: s-=2.0
        elif inv_mo<1.5: s-=1.0
        elif inv_mo>3.0: s+=1.5
        elif inv_mo>4.5: s+=2.5
    if dom is not None:
        if dom<7: s-=1.5
        elif dom<14: s-=0.5
        elif dom>30: s+=1.5
        elif dom>45: s+=2.5
    if pct is not None:
        p=pct*100 if pct<2 else pct
        if p>60: s-=1.5
        elif p>40: s-=0.5
        elif p<20: s+=1.0
        elif p<10: s+=2.0
    return round(min(10,max(1,s)),1)

def main():
    print(f"=== Sammamish Market Fetcher ===\n")

    # ── 1. ZHVI zip-level (primary price source) ──────────────────────────
    print(f"[ZHVI zip-level — {TARGET_ZIP}]")
    zhvi_rows = fetch_csv(ZHVI_ZIP_URL)
    zhvi_row  = find_row(zhvi_rows, "RegionName", TARGET_ZIP)
    zhvi_s    = extract_series(zhvi_row) if zhvi_row else []
    print(f"  zip {TARGET_ZIP}: {len(zhvi_s)} monthly points")

    # ── 2. Metro-level weekly metrics (Seattle metro) ─────────────────────
    print(f"\n[Metro price — {METRO_NAME}]")
    metro_price_rows = fetch_csv(METRO_PRICE_URL)
    metro_price_row  = find_row(metro_price_rows, "RegionName", METRO_NAME)
    metro_price_s    = extract_series(metro_price_row) if metro_price_row else []
    print(f"  {len(metro_price_s)} weekly points")

    print(f"\n[Metro DOM — {METRO_NAME}]")
    metro_dom_rows = fetch_csv(METRO_DOM_URL)
    metro_dom_row  = find_row(metro_dom_rows, "RegionName", METRO_NAME)
    metro_dom_s    = extract_series(metro_dom_row) if metro_dom_row else []
    print(f"  {len(metro_dom_s)} weekly points")

    print(f"\n[Metro inventory — {METRO_NAME}]")
    metro_inv_rows = fetch_csv(METRO_INV_URL)
    metro_inv_row  = find_row(metro_inv_rows, "RegionName", METRO_NAME)
    metro_inv_s    = extract_series(metro_inv_row) if metro_inv_row else []
    print(f"  {len(metro_inv_s)} weekly points")

    print(f"\n[Metro pct over list — {METRO_NAME}]")
    metro_pct_rows = fetch_csv(METRO_PCT_URL)
    metro_pct_row  = find_row(metro_pct_rows, "RegionName", METRO_NAME)
    metro_pct_s    = extract_series(metro_pct_row) if metro_pct_row else []
    print(f"  {len(metro_pct_s)} weekly points")

    # ── 3. Decide price source ─────────────────────────────────────────────
    # Prefer ZHVI for price trend (it's zip-specific to 98075).
    # ZHVI is a value index not a sale price, but tracks closely.
    # Scale it: Sammamish typically trades ~8-12% above metro median.
    SAMMAMISH_PREMIUM = 1.10  # 10% above Seattle metro

    if zhvi_s:
        print(f"\n  Using ZHVI zip-level data (zip 98075) for price trend.")
        price_series = zhvi_s
        # ZHVI values for 98075 should already reflect local prices
    elif metro_price_s:
        print(f"\n  Falling back to Seattle metro sale price + Sammamish premium.")
        price_series = [{"date":p["date"],"value":p["value"]*SAMMAMISH_PREMIUM} for p in metro_price_s]
    else:
        print(f"\n  No price data found.")
        price_series = []

    monthly = to_monthly(price_series)
    forecast = build_forecast(monthly)

    cur_price = latest(price_series)
    cur_dom   = latest(metro_dom_s)
    cur_inv   = latest(metro_inv_s)
    cur_pct   = latest(metro_pct_s)

    months_inv = round(cur_inv / 3500, 1) if cur_inv else None  # Seattle metro ~3500 sales/mo
    pct_pct    = round(cur_pct*100,1) if cur_pct and cur_pct<2 else (round(cur_pct,1) if cur_pct else None)
    lts        = round(100+(pct_pct/100)*4.5,1) if pct_pct else None

    price_yoy = yoy_monthly(monthly) if monthly else None
    price_mom = mom_monthly(monthly) if monthly else None

    base = buyer_score(months_inv, cur_dom, cur_pct)
    ss = {
        "spring":{"score":max(1,round(base*0.55)),"label":"Seller market",        "note":"Peak competition"},
        "summer":{"score":max(1,round(base*0.65)),"label":"Seller market",        "note":"Still competitive"},
        "fall":  {"score":min(10,round(base*1.10)),"label":"Balanced/buyer-lean", "note":"Less competition"},
        "winter":{"score":min(10,round(base*1.25)),"label":"Buyer-friendly",      "note":"Motivated sellers"},
    }

    fall_pts  =[p for p in forecast if p.get("type")=="forecast" and p["month"] in ["Sep '26","Oct '26","Nov '26"]]
    spr_pts   =[p for p in forecast if p.get("type")=="forecast" and p["month"] in ["Mar '26","Apr '26","May '26"]]
    fall_pred = round(sum(p["price"] for p in fall_pts)/len(fall_pts)) if fall_pts else None
    spr_pred  = round(sum(p["price"] for p in spr_pts)/len(spr_pts)) if spr_pts else None
    fall_delta= round((fall_pred-cur_price)/cur_price*100,1) if fall_pred and cur_price else None

    rec = "fall" if ss["fall"]["score"]>=ss["spring"]["score"] else "spring"

    price_source = "ZHVI zip 98075" if zhvi_s else ("Seattle metro sale price + 10% Sammamish premium" if metro_price_s else "No data")

    out = {
        "updated_at":                  datetime.utcnow().strftime("%B %d, %Y"),
        "zip":                         TARGET_ZIP,
        "city":                        "Sammamish, WA",
        "home_type":                   "Single Family Residential",
        "price_range":                 "$1.25M \u2013 $2.0M",
        "median_price":                round(cur_price) if cur_price else None,
        "yoy_pct":                     price_yoy,
        "mom_pct":                     price_mom,
        "months_inventory":            months_inv,
        "avg_dom":                     round(cur_dom) if cur_dom else None,
        "list_to_sale":                lts,
        "pct_sold_above_list":         pct_pct,
        "new_listings":                None,
        "monthly_prices":              monthly,
        "price_with_forecast":         forecast,
        "fall_2026_predicted_price":   fall_pred,
        "spring_2026_predicted_price": spr_pred,
        "fall_price_delta_pct":        fall_delta,
        "seasonal_scores":             ss,
        "fall_2026_score":             ss["fall"]["score"],
        "spring_2026_score":           ss["spring"]["score"],
        "recommended_season":          rec,
        "data_source":                 f"Zillow ZHVI (zip 98075) + Seattle metro indicators \u2014 {price_source}",
        "criteria":                    "4BR \u00b7 2,400\u20133,200 sqft \u00b7 $1.25M\u20132.0M \u00b7 SFR \u00b7 Skyline HS"
    }

    with open(OUTPUT,"w") as f:
        json.dump(out, f, indent=2)

    print(f"\n\u2713 data.json written")
    print(f"  Price source:   {price_source}")
    print(f"  Median price:   {'${:,}'.format(round(cur_price)) if cur_price else 'NULL'}")
    print(f"  YoY:            {price_yoy}%" if price_yoy else "  YoY:            N/A")
    print(f"  MoM:            {price_mom}%" if price_mom else "  MoM:            N/A")
    print(f"  DOM:            {round(cur_dom) if cur_dom else 'N/A'}")
    print(f"  Inventory mo:   {months_inv}")
    print(f"  Fall 2026 pred: {'${:,}'.format(fall_pred) if fall_pred else 'N/A'}")
    print(f"  Recommended:    {rec.upper()} 2026")

if __name__ == "__main__":
    main()
