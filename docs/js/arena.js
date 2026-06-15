// Head-to-head trajectory comparison for MemGUI-Bench.

let arenaAgents = [];
let arenaState = {
  agentA: null,
  agentB: null,
  trajUrlA: '',
  trajUrlB: '',
  dataA: null,
  dataB: null,
  activeFilter: 'all',
  activeTask: null,
  taskRows: [],
  renderGeneration: 0,
};

document.addEventListener('DOMContentLoaded', async () => {
  await loadAgentList();
  await loadTrajManifest();
  const loaded = await Promise.all(AGENT_FILES.map(async (agentId) => {
    try {
      const agent = await fetchBenchmarkJson(`agents/${agentId}.json`);
      agent.id = agentId;
      return agent;
    } catch (error) {
      console.warn(`Failed to load ${agentId}`, error);
      return null;
    }
  }));
  arenaAgents = loaded.filter((agent) => agent && hasTrajectoryBundle(agent));
  setupArena();
});

function setupArena() {
  const selectA = document.getElementById('arenaModelA');
  const selectB = document.getElementById('arenaModelB');
  const loading = document.getElementById('arenaLoading');
  const comparison = document.getElementById('arenaComparison');

  if (arenaAgents.length < 2) {
    loading.classList.add('is-active');
    loading.querySelector('span').textContent = 'At least two trajectory-enabled agents are required.';
    return;
  }

  const options = arenaAgents.map((agent) => `<option value="${agent.id}">${agent.name}</option>`).join('');
  selectA.innerHTML = options;
  selectB.innerHTML = options;

  const params = new URLSearchParams(window.location.search);
  const requestedA = params.get('modelA') || params.get('model');
  const requestedB = params.get('modelB');
  const first = findAgentId(requestedA) || arenaAgents[0].id;
  const second = findAgentId(requestedB) || arenaAgents.find((agent) => agent.id !== first)?.id || arenaAgents[1].id;
  selectA.value = first;
  selectB.value = second;
  arenaState.activeFilter = params.get('filter') || 'all';
  arenaState.activeTask = params.get('task') || null;

  selectA.addEventListener('change', loadArenaComparison);
  selectB.addEventListener('change', loadArenaComparison);
  document.getElementById('arenaMatrix').addEventListener('click', (event) => {
    const button = event.target.closest('[data-filter]');
    if (!button) return;
    arenaState.activeFilter = button.dataset.filter;
    renderArenaTaskList();
  });
  comparison.addEventListener('click', (event) => {
    const button = event.target.closest('[data-arena-expand-all]');
    if (!button) return;
    const blocks = comparison.querySelectorAll('.traj-screenshot-block');
    if (!blocks.length) return;
    const allOpen = [...blocks].every((block) => block.open);
    blocks.forEach((block) => { block.open = !allOpen; });
    updateArenaExpandAll(comparison);
  });
  comparison.addEventListener('toggle', (event) => {
    if (event.target.classList?.contains('traj-screenshot-block')) {
      updateArenaExpandAll(comparison);
    }
  }, true);

  loadArenaComparison();
}

function findAgentId(nameOrId) {
  if (!nameOrId) return null;
  const decoded = decodeURIComponent(nameOrId);
  const agent = arenaAgents.find((item) => item.id === decoded || item.name === decoded);
  return agent ? agent.id : null;
}

function agentById(id) {
  return arenaAgents.find((agent) => agent.id === id) || null;
}

async function loadArenaComparison() {
  const selectA = document.getElementById('arenaModelA');
  const selectB = document.getElementById('arenaModelB');
  const loading = document.getElementById('arenaLoading');
  const matrix = document.getElementById('arenaMatrix');
  const taskList = document.getElementById('arenaTaskList');
  const comparison = document.getElementById('arenaComparison');

  arenaState.agentA = agentById(selectA.value);
  arenaState.agentB = agentById(selectB.value);
  arenaState.trajUrlA = trajectoryBundleUrl(arenaState.agentA);
  arenaState.trajUrlB = trajectoryBundleUrl(arenaState.agentB);
  arenaState.dataA = null;
  arenaState.dataB = null;
  arenaState.taskRows = [];
  matrix.innerHTML = '';
  taskList.innerHTML = '';
  comparison.innerHTML = '<div class="arena-empty">Select two agents to compare their trajectories.</div>';
  loading.classList.add('is-active');
  loading.querySelector('span').textContent = 'Loading trajectory bundles...';

  try {
    const [dataA, dataB] = await Promise.all([
      MemGUITraj.getTrajectoryData(arenaState.trajUrlA),
      MemGUITraj.getTrajectoryData(arenaState.trajUrlB),
    ]);
    arenaState.dataA = dataA;
    arenaState.dataB = dataB;
  } catch (error) {
    loading.querySelector('span').textContent = `Failed to load trajectories: ${error.message}`;
    return;
  }

  loading.classList.remove('is-active');
  buildArenaRows();
  renderArenaMatrix();
  renderArenaTaskList();
}

function buildArenaRows() {
  const dataA = arenaState.dataA || {};
  const dataB = arenaState.dataB || {};
  const tasksA = Object.keys(dataA).filter((key) => key !== '_meta');
  const tasksB = new Set(Object.keys(dataB).filter((key) => key !== '_meta'));
  arenaState.taskRows = tasksA.filter((task) => tasksB.has(task)).sort().map((taskName) => {
    const taskA = dataA[taskName];
    const taskB = dataB[taskName];
    const attemptA = MemGUITraj.taskForAttempt(taskA, MemGUITraj.primaryAttemptIndex(taskA));
    const attemptB = MemGUITraj.taskForAttempt(taskB, MemGUITraj.primaryAttemptIndex(taskB));
    const statusA = taskStatus(taskA);
    const statusB = taskStatus(taskB);
    return {
      taskName,
      taskA,
      taskB,
      attemptA,
      attemptB,
      statusA,
      statusB,
      filter: statusA === 'unknown' || statusB === 'unknown'
        ? 'unknown'
        : `${statusA === 'pass' ? 'p' : 'f'}${statusB === 'pass' ? 'p' : 'f'}`,
      stepsA: attemptA?.traj?.length || 0,
      stepsB: attemptB?.traj?.length || 0,
    };
  });

  if (!arenaState.activeTask || !arenaState.taskRows.some((row) => row.taskName === arenaState.activeTask)) {
    arenaState.activeTask = arenaState.taskRows[0]?.taskName || null;
  }
}

function filterRows() {
  if (arenaState.activeFilter === 'all') return arenaState.taskRows;
  return arenaState.taskRows.filter((row) => row.filter === arenaState.activeFilter);
}

function taskStatus(task) {
  return MemGUITraj.taskStatus(task);
}

function renderArenaMatrix() {
  const matrix = document.getElementById('arenaMatrix');
  const counts = { all: arenaState.taskRows.length, pp: 0, pf: 0, fp: 0, ff: 0, unknown: 0 };
  arenaState.taskRows.forEach((row) => { counts[row.filter] += 1; });
  const labels = [
    ['all', 'All shared tasks'],
    ['pp', 'Both pass'],
    ['pf', `${arenaState.agentA.name} pass only`],
    ['fp', `${arenaState.agentB.name} pass only`],
    ['ff', 'Both fail'],
    ['unknown', 'Unknown result'],
  ];
  matrix.innerHTML = labels.map(([key, label]) => `
    <button type="button" class="arena-matrix-cell ${arenaState.activeFilter === key ? 'is-active' : ''}" data-filter="${key}">
      <span class="arena-cell-count">${counts[key]}</span>
      <span class="arena-cell-label">${MemGUITraj.escHtml(label)}</span>
    </button>
  `).join('');
}

function renderArenaTaskList() {
  renderArenaMatrix();
  const rows = filterRows();
  const taskList = document.getElementById('arenaTaskList');
  const count = document.getElementById('arenaTaskCount');
  count.textContent = `${rows.length} tasks`;

  if (!rows.length) {
    taskList.innerHTML = '<div class="arena-empty">No tasks in this bucket.</div>';
    document.getElementById('arenaComparison').innerHTML = '<div class="arena-empty">Choose another bucket to inspect trajectories.</div>';
    return;
  }

  if (!rows.some((row) => row.taskName === arenaState.activeTask)) {
    arenaState.activeTask = rows[0].taskName;
  }

  taskList.innerHTML = rows.map((row) => `
    <button type="button" class="arena-task-row ${row.taskName === arenaState.activeTask ? 'is-active' : ''}" data-task="${MemGUITraj.escHtml(row.taskName)}">
      <span class="arena-task-name">${MemGUITraj.escHtml(row.taskName)}</span>
      <span class="arena-task-meta">
        ${miniBadge(arenaState.agentA.name, row.statusA)}
        ${miniBadge(arenaState.agentB.name, row.statusB)}
        <span class="arena-mini-badge arena-mini-steps">${row.stepsA}/${row.stepsB} steps</span>
      </span>
    </button>
  `).join('');

  taskList.querySelectorAll('[data-task]').forEach((button) => {
    button.addEventListener('click', () => {
      arenaState.activeTask = button.dataset.task;
      renderArenaTaskList();
    });
  });
  renderArenaComparison();
}

function miniBadge(label, status) {
  const text = status === 'pass' ? 'Pass' : status === 'fail' ? 'Fail' : 'Unknown';
  return `<span class="arena-mini-badge arena-mini-${status}">${MemGUITraj.escHtml(label)} ${text}</span>`;
}

function renderArenaComparison() {
  const row = arenaState.taskRows.find((item) => item.taskName === arenaState.activeTask);
  const comparison = document.getElementById('arenaComparison');
  if (!row) {
    comparison.innerHTML = '<div class="arena-empty">No task selected.</div>';
    return;
  }

  const generation = ++arenaState.renderGeneration;
  const goal = row.attemptA?.traj?.[0]?.task_goal || row.attemptB?.traj?.[0]?.task_goal || '';
  comparison.innerHTML = `
    <div class="arena-comparison-head">
      <div class="arena-comparison-title-row">
        <h2>${MemGUITraj.escHtml(row.taskName)}</h2>
        <button type="button" class="traj-expand-all arena-expand-all" data-arena-expand-all hidden>Expand all</button>
      </div>
      ${goal ? `<div class="arena-goal">${MemGUITraj.escHtml(goal)}</div>` : ''}
    </div>
    <div class="arena-columns">
      ${arenaColumnHtml('A', arenaState.agentA, row.attemptA, arenaState.dataA?._meta, row.taskA)}
      ${arenaColumnHtml('B', arenaState.agentB, row.attemptB, arenaState.dataB?._meta, row.taskB)}
    </div>
  `;
  updateArenaExpandAll(comparison);

  const metaA = arenaState.dataA?._meta || null;
  const metaB = arenaState.dataB?._meta || null;
  const urlA = MemGUITraj.videoUrlFor(arenaState.trajUrlA, metaA);
  const urlB = MemGUITraj.videoUrlFor(arenaState.trajUrlB, metaB);
  const bodyA = comparison.querySelector('[data-arena-body="A"]');
  const bodyB = comparison.querySelector('[data-arena-body="B"]');
  if (urlA && metaA) {
    const promiseA = MemGUITraj.loadVideo(urlA);
    promiseA.then(() => {
      if (generation === arenaState.renderGeneration) MemGUITraj.renderCanvases(bodyA, row.attemptA, metaA, promiseA);
    });
  }
  if (urlB && metaB) {
    const promiseB = MemGUITraj.loadVideo(urlB);
    promiseB.then(() => {
      if (generation === arenaState.renderGeneration) MemGUITraj.renderCanvases(bodyB, row.attemptB, metaB, promiseB);
    });
  }
}

function arenaColumnHtml(side, agent, task, meta, sourceTask = null) {
  const status = taskStatus(task);
  const text = status === 'pass' ? 'Pass' : status === 'fail' ? 'Fail' : 'Unknown';
  const badgeClass = status === 'pass'
    ? 'traj-result-pass'
    : status === 'fail'
      ? 'traj-result-fail'
      : 'traj-result-unknown';
  const sourceAttempts = MemGUITraj.attemptsForTask(sourceTask || task);
  const attemptLabel = sourceAttempts.length > 1 && task?.label
    ? `<span class="arena-attempt-label">${MemGUITraj.escHtml(task.label)}</span>`
    : '';
  return `
    <section class="arena-col">
      <div class="arena-col-head">
        <span class="arena-col-name">${MemGUITraj.escHtml(agent.name)}${attemptLabel}</span>
        <span class="traj-result ${badgeClass}">${MemGUITraj.escHtml(text)}</span>
      </div>
      <div class="arena-col-body" data-arena-body="${side}">
        ${MemGUITraj.renderTaskHtml(task, meta, side)}
      </div>
    </section>
  `;
}

function updateArenaExpandAll(container) {
  const button = container.querySelector('[data-arena-expand-all]');
  if (!button) return;
  const blocks = container.querySelectorAll('.traj-screenshot-block');
  if (!blocks.length) {
    button.hidden = true;
    return;
  }
  button.hidden = false;
  button.textContent = [...blocks].every((block) => block.open) ? 'Collapse all' : 'Expand all';
}
