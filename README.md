# MAME Rebuild

Python-only helper for auditing and rebuilding a MAME `images/` tree.

The script reads MAME XML and software-list XML, indexes ZIP/7z archives with
`7z`, checks CHDs with `chdman` when available, and builds a safe
`work_mame/clean_images/` tree before any rsync update.

## Basic Usage

```bash
./mame_rebuild.py --scan-only --skip-xml --scan-jobs 8
./mame_rebuild.py --rebuild-plan-only --skip-xml --scan-jobs 8
./mame_rebuild.py --scan-only --skip-xml --torrent-plan torrent_file_list.txt
./mame_rebuild.py --skip-xml --merge-mode merged --no-qnap
```

Current implementation supports `--merge-mode merged`.

## qBittorrent File Selection

`mame_rebuild.py --torrent-plan` creates a wanted file list.  Apply it to an
already-added qBittorrent torrent with:

```bash
./qb_select_wanted.py \
  --url http://localhost:8080 \
  --user admin \
  --password 'password' \
  --wanted work_mame/reports/torrent_wanted_files.txt \
  --torrent-name 'MAME 0.287 ROMs' \
  --dry-run
```

When `--hash` is omitted, the tool inspects qBittorrent torrents and picks the
one with the most wanted-file matches.  Use `--torrent-name` to narrow the
auto-detection.  When the dry run looks right, omit `--dry-run`.  Add `--resume`
to start the torrent after priorities are applied.  The tool first sets all
torrent files to priority `0`, then sets wanted files to priority `1`.

This helper only controls an existing qBittorrent torrent.  It does not fetch
metadata from magnet links and does not download files by itself.

## Structure

- `mame_rebuild.py`: MAME audit/rebuild CLI.
- `qb_select_wanted.py`: qBittorrent file priority CLI.
- `mame_manager/qbittorrent.py`: qBittorrent Web API adapter and file matching.

## Safety

- `--scan-only` is read-only.
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
