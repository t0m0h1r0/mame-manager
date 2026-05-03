# MAME Rebuild

Python-only helper for auditing and rebuilding a MAME `images/` tree.

The script reads MAME XML and software-list XML, indexes ZIP/7z archives with
`7z`, checks CHDs with `chdman` when available, and builds a safe
`work_mame/clean_images/` tree before any rsync update.

## Basic Usage

```bash
./mame_manager.py --scan-only --skip-xml --scan-jobs 8
./mame_manager.py --rebuild-plan-only --skip-xml --scan-jobs 8
./mame_manager.py --scan-only --skip-xml --torrent-plan torrent_file_list.txt
./mame_manager.py --scan-only --skip-xml --qbittorrent-url http://localhost:8080 --qbittorrent-password 'password' --qbittorrent-name 'MAME 0.287 ROMs' --qbittorrent-dry-run
./mame_manager.py --skip-xml --merge-mode merged --no-qnap
```

Current implementation supports `--merge-mode merged`.

## qBittorrent Download Selection

`mame_manager.py` can directly instruct an already-added qBittorrent torrent to
download only missing or broken archives.  It inspects the torrents exposed by
the WebUI, chooses the torrent with the most matching missing targets, sets all
torrent files to priority `0`, then sets only wanted files to priority `1`.

```bash
./mame_manager.py \
  --scan-only \
  --skip-xml \
  --qbittorrent-url http://localhost:8080 \
  --qbittorrent-user admin \
  --qbittorrent-password 'password' \
  --qbittorrent-name 'MAME 0.287 ROMs' \
  --qbittorrent-dry-run
```

When the dry run looks right, omit `--qbittorrent-dry-run`.  Add
`--qbittorrent-resume` to start the torrent after priorities are applied.  Use
`--qbittorrent-name` to narrow auto-detection, or `--qbittorrent-hash` when you
want to force a specific torrent.  `QBITTORRENT_URL`, `QBITTORRENT_USER`, and
`QBITTORRENT_PASSWORD` environment variables are also accepted.

This integration only controls an existing qBittorrent torrent.  It does not fetch
metadata from magnet links and does not download files by itself.

## Architecture

The code is arranged around the data flow, not the order in which the original
script happened to run:

1. `catalog` defines what a correct MAME collection should contain.
2. `inventory` observes what exists on disk.
3. `audit`, `builder`, and `torrents` decide what is complete, missing,
   reusable, rebuildable, or worth downloading.
4. `media`, `publisher`, `qbittorrent`, and `runtime` perform edge effects:
   CHD/sample handling, rsync, WebUI calls, filesystem, and subprocess work.

CLI files stay thin.  Business logic lives in the package.

```text
mame_manager.py                  main audit/rebuild/qBittorrent CLI wrapper

mame_manager/
  cli.py                         argument parsing for mame_manager.py
  workflow.py                    top-level use case orchestration
  settings.py                    immutable runtime configuration
  catalog.py                     MAME XML/software-list extraction and parsing
  inventory.py                   input fingerprinting and archive indexing
  audit.py                       ROM completeness audit and set/file counts
  media.py                       CHD cache plus CHD/sample reporting/placement
  builder.py                     clean_images archive reuse and rebuild
  publisher.py                   guarded rsync publication
  torrents.py                    wanted-file plan from missing/broken targets
  qbittorrent.py                 qBittorrent Web API adapter and file matching
  reports.py                     report and summary writing
  runtime.py                     subprocess, hashing, JSON, and preflight tools
```

## Safety

- `--scan-only` is read-only unless qBittorrent write options are supplied.
- `--qbittorrent-dry-run` inspects WebUI matches without changing torrent priorities.
- Normal rebuilds write to `work_mame/clean_images/` first.
- `images/` updates go through `rsync --dry-run --itemize-changes`.
- Large rsync changes are stopped unless `--force-large-sync` is used.

## Reports

Reports are written under:

```text
work_mame/reports/
```

Important files include:

- `summary.txt`
- `arcade_missing_roms.txt`
- `software_missing_roms.txt`
- `arcade_complete_sets.txt`
- `software_complete_sets.txt`
- `arcade_incomplete_sets.txt`
- `software_incomplete_sets.txt`
- `archive_errors.txt`
- `torrent_wanted_files.txt`
- `torrent_unmatched_targets.txt`
- `torrent_target_map.tsv`
- `torrent_broken_archive_wanted_files.txt`
- `qbittorrent_selected_files.txt`
- `qbittorrent_unmatched_wanted_files.txt`
