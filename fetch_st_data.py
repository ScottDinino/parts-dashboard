"""
Fetches Purchase Order data from ServiceTitan API and saves to data/po_data.json
Run this locally or via GitHub Actions before building the dashboard.
"""
import requests
import json
import os
from datetime import datetime, timezone

TENANT_ID     = (os.environ.get("ST_TENANT_ID")     or "973792675").strip()
CLIENT_ID     = (os.environ.get("ST_CLIENT_ID")     or "cid.iuqpyeu1p6hablalzrq6jjzf1").strip()
CLIENT_SECRET = (os.environ.get("ST_CLIENT_SECRET") or "cs1.i6kdgrqq4dgx7nmf8lv791mwp3udwd37qu6rfbm6v3sphkmf0b").strip()
APP_KEY       = (os.environ.get("ST_APP_KEY")       or "ak1.mm0wsdj7a3lvfu46i30r7qpbe").strip()

BASE_URL = f"https://api.servicetitan.io/inventory/v2/tenant/{TENANT_ID}"


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


def main():
    print("Authenticating with ServiceTitan...")
    token = get_token()
    headers = get_headers(token)
    print("Token obtained.\n")

    # Fetch vendors
    print("Fetching vendors...")
    vendors_raw = fetch_all_pages(f"{BASE_URL}/vendors", headers)
    vendor_map = {v["id"]: v.get("name", "Unknown") for v in vendors_raw}
    print(f"  {len(vendor_map)} vendors loaded.\n")

    # Fetch POs from start of current year
    year = datetime.now(timezone.utc).year
    since = f"{year}-01-01T00:00:00Z"
    print(f"Fetching POs since {since}...")
    pos_raw = fetch_all_pages(f"{BASE_URL}/purchase-orders", headers, params={
        "createdOnOrAfter": since,
    })
    print(f"  {len(pos_raw)} POs loaded.\n")

    # Build clean PO records
    pos = []
    for po in pos_raw:
        vendor_name = vendor_map.get(po.get("vendorId"), "Unknown Vendor")
        items = []
        for item in po.get("items", []):
            items.append({
                "id": item.get("id"),
                "skuName": item.get("skuName", ""),
                "skuCode": item.get("skuCode", ""),
                "description": item.get("description", ""),
                "quantity": item.get("quantity", 0),
                "quantityReceived": item.get("quantityReceived", 0),
                "cost": item.get("cost", 0),
                "total": item.get("total", 0),
                "status": item.get("status", ""),
            })
        pos.append({
            "id": po["id"],
            "number": po.get("number", ""),
            "status": po.get("status", ""),
            "vendorId": po.get("vendorId"),
            "vendorName": vendor_name,
            "jobId": po.get("jobId"),
            "date": po.get("date", ""),
            "requiredOn": po.get("requiredOn", ""),
            "sentOn": po.get("sentOn"),
            "receivedOn": po.get("receivedOn"),
            "total": po.get("total", 0),
            "tax": po.get("tax", 0),
            "shipping": po.get("shipping", 0),
            "summary": po.get("summary", ""),
            "businessUnitId": po.get("businessUnitId"),
            "items": items,
        })

    output = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "vendorMap": vendor_map,
        "purchaseOrders": pos,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/po_data.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved {len(pos)} POs to data/po_data.json")
    print(f"Statuses: { {s: sum(1 for p in pos if p['status']==s) for s in set(p['status'] for p in pos)} }")


if __name__ == "__main__":
    main()
