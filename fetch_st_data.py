"""
Fetches Job and Purchase Order data from ServiceTitan API.
Saves:
  data/jobs.json    — HC - Return to Repair jobs (Hold status)
  data/po_data.json — Purchase orders YTD

Run locally or via GitHub Actions before building the dashboard.
"""
import requests
import json
import os
import time
from datetime import datetime, timezone

TENANT_ID     = (os.environ.get("ST_TENANT_ID")     or "973792675").strip()
CLIENT_ID     = (os.environ.get("ST_CLIENT_ID")     or "cid.iuqpyeu1p6hablalzrq6jjzf1").strip()
CLIENT_SECRET = (os.environ.get("ST_CLIENT_SECRET") or "cs1.i6kdgrqq4dgx7nmf8lv791mwp3udwd37qu6rfbm6v3sphkmf0b").strip()
APP_KEY       = (os.environ.get("ST_APP_KEY")       or "ak1.mm0wsdj7a3lvfu46i30r7qpbe").strip()

INVENTORY_URL = f"https://api.servicetitan.io/inventory/v2/tenant/{TENANT_ID}"
JPM_URL       = f"https://api.servicetitan.io/jpm/v2/tenant/{TENANT_ID}"
ACCOUNTING_URL = f"https://api.servicetitan.io/accounting/v2/tenant/{TENANT_ID}"

RTR_JOB_TYPE_ID = 338261201  # HC - Return to Repair

# Tag ID → human-readable name (cross-referenced from historical Excel exports)
TAG_MAP = {
    85227503:  "Parts Received",
    85211127:  "Parts Ordered",
    85098865:  "Need to order part (NTO)",
    198955163: "Trane Supply",
    198955682: "Gemaire",
    198955800: "Carrier enterprise",
    198955925: "Goodman distribution",
    198973922: "Baker Supply",
    198952592: "Lennox Supply",
    91088839:  "Club Member",
    85052655:  "10-10-10",
    182987058: "10-Year Labor",
    182987112: "PLM",
    85227503:  "Parts Received",
    464609934: "Club Member 3 sys",
    586007079: "PSL Zone 4",
    99437300:  "5-YR Labor Warranty",
    99431657:  "2-YR Labor Warranty",
    182987059: "5 YEAR WARRANTY",
}


def get_token():
    resp = requests.post("https://auth.servicetitan.io/connect/token", data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "ST-App-Key": APP_KEY,
    }


def fetch_all_pages(url, headers, params=None):
    """Fetch all pages from a paginated endpoint."""
    results = []
    page = 1
    params = params or {}
    while True:
        params["page"] = page
        params["pageSize"] = 100
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("data", []))
        print(f"  Page {page}: {len(data.get('data', []))} records")
        if not data.get("hasMore"):
            break
        page += 1
    return results


def fetch_one(url, headers):
    """Fetch a single resource, return None on error."""
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Job fetching
# ---------------------------------------------------------------------------

def fetch_rtr_jobs(headers):
    """Fetch all HC - Return to Repair jobs with Hold status."""
    print("Fetching RTR Hold jobs...")
    jobs = fetch_all_pages(f"{JPM_URL}/jobs", headers, params={
        "jobTypeId": RTR_JOB_TYPE_ID,
        "jobStatus": "Hold",
    })
    print(f"  {len(jobs)} RTR Hold jobs loaded.\n")
    return jobs


def enrich_job(job, headers):
    """
    Add scheduled date (from last appointment) and customer/BU (from invoice).
    Returns an enriched job dict ready for the dashboard.
    """
    job_id     = job["id"]
    job_number = job.get("jobNumber", str(job_id))
    tag_ids    = list(set(job.get("tagTypeIds", [])))
    tag_names  = [TAG_MAP[tid] for tid in tag_ids if tid in TAG_MAP]

    # Scheduled date from last appointment
    sched_date = None
    appt_id = job.get("lastAppointmentId")
    if appt_id:
        appt = fetch_one(f"{JPM_URL}/appointments/{appt_id}", headers)
        if appt and appt.get("start"):
            try:
                sched_date = appt["start"][:10]  # "YYYY-MM-DD"
            except Exception:
                pass

    # Customer name and BU name from invoice
    customer = ""
    bunit    = ""
    inv_id = job.get("invoiceId")
    if inv_id:
        inv_data = fetch_one(
            f"{ACCOUNTING_URL}/invoices",
            headers,
        )
        # Use targeted single-id fetch via list endpoint
        resp = requests.get(
            f"{ACCOUNTING_URL}/invoices",
            headers=headers,
            params={"page": 1, "pageSize": 1, "ids": str(inv_id)},
        )
        if resp.status_code == 200 and resp.json().get("data"):
            inv = resp.json()["data"][0]
            customer = inv.get("customer", {}).get("name", "") or ""
            bunit    = (inv.get("businessUnit") or {}).get("name", "") or ""

    created_on = job.get("createdOn", "")
    created_date = created_on[:10] if created_on else None  # "YYYY-MM-DD"

    return {
        "id":           job_id,
        "jobNumber":    job_number,
        "jobStatus":    job.get("jobStatus", ""),
        "total":        job.get("total", 0),
        "createdOn":    created_date,
        "scheduledDate": sched_date,
        "tagNames":     tag_names,
        "customer":     customer,
        "businessUnit": bunit,
        "businessUnitId": job.get("businessUnitId"),
        "soldById":     job.get("soldById"),
        "invoiceId":    inv_id,
    }


def fetch_jobs_data(headers):
    """Fetch and enrich all RTR Hold jobs. Returns list of job dicts."""
    raw_jobs = fetch_rtr_jobs(headers)
    enriched = []
    total = len(raw_jobs)
    for i, job in enumerate(raw_jobs):
        print(f"  Enriching job {i+1}/{total}: {job.get('jobNumber','?')}")
        enriched.append(enrich_job(job, headers))
        # small delay to avoid rate limiting
        if i % 10 == 9:
            time.sleep(0.5)
    return enriched


# ---------------------------------------------------------------------------
# PO fetching (unchanged)
# ---------------------------------------------------------------------------

def fetch_po_data(headers):
    """Fetch vendors, PO types, and all YTD purchase orders."""
    print("Fetching vendors...")
    vendors_raw = fetch_all_pages(f"{INVENTORY_URL}/vendors", headers)
    vendor_map = {v["id"]: v.get("name", "Unknown") for v in vendors_raw}
    print(f"  {len(vendor_map)} vendors loaded.\n")

    print("Fetching PO types...")
    types_raw = fetch_all_pages(f"{INVENTORY_URL}/purchase-order-types", headers)
    po_type_map = {t["id"]: t.get("name", "").strip() for t in types_raw}
    print(f"  {len(po_type_map)} PO types loaded: {list(po_type_map.values())}\n")

    year = datetime.now(timezone.utc).year
    since = f"{year}-01-01T00:00:00Z"
    print(f"Fetching POs since {since}...")
    pos_raw = fetch_all_pages(f"{INVENTORY_URL}/purchase-orders", headers, params={
        "createdOnOrAfter": since,
    })
    print(f"  {len(pos_raw)} POs loaded.\n")

    pos = []
    for po in pos_raw:
        vendor_name = vendor_map.get(po.get("vendorId"), "Unknown Vendor")
        items = []
        for item in po.get("items", []):
            items.append({
                "id":               item.get("id"),
                "skuName":          item.get("skuName", ""),
                "skuCode":          item.get("skuCode", ""),
                "description":      item.get("description", ""),
                "quantity":         item.get("quantity", 0),
                "quantityReceived": item.get("quantityReceived", 0),
                "cost":             item.get("cost", 0),
                "total":            item.get("total", 0),
                "status":           item.get("status", ""),
            })
        pos.append({
            "id":             po["id"],
            "number":         po.get("number", ""),
            "status":         po.get("status", ""),
            "typeId":         po.get("typeId"),
            "typeName":       po_type_map.get(po.get("typeId"), ""),
            "vendorId":       po.get("vendorId"),
            "vendorName":     vendor_name,
            "jobId":          po.get("jobId"),
            "date":           po.get("date", ""),
            "requiredOn":     po.get("requiredOn", ""),
            "sentOn":         po.get("sentOn"),
            "receivedOn":     po.get("receivedOn"),
            "total":          po.get("total", 0),
            "tax":            po.get("tax", 0),
            "shipping":       po.get("shipping", 0),
            "summary":        po.get("summary", ""),
            "businessUnitId": po.get("businessUnitId"),
            "items":          items,
        })

    return pos, vendor_map, po_type_map


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Authenticating with ServiceTitan...")
    token = get_token()
    headers = get_headers(token)
    print("Token obtained.\n")

    os.makedirs("data", exist_ok=True)

    # --- Jobs ---
    print("=" * 50)
    print("JOBS")
    print("=" * 50)
    jobs = fetch_jobs_data(headers)

    jobs_output = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
    }
    with open("data/jobs.json", "w") as f:
        json.dump(jobs_output, f, indent=2)
    print(f"\nSaved {len(jobs)} jobs to data/jobs.json")

    status_counts = {}
    for j in jobs:
        for tag in j.get("tagNames", []):
            if tag in ("Parts Received", "Parts Ordered", "Need to order part (NTO)"):
                status_counts[tag] = status_counts.get(tag, 0) + 1
    print(f"Parts status breakdown: {status_counts}")

    # --- POs ---
    print("\n" + "=" * 50)
    print("PURCHASE ORDERS")
    print("=" * 50)
    pos, vendor_map, po_type_map = fetch_po_data(headers)

    po_output = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "vendorMap": vendor_map,
        "poTypeMap": po_type_map,
        "purchaseOrders": pos,
    }
    with open("data/po_data.json", "w") as f:
        json.dump(po_output, f, indent=2)
    print(f"Saved {len(pos)} POs to data/po_data.json")
    print(f"PO statuses: { {s: sum(1 for p in pos if p['status']==s) for s in set(p['status'] for p in pos)} }")


if __name__ == "__main__":
    main()
