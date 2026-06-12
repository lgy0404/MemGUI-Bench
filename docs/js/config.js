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
const DATA_BASE_PATHS = ["data", "docs/data"];

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
