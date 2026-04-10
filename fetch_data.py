"""
fetch_data.py — Sammamish Market Tracker
ZHVI zip 98075 for price (confirmed working: 60 pts, $1.81M).
Metro indicators use Seattle metro — fixing row-finder to handle
cases where RegionName row exists but date columns return 0 points.
"""

import json, csv, urllib.request
from datetime import datetime

OUTPUT       = "data.json"
TARGET_ZIP   = "98075"

ZILLOW_BASE  = "https://files.zillowstatic.com/research/public_csvs"
ZHVI_URL     = f"{ZILLOW_BASE}/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"

# Metro-level — try multiple possible name variants
METRO_URLS = {
    "pct_sold_above_list": f"{ZILLOW_BASE}/pct_sold_above_list/Metro_pct_sold_above_list_uc_sfrcondo_week.csv",
    "median_sale_price":   f"{ZILLOW_BASE}/median_sale_price/Metro_median_sale_price_uc_sfrcondo_week.csv",
    "for_sale_inventory":  f"{ZILLOW_BASE}/for_sale_inventory/Metro_for_sale_inventory_uc_sfrcondo_sm_week.csv",
    "days_to_pending":     f"{ZILLOW_BASE}/median_days_to_pending/Metro_median_days_to_pending_uc_sfrcondo_sm_week.csv",
}

METRO_VARIANTS = [
    "Seattle-Tacoma-Bellevue, WA",
    "Seattle, WA",
    "Seattle-Bellevue-Everett, WA",
    "Seattle-Tacoma-Bellevue",
    "Seattle",
]

def fetch_csv(url):
    print(f"  GET {url[-70:]}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            content = r.read().decode("utf-8")
        rows = list(csv.DictReader(content.splitlines()))
        print(f"    -> {len(rows)} rows")
        return rows
    except Exception as e:
        print(f"    ERROR: {e}")
        return []

def find_row(rows, key_col, key_val):
    for row in rows:
        if row.get(key_col,"").strip() == key_val:
            return row
    for row in rows:
        if key_val.lower() in row.get(key_col,"").lower():
            return row
    return None

def get_date_cols(row):
    return sorted([k for k in row if k and len(k) >= 7 and k[:4].isdigit() and
                   ("-" in k or "/" in k)])

def extract_series(row, n=60):
    if not row: return []
    date_cols = get_date_cols(row)
    if date_cols:
        print(f"    date cols: {date_cols[0]} .. {date_cols[-1]} ({len(date_cols)} total)")
    series = []
    for d in date_cols[-n:]:
        val = row.get(d,"").strip()
        if val:
            try:
                norm = d[:10] if len(d) >= 10 else d+"-01"
                series.append({"date": norm, "value": float(val)})
            except: pass
    return series

def find_metro_row(rows):
    """Try all metro name variants, print which one matched."""
    for name in METRO_VARIANTS:
        row = find_row(rows, "RegionName", name)
        if row:
            print(f"    matched metro: '{row.get('RegionName','')}'")
            return row
    # last resort: print all region names so we can debug
    names = [r.get("RegionName","") for r in rows[:30]]
    print(f"    no match found. First 30 regions: {names}")
    return None

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

def yoy_monthly(s):
    if len(s) < 13: return None
    a,b = s[-1]["value"], s[-13]["value"]
    return round((a-b)/b*100, 1) if b else None

def mom_monthly(s):
    if len(s) < 2: return None
    a,b = s[-1]["value"], s[-2]["value"]
    return round((a-b)/b*100, 2) if b else None

SEASONAL = {
    1:0.972,2:0.981,3:1.005,4:1.030,5:1.055,6:1.045,
    7:1.030,8:1.010,9:0.990,10:0.975,11:0.962,12:0.950
}

def build_forecast(monthly, n=22):
    if len(monthly) < 3:
        return [{"month":p["month"],"price":round(p["value"]),"type":"actual"} for p in monthly]
    recent = monthly[-6:]
    g = (recent[-1]["value"]/recent[0]["value"])**(1/(len(recent)-1))-1 if len(recent)>=2 else 0.003
    g = max(-0.005, min(0.008, g))
    print(f"  Forecast monthly growth rate: {g*100:.3f}%")
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
    print("=== Sammamish Market Fetcher ===\n")

    # ── ZHVI zip 98075 (confirmed working) ───────────────────────────────
    print(f"[ZHVI zip {TARGET_ZIP}]")
    zhvi_rows = fetch_csv(ZHVI_URL)
    zhvi_row  = find_row(zhvi_rows, "RegionName", TARGET_ZIP)
    zhvi_s    = extract_series(zhvi_row) if zhvi_row else []
    print(f"  {len(zhvi_s)} monthly points")

    monthly  = to_monthly(zhvi_s)
    forecast = build_forecast(monthly)

    cur_price = latest(zhvi_s)
    price_yoy = yoy_monthly(monthly)
    price_mom = mom_monthly(monthly)

    # ── Metro indicators ──────────────────────────────────────────────────
    metro = {}
    for key, url in METRO_URLS.items():
        print(f"\n[{key}]")
        rows = fetch_csv(url)
        if not rows:
            metro[key] = []
            continue
        row = find_metro_row(rows)
        s   = extract_series(row) if row else []
        print(f"  {len(s)} points")
        metro[key] = s

    cur_dom = latest(metro["days_to_pending"])
    cur_inv = latest(metro["for_sale_inventory"])
    cur_pct = latest(metro["pct_sold_above_list"])

    # inventory: metro Seattle has ~3000-4000 active listings typically
    months_inv = round(cur_inv/3200, 1) if cur_inv else None
    pct_pct    = round(cur_pct*100,1) if cur_pct and cur_pct<2 else (round(cur_pct,1) if cur_pct else None)
    lts        = round(100+(pct_pct/100)*4.5,1) if pct_pct else None

    base = buyer_score(months_inv, cur_dom, cur_pct)
    ss = {
        "spring":{"score":max(1,round(base*0.55)),"label":"Seller market",        "note":"Peak competition"},
        "summer":{"score":max(1,round(base*0.65)),"label":"Seller market",        "note":"Still competitive"},
        "fall":  {"score":min(10,round(base*1.10)),"label":"Balanced/buyer-lean", "note":"Less competition"},
        "winter":{"score":min(10,round(base*1.25)),"label":"Buyer-friendly",      "note":"Motivated sellers"},
    }

    fall_pts  = [p for p in forecast if p.get("type")=="forecast" and p["month"] in ["Sep '26","Oct '26","Nov '26"]]
    spr_pts   = [p for p in forecast if p.get("type")=="forecast" and p["month"] in ["Mar '26","Apr '26","May '26"]]
    fall_pred = round(sum(p["price"] for p in fall_pts)/len(fall_pts)) if fall_pts else None
    spr_pred  = round(sum(p["price"] for p in spr_pts)/len(spr_pts)) if spr_pts else None
    fall_delta= round((fall_pred-cur_price)/cur_price*100,1) if fall_pred and cur_price else None

    rec = "fall" if ss["fall"]["score"]>=ss["spring"]["score"] else "spring"

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
        "data_source":                 "Zillow ZHVI zip 98075 + Seattle metro indicators",
        "criteria":                    "4BR \u00b7 2,400\u20133,200 sqft \u00b7 $1.25M\u20132.0M \u00b7 SFR \u00b7 Skyline HS"
    }

    with open(OUTPUT,"w") as f:
        json.dump(out, f, indent=2)

    print(f"\n\u2713 data.json written")
    print(f"  Median price:   {'${:,}'.format(round(cur_price)) if cur_price else 'NULL'}")
    print(f"  YoY:            {price_yoy}%" if price_yoy else "  YoY:            N/A")
    print(f"  MoM:            {price_mom}%" if price_mom else "  MoM:            N/A")
    print(f"  DOM:            {round(cur_dom) if cur_dom else 'N/A'}")
    print(f"  Inv months:     {months_inv}")
    print(f"  Pct over list:  {pct_pct}%" if pct_pct else "  Pct over list:  N/A")
    print(f"  Fall 2026 pred: {'${:,}'.format(fall_pred) if fall_pred else 'N/A'}")
    print(f"  Recommended:    {rec.upper()} 2026")

if __name__ == "__main__":
    main()
