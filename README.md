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
