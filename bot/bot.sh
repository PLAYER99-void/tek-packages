#!/bin/bash
# Tek package bot, inside the tek-builder container: builds Arch package bases into .tek packages.
#   bot.sh <list> <out>      list = lines "<base> <first package name>"; out gets pkgs/*.tek, logs/<base>.log, status.tsv
# Per base: tek import (Arch PKGBUILD -> TEKBUILD), install its dependencies from the Tek repos (the published shards
# plus what this run built, file:///<out>/pkgs), build with Tek's flags, install the result so later bases can use it.
# Bases that fail get one more try at the end (dependency loops: their partners may be built by then).
set -uo pipefail
LIST=$1 OUT=$2
mkdir -p "$OUT/pkgs" "$OUT/logs" /imp
[ -x /bot/tek ] && install -m755 /bot/tek /usr/bin/tek   # the newest tek (CI: from the builder release)
: > "$OUT/status.tsv"
# Tek's build flags: x86-64-v3 (AVX2), -O2, LTO where the package allows it; parallel make
export CFLAGS="-march=x86-64-v3 -mtune=generic -O2 -pipe -fno-plt -fexceptions -Wp,-D_FORTIFY_SOURCE=3 -fstack-clash-protection -fcf-protection"
export CXXFLAGS="$CFLAGS -Wp,-D_GLIBCXX_ASSERTIONS" LDFLAGS="-Wl,-O1 -Wl,--sort-common -Wl,--as-needed -Wl,-z,relro -Wl,-z,now"
export RUSTFLAGS="-C target-cpu=x86-64-v3 -C opt-level=3" MAKEFLAGS="-j$(nproc)" NINJAFLAGS="-j$(nproc)"
export TEK_PROGRESS=lines   # no progress bars in CI logs

# this run's own packages are a repo too (first), then the published shards
tek repo-index "$OUT/pkgs" >/dev/null
{ echo "repo = run file://$OUT/pkgs"; for k in 0 1 2 3 4 5 6 7 8 9; do echo "repo = tek$k https://github.com/PLAYER99-void/tek-packages/releases/download/pkgs-$k"; done; } > /etc/tek/tek.conf
tek -Sy >/dev/null 2>&1 || true

have() {   # in the base system, or installed by tek
    grep -q "^$1 " /var/lib/tek/base-provides 2>/dev/null || tek -Q "$1" >/dev/null 2>&1
}

build_one() {   # build_one <base> <pkg>: 0 = built
    local base=$1 pkg=$2 log="$OUT/logs/$1.log" d t0 deps dep
    t0=$(date +%s)
    {
        echo "### $base ($pkg) $(date -u)"
        rm -rf "/imp/$pkg" "/imp/$base"
        tek import "$base" --out /imp || tek import "$pkg" --out /imp || { echo "IMPORT FAILED"; return 1; }
        d=/imp/$pkg; [ -f "$d/TEKBUILD" ] || d=/imp/$base; [ -f "$d/TEKBUILD" ] || { echo "no TEKBUILD after import"; return 1; }
        deps=$(bash -c 'source "$1"; printf "%s\n" "${depends[@]}" "${makedepends[@]}"' _ "$d/TEKBUILD" 2>/dev/null | sed 's/[<>=:].*//' | sort -u)
        for dep in $deps; do
            have "$dep" && continue
            tek -Sy >/dev/null 2>&1
            tek -S --native --noconfirm "$dep" >/dev/null 2>&1 || echo "dependency not available yet: $dep"
        done
        timeout 10800 tek build "$d" --out "$OUT/pkgs" || return 1
        for f in "$OUT"/pkgs/*.tek; do [ "$f" -nt "$log.start" ] && tek -U --noconfirm "$f" >/dev/null 2>&1; done
        tek repo-index "$OUT/pkgs" >/dev/null
    } >> "$log" 2>&1
}

pass() {   # pass <list>: build every line, print the failed lines
    local base pkg t0
    while read -r base pkg; do
        [ -n "$base" ] || continue
        t0=$(date +%s); touch "$OUT/logs/$base.log.start"
        if build_one "$base" "$pkg"; then
            printf '%s\tok\t%s\n' "$base" $(( $(date +%s) - t0 )) >> "$OUT/status.tsv"; echo "OK    $base ($(( $(date +%s) - t0 )) s)" >&2
        else
            echo "$base $pkg"; echo "FAIL  $base ($(tail -n 1 "$OUT/logs/$base.log" | cut -c1-120))" >&2
        fi
        rm -f "$OUT/logs/$base.log.start"
    done < "$1"
}

pass "$LIST" > /tmp/retry
if [ -s /tmp/retry ]; then
    echo "== second try for $(wc -l < /tmp/retry) bases" >&2
    pass /tmp/retry > /tmp/failed
    while read -r base pkg; do printf '%s\tfail\t0\t%s\n' "$base" "$(grep -m1 -iE 'error|failed|not found' "$OUT/logs/$base.log" | cut -c1-200)" >> "$OUT/status.tsv"; done < /tmp/failed
fi
echo "== $(grep -c $'\tok\t' "$OUT/status.tsv") built, $(grep -c $'\tfail\t' "$OUT/status.tsv") failed" >&2
