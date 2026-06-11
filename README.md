<div align="center">
  <img src="./assets/memgui-bench-logo.drawio.png" alt="Banner" />

<p>
    <img src="https://img.shields.io/badge/Tasks-128-blue" alt="Tasks"/>
    <img src="https://img.shields.io/badge/Apps-26-green" alt="Apps"/>
    <img src="https://img.shields.io/badge/Scenarios-68-orange" alt="Scenarios"/>
    <img src="https://img.shields.io/badge/Avg_Steps-36-red" alt="Avg Steps"/>
    <img src="https://img.shields.io/badge/Cross_App-1~4_apps-purple" alt="Cross App"/>
    <img src="https://img.shields.io/badge/Memory_Intensive-89.8%25-brightgreen" alt="Memory Intensive"/>
    <img src="https://img.shields.io/badge/License-MIT-lightgrey" alt="License"/>
  </p>

<p>
    <a href="https://arxiv.org/abs/2602.06075">
      <img src="https://img.shields.io/badge/Paper-arXiv%3A2602.06075-blue?logo=arxiv&logoColor=white" alt="Paper"/>
    </a>
    <a href="https://lgy0404.github.io/MemGUI-Bench/">
      <img src="https://img.shields.io/badge/Website-Online-blueviolet?logo=google-chrome&logoColor=white" alt="Website"/>
    </a>
    <a href="https://lgy0404.github.io/MemGUI-Bench/leaderboard.html">
      <img src="https://img.shields.io/badge/Leaderboard-View-orange?logo=star&logoColor=white" alt="Leaderboard"/>
    </a>
    <a href="https://huggingface.co/datasets/lgy0404/MemGUI-Bench">
      <img src="https://img.shields.io/badge/Tasks-HuggingFace-yellow?logo=huggingface&logoColor=white" alt="Tasks"/>
    </a>
    <a href="https://huggingface.co/datasets/lgy0404/memgui-bench-trajs">
      <img src="https://img.shields.io/badge/Trajectories-HuggingFace-yellow?logo=huggingface&logoColor=white" alt="Trajectories"/>
    </a>
  </p>
</div>

---

## 📋 Table of Contents

- [💾 Installation](#-installation)
- [🚀 Quick Start](#-quick-start)
- [📁 Benchmark Session](#-benchmark-session)
- [📊 Metrics](#-metrics)
- [🤖 Adding a New Agent](#-adding-a-new-agent)
- [📤 Leaderboard Submission](#-leaderboard-submission)
- [📚 Tasks](#tasks)
- [📝 Citation](#-citation)
- [📧 Contact](#-contact)

---

## 📢 Updates
- **2026-02-15**: 🎉 MemGUI-Bench adopted by [Mobile-Agent-v3.5](https://github.com/X-PLUG/MobileAgent)! Congrats to the Tongyi Lab team for achieving **27.1%** on Easy tasks with GUI-Owl-1.5-32B. We welcome more agents to challenge the full benchmark! 🚀
- **2026-02-09**: 🗂️ Benchmark tasks now available on HuggingFace: [lgy0404/MemGUI-Bench](https://huggingface.co/datasets/lgy0404/MemGUI-Bench) 
- **2026-02-09**: 📄 Paper released on arXiv! Check out our paper: [arXiv:2602.06075](https://arxiv.org/abs/2602.06075) 
- **2026-02-03**: Initial release of MemGUI-Bench benchmark. Check out our [website](https://lgy0404.github.io/MemGUI-Bench/).


## 💾 Installation

<div align="center">
  <img src="assets/unified-architecture.drawio.png" alt="Task Distribution" width="100%" />
</div>

### System Requirements

- **Linux host** with Docker and KVM acceleration
- Permission to run privileged Docker containers
- Python 3.12 and `uv` on the host

The base Docker image already includes the Android SDK, ADB, emulator binaries,
and MemGUI-AVD snapshot. `mg env build` adds the current MobileWorld-compatible
MemGUI-Bench runtime on top of that base image. Users do not need to install
Android Studio, download AVD snapshots, or configure emulator paths.

### Quick Install

```bash
# Install dependencies with uv
uv sync

# Create local .env from the example
uv run mg env init
```

### Environment Configuration

`uv run mg env init` creates `.env` from `.env.example`. If you prefer to create
the environment file manually:

```bash
cp .env.example .env
```

Edit the `.env` file and configure the following parameters.

**Required for Agent Evaluation:**
- `BASE_URL`: OpenAI-compatible base URL for the agent model
- `API_KEY`: API key for the agent model

**Required for MemGUI-Eval:**
- `MEMGUI_API_KEY`: API key for MemGUI-Eval
- `MEMGUI_STEP_DESC_MODEL`: Step-description model
- `MEMGUI_STEP_DESC_BASE_URL`: Optional step-description endpoint; leave empty to use `BASE_URL`
- `MEMGUI_FINAL_DECISION_MODEL`: Final-decision model
- `MEMGUI_FINAL_DECISION_BASE_URL`: Optional final-decision endpoint; leave empty to use `BASE_URL`

**Example `.env` file:**

```bash
# Agent model configuration
BASE_URL=https://openrouter.fans/v1
API_KEY=YOUR_API_KEY_HERE

# MemGUI-Eval configuration
MEMGUI_API_KEY=YOUR_API_KEY_HERE

# Step description model
MEMGUI_STEP_DESC_MODEL=google/gemini-2.5-flash
MEMGUI_STEP_DESC_BASE_URL=

# Final decision model
MEMGUI_FINAL_DECISION_MODEL=google/gemini-2.5-pro
MEMGUI_FINAL_DECISION_BASE_URL=
```

For leaderboard submissions, we use `MEMGUI_STEP_DESC_MODEL=google/gemini-2.5-flash`
and `MEMGUI_FINAL_DECISION_MODEL=google/gemini-2.5-pro` to keep evaluation
fair across submissions. During debugging, you may use other compatible models
to reduce cost or latency.

> **Note**:
> - `mg env run` mounts local `.env` into each container. `mg eval` runs on the
>   host and writes trajectories directly into local `traj_logs/`.

---

## 🚀 Quick Start

### 1. Check Environment & Prepare Docker Images

```bash
sudo uv run mg env check
```

This verifies Docker, KVM support, `.env`, the MemGUI base image, and the local
runtime image. If the runtime image is missing, build it once:

```bash
sudo uv run mg env build
```

`mg env build` uses the pre-configured MemGUI image as its base and adds
`/app/service`, `/app/docker`, the MobileWorld server, and the entrypoint needed
for host-side orchestration, including automatic ADB authorization and host
port relay. It does not ask you to configure AVDs manually.

### 2. Launch Docker Containers

```bash
sudo uv run mg env run --count 4 --launch-interval 20
```

This launches 4 ready MemGUI backend containers with:
- `--count 4`: Number of parallel containers
- `--launch-interval 20`: Wait 20 seconds between container launches

Each backend runs one Android emulator. Backend ports start at
`http://localhost:6800`, viewer ports start at `http://localhost:7860`, ADB
ports start at `5556`. Trajectory logs are written by the host-side `mg eval`
process into local `traj_logs/`.

### 3. Run Evaluation

```bash
sudo uv run mg eval \
  --agent-type qwen3vl \
  --model-name qwen3-vl-8b \
  --task ALL \
  --log-file-root traj_logs/memgui-qwen3vl \
  --max-concurrency 4
```

`mg eval --max-concurrency 4` discovers four MemGUI backend containers and feeds
the selected tasks through MobileWorld's environment queue. Each backend runs
exactly one Android emulator and writes MobileWorld-format trajectories into
the local `traj_logs/` directory.

### 4. View Results

```bash
uv run mg logs view --log-dir traj_logs/memgui-qwen3vl
```

The viewer opens a local web UI with task-level status, screenshots, action
traces, model predictions, and `result.txt` scores in the MobileWorld layout.

### Debug in a Container

For a single-container debug shell:

```bash
sudo uv run mg env exec 0
uv run mg eval \
  --agent-type qwen3vl \
  --model-name qwen3-vl-8b \
  --task 001-FindProductAndFilter \
  --aw-host http://localhost:6800 \
  --log-file-root traj_logs/debug
```

### Available Commands

| Command | Description |
| ------- | ----------- |
| `sudo uv run mg env check` | Check Docker/KVM/.env, base image, and local runtime image |
| `sudo uv run mg env build` | Build the local MobileWorld-compatible runtime image from the MemGUI base image |
| `sudo uv run mg env run` | Launch backend container(s) with local `.env` mounted |
| `sudo uv run mg env list` | List MemGUI-Bench containers |
| `sudo uv run mg env exec` | Open a shell or run a command in a container for debugging |
| `sudo uv run mg env rm` | Remove MemGUI-Bench containers |
| `uv run mg env init` | Create `.env` from `.env.example` |
| `uv run mg server` | Run the backend service inside a container; normally started by `mg env run` |
| `sudo uv run mg eval` | Run execution/evaluation across MemGUI containers |
| `uv run mg info task` | List or filter benchmark tasks |
| `uv run mg info agent` | List configured agents |
| `uv run mg info app` | Show app-level task counts |
| `uv run mg logs view` | Launch the interactive trajectory viewer |
| `uv run mg logs results` | Print a compact session summary table |
| `uv run mg logs export` | Export a static HTML trajectory site |

### `mg eval` Arguments

| Argument            | Default  | Description                                |
| ------------------- | -------- | ------------------------------------------ |
| `--agent-type` | required | Registered MobileWorld agent name or custom agent path |
| `--model-name` | `.env`/agent default | Agent model name |
| `--llm-base-url` | `.env`/agent default | OpenAI-compatible base URL |
| `--api-key` | `API_KEY` | Agent API key |
| `--task` / `--tasks` | all when omitted | Task id(s), comma-separated, or `ALL` |
| `--task-file` / `--task-csv` | none | MemGUI CSV subset to run, e.g. `data/memgui-tasks-40.csv` |
| `--difficulty` / `--task-difficulty` | none | MemGUI difficulty filter: `easy`/`medium`/`hard`, `1`/`2`/`3`, or `简单`/`中等`/`困难`; comma-separated values are supported |
| `--pass-at-k` / `--attempts` | `1` | Run each MemGUI task until one attempt succeeds or K attempts are exhausted, then aggregate pass@K |
| `--suite-family` | `memgui_bench` | Benchmark suite family |
| `--log-file-root` | `./traj_logs` | Local root for MobileWorld trajectory logs |
| `--aw-host` | auto | Comma-separated backend URL(s); auto-discovered when omitted |
| `--max-round` / `--max-step` | MemGUI task budget | Maximum agent steps per task; omitted uses `int(golden_steps * 2.5 + 1)`, `-1` means unlimited |
| `--step-wait-time` | `3.0` | Seconds to wait after each action before the next screenshot for MemGUI-Bench |
| `--max-concurrency` | number of containers | Maximum concurrent tasks |
| `--shuffle-tasks` | false | Shuffle task order before scheduling |
| `--dry-run` | false | Resolve tasks/backends without execution |

### Examples

```bash
# Full benchmark (execution + evaluation)
uv run mg eval --agent-type qwen3vl --model-name qwen3-vl-8b --task ALL --log-file-root traj_logs/qwen3vl-full

# Run specific task
uv run mg eval --agent-type qwen3vl --model-name qwen3-vl-8b --task 001-FindProductAndFilter --log-file-root traj_logs/debug

# Run the 40-task subset
uv run mg eval --agent-type qwen3vl --model-name qwen3-vl-8b --task-file data/memgui-tasks-40.csv --log-file-root traj_logs/qwen3vl-40

# Run only hard MemGUI tasks
uv run mg eval --agent-type qwen3vl --model-name qwen3-vl-8b --difficulty hard --log-file-root traj_logs/qwen3vl-hard

# Run medium + hard tasks from the 40-task subset
uv run mg eval --agent-type qwen3vl --model-name qwen3-vl-8b --task-file data/memgui-tasks-40.csv --difficulty medium,hard --log-file-root traj_logs/qwen3vl-40-medium-hard

# Run pass@3 on the 40-task subset
uv run mg eval --agent-type qwen3vl --model-name qwen3-vl-8b --task-file data/memgui-tasks-40.csv --pass-at-k 3 --log-file-root traj_logs/qwen3vl-40-pass3

# Use explicit backends
uv run mg eval --agent-type qwen3vl --task ALL --aw-host http://localhost:6800,http://localhost:6801

# Limit concurrency
uv run mg eval --agent-type qwen3vl --task ALL --max-concurrency 2

# Dry run
uv run mg eval --agent-type qwen3vl --task 001-FindProductAndFilter --dry-run
```

### Viewing and Exporting Results

```bash
# Interactive web viewer
uv run mg logs view --log-dir traj_logs/qwen3vl-full --port 8760

# Terminal summary
uv run mg logs results traj_logs/qwen3vl-full

# Static HTML export for sharing or archiving
uv run mg logs export \
  --log-dir traj_logs/qwen3vl-full \
  --output exported-sites/qwen3vl-full
```

For pass@K runs, the task detail page includes attempt tabs. Attempt 1 is stored
in the canonical task folder; later attempts are stored under `_attempt_trajs/`
and can be opened from the same viewer page.

---

## 📁 Benchmark Session

Each run creates an isolated benchmark folder under local `traj_logs/`. The
host-side `mg eval` process writes these files directly, so they are not trapped
inside Docker containers.

- Each task has a MobileWorld `traj.json`, screenshots, marked screenshots, and `result.txt`
- Re-running the same log root skips tasks that already succeeded; pass@K runs
  also skip tasks that already have a completed pass@K aggregate result
- MemGUI-Eval receives a generated compatibility workspace under `_memgui_eval/`

### Output Structure

<details>
<summary><b>Click to expand output directory structure</b></summary>

```
traj_logs/qwen3vl-full/
├── metadata.json
├── 001-FindProductAndFilter/
│   ├── traj.json
│   ├── result.txt
│   ├── thread_<id>.log
│   ├── screenshots/
│   │   └── 001-FindProductAndFilter-0-1.png
│   └── marked_screenshots/
│       └── marked-001-FindProductAndFilter-0-1.png
├── _attempt_trajs/
│   └── 001-FindProductAndFilter/
│       └── attempt_2/
│           ├── traj.json
│           ├── result.txt
│           └── screenshots/
└── _memgui_eval/
    ├── results.csv
    └── 001-FindProductAndFilter/
        └── qwen3vl/
            └── attempt_1/
                ├── log.json
                ├── 0.png, 1.png, ...
                ├── final_decision.json
                └── evaluation_summary.json
```

</details>

---

## 📊 Metrics

The benchmark automatically computes:

| Metric               | Description                                  |
| -------------------- | -------------------------------------------- |
| **Pass@K**     | Success rate within K attempts               |
| **IRR**        | Information Retrieval Rate (memory accuracy) |
| **FRR**        | Failure Recovery Rate (learning from errors) |
| **MTPR**       | Memory Task Performance Ratio                |
| **Step Ratio** | Agent steps / Golden steps                   |
| **Time/Step**  | Average execution time per step              |
| **Cost/Step**  | API cost per step (if applicable)            |

MemGUI-Eval details are saved under `_memgui_eval/`; MobileWorld-facing scores are
written to each task's `result.txt`.

---

## 🤖 Adding a New Agent

MemGUI-Bench now uses MobileWorld's agent interface. Add or reuse an agent under
`src/mobile_world/agents/implementations/`, then register it in
`src/mobile_world/agents/registry.py`.

Agents receive MobileWorld observations and return a prediction string plus a
`JSONAction`. Android action execution, screenshots, trajectory logging, and
parallel scheduling are handled by the shared MobileWorld runtime.

---

## 📤 Leaderboard Submission

After running the benchmark:

### 1. Submit Results JSON (Required)

Create or update a metadata JSON under `docs/data/agents/`:

```json
{
  "name": "YourAgent",
  "backbone": "GPT-4V",
  "type": "Agentic Workflow",
  "institution": "Your Institution",
  "date": "2026-02-03",
  "paperLink": "https://arxiv.org/...",
  "codeLink": "https://github.com/...",
  "hasUITree": true,
  "hasLongTermMemory": false
}
```

Submit via Pull Request to [lgy0404/MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) → `docs/data/agents/`

### 2. Upload Trajectories (Optional but Recommended)

Compress and submit via PR to [lgy0404/memgui-bench-trajs](https://huggingface.co/datasets/lgy0404/memgui-bench-trajs):

```bash
# Compress MobileWorld trajectory folder
cd traj_logs && zip -r your-agent-name.zip memgui-run-name

# Upload via HuggingFace Web UI:
# 1. Go to https://huggingface.co/datasets/lgy0404/memgui-bench-trajs
# 2. Click "Community" → "New Pull Request" → "Upload files"
# 3. Upload your zip file and submit the PR
```

See [submission guide](https://lgy0404.github.io/MemGUI-Bench/submission.html) for details.

---

## 📚Tasks

<div align="left">
  <img src="assets/task-distributions.drawio.png" alt="Task Distribution" width="90%" />
</div>

<table>
  <thead>
    <tr>
      <th>File</th>
      <th>Tasks</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>memgui-tasks-all.csv</code></td>
      <td align="center">128</td>
      <td>Full benchmark</td>
    </tr>
    <tr>
      <td><code>memgui-tasks-40.csv</code></td>
      <td align="center">40</td>
      <td>Subset for quick testing</td>
    </tr>
  </tbody>
</table>

<details>
  <summary><strong>Task Fields</strong> (click to expand)</summary>

<ul>
    <li><code>task_identifier</code></li>
    <li><code>task_description</code></li>
    <li><code>task_app</code></li>
    <li><code>num_apps</code></li>
    <li><code>requires_ui_memory</code></li>
    <li><code>task_difficulty</code></li>
    <li><code>golden_steps</code></li>
  </ul>

</details>

---

## 📝 Citation

```bibtex
@misc{liu2026memguibenchbenchmarkingmemorymobile,
  title={MemGUI-Bench: Benchmarking Memory of Mobile GUI Agents in Dynamic Environments},
  author={Guangyi Liu and Pengxiang Zhao and Yaozhen Liang and Qinyi Luo and Shunye Tang and Yuxiang Chai and Weifeng Lin and Han Xiao and WenHao Wang and Siheng Chen and Zhengxi Lu and Gao Wu and Hao Wang and Liang Liu and Yong Liu},
  year={2026},
  eprint={2602.06075},
  archivePrefix={arXiv},
  primaryClass={cs.DC},
  url={https://arxiv.org/abs/2602.06075},
}
```

---

## 📧 Contact

For questions, issues, or collaborations, please contact: **guangyiliu@zju.edu.cn**

---

## ⭐ Star History

If you find MemGUI-Bench helpful, please consider giving us a star ⭐!

[![Star History Chart](https://api.star-history.com/svg?repos=lgy0404/MemGUI-Bench&type=Date)](https://star-history.com/#lgy0404/MemGUI-Bench&Date)
