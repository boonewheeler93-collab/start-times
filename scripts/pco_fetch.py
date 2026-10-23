#!/usr/bin/env python3
"""Read the next Weekend and SWITCH plans from Planning Center Services and save them to planning.json.

Runs in GitHub Actions with the PCO_APP_ID and PCO_SECRET repository secrets. Read-only: it never changes
anything in Planning Center.
"""
import base64, datetime, json, os, re, sys, urllib.parse, urllib.request

API = "https://api.planningcenteronline.com/services/v2"
APP_ID, SECRET = os.environ.get("PCO_APP_ID", ""), os.environ.get("PCO_SECRET", "")
AUTH = "Basic " + base64.b64encode(f"{APP_ID}:{SECRET}".encode()).decode()

# which service types to read: matched by name (case-insensitive); the SWITCH id is from its Church Center links
WANT = {
    "weekend": {"names": ["northland | weekend", "northland weekend"], "id": None},
    "switch": {"names": ["switch"], "id": "1069572"},
}


def get(path, params=None):
    url = path if path.startswith("http") else API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": AUTH, "User-Agent": "start-times-weekly"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_all(path, params=None):
    out, inc, data = [], [], get(path, params)
    while True:
        out += data.get("data", [])
        inc += data.get("included", [])
        nxt = (data.get("links") or {}).get("next")
        if not nxt:
            return out, inc
        data = get(nxt)


def find_type(key):
    w = WANT[key]
    types, _ = get_all("/service_types", {"per_page": 100})
    print(f"[{key}] service types visible to this token:")
    for t in types:
        print("   ", t["id"], "-", t["attributes"].get("name"))
    if w["id"] and any(t["id"] == w["id"] for t in types):
        return next(t for t in types if t["id"] == w["id"])
    for t in types:
        nm = (t["attributes"].get("name") or "").lower()
        if any(n in nm for n in w["names"]):
            return t
    return None


def next_plan(type_id):
    since = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    plans, _ = get_all(f"/service_types/{type_id}/plans", {"filter": "after", "after": since, "order": "sort_date", "per_page": 5})
    return plans[0] if plans else None


def plan_detail(type_id, plan):
    pid = plan["id"]
    items, inc = get_all(f"/service_types/{type_id}/plans/{pid}/items", {"include": "item_notes,song,arrangement,key", "per_page": 100})
    notes = {}
    for x in inc:
        if x["type"] == "ItemNote":
            iid = ((x.get("relationships") or {}).get("item") or {}).get("data", {}) or {}
            notes.setdefault(iid.get("id"), []).append({"category": x["attributes"].get("category_name"), "content": x["attributes"].get("content")})
    # item notes aren't always linked back from the include, so fetch them per item when missing
    out, section = [], ""
    for it in sorted(items, key=lambda i: i["attributes"].get("sequence") or 0):
        a = it["attributes"]
        if a.get("item_type") == "header":
            section = a.get("title") or ""
            continue
        nn = notes.get(it["id"])
        if nn is None:
            try:
                raw, _ = get_all(f"/service_types/{type_id}/plans/{pid}/items/{it['id']}/item_notes")
                nn = [{"category": n["attributes"].get("category_name"), "content": n["attributes"].get("content")} for n in raw]
            except Exception as e:  # keep going; notes are a bonus
                print("   notes failed for", a.get("title"), e)
                nn = []
        out.append({
            "title": a.get("title"), "type": a.get("item_type"), "section": section,
            "length": a.get("length"), "position": a.get("service_position"),
            "description": a.get("description"), "key": a.get("key_name"),
            "notes": nn,
            # only songs and the walk-in have a leader; other items use "+" for bullet points
            "lead": find_lead(a.get("description"), nn) if (a.get("item_type") == "song" or re.match(r"\s*walk-?in", a.get("title") or "", re.I)) else None,
        })
    times, _ = get_all(f"/service_types/{type_id}/plans/{pid}/plan_times")
    return {
        "plan_id": pid, "title": plan["attributes"].get("title"), "series": plan["attributes"].get("series_title"),
        "dates": plan["attributes"].get("dates"), "sort_date": plan["attributes"].get("sort_date"),
        "times": sorted([t["attributes"].get("starts_at") for t in times if t["attributes"].get("time_type") == "service"]),
        "items": out,
    }


def find_lead(desc, notes):
    """Who's leading: a '+ Name' line, or a Lead/Who/Person note. Day splits like 'Jill (SAT) / Tara (SUN)' become a dict."""
    text = ""
    for n in notes or []:
        if (n.get("category") or "").lower() in ("lead", "who", "person", "worship leader", "vocals"):
            text = n.get("content") or ""
            if text.strip():
                break
    m = re.search(r"^\s*\+\s*(.+)$", (desc or "") + "\n" + text, re.M)
    raw = (m.group(1) if m else text).strip()
    if not raw:
        return None
    parts = re.findall(r"([A-Za-z][\w .'\-]*?)\s*\((SAT|SATURDAY|SUN|SUNDAY)\)", raw, re.I)
    if parts:
        return {("Saturday" if d.upper().startswith("SAT") else "Sunday"): n.strip() for n, d in parts}
    return raw.splitlines()[0].strip()


def main():
    if not APP_ID or not SECRET:
        sys.exit("PCO_APP_ID and PCO_SECRET are not set")
    result = {"updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"}
    for key in WANT:
        t = find_type(key)
        if not t:
            print(f"[{key}] no matching service type found")
            result[key] = None
            continue
        print(f"[{key}] using service type {t['id']} ({t['attributes'].get('name')})")
        p = next_plan(t["id"])
        if not p:
            print(f"[{key}] no upcoming plan")
            result[key] = None
            continue
        d = plan_detail(t["id"], p)
        d["service_type"] = {"id": t["id"], "name": t["attributes"].get("name")}
        print(f"[{key}] plan {d['plan_id']} {d['dates']}: {len(d['items'])} items")
        for i in d["items"]:
            print(f"    {i['section'][:18]:18} | {i['title'][:40]:40} | {i['length']} | lead: {i['lead']}")
        result[key] = d
    with open("planning.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("saved planning.json")


if __name__ == "__main__":
    main()
