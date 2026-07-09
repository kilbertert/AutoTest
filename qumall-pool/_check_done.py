import json, os
p_done = r"\\192.168.2.77\qumall-pool\jobs\done"
p_pending = r"\\192.168.2.77\qumall-pool\jobs\pending"
p_failed = r"\\192.168.2.77\qumall-pool\jobs\failed"
p_claimed = r"\\192.168.2.77\qumall-pool\jobs\claimed"

print("=== done/ (%d files) ===" % len(os.listdir(p_done)))
done_modules = set()
for f in sorted(os.listdir(p_done)):
    full = os.path.join(p_done, f)
    try:
        d = json.load(open(full, encoding="utf-8"))
        done_modules.add(d["module"])
        print("  ", d["module"], "rows", d["first_row"], "-", d["last_row"], "stats:", d.get("stats"))
    except Exception as e:
        print("  ", f, "ERR", e)

print()
print("=== pending/ (%d files) ===" % len(os.listdir(p_pending)))
pending_modules = set()
for f in sorted(os.listdir(p_pending)):
    full = os.path.join(p_pending, f)
    d = json.load(open(full, encoding="utf-8"))
    pending_modules.add(d["module"])

print("  modules still pending:", len(pending_modules))
for m in sorted(pending_modules):
    print("    -", m)

print()
print("=== failed/ (%d files) ===" % len(os.listdir(p_failed)) if os.path.exists(p_failed) else "n/a")
failed_modules = set()
if os.path.exists(p_failed):
    for f in sorted(os.listdir(p_failed)):
        full = os.path.join(p_failed, f)
        d = json.load(open(full, encoding="utf-8"))
        failed_modules.add(d["module"])
        print("  ", d["module"], "stats:", d.get("stats"))

print()
print("=== claimed/ ===")
if os.path.exists(p_claimed):
    for w in os.listdir(p_claimed):
        wp = os.path.join(p_claimed, w)
        n = len(os.listdir(wp))
        print("  worker", w, "has", n, "claimed jobs")
        for f in os.listdir(wp):
            full = os.path.join(wp, f)
            d = json.load(open(full, encoding="utf-8"))
            print("    -", d["module"])
