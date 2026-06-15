# MemGUI-Bench GitHub Pages

This is the official project page for **MemGUI-Bench: Benchmarking Memory of Mobile GUI Agents in Dynamic Environments**.

## 🚀 Quick Start

### Local Development

```bash
# Simply open index.html in a browser
# Or use a local server:
python -m http.server 8000
# Then visit http://localhost:8000
```

### Deployment

This site is designed for GitHub Pages. Simply:
1. Push to the `gh-pages` branch, or
2. Configure GitHub Pages in repository settings to serve from the `main` branch

## 📁 Project Structure

```
memgui-bench-gh-page/
├── index.html              # Main landing page
├── arena.html              # Side-by-side trajectory comparison
├── leaderboard.html        # Results leaderboard
├── submission.html         # Submission guidelines
├── css/
│   ├── style.css           # Global styles
│   ├── leaderboard.css     # Leaderboard-specific styles
│   ├── traj.css            # Trajectory viewer styles
│   ├── arena.css           # Arena-specific styles
│   └── submission.css      # Submission page styles
├── js/
│   ├── config.js           # Shared static data loading
│   ├── leaderboard.js      # Leaderboard functionality
│   ├── traj-viewer.js      # Static trajectory modal
│   └── arena.js            # Arena comparison functionality
├── data/
│   ├── index.json          # Agent file list
│   └── agents/*.json       # Per-agent leaderboard data
├── trajs/
│   ├── index.json          # Generated trajectory bundle manifest
│   ├── <agent>.json.gz     # Generated trajectory data
│   └── <agent>.mp4         # Generated screenshot frame store
├── assets/
│   └── favicon.png         # Site favicon
└── README.md
```

## 📊 Leaderboard Management

### Adding New Results

1. Add or edit `data/agents/<agent-id>.json`
2. Add a new agent entry following the existing format:

```json
{
  "name": "YourAgent",
  "type": "Agentic Workflow",
  "link": "https://github.com/...",
  "hasLongTermMemory": true,
  "shortTerm": {
    "easy": 41.7,
    "medium": 19.0,
    "hard": 18.4,
    "overall": 27.3,
    "irr": 39.5,
    "mtpr": 0.45,
    "timePerStep": 28.1,
    "costPerStep": 0.051
  },
  "longTerm": {
    "easy": 64.6,
    "medium": 42.9,
    "hard": 36.8,
    "overall": 49.2,
    "frr": 21.5,
    "improvement": 21.9
  }
}
```

3. Add the agent id to `data/index.json`

## 🧭 Trajectory Viewer and Arena

Trajectory bundles are generated into `trajs/` and are intentionally hidden
from the homepage until `trajs/index.json` contains the corresponding
`trajs/<agent>.json.gz` entry.

From the project root:

```bash
export HF_ENDPOINT=https://hf-mirror.com
bash scripts/download_and_bundle_trajs.sh
scripts/start_traj_parallel_stage_downloads.sh
scripts/start_traj_named_stage_supervisor.sh
scripts/start_traj_finalize_watcher.sh
scripts/start_traj_finalize_poller.sh
scripts/start_traj_staged_handoff_watcher.sh
scripts/start_traj_download_supervisor.sh
scripts/check_traj_status.sh
scripts/write_traj_status_snapshot.sh
scripts/import_staged_traj_zips.sh
scripts/promote_staged_traj_partials.sh
scripts/finalize_ready_trajs.sh
scripts/verify_ready_bundles.sh
scripts/verify_traj_bundles.py
scripts/verify_traj_site.py
scripts/audit_traj_goal.py
```

The main download script stores source zips in `traj_logs/`, downloads agents in
parallel by default, converts legacy MemGUI-Eval logs when needed, and writes
final `.json.gz` plus `.mp4` bundles to `docs/trajs/`. It downloads each agent
under `traj_logs/_parallel_downloads/<agent>/` to avoid shared `.hfd` state,
then imports completed zips into `traj_logs/` only after their exact expected
byte size is verified. Tune it with `DOWNLOAD_CONCURRENCY` (default `3`),
`HFD_THREADS` (default `6` per file), and `HFD_JOBS` (default `1`).
`start_traj_parallel_stage_downloads.sh` can still predownload a specific subset
under `traj_logs/_parallel_downloads/` if you want a separate staged run.
`start_traj_named_stage_supervisor.sh` keeps an extra named staged download
group alive, for example a temporary `gui_m3a` group prefetching `gui-owl-7b`
and `m3a` while the main staged downloader handles later agents.
`finalize_ready_trajs.sh` can safely re-scan completed zips
and create or validate any missing bundles without touching partial downloads.
`start_traj_finalize_poller.sh` periodically performs the same safe scan while
long downloads are still running.
`start_traj_staged_handoff_watcher.sh` watches the root download sequence and
promotes stronger staged partials at handoff points so resumed root downloads
do not discard useful staged progress. It checks every 10 seconds by default;
override with `STAGED_HANDOFF_INTERVAL_SECONDS`.
`start_traj_finalize_watcher.sh` waits for the background downloader to exit,
then runs the finalizer and audit automatically.
`start_traj_download_supervisor.sh` keeps the long-running download pipeline
alive by restarting the downloader, poller, finalizer watcher, staged handoff
watcher, or staged parallel downloader if any of them exit before the final
audit passes. It writes a `check_traj_status.sh` snapshot every 15 minutes by
default; override with `TRAJ_SUPERVISOR_INTERVAL_SECONDS`.
`verify_ready_bundles.sh` is a read-only helper for validating any already
generated bundles as they appear.
`audit_traj_goal.py` checks the downloaded zips, extraction markers, generated
bundles, MP4 frame stores, manifest entries, site integration, and legacy
conversion smoke test.

### Metrics Explained

#### Short-Term Memory (pass@1)
- **SR (Success Rate)**: Percentage of tasks completed successfully
- **IRR (Information Retention Rate)**: Memory fidelity metric
- **MTPR (Memory-Task Proficiency Ratio)**: Memory-specific capability

#### Long-Term Memory (pass@k)
- **SR@k**: Multi-attempt success rate
- **FRR (Failure Recovery Rate)**: Learning from failure efficiency
- **Improvement**: Performance gain from pass@1 to pass@k

## 🔧 Customization

### Updating Links

1. **Paper Link**: Update in `index.html` hero buttons
2. **GitHub Link**: Update in `index.html` and navigation
3. **Dataset Link**: Update in `index.html` hero buttons

### Changing Colors

Edit CSS variables in `css/style.css`:

```css
:root {
  --primary: #6366f1;        /* Primary accent color */
  --accent: #22d3ee;         /* Secondary accent */
  --bg-dark: #0f0f1a;        /* Background color */
  /* ... */
}
```

## 📧 Contact

For questions about the benchmark or leaderboard submissions, please contact: memgui-bench@example.com

## 📜 License

MIT License - See LICENSE file for details.
