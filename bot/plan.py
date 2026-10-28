#!/usr/bin/env python3
"""Build plan for the Tek package bot: which Arch package bases to build, in dependency waves.

Reads Arch's repo databases (core/extra/multilib .db: name, base, version, depends, makedepends, provides), takes the
wanted names (tools/repo/packages.txt) plus everything they need at build or run time, drops what the Tek base
system already has (/var/lib/tek/base-provides of the builder, or tools/repo/base-provides.txt), and sorts the package
bases into waves: a base is in wave N when all its dependencies are built in waves < N. One wave = one CI run.

  python3 tools/repo/plan.py [packages.txt] [out.json]        (downloads the .db files into ~/.cache/tek-plan)
"""
import io, json, os, re, sys, tarfile, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MIRROR = "https://geo.mirror.pkgbuild.com"
REPOS = ["core", "extra", "multilib"]
CACHE = os.path.expanduser("~/.cache/tek-plan")


def strip_ver(dep):
    return re.split(r"[<>=:]", dep, maxsplit=1)[0].strip()


def load_db(repo):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{repo}.db")
    if not os.path.exists(path):
        urllib.request.urlretrieve(f"{MIRROR}/{repo}/os/x86_64/{repo}.db", path)
    pkgs = {}
    with tarfile.open(path) as t:
        for m in t.getmembers():
            if not m.name.endswith("/desc"):
                continue
            fields, key = defaultdict(list), None
            for line in t.extractfile(m).read().decode().splitlines():
                if line.startswith("%") and line.endswith("%"):
                    key = line.strip("%")
                elif line and key:
                    fields[key].append(line)
            name = fields["NAME"][0]
            pkgs[name] = {
                "name": name, "repo": repo,
                "base": (fields.get("BASE") or [name])[0],
                "version": fields["VERSION"][0],
                "depends": [strip_ver(d) for d in fields.get("DEPENDS", [])],
                "makedepends": [strip_ver(d) for d in fields.get("MAKEDEPENDS", [])],   # no CHECKDEPENDS: the bot skips tests
                "provides": [strip_ver(p) for p in fields.get("PROVIDES", [])],
            }
    return pkgs


def base_provides():
    for p in ("/var/lib/tek/base-provides", os.path.join(HERE, "base-provides.txt")):
        if os.path.exists(p):
            return {l.split()[0] for l in open(p) if l.strip()}
    return set()


def plan(wanted, pkgs, have):
    provider = {}
    for p in pkgs.values():
        provider.setdefault(p["name"], p["name"])
        for v in p["provides"]:
            provider.setdefault(v, p["name"])
    # closure over run + build dependencies
    need, todo, missing = set(), [w for w in wanted], set()
    while todo:
        n = todo.pop()
        if n in have:
            continue
        name = provider.get(n)
        if name is None:
            missing.add(n)
            continue
        if name in need or name in have:
            continue
        need.add(name)
        p = pkgs[name]
        todo.extend(p["depends"] + p["makedepends"])
    # group into bases, dependency edges between bases
    bases = defaultdict(set)
    for n in need:
        bases[pkgs[n]["base"]].add(n)
    deps = defaultdict(set)
    for b, names in bases.items():
        for n in names:
            for d in pkgs[n]["depends"] + pkgs[n]["makedepends"]:
                if d in have or provider.get(d) is None:
                    continue
                db = pkgs[provider[d]]["base"]
                if db != b and provider[d] in need:
                    deps[b].add(db)
    # dependency loops (strongly connected components, Tarjan) become one unit: built once with what is there, then
    # rebuilt against itself in the next wave. Waves over the loop-free graph of units (Kahn).
    index, low, stack, on, comp, n = {}, {}, [], set(), {}, [0]
    sys.setrecursionlimit(100000)
    def strong(v):
        index[v] = low[v] = n[0]; n[0] += 1; stack.append(v); on.add(v)
        for w in deps[v]:
            if w not in index:
                strong(w); low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            while True:
                w = stack.pop(); on.discard(w); comp[w] = v
                if w == v:
                    break
    for b in sorted(bases):
        if b not in index:
            strong(b)
    units = defaultdict(set)
    for b, c in comp.items():
        units[c].add(b)
    udeps = {c: {comp[d] for b in members for d in deps[b]} - {c} for c, members in units.items()}
    done, left, waves = set(), set(units), []
    while left:
        ready = sorted(c for c in left if udeps[c] <= done)
        assert ready, "the unit graph has no loops"
        bs = sorted(b for c in ready for b in units[c])
        waves.append({"bases": bs, "loops": [sorted(units[c]) for c in ready if len(units[c]) > 1]})
        done |= set(ready); left -= set(ready)
    return bases, deps, waves, missing


def main():
    lst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "packages.txt")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "plan.json")
    pkgs = {}
    for r in REPOS:
        pkgs.update(load_db(r))
    wanted = [l.strip() for l in open(lst) if l.strip() and not l.startswith("#")]
    have = base_provides()
    bases, deps, waves, missing = plan(wanted, pkgs, have)
    json.dump({
        "waves": waves,
        "bases": {b: {"pkgs": sorted(n), "version": pkgs[sorted(n)[0]]["version"], "deps": sorted(deps[b])} for b, n in bases.items()},
        "missing": sorted(missing),
    }, open(out, "w"), indent=1)
    print(f"{len(wanted)} wanted -> {sum(len(n) for n in bases.values())} packages in {len(bases)} bases, "
          f"{len(waves)} waves (sizes {[len(w['bases']) for w in waves][:40]}), "
          f"{sum(len(l) for w in waves for l in w['loops'])} bases in {sum(len(w['loops']) for w in waves)} loops, biggest loop {max([len(l) for w in waves for l in w['loops']] or [0])}, "
          f"{len(missing)} unresolved names: {sorted(missing)[:10]}")


if __name__ == "__main__":
    # self-check on a tiny graph: c needs b needs a; d is in the base system
    t = {"a": {"name": "a", "base": "a", "version": "1", "depends": ["d"], "makedepends": [], "provides": []},
         "b": {"name": "b", "base": "b", "version": "1", "depends": ["a"], "makedepends": [], "provides": ["bee"]},
         "c": {"name": "c", "base": "c", "version": "1", "depends": [], "makedepends": ["bee"], "provides": []}}
    _, _, w, miss = plan(["c"], t, {"d"})
    assert [x["bases"] for x in w] == [["a"], ["b"], ["c"]] and not miss, w
    t["a"]["makedepends"] = ["c"]   # a loop a -> c -> b -> a is one unit in one wave
    _, _, w, _ = plan(["c"], t, {"d"})
    assert [x["bases"] for x in w] == [["a", "b", "c"]] and w[0]["loops"] == [["a", "b", "c"]], w
    main()
