#!/usr/bin/env python3
"""
Parts Dashboard Generator
Reads the Parts Report Excel and produces a standalone HTML dashboard.
Run this script any time you want a fresh dashboard.
"""

import openpyxl
import os
import json
from datetime import datetime, date, timedelta

EXCEL_PAST   = "data/parts_report_past.xlsx"
EXCEL_FUTURE = "data/parts_report_future.xlsx"
OUTPUT_FILE  = "index.html"

def get_status(tags_str):
    if not tags_str:
        return "Unknown"
    tags_lower = tags_str.lower()
    if "received" in tags_lower:
        return "Received"
    if "parts ordered" in tags_lower:
        return "Ordered"
    if "need to order" in tags_lower or "nto" in tags_lower:
        return "NTO"
    return "Unknown"

def get_supplier(tags_str):
    if not tags_str:
        return ""
    suppliers = ["Baker Supply", "Carrier enterprise", "Gemaire", "Trane Supply",
                 "Goodman distribution", "Baker Supply"]
    for s in suppliers:
        if s.lower() in tags_str.lower():
            return s
    return ""

def clean_tags(tags_str):
    if not tags_str:
        return []
    status_keywords = [
        "need to order part (nto)", "parts ordered", "received",
        "baker supply", "carrier enterprise", "gemaire", "trane supply",
        "goodman distribution"
    ]
    tags = [t.strip() for t in tags_str.split(",")]
    cleaned = []
    seen = set()
    for tag in tags:
        tl = tag.lower()
        skip = False
        for kw in status_keywords:
            if kw in tl:
                skip = True
                break
        if not skip and tl not in seen:
            cleaned.append(tag)
            seen.add(tl)
    return cleaned

def days_label(delta):
    if delta < 0:
        return f"{abs(delta)}d overdue"
    elif delta == 0:
        return "TODAY"
    elif delta == 1:
        return "Tomorrow"
    else:
        return f"In {delta} days"

def load_file(path, today, seen_jobs):
    """Load one Excel file and return a list of row dicts. Skips duplicate job numbers."""
    if not os.path.exists(path):
        print(f"  Skipping (not found): {path}")
        return []

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # skip header

        job_type = row[0]
        revenue  = float(row[1]) if row[1] else 0.0
        tags_str = str(row[2]).strip() if row[2] else ""
        job_num  = str(row[3]).strip() if row[3] else ""
        sched_dt = row[5]
        tech     = str(row[6]) if row[6] else ""
        sold_by  = str(row[8]) if row[8] else ""
        booked_by= str(row[11]) if row[11] else ""
        bunit    = str(row[14]) if row[14] else ""
        customer = str(row[15]) if row[15] else ""
        # Created Date was col 17 in old export — not present in new files
        created_dt = row[17] if len(row) > 17 else None

        if not job_num or not job_type:
            continue
        if job_num in seen_jobs:
            continue  # deduplicate across files
        seen_jobs.add(job_num)

        sched_date   = sched_dt.date()   if isinstance(sched_dt,   datetime) else sched_dt
        created_date = created_dt.date() if isinstance(created_dt, datetime) else None

        status     = get_status(tags_str)
        supplier   = get_supplier(tags_str)
        extra_tags = clean_tags(tags_str)

        days_to_sched  = (sched_date   - today).days if sched_date   else None
        days_since_ord = (today - created_date).days if created_date else None

        rows.append({
            "job_num":        job_num,
            "customer":       customer,
            "status":         status,
            "supplier":       supplier,
            "extra_tags":     extra_tags,
            "sched_date":     sched_date,
            "created_date":   created_date,
            "days_to_sched":  days_to_sched,
            "days_since_ord": days_since_ord,
            "revenue":        revenue,
            "tech":           tech,
            "sold_by":        sold_by,
            "booked_by":      booked_by,
            "bunit":          bunit,
        })

    print(f"  Loaded {len(rows)} rows from {os.path.basename(path)}")
    return rows


def load_data():
    today    = date.today()
    seen     = set()
    rows     = load_file(EXCEL_PAST,   today, seen)
    rows    += load_file(EXCEL_FUTURE, today, seen)
    print(f"  Total combined: {len(rows)} jobs")
    return rows, today

def build_html(rows, today):
    # ── JSON payload for JS filtering ─────────────────────────────────
    jobs_json = json.dumps([{
        "job_num":        r["job_num"],
        "customer":       r["customer"],
        "status":         r["status"],
        "supplier":       r["supplier"],
        "extra_tags":     r["extra_tags"],
        "sched_date":     r["sched_date"].isoformat()   if r["sched_date"]   else None,
        "created_date":   r["created_date"].isoformat() if r["created_date"] else None,
        "days_to_sched":  r["days_to_sched"],
        "days_since_ord": r["days_since_ord"],
        "revenue":        r["revenue"],
        "bunit":          r["bunit"],
        "sold_by":        r["sold_by"],
        "booked_by":      r["booked_by"],
    } for r in rows])

    # ── Summary counts ────────────────────────────────────────────────
    nto_count      = sum(1 for r in rows if r["status"] == "NTO")
    ordered_count  = sum(1 for r in rows if r["status"] == "Ordered")
    received_count = sum(1 for r in rows if r["status"] == "Received")
    overdue_count  = sum(1 for r in rows if r["days_to_sched"] is not None and r["days_to_sched"] < 0 and r["status"] != "Received")
    today_count    = sum(1 for r in rows if r["days_to_sched"] == 0 and r["status"] != "Received")
    tomorrow_count = sum(1 for r in rows if r["days_to_sched"] == 1 and r["status"] != "Received")
    rev_pending    = sum(r["revenue"] for r in rows if r["status"] in ("NTO", "Ordered"))
    rev_total      = sum(r["revenue"] for r in rows)

    # ── Timeline buckets ───────────────────────────────────────────────
    buckets = {}
    for r in rows:
        if r["status"] == "Received":
            continue
        d = r["sched_date"]
        if d not in buckets:
            buckets[d] = []
        buckets[d].append(r)
    sorted_dates = sorted(d for d in buckets if d is not None)

    # ── Chart data ─────────────────────────────────────────────────────
    chart_labels = [str(d) for d in sorted_dates]
    chart_data   = [len(buckets[d]) for d in sorted_dates]

    # ── Row HTML helpers ───────────────────────────────────────────────
    def status_badge(status):
        cls = {"NTO": "badge-nto", "Ordered": "badge-ordered", "Received": "badge-received"}.get(status, "badge-unknown")
        return f'<span class="badge {cls}">{status}</span>'

    def countdown_badge(days, status):
        if status == "Received":
            return '<span class="countdown received-tag">At Shop</span>'
        if days is None:
            return '<span class="countdown unknown">No Date</span>'
        if days < 0:
            return f'<span class="countdown overdue">{abs(days)}d OVERDUE</span>'
        if days == 0:
            return '<span class="countdown today">TODAY</span>'
        if days == 1:
            return '<span class="countdown tomorrow">Tomorrow</span>'
        if days <= 3:
            return f'<span class="countdown soon">In {days} days</span>'
        return f'<span class="countdown future">In {days} days</span>'

    def row_class(r):
        if r["status"] == "Received": return "row-received"
        d = r["days_to_sched"]
        if d is None: return ""
        if d < 0:  return "row-overdue"
        if d == 0: return "row-today"
        if d == 1: return "row-tomorrow"
        if d <= 3: return "row-soon"
        return ""

    # Build main table rows
    table_rows = ""
    sorted_rows = sorted(rows, key=lambda r: (
        r["sched_date"] if r["sched_date"] else date(9999,1,1),
        r["status"]
    ))
    for r in sorted_rows:
        tags_html = " ".join(f'<span class="tag">{t}</span>' for t in r["extra_tags"])
        created_str = r["created_date"].strftime("%m/%d/%y") if r["created_date"] else "—"
        sched_str   = r["sched_date"].strftime("%m/%d/%y")   if r["sched_date"]   else "—"
        age = f'{r["days_since_ord"]}d ago' if r["days_since_ord"] is not None else "—"
        table_rows += f"""
        <tr class="{row_class(r)}">
          <td><a href="https://go.servicetitan.com/#/Job/Index/{r['job_num']}" target="_blank" class="job-link">#{r['job_num']}</a></td>
          <td class="td-customer">{r['customer']}</td>
          <td>{status_badge(r['status'])}</td>
          <td class="td-supplier">{r['supplier'] or '—'}</td>
          <td>{created_str}<br><small class="muted">{age}</small></td>
          <td>{sched_str}</td>
          <td>{countdown_badge(r['days_to_sched'], r['status'])}</td>
          <td class="tags-cell">{tags_html}</td>
        </tr>"""

    # ── Customer Status Board ──────────────────────────────────────────
    def status_sort_key(r):
        order = {"NTO": 0, "Ordered": 1, "Received": 2, "Unknown": 3}
        return (order.get(r["status"], 3), -(r["days_since_ord"] or 0))

    status_rows = ""
    for r in sorted(rows, key=status_sort_key):
        created_str = r["created_date"].strftime("%m/%d/%y") if r["created_date"] else "—"
        sched_str   = r["sched_date"].strftime("%m/%d/%y")   if r["sched_date"]   else "—"
        wait_days   = r["days_since_ord"] or 0
        wait_hrs    = wait_days * 24
        wait_str    = f"{wait_days}d ({wait_hrs}h)" if wait_days > 0 else "Today"
        late_cls    = " wait-critical" if wait_days >= 2 else (" wait-warn" if wait_days == 1 else "")
        status_rows += f"""
        <tr>
          <td>{r['customer']}</td>
          <td><a href="https://go.servicetitan.com/#/Job/Index/{r['job_num']}" target="_blank" class="job-link">#{r['job_num']}</a></td>
          <td>{status_badge(r['status'])}</td>
          <td>{r['supplier'] or '—'}</td>
          <td>{created_str}</td>
          <td>{sched_str}</td>
          <td>{countdown_badge(r['days_to_sched'], r['status'])}</td>
          <td><span class="wait-pill{late_cls}">{wait_str}</span></td>
        </tr>"""

    # ── No Air Section ─────────────────────────────────────────────────
    no_air_rows = [r for r in rows if r["status"] != "Received" and (r["days_since_ord"] or 0) >= 2]
    no_air_rows.sort(key=lambda r: -(r["days_since_ord"] or 0))
    no_air_count = len(no_air_rows)

    no_air_cards = ""
    for r in no_air_rows:
        wait_days = r["days_since_ord"] or 0
        wait_hrs  = wait_days * 24
        created_str = r["created_date"].strftime("%m/%d/%y") if r["created_date"] else "—"
        sched_str   = r["sched_date"].strftime("%m/%d/%y")   if r["sched_date"]   else "No Date"
        urgency_cls = "noair-critical" if wait_days >= 5 else ("noair-urgent" if wait_days >= 3 else "noair-warn")
        no_air_cards += f"""
        <div class="noair-card {urgency_cls}">
          <div class="noair-wait-row">
            <div class="noair-wait">{wait_days}</div>
            <div class="noair-wait-unit">days</div>
          </div>
          <div class="noair-hrs">{wait_hrs} hours without A/C</div>
          <div class="noair-divider"></div>
          <div class="noair-customer">{r['customer']}</div>
          <div class="noair-job">
            <a href="https://go.servicetitan.com/#/Job/Index/{r['job_num']}" target="_blank" class="job-link">#{r['job_num']}</a>
            {status_badge(r['status'])}
          </div>
          <div class="noair-detail"><span>Ordered {created_str}</span><span>·</span>{countdown_badge(r['days_to_sched'], r['status'])}</div>
          {'<div class="noair-supplier">📦 ' + r['supplier'] + '</div>' if r['supplier'] else ''}
        </div>"""

    if not no_air_cards:
        no_air_cards = '<div style="color:#64748b; font-size:14px; padding:16px 0;">No customers have been waiting longer than 48 hours.</div>'

    # ── Timeline: original row view ────────────────────────────────────
    timeline_html = ""
    for d in sorted_dates:
        day_rows = buckets[d]
        delta = (d - today).days
        if delta < 0:
            label = f'<span class="tl-label overdue">{d.strftime("%a %b %d")} — {abs(delta)}d OVERDUE</span>'
            tl_cls = "tl-overdue"
        elif delta == 0:
            label = f'<span class="tl-label today">TODAY — {d.strftime("%a %b %d")}</span>'
            tl_cls = "tl-today"
        elif delta == 1:
            label = f'<span class="tl-label tomorrow">TOMORROW — {d.strftime("%a %b %d")}</span>'
            tl_cls = "tl-tomorrow"
        else:
            label = f'<span class="tl-label future">{d.strftime("%A, %b %d")}</span>'
            tl_cls = "tl-future"

        cards = ""
        for r in sorted(day_rows, key=lambda x: x["status"]):
            sup_html = f'<div class="card-supplier">{r["supplier"]}</div>' if r["supplier"] else ""
            cards += f"""
            <div class="tl-card {tl_cls}">
              <div class="card-top">
                <span class="card-job">#{r['job_num']}</span>
                {status_badge(r['status'])}
              </div>
              <div class="card-customer">{r['customer']}</div>
              {sup_html}
            </div>"""

        timeline_html += f"""
        <div class="tl-group">
          <div class="tl-header">{label} <span class="tl-divider"></span><span class="tl-count">{len(day_rows)} job{'s' if len(day_rows)!=1 else ''}</span></div>
          <div class="tl-cards">{cards}</div>
        </div>"""

    # ── Timeline: swimlane / kanban view ───────────────────────────────
    swimlane_cols = ""
    for d in sorted_dates:
        day_rows = buckets[d]
        delta = (d - today).days

        if delta < 0:
            col_cls   = "sl-col-overdue"
            day_label = f'<span class="sl-day-badge sl-badge-overdue">{abs(delta)}d OVERDUE</span>'
        elif delta == 0:
            col_cls   = "sl-col-today"
            day_label = '<span class="sl-day-badge sl-badge-today">TODAY</span>'
        elif delta == 1:
            col_cls   = "sl-col-tomorrow"
            day_label = '<span class="sl-day-badge sl-badge-tomorrow">TOMORROW</span>'
        elif delta <= 4:
            col_cls   = "sl-col-soon"
            day_label = f'<span class="sl-day-badge sl-badge-soon">In {delta}d</span>'
        else:
            col_cls   = "sl-col-future"
            day_label = f'<span class="sl-day-badge sl-badge-future">In {delta}d</span>'

        col_cards = ""
        for r in sorted(day_rows, key=lambda x: ({"NTO":0,"Ordered":1,"Received":2}.get(x["status"],3))):
            wait = r["days_since_ord"] or 0
            wait_html = ""
            if wait >= 2:
                w_cls = "sl-card-wait-crit" if wait >= 5 else ("sl-card-wait-urgent" if wait >= 3 else "sl-card-wait-warn")
                wait_html = f'<div class="sl-card-wait {w_cls}">{wait}d waiting</div>'
            sup = f'<div class="sl-card-sup">📦 {r["supplier"]}</div>' if r["supplier"] else ""
            col_cards += f"""
            <div class="sl-card">
              <div class="sl-card-top">
                {status_badge(r['status'])}
                <a href="https://go.servicetitan.com/#/Job/Index/{r['job_num']}" target="_blank" class="job-link">#{r['job_num']}</a>
              </div>
              <div class="sl-card-customer">{r['customer']}</div>
              {sup}
              {wait_html}
            </div>"""

        swimlane_cols += f"""
        <div class="sl-col {col_cls}">
          <div class="sl-col-header">
            <div class="sl-col-dayname">{d.strftime("%a")}</div>
            <div class="sl-col-date">{d.strftime("%b %d")}</div>
            <div class="sl-col-meta">{day_label} <span class="sl-col-count">{len(day_rows)}</span></div>
          </div>
          <div class="sl-col-body">{col_cards}</div>
        </div>"""

    generated = datetime.now().strftime("%m/%d/%Y %I:%M %p")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Parts Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg:          #080b12;
  --surface:     #0e1420;
  --surface2:    #131b2a;
  --border:      #1c2840;
  --border2:     #243050;
  --text:        #e8edf5;
  --text-2:      #8899b4;
  --text-3:      #4a5878;
  --red:         #ef4444;
  --red-dim:     #7f1d1d;
  --orange:      #f97316;
  --orange-dim:  #7c2d12;
  --yellow:      #f59e0b;
  --yellow-dim:  #78350f;
  --green:       #22c55e;
  --green-dim:   #14532d;
  --blue:        #3b82f6;
  --blue-dim:    #1e3a5f;
  --purple:      #a78bfa;
  --purple-dim:  #312e81;
  --cyan:        #22d3ee;
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Inter', -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}

/* ── SCROLLBAR ───────────────────────────────────── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: var(--bg); }}
::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 3px; }}

/* ── HEADER ──────────────────────────────────────── */
.header {{
  position: relative; overflow: hidden;
  background: linear-gradient(135deg, #0d1526 0%, #111e35 50%, #0d1526 100%);
  border-bottom: 1px solid var(--border);
  padding: 28px 40px;
}}
.header::before {{
  content: '';
  position: absolute; inset: 0;
  background: radial-gradient(ellipse 60% 80% at 80% 50%, rgba(59,130,246,.08) 0%, transparent 70%);
  pointer-events: none;
}}
.header-inner {{ position: relative; max-width: 1440px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; }}
.header-left h1 {{
  font-size: 22px; font-weight: 800; letter-spacing: -.3px;
  background: linear-gradient(90deg, #e8edf5 0%, #93c5fd 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}}
.header-left .sub {{ color: var(--text-3); font-size: 12px; margin-top: 5px; font-weight: 500; }}
.header-right {{ display: flex; align-items: center; gap: 10px; }}
.header-pill {{
  background: var(--surface2); border: 1px solid var(--border2);
  border-radius: 99px; padding: 6px 14px;
  font-size: 12px; font-weight: 600; color: var(--text-2);
}}

/* ── CONTAINER ───────────────────────────────────── */
.container {{ max-width: 1440px; margin: 0 auto; padding: 32px 40px; }}

/* ── STAT CARDS ──────────────────────────────────── */
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 14px; margin-bottom: 36px; }}
.stat-card {{
  position: relative; overflow: hidden;
  background: var(--surface); border-radius: 16px;
  padding: 20px 22px; border: 1px solid var(--border);
  transition: transform .2s, border-color .2s;
}}
.stat-card:hover {{ transform: translateY(-2px); border-color: var(--border2); }}
.stat-card::after {{
  content: ''; position: absolute; bottom: -30px; right: -20px;
  width: 90px; height: 90px; border-radius: 50%;
  opacity: .07; pointer-events: none;
}}
.stat-card .s-icon {{ font-size: 20px; margin-bottom: 12px; display: block; }}
.stat-card .label {{ font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .1em; color: var(--text-3); margin-bottom: 6px; }}
.stat-card .value {{ font-size: 40px; font-weight: 900; line-height: 1; letter-spacing: -1px; }}
.stat-card .delta {{ font-size: 11px; color: var(--text-3); margin-top: 6px; }}

.stat-nto      {{ border-top: 2px solid var(--orange); }}
.stat-nto      .value {{ color: var(--orange); }}
.stat-nto::after {{ background: var(--orange); }}

.stat-ordered  {{ border-top: 2px solid var(--blue); }}
.stat-ordered  .value {{ color: var(--blue); }}
.stat-ordered::after {{ background: var(--blue); }}

.stat-received {{ border-top: 2px solid var(--green); }}
.stat-received .value {{ color: var(--green); }}
.stat-received::after {{ background: var(--green); }}

.stat-overdue  {{ border-top: 2px solid var(--red); }}
.stat-overdue  .value {{ color: var(--red); }}
.stat-overdue::after {{ background: var(--red); }}

.stat-today    {{ border-top: 2px solid var(--yellow); }}
.stat-today    .value {{ color: var(--yellow); }}
.stat-today::after {{ background: var(--yellow); }}

.stat-tomorrow {{ border-top: 2px solid var(--purple); }}
.stat-tomorrow .value {{ color: var(--purple); }}
.stat-tomorrow::after {{ background: var(--purple); }}

.stat-total    {{ border-top: 2px solid var(--cyan); }}
.stat-total    .value {{ color: var(--cyan); }}
.stat-total::after {{ background: var(--cyan); }}

.stat-rev      {{ border-top: 2px solid #34d399; }}
.stat-rev      .value {{ color: #34d399; font-size: 28px; letter-spacing: -1px; }}
.stat-rev::after {{ background: #34d399; }}
.stat-rev.tile-active {{ box-shadow: 0 0 0 2px #34d399; }}

/* ── SECTION TITLE ───────────────────────────────── */
.section-title {{
  display: flex; align-items: center; gap: 10px;
  font-size: 13px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--text-2); margin-bottom: 18px; margin-top: 40px;
}}
.section-title::after {{
  content: ''; flex: 1; height: 1px;
  background: linear-gradient(90deg, var(--border2) 0%, transparent 100%);
}}

/* ── CHART ───────────────────────────────────────── */
.chart-wrap {{
  background: var(--surface); border-radius: 16px;
  padding: 24px; border: 1px solid var(--border);
  height: 240px; margin-bottom: 0;
}}

/* ── NTO ALERT ───────────────────────────────────── */
.alert-box {{
  background: linear-gradient(135deg, #2d1407 0%, #1f0d03 100%);
  border: 1px solid #b45309;
  border-radius: 14px; padding: 18px 22px; margin-bottom: 28px;
  display: flex; align-items: center; gap: 16px;
  box-shadow: 0 0 30px rgba(249,115,22,.08);
}}
.alert-box .alert-icon {{ font-size: 32px; flex-shrink: 0; }}
.alert-box .alert-text h3 {{ color: #fdba74; font-size: 15px; font-weight: 800; }}
.alert-box .alert-text p  {{ color: #92400e; font-size: 13px; margin-top: 4px; font-weight: 500; }}
.alert-box.hidden {{ display: none; }}

/* ── BADGES ──────────────────────────────────────── */
.badge {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10px; font-weight: 700; padding: 3px 9px;
  border-radius: 99px; text-transform: uppercase; letter-spacing: .06em;
  border: 1px solid transparent;
}}
.badge-nto      {{ background: rgba(249,115,22,.15); color: #fb923c; border-color: rgba(249,115,22,.3); }}
.badge-ordered  {{ background: rgba(59,130,246,.15);  color: #60a5fa; border-color: rgba(59,130,246,.3); }}
.badge-received {{ background: rgba(34,197,94,.15);   color: #4ade80; border-color: rgba(34,197,94,.3); }}
.badge-unknown  {{ background: rgba(100,116,139,.15); color: #94a3b8; border-color: rgba(100,116,139,.3); }}

/* ── COUNTDOWN PILL ──────────────────────────────── */
.countdown {{
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 700; padding: 4px 10px;
  border-radius: 8px; white-space: nowrap; letter-spacing: .02em;
}}
.countdown.overdue      {{ background: rgba(239,68,68,.15);   color: #fca5a5; border: 1px solid rgba(239,68,68,.3); }}
.countdown.today        {{ background: rgba(245,158,11,.15);  color: #fde68a; border: 1px solid rgba(245,158,11,.3); }}
.countdown.tomorrow     {{ background: rgba(167,139,250,.15); color: #c4b5fd; border: 1px solid rgba(167,139,250,.3); }}
.countdown.soon         {{ background: rgba(59,130,246,.15);  color: #93c5fd; border: 1px solid rgba(59,130,246,.3); }}
.countdown.future       {{ background: var(--surface2); color: var(--text-3); border: 1px solid var(--border); }}
.countdown.received-tag {{ background: rgba(34,197,94,.15);   color: #86efac; border: 1px solid rgba(34,197,94,.3); }}
.countdown.unknown      {{ background: var(--surface2); color: var(--text-3); border: 1px solid var(--border); }}

/* ── TIMELINE ────────────────────────────────────── */
.tl-group {{ margin-bottom: 24px; }}
.tl-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }}
.tl-label {{
  font-size: 12px; font-weight: 800; padding: 5px 14px;
  border-radius: 99px; letter-spacing: .05em; text-transform: uppercase; border: 1px solid transparent;
}}
.tl-label.overdue  {{ background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.3); }}
.tl-label.today    {{ background: rgba(245,158,11,.15); color: #fde68a; border-color: rgba(245,158,11,.3); }}
.tl-label.tomorrow {{ background: rgba(167,139,250,.15); color: #c4b5fd; border-color: rgba(167,139,250,.3); }}
.tl-label.future   {{ background: rgba(59,130,246,.1); color: #93c5fd; border-color: rgba(59,130,246,.2); }}
.tl-divider {{ flex: 1; height: 1px; background: var(--border); }}
.tl-count {{
  font-size: 11px; font-weight: 600; color: var(--text-3);
  background: var(--surface2); border: 1px solid var(--border); border-radius: 99px; padding: 2px 10px;
}}
.tl-cards {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.tl-card {{
  background: var(--surface); border-radius: 12px;
  padding: 14px 16px; min-width: 190px; max-width: 240px;
  border: 1px solid var(--border); position: relative; overflow: hidden;
  transition: transform .15s, border-color .15s;
}}
.tl-card:hover {{ transform: translateY(-2px); border-color: var(--border2); }}
.tl-card::before {{
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
}}
.tl-card.tl-overdue::before  {{ background: var(--red); }}
.tl-card.tl-today::before    {{ background: var(--yellow); }}
.tl-card.tl-tomorrow::before {{ background: var(--purple); }}
.tl-card.tl-future::before   {{ background: var(--blue); }}
.card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }}
.card-job {{ font-size: 11px; font-weight: 700; color: var(--text-3); font-family: 'SF Mono', 'Fira Code', monospace; }}
.card-customer {{ font-size: 13px; font-weight: 700; color: var(--text); line-height: 1.3; }}
.card-supplier {{ font-size: 11px; color: var(--text-3); margin-top: 5px; font-weight: 500; }}

/* ── NO AIR ──────────────────────────────────────── */
.noair-banner {{
  background: linear-gradient(135deg, #1f0505 0%, #120303 100%);
  border: 1px solid rgba(239,68,68,.4);
  border-radius: 14px; padding: 16px 22px; margin-bottom: 20px;
  display: flex; align-items: center; gap: 14px;
  box-shadow: 0 0 40px rgba(239,68,68,.08);
}}
.noair-banner .nb-icon {{ font-size: 28px; flex-shrink: 0; }}
.noair-banner .nb-text h3 {{ color: #fca5a5; font-size: 15px; font-weight: 800; }}
.noair-banner .nb-text p  {{ color: rgba(252,165,165,.5); font-size: 12px; margin-top: 3px; }}
.noair-banner.hidden {{ display: none; }}

.noair-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-bottom: 0; }}

.noair-card {{
  border-radius: 16px; padding: 20px; position: relative; overflow: hidden;
  border: 1px solid var(--border); transition: transform .2s;
}}
.noair-card:hover {{ transform: translateY(-3px); }}

.noair-card.noair-warn {{
  background: linear-gradient(145deg, #1a1400 0%, #0e1420 100%);
  border-color: rgba(245,158,11,.3);
  box-shadow: 0 0 20px rgba(245,158,11,.06);
}}
.noair-card.noair-urgent {{
  background: linear-gradient(145deg, #1a0e00 0%, #0e1420 100%);
  border-color: rgba(249,115,22,.4);
  box-shadow: 0 0 24px rgba(249,115,22,.1);
}}
.noair-card.noair-critical {{
  background: linear-gradient(145deg, #1a0000 0%, #0e1420 100%);
  border-color: rgba(239,68,68,.5);
  box-shadow: 0 0 30px rgba(239,68,68,.12);
}}
.noair-card.noair-critical .noair-wait {{ animation: pulse-red 2s ease-in-out infinite; }}

@keyframes pulse-red {{
  0%, 100% {{ opacity: 1; }}
  50%       {{ opacity: .65; }}
}}

.noair-card::before {{
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; border-radius: 16px 16px 0 0;
}}
.noair-card.noair-warn::before     {{ background: linear-gradient(90deg, var(--yellow), transparent); }}
.noair-card.noair-urgent::before   {{ background: linear-gradient(90deg, var(--orange), transparent); }}
.noair-card.noair-critical::before {{ background: linear-gradient(90deg, var(--red), transparent); }}

.noair-wait-row {{ display: flex; align-items: baseline; gap: 6px; margin-bottom: 4px; }}
.noair-wait {{ font-size: 48px; font-weight: 900; line-height: 1; letter-spacing: -2px; }}
.noair-card.noair-warn     .noair-wait {{ color: var(--yellow); }}
.noair-card.noair-urgent   .noair-wait {{ color: var(--orange); }}
.noair-card.noair-critical .noair-wait {{ color: var(--red); }}
.noair-wait-unit {{ font-size: 16px; font-weight: 700; color: var(--text-3); padding-bottom: 4px; }}
.noair-hrs {{ font-size: 12px; color: var(--text-3); font-weight: 500; margin-bottom: 10px; }}
.noair-divider {{ height: 1px; background: var(--border); margin: 10px 0; }}
.noair-customer {{ font-size: 14px; font-weight: 800; color: var(--text); margin-bottom: 5px; line-height: 1.3; }}
.noair-job {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
.noair-detail {{ font-size: 11px; color: var(--text-3); margin-top: 4px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-weight: 500; }}
.noair-supplier {{ font-size: 11px; color: var(--text-2); margin-top: 6px; font-weight: 600; }}

/* ── TABLES ──────────────────────────────────────── */
.table-wrap {{
  background: var(--surface); border-radius: 16px;
  border: 1px solid var(--border); overflow: auto; margin-bottom: 0;
}}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead th {{
  background: var(--surface2); padding: 13px 16px;
  text-align: left; font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .08em;
  color: var(--text-3); border-bottom: 1px solid var(--border);
  white-space: nowrap; position: sticky; top: 0; z-index: 1;
}}
tbody tr {{ border-bottom: 1px solid var(--border); transition: background .12s; }}
tbody tr:last-child {{ border-bottom: none; }}
tbody tr:hover {{ background: rgba(255,255,255,.03); }}
tbody td {{ padding: 12px 16px; vertical-align: middle; }}

.row-overdue  {{ background: rgba(239,68,68,.05); }}
.row-today    {{ background: rgba(245,158,11,.05); }}
.row-tomorrow {{ background: rgba(167,139,250,.05); }}
.row-soon     {{ background: rgba(59,130,246,.03); }}
.row-received {{ opacity: .5; }}

.td-customer {{ font-weight: 600; color: var(--text); }}
.td-supplier {{ font-weight: 600; color: var(--text-2); font-size: 12px; }}
.job-link {{ color: var(--blue); text-decoration: none; font-family: 'SF Mono','Fira Code',monospace; font-size: 11px; font-weight: 700; }}
.job-link:hover {{ color: #93c5fd; text-decoration: underline; }}
.muted {{ color: var(--text-3); font-size: 11px; font-weight: 500; }}
.tags-cell {{ max-width: 260px; }}
.tag {{
  display: inline-block; background: var(--surface2);
  color: var(--text-3); font-size: 10px; font-weight: 500;
  padding: 2px 7px; border-radius: 5px; margin: 2px 2px 2px 0;
  border: 1px solid var(--border);
}}

.wait-pill         {{ font-size: 12px; font-weight: 600; color: var(--text-3); }}
.wait-pill.wait-warn     {{ color: var(--yellow); }}
.wait-pill.wait-critical {{ color: var(--red); font-weight: 800; }}

/* ── DONUT CLUSTER ───────────────────────────────── */
.top-grid {{ display: grid; grid-template-columns: 1fr 340px; gap: 20px; align-items: start; margin-bottom: 0; }}
@media (max-width: 900px) {{ .top-grid {{ grid-template-columns: 1fr; }} }}
.donut-wrap {{
  background: var(--surface); border-radius: 16px;
  padding: 24px; border: 1px solid var(--border);
  height: 240px; display: flex; flex-direction: column;
}}
.donut-wrap canvas {{ flex: 1; }}
.donut-legend {{ display: flex; flex-direction: column; gap: 10px; }}
.dl-item {{ display: flex; align-items: center; gap: 10px; }}
.dl-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
.dl-label {{ font-size: 12px; font-weight: 600; color: var(--text-2); flex: 1; }}
.dl-val {{ font-size: 14px; font-weight: 800; }}

/* ── TILE INTERACTIVITY ──────────────────────────── */
.stat-card {{ cursor: pointer; }}
.stat-card .tile-hint {{
  font-size: 10px; font-weight: 600; color: var(--text-3);
  margin-top: 10px; opacity: 0; transition: opacity .2s;
  text-transform: uppercase; letter-spacing: .06em;
}}
.stat-card:hover .tile-hint {{ opacity: 1; }}
.stat-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 30px rgba(0,0,0,.3); }}
.stat-card.tile-active {{
  box-shadow: 0 0 0 2px currentColor;
  transform: translateY(-3px);
}}
.stat-nto.tile-active      {{ box-shadow: 0 0 0 2px var(--orange); }}
.stat-ordered.tile-active  {{ box-shadow: 0 0 0 2px var(--blue); }}
.stat-received.tile-active {{ box-shadow: 0 0 0 2px var(--green); }}
.stat-overdue.tile-active  {{ box-shadow: 0 0 0 2px var(--red); }}
.stat-today.tile-active    {{ box-shadow: 0 0 0 2px var(--yellow); }}
.stat-tomorrow.tile-active {{ box-shadow: 0 0 0 2px var(--purple); }}
.stat-total.tile-active    {{ box-shadow: 0 0 0 2px var(--cyan); }}

/* ── FILTER PANEL ────────────────────────────────── */
.fp-header {{
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 16px;
}}
.fp-title {{
  font-size: 15px; font-weight: 800; color: var(--text);
  display: flex; align-items: center; gap: 10px;
}}
.fp-close {{
  background: var(--surface2); border: 1px solid var(--border);
  color: var(--text-3); border-radius: 8px; padding: 6px 14px;
  font-size: 12px; font-weight: 700; cursor: pointer;
  font-family: 'Inter', sans-serif; transition: all .15s;
}}
.fp-close:hover {{ border-color: var(--border2); color: var(--text); }}

.fp-cards {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}}
.fp-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 18px 20px;
  transition: transform .15s, border-color .15s;
  position: relative; overflow: hidden;
}}
.fp-card:hover {{ transform: translateY(-2px); border-color: var(--border2); }}
.fp-card::before {{
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
}}
.fp-card.fc-nto::before      {{ background: var(--orange); }}
.fp-card.fc-ordered::before  {{ background: var(--blue); }}
.fp-card.fc-received::before {{ background: var(--green); }}
.fp-card.fc-overdue::before  {{ background: var(--red); }}
.fp-card.fc-today::before    {{ background: var(--yellow); }}
.fp-card.fc-tomorrow::before {{ background: var(--purple); }}
.fp-card.fc-rev::before      {{ background: #34d399; }}

.fp-card-top {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 10px; }}
.fp-customer {{ font-size: 16px; font-weight: 800; color: var(--text); line-height: 1.2; }}
.fp-job-link {{
  color: var(--blue); text-decoration: none; font-family: 'SF Mono','Fira Code',monospace;
  font-size: 11px; font-weight: 700; white-space: nowrap;
  background: var(--surface2); border: 1px solid var(--border);
  padding: 3px 8px; border-radius: 6px;
}}
.fp-job-link:hover {{ color: #93c5fd; border-color: var(--border2); }}

.fp-badges {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }}

.fp-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.fp-field {{ background: var(--surface2); border-radius: 8px; padding: 8px 10px; border: 1px solid var(--border); }}
.fp-field-label {{ font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--text-3); margin-bottom: 3px; }}
.fp-field-value {{ font-size: 13px; font-weight: 700; color: var(--text); }}
.fp-field-value.accent-orange {{ color: var(--orange); }}
.fp-field-value.accent-red    {{ color: var(--red); }}
.fp-field-value.accent-green  {{ color: var(--green); }}
.fp-field-value.accent-yellow {{ color: var(--yellow); }}
.fp-field-value.accent-purple {{ color: var(--purple); }}
.fp-field-value.accent-blue   {{ color: var(--blue); }}

.fp-tags {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 4px; }}
.fp-bunit {{ font-size: 11px; color: var(--text-3); font-weight: 500; margin-top: 10px; }}
.fp-sold {{ font-size: 11px; color: var(--text-3); font-weight: 500; margin-top: 3px; }}

.fp-empty {{
  grid-column: 1/-1; text-align: center;
  padding: 40px; color: var(--text-3); font-size: 14px; font-weight: 600;
}}

/* ── VIEW TOGGLE ─────────────────────────────────── */
.view-toggle {{ display: flex; gap: 6px; margin-bottom: 18px; }}
.vt-btn {{
  display: flex; align-items: center; gap: 7px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 8px 16px;
  font-size: 12px; font-weight: 700; color: var(--text-3);
  cursor: pointer; transition: all .18s; font-family: 'Inter', sans-serif;
  letter-spacing: .02em;
}}
.vt-btn:hover {{ border-color: var(--border2); color: var(--text-2); }}
.vt-btn.active {{
  background: var(--blue-dim); border-color: rgba(59,130,246,.5);
  color: #93c5fd;
}}
.vt-btn .vt-icon {{ font-size: 14px; }}

/* ── SWIMLANE ────────────────────────────────────── */
.swimlane-wrap {{
  overflow-x: auto; overflow-y: visible;
  padding-bottom: 12px;
  /* custom scrollbar */
  scrollbar-width: thin;
  scrollbar-color: var(--border2) transparent;
}}
.swimlane-wrap::-webkit-scrollbar {{ height: 5px; }}
.swimlane-wrap::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 3px; }}

.swimlane {{
  display: flex; gap: 12px;
  align-items: flex-start;
  min-width: max-content;
  padding: 2px 2px 4px;
}}

.sl-col {{
  width: 210px; flex-shrink: 0;
  border-radius: 14px; border: 1px solid var(--border);
  background: var(--surface); overflow: hidden;
  display: flex; flex-direction: column;
}}

.sl-col-overdue  {{ border-color: rgba(239,68,68,.35); background: rgba(239,68,68,.04); }}
.sl-col-today    {{ border-color: rgba(245,158,11,.35); background: rgba(245,158,11,.04); }}
.sl-col-tomorrow {{ border-color: rgba(167,139,250,.3); background: rgba(167,139,250,.03); }}
.sl-col-soon     {{ border-color: rgba(59,130,246,.25); background: rgba(59,130,246,.03); }}
.sl-col-future   {{ border-color: var(--border); }}

.sl-col-header {{
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--border);
  position: relative;
}}
.sl-col-overdue  .sl-col-header {{ border-bottom-color: rgba(239,68,68,.2); }}
.sl-col-today    .sl-col-header {{ border-bottom-color: rgba(245,158,11,.2); }}
.sl-col-tomorrow .sl-col-header {{ border-bottom-color: rgba(167,139,250,.2); }}
.sl-col-soon     .sl-col-header {{ border-bottom-color: rgba(59,130,246,.2); }}

.sl-col-dayname {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: var(--text-3); margin-bottom: 2px; }}
.sl-col-date    {{ font-size: 20px; font-weight: 900; letter-spacing: -.5px; color: var(--text); margin-bottom: 8px; }}
.sl-col-overdue  .sl-col-date {{ color: var(--red); }}
.sl-col-today    .sl-col-date {{ color: var(--yellow); }}
.sl-col-tomorrow .sl-col-date {{ color: var(--purple); }}
.sl-col-soon     .sl-col-date {{ color: var(--blue); }}

.sl-col-meta {{ display: flex; align-items: center; justify-content: space-between; }}
.sl-day-badge {{
  font-size: 9px; font-weight: 800; padding: 3px 8px;
  border-radius: 99px; text-transform: uppercase; letter-spacing: .07em;
  border: 1px solid transparent;
}}
.sl-badge-overdue  {{ background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.3); }}
.sl-badge-today    {{ background: rgba(245,158,11,.15); color: #fde68a; border-color: rgba(245,158,11,.3); }}
.sl-badge-tomorrow {{ background: rgba(167,139,250,.15); color: #c4b5fd; border-color: rgba(167,139,250,.3); }}
.sl-badge-soon     {{ background: rgba(59,130,246,.15); color: #93c5fd; border-color: rgba(59,130,246,.3); }}
.sl-badge-future   {{ background: var(--surface2); color: var(--text-3); border-color: var(--border); }}

.sl-col-count {{
  font-size: 11px; font-weight: 800; color: var(--text-3);
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 99px; width: 22px; height: 22px;
  display: inline-flex; align-items: center; justify-content: center;
}}

.sl-col-body {{ padding: 10px; display: flex; flex-direction: column; gap: 8px; }}

.sl-card {{
  background: var(--surface2); border-radius: 10px;
  padding: 11px 12px; border: 1px solid var(--border);
  transition: transform .15s, border-color .15s;
  cursor: default;
}}
.sl-card:hover {{ transform: translateY(-2px); border-color: var(--border2); }}
.sl-card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; }}
.sl-card-customer {{ font-size: 13px; font-weight: 700; color: var(--text); line-height: 1.3; margin-bottom: 4px; }}
.sl-card-sup {{ font-size: 10px; color: var(--text-3); font-weight: 500; margin-top: 4px; }}
.sl-card-wait {{
  display: inline-block; margin-top: 7px;
  font-size: 10px; font-weight: 800; padding: 2px 8px;
  border-radius: 99px; letter-spacing: .04em;
}}
.sl-card-wait-warn   {{ background: rgba(245,158,11,.15); color: #fde68a; border: 1px solid rgba(245,158,11,.3); }}
.sl-card-wait-urgent {{ background: rgba(249,115,22,.15); color: #fdba74; border: 1px solid rgba(249,115,22,.3); }}
.sl-card-wait-crit   {{ background: rgba(239,68,68,.15);  color: #fca5a5; border: 1px solid rgba(239,68,68,.3); }}
</style>
</head>
<body>

<!-- ── HEADER ────────────────────────────────────── -->
<div class="header">
  <div class="header-inner">
    <div class="header-left">
      <h1>Parts Dashboard</h1>
      <div class="sub">Nick &amp; Max &nbsp;·&nbsp; {today.strftime("%A, %B %d, %Y")} &nbsp;·&nbsp; Generated {generated}</div>
    </div>
    <div class="header-right">
      <span class="header-pill">{len(rows)} Total Jobs</span>
      {'<span class="header-pill" style="color:#fb923c;border-color:rgba(249,115,22,.4)">⚠ ' + str(nto_count) + ' NTO</span>' if nto_count > 0 else ''}
      {'<span class="header-pill" style="color:#fca5a5;border-color:rgba(239,68,68,.4)">🔥 ' + str(no_air_count) + ' No Air 48h+</span>' if no_air_count > 0 else ''}
    </div>
  </div>
</div>

<div class="container">

<!-- ── NTO ALERT ─────────────────────────────────── -->
<div class="alert-box{'  hidden' if nto_count == 0 else ''}">
  <div class="alert-icon">⚠️</div>
  <div class="alert-text">
    <h3>{nto_count} Part{'s' if nto_count!=1 else ''} Need to Be Ordered Right Now</h3>
    <p>Order today → arrives next day. Every hour counts for these customers.</p>
  </div>
</div>

<!-- ── STAT CARDS ─────────────────────────────────── -->
<div class="stats-grid">
  <div class="stat-card stat-nto"      onclick="filterJobs('nto')"      title="Click to view NTO jobs">
    <span class="s-icon">📦</span>
    <div class="label">Need to Order</div>
    <div class="value">{nto_count}</div>
    <div class="delta">Unordered parts</div>
    <div class="tile-hint">Click to view →</div>
  </div>
  <div class="stat-card stat-ordered"  onclick="filterJobs('ordered')"  title="Click to view ordered jobs">
    <span class="s-icon">🚚</span>
    <div class="label">Parts Ordered</div>
    <div class="value">{ordered_count}</div>
    <div class="delta">In transit</div>
    <div class="tile-hint">Click to view →</div>
  </div>
  <div class="stat-card stat-received" onclick="filterJobs('received')" title="Click to view received jobs">
    <span class="s-icon">✅</span>
    <div class="label">At Shop</div>
    <div class="value">{received_count}</div>
    <div class="delta">Ready to install</div>
    <div class="tile-hint">Click to view →</div>
  </div>
  <div class="stat-card stat-overdue"  onclick="filterJobs('overdue')"  title="Click to view overdue jobs">
    <span class="s-icon">🚨</span>
    <div class="label">Overdue</div>
    <div class="value">{overdue_count}</div>
    <div class="delta">Past scheduled date</div>
    <div class="tile-hint">Click to view →</div>
  </div>
  <div class="stat-card stat-today"    onclick="filterJobs('today')"    title="Click to view today's arrivals">
    <span class="s-icon">📬</span>
    <div class="label">Arriving Today</div>
    <div class="value">{today_count}</div>
    <div class="delta">Expected delivery</div>
    <div class="tile-hint">Click to view →</div>
  </div>
  <div class="stat-card stat-tomorrow" onclick="filterJobs('tomorrow')" title="Click to view tomorrow's arrivals">
    <span class="s-icon">📅</span>
    <div class="label">Tomorrow</div>
    <div class="value">{tomorrow_count}</div>
    <div class="delta">Next-day arrivals</div>
    <div class="tile-hint">Click to view →</div>
  </div>
  <div class="stat-card stat-total"    onclick="filterJobs('all')"      title="Click to view all jobs">
    <span class="s-icon">🗂</span>
    <div class="label">Total Jobs</div>
    <div class="value">{len(rows)}</div>
    <div class="delta">On hold for parts</div>
    <div class="tile-hint">Click to view →</div>
  </div>
  <div class="stat-card stat-rev"      onclick="filterJobs('pending_rev')" title="Click to view jobs with pending revenue">
    <span class="s-icon">💰</span>
    <div class="label">Rev Pending</div>
    <div class="value rev-value">${rev_pending:,.0f}</div>
    <div class="delta">NTO + Ordered jobs</div>
    <div class="tile-hint">Click to view →</div>
  </div>
</div>

<!-- ── FILTER PANEL ────────────────────────────────── -->
<div id="filter-panel" style="display:none; margin-bottom:36px;">
  <div class="fp-header">
    <div class="fp-title" id="fp-title"></div>
    <button class="fp-close" onclick="closeFilter()">✕ Close</button>
  </div>
  <div id="fp-cards" class="fp-cards"></div>
</div>

<!-- ── CHART + DONUT ──────────────────────────────── -->
<div class="section-title">Delivery Schedule</div>
<div class="top-grid">
  <div class="chart-wrap">
    <canvas id="dateChart"></canvas>
  </div>
  <div style="display:flex;flex-direction:column;gap:12px;">
    <div style="background:var(--surface);border-radius:16px;padding:20px;border:1px solid var(--border);flex:1;">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-3);margin-bottom:14px;">Parts Status Split</div>
      <canvas id="donutChart" height="150"></canvas>
    </div>
  </div>
</div>

<!-- ── TIMELINE ───────────────────────────────────── -->
<div class="section-title">Arrival Timeline</div>

<div class="view-toggle">
  <button class="vt-btn active" id="btn-rows" onclick="setView('rows')">
    <span class="vt-icon">☰</span> Row View
  </button>
  <button class="vt-btn" id="btn-lanes" onclick="setView('lanes')">
    <span class="vt-icon">⬛</span> Lane View
  </button>
</div>

<div id="view-rows">
  {timeline_html}
</div>

<div id="view-lanes" style="display:none;">
  <div class="swimlane-wrap">
    <div class="swimlane">
      {swimlane_cols}
    </div>
  </div>
</div>

<!-- ── NO AIR ─────────────────────────────────────── -->
<div class="section-title">No Air — Waiting 48+ Hours</div>
<div class="noair-banner{'  hidden' if no_air_count == 0 else ''}">
  <div class="nb-icon">🔥</div>
  <div class="nb-text">
    <h3>{no_air_count} customer{'s are' if no_air_count!=1 else ' is'} without A/C for 2+ days — needs immediate attention</h3>
    <p>Sorted by longest wait. Critical (5d+) cards pulse red.</p>
  </div>
</div>
<div class="noair-grid">
  {no_air_cards}
</div>

<!-- ── CUSTOMER STATUS BOARD ──────────────────────── -->
<div class="section-title">Customer Status Board</div>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Customer</th>
        <th>Job #</th>
        <th>Status</th>
        <th>Supplier</th>
        <th>Ordered</th>
        <th>Sched Date</th>
        <th>Countdown</th>
        <th>Waiting</th>
      </tr>
    </thead>
    <tbody>
      {status_rows}
    </tbody>
  </table>
</div>

<!-- ── FULL DETAIL TABLE ──────────────────────────── -->
<div class="section-title">All Jobs — Full Detail</div>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Job #</th>
        <th>Customer</th>
        <th>Status</th>
        <th>Supplier</th>
        <th>Ordered Date</th>
        <th>Sched Date</th>
        <th>Countdown</th>
        <th>Tags</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</div>

<div style="height:48px;"></div>
</div><!-- /container -->

<script>
/* ── JOB DATA ──────────────────────────────────── */
const JOBS = {jobs_json};
const TODAY = '{today.isoformat()}';

/* ── TILE FILTER ───────────────────────────────── */
let activeFilter = null;

const FILTER_META = {{
  nto:      {{ label: '📦 Need to Order',      cls: 'fc-nto',      color: '#f97316' }},
  ordered:  {{ label: '🚚 Parts Ordered',       cls: 'fc-ordered',  color: '#3b82f6' }},
  received: {{ label: '✅ Received — At Shop',  cls: 'fc-received', color: '#22c55e' }},
  overdue:  {{ label: '🚨 Overdue',             cls: 'fc-overdue',  color: '#ef4444' }},
  today:    {{ label: '📬 Arriving Today',      cls: 'fc-today',    color: '#f59e0b' }},
  tomorrow: {{ label: '📅 Arriving Tomorrow',   cls: 'fc-tomorrow', color: '#a78bfa' }},
  all:         {{ label: '🗂 All Jobs',              cls: '',              color: '#22d3ee' }},
  pending_rev: {{ label: '💰 Revenue Pending',       cls: 'fc-rev',        color: '#34d399' }},
}};

function applyFilter(key, job) {{
  if (key === 'all')      return true;
  if (key === 'nto')      return job.status === 'NTO';
  if (key === 'ordered')  return job.status === 'Ordered';
  if (key === 'received') return job.status === 'Received';
  if (key === 'overdue')  return job.status !== 'Received' && job.days_to_sched !== null && job.days_to_sched < 0;
  if (key === 'today')    return job.status !== 'Received' && job.days_to_sched === 0;
  if (key === 'tomorrow')    return job.status !== 'Received' && job.days_to_sched === 1;
  if (key === 'pending_rev') return (job.status === 'NTO' || job.status === 'Ordered') && job.revenue > 0;
  return false;
}}

function fmtDate(iso) {{
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-US', {{month:'short', day:'numeric', year:'2-digit'}});
}}

function countdown(days, status) {{
  if (status === 'Received') return ['At Shop', 'accent-green'];
  if (days === null)  return ['No Date', ''];
  if (days < 0)  return [`${{Math.abs(days)}}d Overdue`, 'accent-red'];
  if (days === 0) return ['TODAY', 'accent-yellow'];
  if (days === 1) return ['Tomorrow', 'accent-purple'];
  if (days <= 3)  return [`In ${{days}} days`, 'accent-blue'];
  return [`In ${{days}} days`, ''];
}}

function waitLabel(days) {{
  if (!days || days === 0) return ['Ordered today', ''];
  const hrs = days * 24;
  if (days >= 5) return [`${{days}}d / ${{hrs}}h`, 'accent-red'];
  if (days >= 3) return [`${{days}}d / ${{hrs}}h`, 'accent-orange'];
  if (days >= 2) return [`${{days}}d / ${{hrs}}h`, 'accent-yellow'];
  return [`${{days}}d`, ''];
}}

function badgeHTML(status) {{
  const map = {{
    NTO:      ['badge-nto',      'NTO'],
    Ordered:  ['badge-ordered',  'Ordered'],
    Received: ['badge-received', 'Received'],
  }};
  const [cls, label] = map[status] || ['badge-unknown', status];
  return `<span class="badge ${{cls}}">${{label}}</span>`;
}}

function renderCards(key) {{
  const filtered = JOBS.filter(j => applyFilter(key, j));
  const meta = FILTER_META[key];
  const container = document.getElementById('fp-cards');

  if (filtered.length === 0) {{
    container.innerHTML = `<div class="fp-empty">No jobs match this filter.</div>`;
    return;
  }}

  // sort: overdue first, then by sched date, then by wait time desc
  filtered.sort((a, b) => {{
    if (a.days_to_sched !== null && b.days_to_sched !== null) return a.days_to_sched - b.days_to_sched;
    if (a.days_to_sched === null) return 1;
    if (b.days_to_sched === null) return -1;
    return 0;
  }});

  container.innerHTML = filtered.map(job => {{
    const [cdLabel, cdCls] = countdown(job.days_to_sched, job.status);
    const [waitLbl, waitCls] = waitLabel(job.days_since_ord);
    const tags = (job.extra_tags || []).map(t => `<span class="tag">${{t}}</span>`).join('');
    const supplier = job.supplier ? `<span class="tag" style="color:var(--text-2);border-color:var(--border2)">${{job.supplier}}</span>` : '';
    const bunit = job.bunit ? `<div class="fp-bunit">🏢 ${{job.bunit}}</div>` : '';
    const soldBy = job.sold_by ? `<div class="fp-sold">👤 Sold by ${{job.sold_by}}</div>` : '';

    return `
    <div class="fp-card ${{meta.cls}}">
      <div class="fp-card-top">
        <div class="fp-customer">${{job.customer}}</div>
        <a href="https://go.servicetitan.com/#/Job/Index/${{job.job_num}}" target="_blank" class="fp-job-link">#${{job.job_num}}</a>
      </div>
      <div class="fp-badges">
        ${{badgeHTML(job.status)}}      </div>
      <div class="fp-grid">
        <div class="fp-field">
          <div class="fp-field-label">Ordered</div>
          <div class="fp-field-value">${{fmtDate(job.created_date)}}</div>
        </div>
        <div class="fp-field">
          <div class="fp-field-label">Scheduled</div>
          <div class="fp-field-value">${{fmtDate(job.sched_date)}}</div>
        </div>
        <div class="fp-field">
          <div class="fp-field-label">Countdown</div>
          <div class="fp-field-value ${{cdCls}}">${{cdLabel}}</div>
        </div>
        <div class="fp-field">
          <div class="fp-field-label">Waiting</div>
          <div class="fp-field-value ${{waitCls}}">${{waitLbl}}</div>
        </div>
${{job.revenue > 0 ? `
        <div class="fp-field" style="grid-column:1/-1;border-color:rgba(52,211,153,.25);background:rgba(52,211,153,.06)">
          <div class="fp-field-label" style="color:#6ee7b7">Revenue</div>
          <div class="fp-field-value" style="color:#34d399;font-size:16px">${{job.revenue.toLocaleString('en-US',{{style:'currency',currency:'USD'}})}}</div>
        </div>` : ''}}
      </div>
      <div class="fp-tags">${{supplier}}${{tags}}</div>
      ${{bunit}}
      ${{soldBy}}
    </div>`;
  }}).join('');
}}

function filterJobs(key) {{
  const panel = document.getElementById('filter-panel');
  const titleEl = document.getElementById('fp-title');
  const meta = FILTER_META[key];

  // toggle off if clicking same tile
  if (activeFilter === key) {{
    closeFilter();
    return;
  }}

  activeFilter = key;

  // update tile highlights
  document.querySelectorAll('.stat-card').forEach(c => c.classList.remove('tile-active'));
  const tileMap = {{nto:'stat-nto', ordered:'stat-ordered', received:'stat-received',
                    overdue:'stat-overdue', today:'stat-today', tomorrow:'stat-tomorrow',
                    all:'stat-total', pending_rev:'stat-rev'}};
  const tileEl = document.querySelector('.' + tileMap[key]);
  if (tileEl) tileEl.classList.add('tile-active');

  const filtered = JOBS.filter(j => applyFilter(key, j));
  const totalRev = filtered.reduce((s, j) => s + (j.revenue || 0), 0);
  const revNote = totalRev > 0
    ? ` <span style="color:#34d399;font-weight:700;font-size:13px;">· ${{totalRev.toLocaleString('en-US',{{style:'currency',currency:'USD',maximumFractionDigits:0}})}}</span>`
    : '';
  titleEl.innerHTML = `${{meta.label}}${{revNote}} <span style="color:var(--text-3);font-weight:500;font-size:12px;margin-left:8px;">— click tile again to close</span>`;
  renderCards(key);
  panel.style.display = '';

  // smooth scroll to panel
  setTimeout(() => panel.scrollIntoView({{behavior: 'smooth', block: 'start'}}), 50);
}}

function closeFilter() {{
  activeFilter = null;
  document.getElementById('filter-panel').style.display = 'none';
  document.querySelectorAll('.stat-card').forEach(c => c.classList.remove('tile-active'));
}}

/* ── VIEW TOGGLE ───────────────────────────────── */
function setView(v) {{
  document.getElementById('view-rows').style.display  = v === 'rows'  ? '' : 'none';
  document.getElementById('view-lanes').style.display = v === 'lanes' ? '' : 'none';
  document.getElementById('btn-rows').classList.toggle('active',  v === 'rows');
  document.getElementById('btn-lanes').classList.toggle('active', v === 'lanes');
  localStorage.setItem('tl-view', v);
}}
// restore last choice
(function() {{ const s = localStorage.getItem('tl-view'); if (s) setView(s); }})();

const todayStr = '{today.isoformat()}';

/* ── BAR CHART ─────────────────────────────────── */
const barLabels = {chart_labels};
const barData   = {chart_data};

const barColors = barLabels.map(l => {{
  if (l < todayStr) return 'rgba(239,68,68,0.75)';
  if (l === todayStr) return 'rgba(245,158,11,0.85)';
  const diff = (new Date(l) - new Date(todayStr)) / 86400000;
  if (diff === 1) return 'rgba(167,139,250,0.8)';
  if (diff <= 3) return 'rgba(59,130,246,0.75)';
  return 'rgba(34,211,238,0.5)';
}});

new Chart(document.getElementById('dateChart').getContext('2d'), {{
  type: 'bar',
  data: {{
    labels: barLabels.map(l => {{
      const d = new Date(l + 'T00:00:00');
      return d.toLocaleDateString('en-US', {{weekday:'short', month:'short', day:'numeric'}});
    }}),
    datasets: [{{
      label: 'Jobs',
      data: barData,
      backgroundColor: barColors,
      borderRadius: 8,
      borderSkipped: false,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#0e1420',
        borderColor: '#1c2840',
        borderWidth: 1,
        titleColor: '#e8edf5',
        bodyColor: '#8899b4',
        callbacks: {{ label: c => ` ${{c.raw}} job${{c.raw !== 1 ? 's' : ''}}` }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ color: '#1c2840' }}, ticks: {{ color: '#4a5878', font: {{ size: 11, family: 'Inter' }} }} }},
      y: {{ grid: {{ color: '#1c2840' }}, ticks: {{ color: '#4a5878', stepSize: 1, font: {{ size: 11 }} }}, beginAtZero: true }}
    }}
  }}
}});

/* ── DONUT CHART ───────────────────────────────── */
const nto = {nto_count}, ordered = {ordered_count}, received = {received_count};
new Chart(document.getElementById('donutChart').getContext('2d'), {{
  type: 'doughnut',
  data: {{
    labels: ['Need to Order', 'Ordered', 'Received'],
    datasets: [{{
      data: [nto, ordered, received],
      backgroundColor: ['rgba(249,115,22,.8)', 'rgba(59,130,246,.8)', 'rgba(34,197,94,.8)'],
      borderColor: ['#f97316', '#3b82f6', '#22c55e'],
      borderWidth: 1,
      hoverOffset: 6,
    }}]
  }},
  options: {{
    responsive: true,
    cutout: '68%',
    plugins: {{
      legend: {{
        position: 'bottom',
        labels: {{ color: '#8899b4', font: {{ size: 11, family: 'Inter' }}, padding: 12, boxWidth: 10, boxHeight: 10 }}
      }},
      tooltip: {{
        backgroundColor: '#0e1420',
        borderColor: '#1c2840',
        borderWidth: 1,
        titleColor: '#e8edf5',
        bodyColor: '#8899b4',
      }}
    }}
  }}
}});
</script>

</body>
</html>"""
    return html


def main():
    print("Loading parts data...")
    rows, today = load_data()
    print(f"Found {len(rows)} jobs. Today is {today}")
    html = build_html(rows, today)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
