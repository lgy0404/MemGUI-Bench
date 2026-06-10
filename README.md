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

- [💾 Environment Setup](#-environment-setup)
- [⚙️ Configuration](#️-configuration)
- [🚀 Usage](#-usage)
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


## 💾 Environment Setup

<div align="center">
  <img src="assets/unified-architecture.drawio.png" alt="Task Distribution" width="100%" />
</div>

### System Requirements

- **Linux host** with Docker and KVM acceleration
- Permission to run privileged Docker containers
- Python 3.11 and `uv` on the host

The Docker image already includes the Android SDK, ADB, emulator binaries,
MemGUI-AVD snapshot, Python dependencies, and benchmark code. Users do not need
to install Android Studio, download AVD snapshots, or configure emulator paths.

### Quick Install

```bash
# Create local config.yaml and edit the API/model fields
uv run mg env init

# Check Docker/KVM and pull the pre-configured image if needed
sudo uv run mg env check

# Launch ready MemGUI backend containers with local config/results mounted
sudo uv run mg env run --count 4

# Run the benchmark from the host; --num-emulators controls backend count
sudo uv run mg eval \
  --agent-type Qwen3VL \
  --tasks ALL \
  --session-id my-experiment \
  --num-emulators 4
```

`mg env run` starts detached privileged backend containers from the configured
image, maps backend ports from `http://localhost:6800`, maps the trajectory
viewer port from `http://localhost:8760`, and waits for `/health` before the
container is treated as ready. It also mounts the host `./config.yaml` and
`./results` into the container, so trajectory logs are stored locally instead of
inside the container filesystem.
Use `sudo uv run mg env run --results-dir ./my-results` to choose a different
local trajectory directory. `mg eval --num-emulators N` discovers N MemGUI
backends on the host and feeds tasks to them through a dynamic queue, with one
Android emulator inside each backend container.

### Environment Configuration

On the host, create `config.yaml` from the example:

```bash
uv run mg env init
```

Edit only the experiment and API fields:

- `BASE_URL`: OpenAI-compatible model endpoint
- `QWEN_API_KEY`: API key for the evaluated agent model
- `MEMGUI_API_KEY`: API key for MemGUI-Eval
- `QWEN_MODEL`: Agent model name
- `NUM_OF_EMULATOR`: Number of parallel MemGUI backend containers

## ⚙️ Configuration

Minimal `config.yaml` fields to edit:

```yaml
ENVIRONMENT_MODE: "docker"

BASE_URL: "https://api.openai.com/v1"
QWEN_API_KEY: "your-api-key"
QWEN_MODEL: "qwen3-vl-8b"
MEMGUI_API_KEY: "your-api-key"

AGENT_NAME: "Qwen3VL"
DATASET_PATH: "./data/memgui-tasks-all.csv"
SESSION_ID_SUFFIX: "my-experiment"
NUM_OF_EMULATOR: 4
MAX_EVAL_SUBPROCESS: 8
```

---

## 🚀 Usage

MemGUI-Bench provides a MobileWorld-style CLI for running experiments, checking
configuration, and browsing trajectories.

### Quick Start

```bash
# 1. Create/edit local config.yaml
uv run mg env init

# 2. Check Docker/KVM, pull the image, and launch containers
sudo uv run mg env check
sudo uv run mg env run --count 4

# 3. Run the full benchmark from the host
sudo uv run mg eval \
  --agent-type Qwen3VL \
  --tasks ALL \
  --session-id my-experiment \
  --max-attempts 3 \
  --num-emulators 4
```

`mg eval --num-emulators 4` discovers four MemGUI backend containers and feeds
the selected tasks through a dynamic environment queue. Each backend runs
exactly one Android emulator and writes trajectories into the mounted local
`./results` directory.

For a single-container debug shell:

```bash
sudo uv run mg env exec
uv run mg eval \
  --agent-type Qwen3VL \
  --tasks 001-FindProductAndFilter \
  --session-id my-experiment \
  --max-attempts 3 \
  --num-emulators 1 \
  --no-container
```

View trajectories and results from the host:

```bash
uv run mg logs view --log-dir results/session-my-experiment
```

The viewer opens a local web UI at `http://localhost:8760`, with task-level
status, per-attempt screenshots, action traces, evaluator decisions, IRR, and
BadCase analysis. Because `mg env run` mounts host `./results`, the same
`results/session-*` directories are available on the host after the container
exits or is removed.

### Available Commands

| Command | Description |
| ------- | ----------- |
| `sudo uv run mg env check` | Check Docker/KVM and pull the configured image if needed |
| `sudo uv run mg env run` | Launch container(s) with local config/results mounted |
| `sudo uv run mg env list` | List MemGUI-Bench containers |
| `sudo uv run mg env exec` | Open a shell or run a command in a container for debugging |
| `sudo uv run mg env rm` | Remove MemGUI-Bench containers |
| `uv run mg env init` | Create `config.yaml` from `config.yaml.example.opensource` |
| `uv run mg server` | Run the backend service inside a container; normally started by `mg env run` |
| `sudo uv run mg eval` / `sudo uv run mg run` | Run execution/evaluation across MemGUI containers |
| `uv run mg info task` | List or filter benchmark tasks |
| `uv run mg info agent` | List configured agents |
| `uv run mg info app` | Show app-level task counts |
| `uv run mg logs view` | Launch the interactive trajectory viewer |
| `uv run mg logs results` | Print a compact session summary table |
| `uv run mg logs export` | Export a static HTML trajectory site |

### `mg eval` Arguments

| Argument            | Default  | Description                                |
| ------------------- | -------- | ------------------------------------------ |
| `--agent-type` / `--agents` | config | Agent name(s), comma-separated             |
| `--tasks`         | `ALL`    | Task id(s), comma-separated, or `ALL`      |
| `--mode`          | `full` | `full` (exec+eval) / `exec` / `eval` |
| `--session-id`    | config   | Session identifier for results             |
| `--max-attempts`  | 3        | Max attempts per task                      |
| `--num-emulators` | config   | Override `NUM_OF_EMULATOR`                 |
| `--max-concurrency` | config | Alias for `--num-emulators`                |
| `--aw-host` / `--backend` | auto | Comma-separated backend URL(s); auto-discovered when omitted |
| `--auto-retry` | 0 | Retry backend task failures at the host scheduling layer |
| `--no-container` | False | Run in the current environment instead of backend containers |
| `--model-name`    | config   | Override the agent model name              |
| `--llm-base-url`  | config   | Override OpenAI-compatible base URL        |
| `--api-key`       | config   | Override the agent API key                 |
| `--memgui-api-key` | `--api-key` | Override the evaluator API key         |
| `--overwrite`     | False    | Overwrite existing results                 |
| `--no-concurrent` | False    | Disable parallel execution                 |

### Examples

```bash
# Full benchmark (execution + evaluation)
uv run mg eval --agent-type Qwen3VL --tasks ALL --session-id qwen3vl-full

# Run specific task
uv run mg eval --agent-type Qwen3VL --tasks 001-FindProductAndFilter --session-id debug

# Evaluation only (on existing trajectories)
uv run mg eval --mode eval --session-id my-experiment

# Multiple attempts
uv run mg eval --max-attempts 5 --session-id pass5

# Disable parallel execution
uv run mg eval --no-concurrent --session-id single-backend

# Print the underlying runner command without executing it
uv run mg eval --agent-type Qwen3VL --tasks 001-FindProductAndFilter --dry-run
```

### Viewing and Exporting Results

```bash
# Interactive web viewer
uv run mg logs view --log-dir results/session-my-experiment --port 8760

# Terminal summary
uv run mg logs results results/session-my-experiment

# Static HTML export for sharing or archiving
uv run mg logs export \
  --log-dir results/session-my-experiment \
  --output exported-sites/my-experiment
```

---

## 📁 Benchmark Session

Each `session_id` creates an isolated benchmark folder in local `./results/`.
When running in Docker through `mg env run`, this directory is mounted into the
container and remains on the host.

- The dataset is copied to `results.csv` to track progress
- Re-running the same session resumes from incomplete tasks
- Results accumulate across runs

### Output Structure

<details>
<summary><b>Click to expand output directory structure</b></summary>

```
results/session-{session_id}/
├── results.csv                    # Aggregated execution & evaluation metrics
├── results.csv.lock               # File lock for concurrent access
├── metrics_summary.json           # Computed benchmark metrics
├── {agent_name}.json              # Leaderboard format (for submission)
├── config.yaml                    # Config snapshot for reproducibility
│
└── {task_id}/
    └── {agent_name}/
        └── attempt_{n}/
            ├── log.json                    # Execution log with actions
            ├── 0.png, 1.png, ...          # Raw screenshots per step
            ├── stdout.txt, stderr.txt     # Process output logs
            ├── error.json                 # Error info (if any)
            │
            ├── visualize_actions/         # Action visualization images
            │   └── step_1.png, step_2.png, ...
            │
            ├── single_actions/            # Individual action screenshots
            │   └── step_1.png, step_2.png, ...
            │
            ├── puzzle/                    # Evaluation puzzle images
            │   ├── puzzle.png
            │   ├── pre_eval_puzzle.png
            │   └── supplemental_puzzle.png (if needed)
            │
            ├── evaluation_summary.json    # Detailed evaluation results
            ├── final_decision.json        # Final evaluation decision
            ├── irr_analysis.json          # IRR evaluation results
            ├── badcase_analysis.json      # BadCase classification
            └── step_*_description.json    # Step-by-step analysis
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

Results are saved to `metrics_summary.json` and `{agent_name}.json` (leaderboard format).

---

## 🤖 Adding a New Agent

### Step 1: Add Config

Add your agent to `config.yaml`:

```yaml
AGENTS:
  - NAME: "MyAgent"
    REPO_PATH: "./framework/models/MyAgent"
    ENV_NAME: ""
```

### Step 2: Implement Agent Class

Create your agent class in `framework/agents.py`:

```python
class MyAgent(AndroidWorldAgent):
    agent_name = "MyAgent"
  
    def construct_command(self, task, full_task_description, output_dir, device):
        script = "run.py"
        args = f'--task "{full_task_description}" --output {output_dir} --device {device["serial"]}'
        return script, args
```

### Step 3: Output Format

Your agent must output:

- Screenshots: `0.png`, `1.png`, ... (one per step)
- Log file: `log.json` with execution summary

The benchmark handles evaluation automatically.

---

## 📤 Leaderboard Submission

After running the benchmark:

### 1. Submit Results JSON (Required)

Find `{agent_name}.json` in your session folder and fill in metadata:

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
# Compress session folder
cd results && zip -r your-agent-name.zip session-{id}

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
