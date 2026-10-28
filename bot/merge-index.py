#!/usr/bin/env python3
"""Merge index fragments into the Tek repo shards.

  merge-index.py <work-dir> <fragment index.json>...
Every package goes to shard crc32(name) % 10. <work-dir>/pkgs-K/index.json (the shard's published index, if any) is
updated in place: a newer build of a name replaces the old entry. Prints "K file" for every .tek that must be uploaded
to release pkgs-K.
"""
import json, os, sys, zlib

SHARDS = 10


def shard(name):
    return zlib.crc32(name.encode()) % SHARDS


def main():
    work, frags = sys.argv[1], sys.argv[2:]
    idx = {}
    for k in range(SHARDS):
        p = os.path.join(work, f"pkgs-{k}", "index.json")
        idx[k] = {e["info"]["name"]: e for e in json.load(open(p))["packages"]} if os.path.exists(p) else {}
    for f in frags:
        for e in json.load(open(f))["packages"]:
            k = shard(e["info"]["name"])
            idx[k][e["info"]["name"]] = e
            print(k, os.path.join(os.path.dirname(f), e["filename"]))
    for k, entries in idx.items():
        os.makedirs(os.path.join(work, f"pkgs-{k}"), exist_ok=True)
        json.dump({"packages": sorted(entries.values(), key=lambda e: e["info"]["name"])},
                  open(os.path.join(work, f"pkgs-{k}", "index.json"), "w"), indent=1)


if __name__ == "__main__":
    assert shard("htop") == shard("htop") and 0 <= shard("x") < SHARDS
    main()
