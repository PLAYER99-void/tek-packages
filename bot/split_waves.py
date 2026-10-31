#!/usr/bin/env python3
"""Split every wave of plan.json into dependency levels, so bases that need each other are never built in the same CI run.
A wave built in parallel jobs cannot share results, so the big wave 5 (a dependency loop) failed almost entirely. Level = 1 +
the deepest level among its dependencies in the same wave; an edge that closes a cycle is ignored (the cycle's members then
land in the same level and the bot's end-of-run retry is their second chance).
   python3 tools/repo/split_waves.py [plan.json] [out.json]"""
import json, sys
sys.setrecursionlimit(100000)
src = sys.argv[1] if len(sys.argv) > 1 else "tools/repo/plan.json"; dst = sys.argv[2] if len(sys.argv) > 2 else src
p = json.load(open(src))
bases = p["bases"]
provider = {}
for b, e in bases.items():
    for n in e["pkgs"]: provider[n] = b
new = []
for w in p["waves"]:
    members = set(w["bases"]); level = {}; state = {}
    def lv(b):
        if b in level: return level[b]
        if state.get(b) == 1: return -1          # on the stack: a cycle edge, ignored
        state[b] = 1; m = -1
        for d in bases[b].get("deps", []):
            db = provider.get(d, d)
            if db in members and db != b: m = max(m, lv(db))
        state[b] = 2; level[b] = m + 1; return level[b]
    for b in w["bases"]: lv(b)
    groups = {}
    for b in w["bases"]: groups.setdefault(level[b], []).append(b)
    for k in sorted(groups): new.append({"bases": groups[k], "loops": w.get("loops", []) if k == 0 else []})
p["waves"] = new
json.dump(p, open(dst, "w"))
print(len(new), "waves:", [len(w["bases"]) for w in new])
