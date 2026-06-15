// MemGUI-Bench Configuration
// Agent list is loaded from data/index.json, with a checked-in fallback so the
// leaderboard still works when opened from a static file preview.

const DEFAULT_AGENT_FILES = [
  "agent-s2",
  "appagent",
  "cogagent",
  "gui-owl-7b",
  "m3a",
  "mobile-agent-e",
  "mobile-agent-v2",
  "seeact",
  "t3a",
  "ui-tars-1.5-7b",
  "ui-venus-7b",
  "qwen3-vl-8b-instruct",
  "qwen3-vl-32b-instruct",
  "qwen3-vl-235b-a22b-instruct",
  "qwen3-vl-235b-a22b-thinking",
  "gui-owl-1.5-8b-instruct",
  "gui-owl-1.5-32b-instruct"
];

let AGENT_FILES = [...DEFAULT_AGENT_FILES];
let TRAJ_FILES = null;
let TRAJ_FILE_URLS = new Map();
const DATA_BASE_PATHS = ["data", "docs/data"];
const TRAJ_DATASET_BASE_URL = "https://huggingface.co/datasets/lgy0404/memgui-bench-trajs/resolve/main/";
const TRAJ_REMOTE_BASE_URL = `${TRAJ_DATASET_BASE_URL}site/trajs/`;
const TRAJ_MANIFEST_PATHS = [
  `${TRAJ_REMOTE_BASE_URL}index.json`,
  "trajs/index.json",
  "docs/trajs/index.json",
];

// Task counts (fixed for MemGUI-Bench)
const TASK_COUNTS = {
  total: 128,
  difficulty: {
    easy: 48,
    medium: 42,
    hard: 38
  },
  crossApp: {
    app1: 28,
    app2: 56,
    app3: 34,
    app4: 10
  }
};

// Load agent list from data/index.json
async function fetchBenchmarkJson(relativePath) {
  let lastError = null;
  for (const basePath of DATA_BASE_PATHS) {
    try {
      const response = await fetch(`${basePath}/${relativePath}`);
      if (response.ok) {
        return response.json();
      }
      lastError = new Error(`${response.status} ${response.statusText}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error(`Failed to load ${relativePath}`);
}

async function loadAgentList() {
  try {
    const data = await fetchBenchmarkJson('index.json');
    AGENT_FILES = data.agents?.length ? data.agents : [...DEFAULT_AGENT_FILES];
  } catch (error) {
    console.error('Failed to load agent list:', error);
    AGENT_FILES = [...DEFAULT_AGENT_FILES];
  }
  return AGENT_FILES;
}

function normalizeTrajPath(path) {
  return String(path || '').replace(/^\.?\//, '');
}

function isAbsoluteUrl(path) {
  return /^https?:\/\//i.test(String(path || ''));
}

function manifestFileUrl(manifestPath, filePath) {
  if (isAbsoluteUrl(filePath)) return filePath;
  const normalized = normalizeTrajPath(filePath);
  if (!isAbsoluteUrl(manifestPath)) return normalized;
  const relativeName = normalized.replace(/^trajs\//, '').replace(/^site\/trajs\//, '');
  return new URL(relativeName, manifestPath).href;
}

async function loadTrajManifest() {
  for (const manifestPath of TRAJ_MANIFEST_PATHS) {
    try {
      const response = await fetch(manifestPath);
      if (!response.ok) continue;
      const data = await response.json();
      const files = Array.isArray(data.files) ? data.files : [];
      TRAJ_FILES = new Set();
      TRAJ_FILE_URLS = new Map();
      files.forEach((file) => {
        const path = normalizeTrajPath(file);
        const shortPath = path.replace(/^trajs\//, '').replace(/^site\/trajs\//, '');
        const localPath = `trajs/${shortPath}`;
        const url = manifestFileUrl(manifestPath, path);
        [path, shortPath, localPath].forEach((key) => {
          TRAJ_FILES.add(key);
          TRAJ_FILE_URLS.set(key, url);
        });
      });
      return TRAJ_FILES;
    } catch (error) {
      // Try the next static path.
    }
  }
  TRAJ_FILE_URLS = new Map();
  TRAJ_FILES = new Set();
  return TRAJ_FILES;
}

function hasTrajectoryBundle(agent) {
  if (!agent?.trajFile) return false;
  if (!TRAJ_FILES) return true;
  const path = normalizeTrajPath(agent.trajFile);
  return TRAJ_FILES.has(path) || TRAJ_FILES.has(path.replace(/^trajs\//, ''));
}

function trajectoryBundleUrl(agent) {
  if (!agent?.trajFile) return '';
  if (isAbsoluteUrl(agent.trajFile)) return agent.trajFile;
  const path = normalizeTrajPath(agent.trajFile);
  return TRAJ_FILE_URLS.get(path) || TRAJ_FILE_URLS.get(path.replace(/^trajs\//, '')) || agent.trajFile;
}
