#!/usr/bin/env python3
"""
Parts Dashboard Generator
Reads job data from ServiceTitan API export (data/jobs.json) and produces
a standalone HTML dashboard.  Run fetch_st_data.py first to refresh the data.
"""

import os
import json
from datetime import datetime, date, timedelta

JOBS_DATA_FILE = "data/jobs.json"
PO_DATA_FILE   = "data/po_data.json"
OUTPUT_FILE    = "index.html"

# Only show jobs from these business unit prefixes (change as needed)
ACTIVE_BU_PREFIXES = ("CS", "PLM")

SUPPLIERS = [
    "Baker Supply", "Carrier enterprise", "Gemaire", "Trane Supply",
    "Goodman distribution", "Lennox Supply",
]
STATUS_TAGS = {
    "parts received":           "Received",
    "parts ordered":            "Ordered",
    "need to order part (nto)": "NTO",
}


def get_status(tag_names):
    for tag in tag_names:
        tl = tag.lower()
        for kw, val in STATUS_TAGS.items():
            if kw in tl:
                return val
    return "Unknown"


def get_supplier(tag_names):
    for tag in tag_names:
        for s in SUPPLIERS:
            if s.lower() == tag.lower():
                return s
    return ""


def clean_tags(tag_names):
    """Return display tags — drop status/supplier tags, deduplicate."""
    skip_lower = set(STATUS_TAGS.keys()) | {s.lower() for s in SUPPLIERS}
    seen = set()
    result = []
    for tag in tag_names:
        tl = tag.lower()
        if tl in skip_lower:
            continue
        if tl not in seen:
            result.append(tag)
            seen.add(tl)
    return result


def days_label(delta):
    if delta < 0:
        return f"{abs(delta)}d overdue"
    elif delta == 0:
        return "TODAY"
    elif delta == 1:
        return "Tomorrow"
    else:
        return f"In {delta} days"


def load_data():
    """Load jobs from API JSON export. Returns (rows, today)."""
    today = date.today()

    if not os.path.exists(JOBS_DATA_FILE):
        print(f"  No job data found at {JOBS_DATA_FILE} — run fetch_st_data.py first.")
        return [], today

    with open(JOBS_DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    fetched_at = raw.get("fetchedAt", "")
    jobs_raw   = raw.get("jobs", [])
    print(f"  Loaded {len(jobs_raw)} jobs from API (fetched: {fetched_at[:10]})")

    rows = []
    for j in jobs_raw:
        job_num = str(j.get("jobNumber", "")).strip()
        if not job_num or len(job_num) < 7:
            continue

        bunit = j.get("businessUnit", "")
        if not bunit.upper().startswith(ACTIVE_BU_PREFIXES):
            continue

        tag_names = j.get("tagNames", [])
        status    = get_status(tag_names)
        supplier  = get_supplier(tag_names)
        extra_tags = clean_tags(tag_names)

        sched_str   = j.get("scheduledDate")   # "YYYY-MM-DD" or None
        created_str = j.get("createdOn")        # "YYYY-MM-DD" or None

        sched_date   = date.fromisoformat(sched_str)   if sched_str   else None
        created_date = date.fromisoformat(created_str) if created_str else None

        days_to_sched  = (sched_date   - today).days if sched_date   else None
        days_since_ord = (today - created_date).days if created_date else None

        rows.append({
            "job_num":        job_num,
            "customer":       j.get("customer", ""),
            "status":         status,
            "supplier":       supplier,
            "extra_tags":     extra_tags,
            "sched_date":     sched_date,
            "created_date":   created_date,
            "days_to_sched":  days_to_sched,
            "days_since_ord": days_since_ord,
            "revenue":        float(j.get("total", 0) or 0),
            "tech":           "",  # not available via current API credentials
            "bunit":          bunit,
        })

    print(f"  {len(rows)} valid jobs loaded.")
    return rows, today

def load_po_data():
    """Load purchase order data from ServiceTitan API export."""
    if not os.path.exists(PO_DATA_FILE):
        print(f"  No PO data found at {PO_DATA_FILE} — skipping.")
        return [], {}, ""
    with open(PO_DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    pos = raw.get("purchaseOrders", [])
    fetched_at = raw.get("fetchedAt", "")
    print(f"  Loaded {len(pos)} POs (fetched: {fetched_at[:10]})")

    # Build job_id → [POs] lookup (exclude canceled)
    # Match by jobId first, then fall back to PO number prefix (e.g. "587877885-001" → job "587877885")
    job_po_map = {}
    for po in pos:
        if po["status"] == "Canceled":
            continue
        job_id = None
        if po.get("jobId"):
            job_id = str(po["jobId"])
        elif po.get("number"):
            prefix = po["number"].split("-")[0]
            if len(prefix) >= 7:
                job_id = prefix
        if job_id:
            job_po_map.setdefault(job_id, []).append(po)

    linked = sum(1 for po in pos if po["status"] != "Canceled" and
                 (po.get("jobId") or (po.get("number") and len(po["number"].split("-")[0]) >= 7)))
    print(f"  {linked} POs linked to jobs ({len(job_po_map)} unique jobs)")
    return pos, job_po_map, fetched_at


def build_po_summary(pos):
    """Compute PO summary stats for the dashboard."""
    active_statuses = {"Pending", "Sent", "PartiallyReceived"}
    received_statuses = {"Received", "Exported"}

    # Vendor spend breakdown (exclude Canceled)
    vendor_spend = {}
    vendor_count = {}
    for po in pos:
        if po["status"] == "Canceled":
            continue
        v = po["vendorName"] or "Unknown"
        vendor_spend[v] = vendor_spend.get(v, 0) + (po["total"] or 0)
        vendor_count[v] = vendor_count.get(v, 0) + 1

    top_vendors = sorted(vendor_spend.items(), key=lambda x: -x[1])[:10]

    total_spend   = sum(po["total"] or 0 for po in pos if po["status"] != "Canceled")
    active_pos    = [po for po in pos if po["status"] in active_statuses]
    active_spend  = sum(po["total"] or 0 for po in active_pos)
    received_pos  = [po for po in pos if po["status"] in received_statuses]
    received_spend = sum(po["total"] or 0 for po in received_pos)
    canceled_count = sum(1 for po in pos if po["status"] == "Canceled")

    return {
        "total_spend":     total_spend,
        "active_spend":    active_spend,
        "received_spend":  received_spend,
        "active_count":    len(active_pos),
        "received_count":  len(received_pos),
        "canceled_count":  canceled_count,
        "total_count":     len(pos),
        "top_vendors":     top_vendors,
        "vendor_spend":    vendor_spend,
        "vendor_count":    vendor_count,
    }


def build_html(rows, today, pos=None, job_po_map=None, po_fetched_at=""):
    """Render the dashboard: summary tiles on top, one sortable table below."""
    pos = pos or []
    job_po_map = job_po_map or {}

    def get_job_pos(job_num):
        """Return list of POs linked to this job."""
        return job_po_map.get(str(job_num), [])

    def po_cost_for_job(job_num):
        """Total part cost across all POs for this job."""
        return sum(po["total"] or 0 for po in get_job_pos(job_num))

    # ── JSON payload — the table is rendered client-side from this ─────
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
        "po_cost":        po_cost_for_job(r["job_num"]),
        "po_count":       len(get_job_pos(r["job_num"])),
        "pos": [{
            "id":         po["id"],
            "number":     po.get("number", ""),
            "status":     po.get("status", ""),
            "typeName":   po.get("typeName", ""),
            "vendorName": po.get("vendorName", ""),
            "date":       (po.get("date") or "")[:10],
            "receivedOn": (po.get("receivedOn") or "")[:10],
            "total":      po.get("total") or 0,
            "parts": [
                {
                    "desc": (item.get("description") or item.get("skuName") or "").strip()[:70],
                    "qty":  item.get("quantity", 1),
                    "cost": item.get("cost") or 0,
                }
                for item in po.get("items", [])[:6]
            ],
        } for po in get_job_pos(r["job_num"])],
    } for r in rows])

    # ── Summary counts (tiles double as filters) ──────────────────────
    nto_count      = sum(1 for r in rows if r["status"] == "NTO")
    ordered_count  = sum(1 for r in rows if r["status"] == "Ordered")
    received_count = sum(1 for r in rows if r["status"] == "Received")
    overdue_count  = sum(1 for r in rows if r["days_to_sched"] is not None
                         and r["days_to_sched"] < 0 and r["status"] != "Received")
    today_count    = sum(1 for r in rows if r["days_to_sched"] == 0 and r["status"] != "Received")
    rev_pending    = sum(r["revenue"] for r in rows if r["status"] in ("NTO", "Ordered"))

    stamp = po_fetched_at[:16].replace("T", " ") if po_fetched_at else today.isoformat()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Parts Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:      #080b12;  --surface:  #0e1420;  --surface2: #131b2a;
  --border:  #1c2840;  --border2:  #243050;
  --text:    #e8edf5;  --text-2:   #8899b4;  --text-3:   #4a5878;
  --red:     #ef4444;  --orange:   #f97316;  --yellow:   #f59e0b;
  --green:   #22c55e;  --blue:     #3b82f6;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family:'Inter',-apple-system,sans-serif; background:var(--bg);
  color:var(--text); min-height:100vh; padding:24px; font-size:14px;
}}
.wrap {{ max-width:1500px; margin:0 auto; }}

/* ── Header ── */
header {{ margin-bottom:20px; }}
h1 {{
  font-size:24px; font-weight:800; letter-spacing:-.4px;
  background:linear-gradient(90deg,#e8edf5 0%,#93c5fd 100%);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  background-clip:text; display:inline-block;
}}
.sub {{ color:var(--text-3); font-size:12px; margin-top:4px; }}

/* ── Tiles ── */
.tiles {{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:10px; margin-bottom:18px;
}}
.tile {{
  background:var(--surface); border:1px solid var(--border);
  border-top:2px solid var(--c,var(--border2)); border-radius:12px;
  padding:14px 16px; cursor:pointer; transition:.15s;
}}
.tile:hover {{ background:var(--surface2); border-color:var(--border2); transform:translateY(-1px); }}
.tile.on {{ background:var(--surface2); box-shadow:0 0 0 1px var(--c,var(--blue)) inset; }}
.tile .v {{ font-size:26px; font-weight:800; color:var(--c,var(--text)); line-height:1.1; }}
.tile .l {{ font-size:11px; color:var(--text-2); font-weight:600; margin-top:3px; letter-spacing:.2px; }}

/* ── Controls ── */
.controls {{ display:flex; gap:10px; margin-bottom:12px; align-items:center; flex-wrap:wrap; }}
#q {{
  flex:1; min-width:220px; background:var(--surface); border:1px solid var(--border2);
  border-radius:9px; padding:10px 14px; color:var(--text); font-size:13px;
  font-family:inherit; outline:none;
}}
#q:focus {{ border-color:var(--blue); }}
#q::placeholder {{ color:var(--text-3); }}
.count {{ color:var(--text-3); font-size:12px; white-space:nowrap; }}
.clear {{
  background:var(--surface2); border:1px solid var(--border2); color:var(--text-2);
  border-radius:8px; padding:9px 14px; font-size:12px; cursor:pointer;
  font-family:inherit; font-weight:600;
}}
.clear:hover {{ color:var(--text); border-color:var(--blue); }}

/* ── Table ── */
.tbl-wrap {{
  background:var(--surface); border:1px solid var(--border);
  border-radius:14px; overflow:hidden;
}}
.scroll {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:1000px; }}
th {{
  text-align:left; font-size:11px; font-weight:700; color:var(--text-2);
  text-transform:uppercase; letter-spacing:.5px; padding:12px 14px;
  border-bottom:1px solid var(--border2); cursor:pointer;
  user-select:none; white-space:nowrap; background:var(--surface2);
}}
th:hover {{ color:var(--text); }}
th .arw {{ opacity:.35; margin-left:4px; font-size:9px; }}
th.sorted {{ color:var(--blue); }}
th.sorted .arw {{ opacity:1; }}
td {{ padding:11px 14px; border-bottom:1px solid var(--border); vertical-align:middle; }}
tr.job {{ cursor:pointer; transition:background .1s; }}
tr.job:hover {{ background:var(--surface2); }}
tr.job:last-child td {{ border-bottom:none; }}
.cust {{ font-weight:600; }}
.bu {{ color:var(--text-3); font-size:11px; }}
.muted {{ color:var(--text-3); }}
.jlink {{ color:var(--blue); text-decoration:none; font-weight:600; font-variant-numeric:tabular-nums; }}
.jlink:hover {{ text-decoration:underline; }}
.num {{ font-variant-numeric:tabular-nums; }}

.badge {{
  display:inline-block; padding:3px 9px; border-radius:20px;
  font-size:10px; font-weight:700; letter-spacing:.3px; white-space:nowrap;
}}
.b-nto      {{ background:rgba(249,115,22,.14); color:var(--orange); }}
.b-ordered  {{ background:rgba(59,130,246,.14); color:var(--blue); }}
.b-received {{ background:rgba(34,197,94,.14);  color:var(--green); }}
.b-unknown  {{ background:rgba(136,153,180,.12); color:var(--text-2); }}

.wait {{ font-weight:700; font-variant-numeric:tabular-nums; }}
.w-hot  {{ color:var(--red); }}
.w-warm {{ color:var(--orange); }}
.w-ok   {{ color:var(--text-2); }}
.sched-late {{ color:var(--red); font-weight:600; }}
.sched-now  {{ color:var(--yellow); font-weight:600; }}

/* ── Expanded PO detail ── */
tr.det > td {{ padding:0; background:#0a0f1a; }}
.det-in {{ padding:14px 18px; border-bottom:1px solid var(--border); }}
.po {{
  background:var(--surface); border:1px solid var(--border2); border-radius:10px;
  padding:12px 14px; margin-bottom:8px;
}}
.po:last-child {{ margin-bottom:0; }}
.po-h {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }}
.po-n {{ color:var(--blue); text-decoration:none; font-weight:700; font-size:12px; }}
.po-n:hover {{ text-decoration:underline; }}
.po-v {{ color:var(--text-2); font-size:12px; }}
.po-t {{ margin-left:auto; font-weight:700; font-variant-numeric:tabular-nums; }}
.part {{
  display:flex; gap:10px; font-size:12px; color:var(--text-2);
  padding:4px 0; border-top:1px dashed var(--border);
}}
.part .d {{ flex:1; }}
.part .q {{ color:var(--text-3); white-space:nowrap; }}
.no-po {{ color:var(--text-3); font-size:12px; font-style:italic; }}
.empty {{ padding:50px; text-align:center; color:var(--text-3); }}
@media (max-width:700px) {{ body {{ padding:12px; }} .tile .v {{ font-size:22px; }} }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>Parts Dashboard</h1>
  <div class="sub">RTR jobs on hold &middot; Coral Springs + Plumbing &middot; updated {stamp}</div>
</header>

<div class="tiles">
  <div class="tile" data-f="all"      style="--c:var(--text)"><div class="v">{len(rows)}</div><div class="l">All Jobs</div></div>
  <div class="tile" data-f="nto"      style="--c:var(--orange)"><div class="v">{nto_count}</div><div class="l">Need To Order</div></div>
  <div class="tile" data-f="ordered"  style="--c:var(--blue)"><div class="v">{ordered_count}</div><div class="l">Parts Ordered</div></div>
  <div class="tile" data-f="received" style="--c:var(--green)"><div class="v">{received_count}</div><div class="l">Parts Received</div></div>
  <div class="tile" data-f="overdue"  style="--c:var(--red)"><div class="v">{overdue_count}</div><div class="l">Overdue</div></div>
  <div class="tile" data-f="today"    style="--c:var(--yellow)"><div class="v">{today_count}</div><div class="l">Scheduled Today</div></div>
  <div class="tile" data-f="all"      style="--c:var(--text-2)"><div class="v">${rev_pending:,.0f}</div><div class="l">Revenue Pending</div></div>
</div>

<div class="controls">
  <input id="q" type="text" placeholder="Search customer, job number, vendor, part&hellip;" autocomplete="off">
  <button class="clear" onclick="resetAll()">Reset</button>
  <span class="count" id="cnt"></span>
</div>

<div class="tbl-wrap">
  <div class="scroll">
    <table>
      <thead><tr id="hdr"></tr></thead>
      <tbody id="body"></tbody>
    </table>
  </div>
</div>

</div>
<script>
const JOBS = {jobs_json};

// Columns: key = field to sort on, num = numeric sort, nulls sort last.
const COLS = [
  {{ key:'status',         label:'Status'    }},
  {{ key:'job_num',        label:'Job #'     }},
  {{ key:'customer',       label:'Customer'  }},
  {{ key:'days_since_ord', label:'Waiting',   num:true }},
  {{ key:'sched_date',     label:'Scheduled' }},
  {{ key:'supplier',       label:'Supplier'  }},
  {{ key:'po_count',       label:'POs',       num:true }},
  {{ key:'revenue',        label:'Revenue',   num:true }},
];

// Default: longest-waiting first — the page opens as an action list.
let sortKey = 'days_since_ord', sortDir = 'desc', filter = 'all', search = '', open_ = null;

const STATUS_RANK = {{ NTO:0, Ordered:1, Received:2, Unknown:3 }};

function money(n) {{ return '$' + (n || 0).toLocaleString('en-US', {{maximumFractionDigits:0}}); }}

function matchesFilter(j) {{
  if (filter === 'all')      return true;
  if (filter === 'nto')      return j.status === 'NTO';
  if (filter === 'ordered')  return j.status === 'Ordered';
  if (filter === 'received') return j.status === 'Received';
  if (filter === 'overdue')  return j.days_to_sched !== null && j.days_to_sched < 0 && j.status !== 'Received';
  if (filter === 'today')    return j.days_to_sched === 0 && j.status !== 'Received';
  return true;
}}

function matchesSearch(j) {{
  if (!search) return true;
  const hay = [
    j.customer, j.job_num, j.supplier, j.bunit, j.status,
    ...(j.extra_tags || []),
    ...(j.pos || []).flatMap(p => [p.vendorName, p.number, ...(p.parts || []).map(x => x.desc)])
  ].join(' ').toLowerCase();
  return hay.includes(search);
}}

function sortVal(j) {{
  if (sortKey === 'status') return STATUS_RANK[j.status] ?? 9;
  return j[sortKey];
}}

function visible() {{
  const out = JOBS.filter(j => matchesFilter(j) && matchesSearch(j));
  const dir = sortDir === 'asc' ? 1 : -1;
  // Blanks (null, undefined, empty string) always sort to the bottom,
  // whichever direction the column is sorted — an empty cell is never
  // the thing you clicked a column to see.
  const blank = v => v === null || v === undefined || v === '';
  out.sort((a, b) => {{
    const x = sortVal(a), y = sortVal(b);
    if (blank(x) && blank(y)) return 0;
    if (blank(x)) return 1;
    if (blank(y)) return -1;
    if (typeof x === 'string') return x.localeCompare(y) * dir;
    return (x - y) * dir;
  }});
  return out;
}}

function waitCls(d) {{ return d >= 14 ? 'w-hot' : d >= 7 ? 'w-warm' : 'w-ok'; }}

function schedCell(j) {{
  if (!j.sched_date) return '<span class="muted">&mdash;</span>';
  const d = j.days_to_sched;
  const nice = new Date(j.sched_date + 'T00:00:00')
    .toLocaleDateString('en-US', {{ month:'short', day:'numeric' }});
  if (d < 0 && j.status !== 'Received') return `<span class="sched-late">${{nice}} &middot; ${{Math.abs(d)}}d late</span>`;
  if (d === 0) return `<span class="sched-now">${{nice}} &middot; today</span>`;
  if (d === 1) return `<span class="sched-now">${{nice}} &middot; tomorrow</span>`;
  return `<span class="num">${{nice}}</span>`;
}}

function badge(s) {{
  const c = {{ NTO:'b-nto', Ordered:'b-ordered', Received:'b-received' }}[s] || 'b-unknown';
  return `<span class="badge ${{c}}">${{s}}</span>`;
}}

function poDetail(j) {{
  if (!j.pos || !j.pos.length) return '<div class="no-po">No purchase orders linked to this job.</div>';
  return j.pos.map(p => `
    <div class="po">
      <div class="po-h">
        <a class="po-n" href="https://go.servicetitan.com/#/Inventory/PurchaseOrder/View/${{p.id}}" target="_blank">PO #${{p.number}}</a>
        ${{badge(p.status === 'Received' || p.status === 'Exported' ? 'Received' : p.status === 'Pending' ? 'NTO' : 'Ordered')}}
        <span class="po-v">${{p.vendorName || 'Unknown vendor'}}${{p.typeName ? ' &middot; ' + p.typeName : ''}}</span>
        <span class="po-t">${{money(p.total)}}</span>
      </div>
      ${{(p.parts || []).map(x => `
        <div class="part"><span class="d">${{x.desc || 'Part'}}</span><span class="q">${{x.qty}} &times; ${{money(x.cost)}}</span></div>
      `).join('')}}
    </div>`).join('');
}}

function render() {{
  // Header
  document.getElementById('hdr').innerHTML = COLS.map(c => {{
    const on = c.key === sortKey;
    const arw = on ? (sortDir === 'asc' ? '&#9650;' : '&#9660;') : '&#9660;';
    return `<th class="${{on ? 'sorted' : ''}}" onclick="sortBy('${{c.key}}')">${{c.label}}<span class="arw">${{arw}}</span></th>`;
  }}).join('');

  const rows = visible();
  const body = document.getElementById('body');

  document.getElementById('cnt').textContent =
    rows.length === JOBS.length ? `${{JOBS.length}} jobs` : `${{rows.length}} of ${{JOBS.length}} jobs`;

  if (!rows.length) {{
    body.innerHTML = '<tr><td colspan="8"><div class="empty">No jobs match.</div></td></tr>';
    return;
  }}

  body.innerHTML = rows.map(j => {{
    const w = j.days_since_ord;
    const detail = open_ === j.job_num
      ? `<tr class="det"><td colspan="8"><div class="det-in">${{poDetail(j)}}</div></td></tr>` : '';
    return `
      <tr class="job" onclick="toggle('${{j.job_num}}')">
        <td>${{badge(j.status)}}</td>
        <td><a class="jlink" href="https://go.servicetitan.com/#/Job/Index/${{j.job_num}}" target="_blank" onclick="event.stopPropagation()">${{j.job_num}}</a></td>
        <td><div class="cust">${{j.customer || '&mdash;'}}</div><div class="bu">${{j.bunit || ''}}</div></td>
        <td>${{w === null ? '<span class="muted">&mdash;</span>' : `<span class="wait ${{waitCls(w)}}">${{w}}d</span>`}}</td>
        <td>${{schedCell(j)}}</td>
        <td class="muted">${{j.supplier || '&mdash;'}}</td>
        <td class="num">${{j.po_count ? j.po_count + ' &middot; ' + money(j.po_cost) : '<span class="muted">&mdash;</span>'}}</td>
        <td class="num">${{money(j.revenue)}}</td>
      </tr>${{detail}}`;
  }}).join('');
}}

function sortBy(k) {{
  if (sortKey === k) {{
    sortDir = sortDir === 'asc' ? 'desc' : 'asc';
  }} else {{
    sortKey = k;
    // Numbers are most useful high-first; text reads better A-Z.
    const col = COLS.find(c => c.key === k);
    sortDir = col && col.num ? 'desc' : 'asc';
  }}
  render();
}}

function toggle(n) {{ open_ = (open_ === n) ? null : n; render(); }}

function setFilter(f, el) {{
  filter = f;
  document.querySelectorAll('.tile').forEach(t => t.classList.remove('on'));
  if (f !== 'all' && el) el.classList.add('on');
  open_ = null;
  render();
}}

function resetAll() {{
  filter = 'all'; search = ''; open_ = null;
  document.getElementById('q').value = '';
  document.querySelectorAll('.tile').forEach(t => t.classList.remove('on'));
  render();
}}

document.querySelectorAll('.tile').forEach(t =>
  t.addEventListener('click', () => setFilter(t.dataset.f, t)));

document.getElementById('q').addEventListener('input', e => {{
  search = e.target.value.trim().toLowerCase();
  open_ = null;
  render();
}});

render();
</script>
</body>
</html>
"""


def main():
    print("Loading parts data...")
    rows, today = load_data()
    print(f"Found {len(rows)} jobs. Today is {today}")
    print("Loading PO data...")
    pos, job_po_map, po_fetched_at = load_po_data()
    html = build_html(rows, today, pos, job_po_map, po_fetched_at)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
