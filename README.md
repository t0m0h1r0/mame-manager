# MAME Rebuild

Python-only helper for auditing and rebuilding a MAME `images/` tree.

The script reads cached MAME XML and software-list XML, indexes ZIP/7z archives
with `7z`, checks CHDs with `chdman` when available, and builds a safe
`work_mame/clean_images/` tree before any rsync update.

By default, newly downloaded material is read from `Downloads/`.  Visible files
under that tree are treated as an incoming pool regardless of directory layout;
hidden files and files under hidden directories are ignored.

## Basic Usage

```bash
./mame_manager.py --scan-jobs 8
./mame_manager.py --scan-only --scan-jobs 8
./mame_manager.py --update-xml --scan-only --scan-jobs 8
./mame_manager.py --check-broken
./mame_manager.py --rebuild-plan-only --scan-jobs 8
./mame_manager.py --scan-only --torrent-plan torrent_file_list.txt
QBITTORRENT_PASSWORD='password' ./mame_manager.py --scan-only --download-missing --qbittorrent-dry-run
./mame_manager.py --rebuild --merge-mode merged
./mame_manager.py --rebuild --merge-mode merged --backup
./mame_manager.py --restore
```

Current implementation supports `--merge-mode merged`.
The default action is scan-only, and XML generation is not performed unless
`--update-xml` is supplied.  Use `--rebuild` to build only changed ROM packages
that use incoming files from `Downloads/`, write them under `clean_images/`, and
sync that patch back to `images/`.  Add `--backup` to also rsync `images/` to the
backup URL.  Use `--restore` to rsync the backup URL back to `images/`.

## Local Configuration

Defaults live in `mame_manager/defaults.py`.  Machine-specific values can be
kept outside git in:

```text
~/.config/mame-manager/config.env
```

Example:

```text
BACKUP_URL=rsync://rsync@192.168.1.112/Game/Multi-Platform/images/
QBITTORRENT_PASSWORD=password
SCAN_JOBS=16
COMPRESS_JOBS=4
```

Environment variables still win over the config file.  A custom config file can
be selected with `--config` or `MAME_MANAGER_CONFIG`.

## Standard Workflow

The intended operating loop is:

```text
scan -> detect missing files -> register qBittorrent downloads -> download
-> rescan -> rebuild clean_images -> rescan/verify -> rsync images -> backup if requested
```

In practice:

1. When the MAME version changes, refresh XML with `--update-xml`.
2. Run a dry run with `--download-missing --qbittorrent-dry-run`.
3. If the selected files look right, run again without `--qbittorrent-dry-run`
   and optionally with `--qbittorrent-resume`.
4. After qBittorrent finishes downloading into `Downloads/`, run with
   `--rebuild`.
5. Add `--backup` only when you want the rsync backup too.

## Broken File Check

Use `--check-broken` to test existing archive and CHD files without parsing DAT
XML or rebuilding anything.

```bash
./mame_manager.py --check-broken
```

The checker runs `7z t` for ZIP/7z archives under `images/roms/`,
`images/software_roms/`, and `Downloads/`.  CHDs under `images/chds/`,
`images/software_chds/`, and `Downloads/` are verified with `chdman verify` when
`chdman` is available.  Results are cached in `work_mame/integrity_cache.json`
using path, size, mtime, and checker, so stopping midway and running the command
again resumes from already verified files.  Broken files are written to
`work_mame/reports/integrity_broken_files.txt`.

## qBittorrent Download Selection

`mame_manager.py` can directly instruct an already-added qBittorrent torrent to
download only missing or broken archives.  It inspects the torrents exposed by
the WebUI, finds every torrent that contains at least one missing or broken
target, sets all files in those torrents to priority `0`, then sets only wanted
files to priority `1` in each matching torrent.
This only happens when `--download-missing` is present.

```bash
QBITTORRENT_PASSWORD='password' \
./mame_manager.py \
  --scan-only \
  --download-missing \
  --qbittorrent-dry-run
```

When the dry run looks right, omit `--qbittorrent-dry-run`.  Add
`--qbittorrent-resume` to start the torrent after priorities are applied.  Use
`--qbittorrent-name` to narrow auto-detection, or `--qbittorrent-hash` when you
want to force a specific torrent.  The default WebUI URL is
`http://localhost:8080`, and the default user is `admin`.  `QBITTORRENT_URL`,
`QBITTORRENT_USER`, and `QBITTORRENT_PASSWORD` environment variables are also
accepted.

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
  defaults.py                    default paths, commands, env vars, and WebUI values
  workflow.py                    top-level use case orchestration
  settings.py                    immutable runtime configuration
  catalog.py                     MAME XML/software-list extraction and parsing
  inventory.py                   input fingerprinting and archive indexing
  integrity.py                   resumable archive/CHD check orchestration
  integrity_targets.py           archive/CHD target discovery
  integrity_runner.py            per-file archive/CHD integrity commands
  integrity_cache.py             resumable integrity result cache
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

- scan-only is the default and is read-only unless `--download-missing` is supplied.
- `--update-xml` is required before generating or refreshing MAME XML.
- `--rebuild` is required before rebuilding changed ROM packages or syncing to `images/`.
- `--backup` is required before rsyncing `images/` to the backup URL.
- `--restore` is required before rsyncing the backup URL back to `images/`.
- `--qbittorrent-dry-run` inspects WebUI matches without changing torrent priorities.
- Normal rebuilds write only changed files with `Downloads/` sources to `work_mame/clean_images/` first.
- `images/` updates go through `rsync --dry-run --itemize-changes` without `--delete`.
- Restore updates mirror the backup URL to `images/` with `rsync --delete-before` after dry-run review.
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
- `rebuild_unbuildable.txt`
- `rebuild_skipped_no_incoming.txt`
- `rsync_backup_to_images_dry_run.txt`
- `integrity_broken_files.txt`
- `integrity_skipped_files.txt`
