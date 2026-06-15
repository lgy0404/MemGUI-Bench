# MemGUI Trajectory Bundles

This directory stores the static trajectory bundles used by the MemGUI-Bench
docs homepage and Arena.

Each generated agent should have:

- `<agent>.json.gz`: bundled trajectory metadata in the MobileWorld-style viewer format
- `<agent>.mp4`: screenshot frame store referenced by `_meta.video_file`

The source zip files are downloaded to `traj_logs/` from:

`https://huggingface.co/datasets/lgy0404/memgui-bench-trajs`

Use the project scripts from the repository root:

```bash
scripts/start_traj_download.sh
scripts/check_traj_status.sh
scripts/verify_traj_bundles.py
```

`scripts/download_and_bundle_trajs.sh` uses `hfd` with `HF_ENDPOINT=https://hf-mirror.com`.
Legacy MemGUI-Eval logs are converted automatically by `docs/bundle_trajs.py`
before bundling.
