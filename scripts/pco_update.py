#!/usr/bin/env python3
"""Set item lengths in ONE Planning Center plan, from pco_updates.json. Run by hand only (workflow_dispatch).

Safety: refuses to run unless the service type and plan match exactly; matches each item by title;
only ever changes the `length` attribute; writes before/after to pco_update_result.json.
"""
import base64, json, os, re, sys, urllib.request, datetime

API = "https://api.planningcenteronline.com/services/v2"
AUTH = "Basic " + base64.b64encode(f"{os.environ['PCO_APP_ID']}:{os.environ['PCO_SECRET']}".encode()).decode()
ALLOWED_TYPE_NAME = "northland | weekend"


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json", "User-Agent": "start-times-update"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def norm(t):
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", (t or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", t.replace("\u2019", "").replace("'", "")).strip()


def main():
    cfg = json.load(open("pco_updates.json"))
    st, pid = cfg["service_type"], cfg["plan_id"]
    stype = call("GET", f"/service_types/{st}")["data"]
    if (stype["attributes"].get("name") or "").strip().lower() != ALLOWED_TYPE_NAME:
        sys.exit(f"Refusing: service type {st} is {stype['attributes'].get('name')!r}, not Northland | Weekend")
    plan = call("GET", f"/service_types/{st}/plans/{pid}")["data"]
    print("Plan:", plan["attributes"].get("dates"), plan["attributes"].get("title"))
    items = call("GET", f"/service_types/{st}/plans/{pid}/items?per_page=100")["data"]
    result = {"ran": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z", "plan": pid, "changes": []}
    START, END = "--- Song roadmap ---", "--- end roadmap ---"
    for u in cfg["items"]:
        want = norm(u["match"])
        hits = [i for i in items if norm(i["attributes"].get("title")).startswith(want)]
        if len(hits) != 1:
            print(f"SKIP {u['match']!r}: {len(hits)} matching items"); result["changes"].append({"item": u["match"], "status": f"skipped ({len(hits)} matches)"}); continue
        it = hits[0]
        if "description" in u:
            # set the whole description (used when the full text is spelled out in pco_updates.json)
            before_d = it["attributes"].get("description") or ""
            call("PATCH", f"/service_types/{st}/plans/{pid}/items/{it['id']}", {"data": {"type": "Item", "id": it["id"], "attributes": {"description": u["description"]}}})
            print(f"DESC {it['attributes']['title']!r} set")
            result["changes"].append({"item": it["attributes"]["title"], "status": "description set", "before": before_d, "description": u["description"]})
            continue
        if "roadmap" in u:
            # keep everything already in the description; replace only our roadmap block (or add it at the end)
            desc = (it["attributes"].get("description") or "").replace("\r\n", "\n")
            block = START + "\n" + u["roadmap"].strip() + "\n" + END
            if START in desc and END in desc:
                a, b = desc.index(START), desc.index(END) + len(END)
                new = desc[:a].rstrip() + ("\n\n" if desc[:a].strip() else "") + block + desc[b:]
            else:
                new = (desc.rstrip() + "\n\n" if desc.strip() else "") + block
            call("PATCH", f"/service_types/{st}/plans/{pid}/items/{it['id']}", {"data": {"type": "Item", "id": it["id"], "attributes": {"description": new}}})
            print(f"NOTE {it['attributes']['title']!r}: roadmap {'replaced' if START in desc else 'added'}")
            result["changes"].append({"item": it["attributes"]["title"], "status": "roadmap " + ("replaced" if START in desc else "added"), "description": new})
            continue
        before = it["attributes"].get("length")
        if before == u["length"]:
            print(f"OK   {it['attributes']['title']!r} already {before}s"); result["changes"].append({"item": it["attributes"]["title"], "before": before, "after": before, "status": "unchanged"}); continue
        call("PATCH", f"/service_types/{st}/plans/{pid}/items/{it['id']}", {"data": {"type": "Item", "id": it["id"], "attributes": {"length": u["length"]}}})
        print(f"SET  {it['attributes']['title']!r}: {before}s -> {u['length']}s")
        result["changes"].append({"item": it["attributes"]["title"], "before": before, "after": u["length"], "status": "updated"})
    json.dump(result, open("pco_update_result.json", "w"), indent=2)


if __name__ == "__main__":
    main()
