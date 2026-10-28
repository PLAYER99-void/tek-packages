# tek-packages

Binary packages for [Tek OS](https://github.com/PLAYER99-void/tek-os), built by the Tek package bot inside the Tek system
(x86-64-v3, from Arch Linux's PKGBUILDs) and installed with `tek -S <name>`.

- `bot/plan.json`: what is built, in dependency waves (made by `bot/plan.py` from Arch's repo databases and `bot/packages.txt`)
- `.github/workflows/build.yml`: builds one wave per run in parallel jobs, then starts the next wave
- Releases `pkgs-0` ... `pkgs-9`: the packages, spread over 10 shards (a GitHub release holds at most 1000 files), each with its `index.json`
- Release `builder`: the build container (`tek-builder.tar.zst`) and the newest `tek`

Tek's `/etc/tek/tek.conf` lists the shards:

    repo = tek0 https://github.com/PLAYER99-void/tek-packages/releases/download/pkgs-0
    ...
    repo = tek9 https://github.com/PLAYER99-void/tek-packages/releases/download/pkgs-9
