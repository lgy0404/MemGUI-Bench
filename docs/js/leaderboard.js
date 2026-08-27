// Leaderboard JavaScript
// Note: AGENT_FILES is defined in config.js (loaded before this script)

let leaderboardData = null;
let currentFilters = {
  agentType: 'all',  // 'all', 'workflow', 'model'
  uiTree: 'all',     // 'all', 'with', 'without'
  ltm: 'all',        // 'all', 'with', 'without'
  sortBy: 'avg_p1_desc'
};

// Sort options for each tab
const sortOptions = {
  main: [
    { value: 'avg_p1_desc', label: 'Avg p@1 ↓' },
    { value: 'avg_p3_desc', label: 'Avg p@3 ↓' },
    { value: 'irr_desc', label: 'IRR ↓' },
    { value: 'mtpr_desc', label: 'MTPR ↓' },
    { value: 'frr_desc', label: 'FRR ↓' }
  ],
  crossapp: [
    { value: 'avg_p1_desc', label: 'Avg p@1 ↓' },
    { value: 'avg_p3_desc', label: 'Avg p@3 ↓' },
    { value: 'irr_desc', label: 'Avg IRR ↓' },
    { value: 'app1_sr_desc', label: '1App p@1 ↓' },
    { value: 'app1_p3_desc', label: '1App p@3 ↓' },
    { value: 'app1_irr_desc', label: '1App IRR ↓' },
    { value: 'app2_sr_desc', label: '2App p@1 ↓' },
    { value: 'app2_p3_desc', label: '2App p@3 ↓' },
    { value: 'app2_irr_desc', label: '2App IRR ↓' },
    { value: 'app3_sr_desc', label: '3App p@1 ↓' },
    { value: 'app3_p3_desc', label: '3App p@3 ↓' },
    { value: 'app3_irr_desc', label: '3App IRR ↓' },
    { value: 'app4_sr_desc', label: '4App p@1 ↓' },
    { value: 'app4_p3_desc', label: '4App p@3 ↓' },
    { value: 'app4_irr_desc', label: '4App IRR ↓' }
  ],
  difficulty: [
    { value: 'avg_p1_desc', label: 'Avg p@1 ↓' },
    { value: 'avg_p3_desc', label: 'Avg p@3 ↓' },
    { value: 'irr_desc', label: 'Avg IRR ↓' },
    { value: 'easy_p1_desc', label: 'Easy p@1 ↓' },
    { value: 'easy_p3_desc', label: 'Easy p@3 ↓' },
    { value: 'easy_irr_desc', label: 'Easy IRR ↓' },
    { value: 'med_p1_desc', label: 'Med p@1 ↓' },
    { value: 'med_p3_desc', label: 'Med p@3 ↓' },
    { value: 'med_irr_desc', label: 'Med IRR ↓' },
    { value: 'hard_p1_desc', label: 'Hard p@1 ↓' },
    { value: 'hard_p3_desc', label: 'Hard p@3 ↓' },
    { value: 'hard_irr_desc', label: 'Hard IRR ↓' }
  ],
  efficiency: [
    { value: 'p1_step_asc', label: 'p@1 Steps (Fewest)' },
    { value: 'p1_time_asc', label: 'p@1 Time/Step (Fastest)' },
    { value: 'p1_cost_asc', label: 'p@1 Cost/Step (Lowest)' },
    { value: 'p3_step_asc', label: 'p@3 Steps (Fewest)' },
    { value: 'p3_time_asc', label: 'p@3 Time/Step (Fastest)' },
    { value: 'p3_cost_asc', label: 'p@3 Cost/Step (Lowest)' }
  ]
};

let currentTab = 'main';
const resultViewMeta = {
  main: {
    title: 'Main Results',
    subtitle: 'Average performance across all 128 tasks'
  },
  difficulty: {
    title: 'Difficulty',
    subtitle: 'Breakdown across easy, medium, and hard tasks'
  },
  crossapp: {
    title: 'Cross-App',
    subtitle: 'Performance by number of apps involved'
  },
  efficiency: {
    title: 'Efficiency',
    subtitle: 'Step, time, and API cost trade-offs'
  }
};

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
  await loadAgentList();  // Load agent list from index.json first
  await loadTrajManifest();
  await loadData();
  setupEventListeners();
  updateSortOptions('main');
  renderTables();
});

// Load data from individual agent JSON files
async function loadData() {
  try {
    // Load each agent file in parallel
    const agentPromises = AGENT_FILES.map(async (agentId) => {
      try {
        return await fetchBenchmarkJson(`agents/${agentId}.json`);
      } catch (error) {
        console.warn(`Failed to load agent: ${agentId}`);
        return null;
      }
    });
    
    const agents = (await Promise.all(agentPromises)).filter(a => a !== null);
    if (AGENT_FILES.length > 0 && agents.length === 0) {
      throw new Error('No agent result files could be loaded');
    }
    
    leaderboardData = {
      lastUpdated: new Date().toISOString().split('T')[0],
      agents: agents
    };
  } catch (error) {
    console.error('Error loading leaderboard data:', error);
    document.getElementById('mainTable').innerHTML = '<p class="text-center text-danger">Error loading data.</p>';
  }
}

// Update sort options based on current tab
function updateSortOptions(tab) {
  const select = document.getElementById('sortBy');
  const options = sortOptions[tab] || sortOptions.main;
  
  select.innerHTML = options.map(opt => 
    `<option value="${opt.value}">${opt.label}</option>`
  ).join('');
  
  // Set default sort for this tab
  currentFilters.sortBy = options[0].value;
  select.value = options[0].value;
}

// Setup event listeners
function setupEventListeners() {
  // Tab change listeners
  document.querySelectorAll('#mainTabs .nav-link').forEach(tab => {
    tab.addEventListener('shown.bs.tab', (e) => {
      const tabId = e.target.id;
      if (tabId === 'main-tab') {
        currentTab = 'main';
        updateSortOptions('main');
      } else if (tabId === 'crossapp-tab') {
        currentTab = 'crossapp';
        updateSortOptions('crossapp');
      } else if (tabId === 'difficulty-tab') {
        currentTab = 'difficulty';
        updateSortOptions('difficulty');
      } else if (tabId === 'efficiency-tab') {
        currentTab = 'efficiency';
        updateSortOptions('efficiency');
      }
      renderTables();
    });
  });

  document.querySelectorAll('#resultViewTabs .home-view-tab').forEach(button => {
    button.addEventListener('click', () => {
      const view = button.dataset.view || 'main';
      setActiveResultView(view);
    });
  });
  
  // Agent type filter
  document.getElementById('agentTypeFilter').addEventListener('change', (e) => {
    currentFilters.agentType = e.target.value;
    renderTables();
  });
  
  // UI Tree filter
  document.getElementById('filterUITree').addEventListener('change', (e) => {
    currentFilters.uiTree = e.target.value;
    renderTables();
  });
  
  // LTM filter
  document.getElementById('filterLTM').addEventListener('change', (e) => {
    currentFilters.ltm = e.target.value;
    renderTables();
  });
  
  // Sort selector
  document.getElementById('sortBy').addEventListener('change', (e) => {
    currentFilters.sortBy = e.target.value;
    renderTables();
  });
  
  // Clear filters
  document.getElementById('clearFilters').addEventListener('click', () => {
    currentFilters = { agentType: 'all', uiTree: 'all', ltm: 'all', sortBy: sortOptions[currentTab][0].value };
    document.getElementById('agentTypeFilter').value = 'all';
    document.getElementById('filterUITree').value = 'all';
    document.getElementById('filterLTM').value = 'all';
    updateSortOptions(currentTab);
    renderTables();
  });
}

function setActiveResultView(view) {
  currentTab = view;
  updateSortOptions(view);

  document.querySelectorAll('#resultViewTabs .home-view-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.view === view);
  });

  document.querySelectorAll('[data-view-panel]').forEach(panel => {
    const isActive = panel.dataset.viewPanel === view;
    panel.hidden = !isActive;
    panel.classList.toggle('active', isActive);
  });

  const meta = resultViewMeta[view] || resultViewMeta.main;
  const title = document.getElementById('resultViewTitle');
  const subtitle = document.getElementById('resultViewSubtitle');
  if (title) title.textContent = meta.title;
  if (subtitle) subtitle.textContent = meta.subtitle;

  renderTables();
}

// Filter and sort data
function getFilteredData() {
  if (!leaderboardData) return [];
  
  let data = [...leaderboardData.agents];
  
  // Filter by agent type
  if (currentFilters.agentType === 'model') {
    data = data.filter(agent => agent.type === 'Agent-as-a-Model');
  } else if (currentFilters.agentType === 'workflow') {
    data = data.filter(agent => agent.type === 'Agentic Workflow');
  }
  
  // Apply UI Tree filter
  if (currentFilters.uiTree === 'with') {
    data = data.filter(agent => agent.hasUITree);
  } else if (currentFilters.uiTree === 'without') {
    data = data.filter(agent => !agent.hasUITree);
  }
  
  // Apply LTM filter
  if (currentFilters.ltm === 'with') {
    data = data.filter(agent => agent.hasLongTermMemory);
  } else if (currentFilters.ltm === 'without') {
    data = data.filter(agent => !agent.hasLongTermMemory);
  }
  
  // Sort
  data.sort((a, b) => {
    const sortKey = currentFilters.sortBy;
    const isAsc = sortKey.endsWith('_asc');
    const multiplier = isAsc ? 1 : -1;
    
    // Get sort value based on key (returns null if data is missing)
    const getValue = (agent) => {
      // Main tab metrics
      if (sortKey.startsWith('avg_p3')) return agent.avg?.p3 ?? null;
      if (sortKey.startsWith('avg_p1')) return agent.avg?.p1 ?? null;
      if (sortKey.startsWith('easy_p1')) return agent.difficulty?.easy?.p1 ?? null;
      if (sortKey.startsWith('easy_p3')) return agent.difficulty?.easy?.p3 ?? null;
      if (sortKey.startsWith('easy_irr')) return agent.difficulty?.easy?.irr ?? null;
      if (sortKey.startsWith('med_p1')) return agent.difficulty?.medium?.p1 ?? null;
      if (sortKey.startsWith('med_p3')) return agent.difficulty?.medium?.p3 ?? null;
      if (sortKey.startsWith('med_irr')) return agent.difficulty?.medium?.irr ?? null;
      if (sortKey.startsWith('hard_p1')) return agent.difficulty?.hard?.p1 ?? null;
      if (sortKey.startsWith('hard_p3')) return agent.difficulty?.hard?.p3 ?? null;
      if (sortKey.startsWith('hard_irr')) return agent.difficulty?.hard?.irr ?? null;
      if (sortKey.startsWith('irr_')) return agent.metrics?.shortTerm?.irr ?? null;
      if (sortKey.startsWith('mtpr')) return agent.metrics?.shortTerm?.mtpr ?? null;
      if (sortKey.startsWith('frr')) return agent.metrics?.longTerm?.frr ?? null;
      
      // Cross-App metrics
      if (sortKey.startsWith('app1_sr')) return agent.crossApp?.app1?.p1 ?? null;
      if (sortKey.startsWith('app1_p3')) return agent.crossApp?.app1?.p3 ?? null;
      if (sortKey.startsWith('app1_irr')) return agent.crossApp?.app1?.irr ?? null;
      if (sortKey.startsWith('app2_sr')) return agent.crossApp?.app2?.p1 ?? null;
      if (sortKey.startsWith('app2_p3')) return agent.crossApp?.app2?.p3 ?? null;
      if (sortKey.startsWith('app2_irr')) return agent.crossApp?.app2?.irr ?? null;
      if (sortKey.startsWith('app3_sr')) return agent.crossApp?.app3?.p1 ?? null;
      if (sortKey.startsWith('app3_p3')) return agent.crossApp?.app3?.p3 ?? null;
      if (sortKey.startsWith('app3_irr')) return agent.crossApp?.app3?.irr ?? null;
      if (sortKey.startsWith('app4_sr')) return agent.crossApp?.app4?.p1 ?? null;
      if (sortKey.startsWith('app4_p3')) return agent.crossApp?.app4?.p3 ?? null;
      if (sortKey.startsWith('app4_irr')) return agent.crossApp?.app4?.irr ?? null;
      
      // Efficiency metrics - Short-Term (p@1)
      if (sortKey.startsWith('p1_step')) return agent.metrics?.shortTerm?.stepRatio ?? null;
      if (sortKey.startsWith('p1_time')) return agent.metrics?.shortTerm?.timePerStep ?? null;
      if (sortKey.startsWith('p1_cost')) return agent.metrics?.shortTerm?.costPerStep ?? null;
      
      // Efficiency metrics - Long-Term (p@3)
      if (sortKey.startsWith('p3_step')) return agent.metrics?.longTerm?.stepRatio ?? null;
      if (sortKey.startsWith('p3_time')) return agent.metrics?.longTerm?.timePerStep ?? null;
      if (sortKey.startsWith('p3_cost')) return agent.metrics?.longTerm?.costPerStep ?? null;
      
      return agent.avg?.p1 ?? null;
    };
    
    const valA = getValue(a);
    const valB = getValue(b);
    
    // Handle null values - always put them at the end
    if (valA === null && valB === null) return 0;
    if (valA === null) return 1;  // a goes to end
    if (valB === null) return -1; // b goes to end
    
    return (valA - valB) * multiplier;
  });
  
  return data;
}

// Find best and second best values
function findBestValues(data) {
  const metrics = ['app1_p1', 'app1_p3', 'app2_p1', 'app2_p3', 'app3_p1', 'app3_p3', 'app4_p1', 'app4_p3',
                   'easy_p1', 'easy_p3', 'easy_irr', 'med_p1', 'med_p3', 'med_irr', 'hard_p1', 'hard_p3', 'hard_irr',
                   'avg_p1', 'avg_p3', 'irr', 'mtpr', 'frr'];
  const best = {};
  const second = {};
  
  metrics.forEach(metric => {
    const values = data.map(agent => {
      if (metric === 'irr' || metric === 'mtpr') {
        return agent.metrics?.shortTerm?.[metric] ?? null;
      } else if (metric === 'frr') {
        return agent.metrics?.longTerm?.frr ?? null;
      }
      const [category, level] = metric.split('_');
      if (category.startsWith('app')) {
        const appKey = category.replace('app', 'app');
        return agent.crossApp[appKey] ? agent.crossApp[appKey][level] : 0;
      } else if (category === 'avg') {
        return agent.avg[level];
      } else {
        // Handle difficulty metrics including irr
        const diffKey = category === 'med' ? 'medium' : category;
        return agent.difficulty[diffKey] ? agent.difficulty[diffKey][level] : 0;
      }
    }).filter(v => v !== null).sort((a, b) => b - a);
    
    best[metric] = values[0] || 0;
    second[metric] = values[1] || 0;
  });
  
  return { best, second };
}

// Get sorted column key from current sort selection
function getSortedColumnKey() {
  const sortKey = currentFilters.sortBy;
  // Map sort key to column identifier
  if (sortKey.startsWith('avg_p3')) return 'avg_p3';
  if (sortKey.startsWith('avg_p1')) return 'avg_p1';
  if (sortKey.startsWith('easy_p1')) return 'easy_p1';
  if (sortKey.startsWith('easy_p3')) return 'easy_p3';
  if (sortKey.startsWith('easy_irr')) return 'easy_irr';
  if (sortKey.startsWith('med_p1')) return 'med_p1';
  if (sortKey.startsWith('med_p3')) return 'med_p3';
  if (sortKey.startsWith('med_irr')) return 'med_irr';
  if (sortKey.startsWith('hard_p1')) return 'hard_p1';
  if (sortKey.startsWith('hard_p3')) return 'hard_p3';
  if (sortKey.startsWith('hard_irr')) return 'hard_irr';
  if (sortKey.startsWith('irr')) return 'irr';
  if (sortKey.startsWith('mtpr')) return 'mtpr';
  if (sortKey.startsWith('frr')) return 'frr';
  if (sortKey.startsWith('app1_sr')) return 'app1_p1';
  if (sortKey.startsWith('app1_irr')) return 'app1_irr';
  if (sortKey.startsWith('app2_sr')) return 'app2_p1';
  if (sortKey.startsWith('app2_irr')) return 'app2_irr';
  if (sortKey.startsWith('app3_sr')) return 'app3_p1';
  if (sortKey.startsWith('app3_irr')) return 'app3_irr';
  if (sortKey.startsWith('app4_sr')) return 'app4_p1';
  if (sortKey.startsWith('app4_irr')) return 'app4_irr';
  if (sortKey.startsWith('p1_step')) return 'p1_step';
  if (sortKey.startsWith('p1_time')) return 'p1_time';
  if (sortKey.startsWith('p1_cost')) return 'p1_cost';
  if (sortKey.startsWith('p3_step')) return 'p3_step';
  if (sortKey.startsWith('p3_time')) return 'p3_time';
  if (sortKey.startsWith('p3_cost')) return 'p3_cost';
  return 'avg_p1';
}

// Format score cell
function formatScore(value, metricKey, bestValues, isSorted = false) {
  const sortedClass = isSorted ? ' sorted-column' : '';
  
  if (value === null || value === undefined) {
    return `<td class="score-cell na${sortedClass}">-</td>`;
  }
  if (value === 0) {
    return `<td class="score-cell zero${sortedClass}">0.0</td>`;
  }
  
  let className = 'score-cell';
  if (value === bestValues.best[metricKey] && value > 0) {
    className += ' best';
  } else if (value === bestValues.second[metricKey] && value > 0) {
    className += ' second';
  }
  className += sortedClass;
  
  // Format based on metric type
  let formatted;
  if (metricKey === 'mtpr') {
    formatted = value.toFixed(2);
  } else {
    formatted = value.toFixed(1);
  }
  
  return `<td class="${className}">${formatted}</td>`;
}

function escapeAttr(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function buildAgentActionLinks(agent) {
  let actionLinks = '';
  if (agent.paperLink) {
    actionLinks += `<a href="${agent.paperLink}" target="_blank" class="action-link"><i class="bi bi-file-text"></i> Paper</a>`;
  }
  if (agent.codeLink) {
    actionLinks += `<a href="${agent.codeLink}" target="_blank" class="action-link"><i class="bi bi-github"></i> Code</a>`;
  }
  if (hasTrajectoryBundle(agent)) {
    actionLinks += `<button type="button" class="action-link traj-link" data-traj-file="${escapeAttr(trajectoryBundleUrl(agent))}" data-model="${escapeAttr(agent.name)}"><i class="bi bi-signpost-split"></i> Traj</button>`;
    actionLinks += `<a href="arena.html?model=${encodeURIComponent(agent.name)}" class="action-link arena-link"><i class="bi bi-columns-gap"></i> Arena</a>`;
  }
  return actionLinks;
}

// Render tables
function renderTables(filteredData = getFilteredData()) {
  // Update result count
  const totalCount = leaderboardData ? leaderboardData.agents.length : 0;
  const countEl = document.getElementById('resultCount');
  if (filteredData.length < totalCount) {
    countEl.textContent = `Showing ${filteredData.length} of ${totalCount} agents`;
    countEl.style.display = 'inline';
  } else {
    countEl.style.display = 'none';
  }
  
  // Render Main Results table
  document.getElementById('mainTable').innerHTML = createTableHTML(filteredData);
  
  // Render Efficiency table
  document.getElementById('efficiencyTable').innerHTML = createEfficiencyTableHTML(filteredData);
  
  // Render Cross-App Complexity table
  document.getElementById('crossAppTable').innerHTML = createCrossAppTableHTML(filteredData);
  
  // Render Difficulty table
  document.getElementById('difficultyTable').innerHTML = createDifficultyTableHTML(filteredData);
}

// Create main table HTML
function createTableHTML(data) {
  if (data.length === 0) {
    return '<div class="empty-state"><i class="bi bi-search"></i><p>No agents match the current filters.</p></div>';
  }
  
  const bestValues = findBestValues(data);
  const sortedCol = getSortedColumnKey();
  
  // Helper to check if column is sorted
  const sc = (col) => sortedCol === col ? ' sorted-column' : '';
  
  let html = `
    <table class="leaderboard-table">
      <thead>
        <tr>
          <th>Rank</th>
          <th>Model & Date</th>
          <th>Type</th>
          <th class="${sc('avg_p1')}" title="Success Rate (pass@1)">p@1</th>
          <th class="${sc('avg_p3')}" title="Success Rate (pass@3)">p@3</th>
          <th class="${sc('irr')}" title="Information Retention Rate">IRR</th>
          <th class="${sc('mtpr')}" title="Memory-Task Proficiency Ratio">MTPR</th>
          <th class="${sc('frr')}" title="Failure Recovery Rate">FRR</th>
        </tr>
      </thead>
      <tbody>
  `;
  
  data.forEach((agent, index) => {
    const rank = index + 1;
    const isFirst = rank === 1;
    
    // Build tags
    let tags = '';
    if (agent.hasUITree) {
      tags += '<span class="tag tag-uitree" title="Uses UI Tree">🌳</span>';
    }
    if (agent.hasLongTermMemory) {
      tags += '<span class="tag tag-ltm" title="Long-Term Memory">🧠</span>';
    }
    
    const actionLinks = buildAgentActionLinks(agent);
    
    // Display name with backbone for workflow types
    let displayName = agent.name;
    if (agent.type === 'Agentic Workflow' && agent.backbone && agent.backbone !== '-') {
      displayName = `${agent.name} <span class="model-backbone">w/ ${agent.backbone}</span>`;
    }
    
    // Get memory metrics
    const irr = agent.metrics?.shortTerm?.irr ?? null;
    const mtpr = agent.metrics?.shortTerm?.mtpr ?? null;
    const frr = agent.metrics?.longTerm?.frr ?? null;
    
    // Rank badge class
    const rankBadgeClass = getRankBadgeClass(rank);
    
    html += `
      <tr class="${isFirst ? 'first-rank' : ''}">
        <td class="rank-cell">
          <span class="rank-badge ${rankBadgeClass}">${rank}</span>
        </td>
        <td class="model-cell">
          <div class="model-info-row">
            <span class="model-name-main">${agent.name}</span>${tags ? `<span class="tags-inline">${tags}</span>` : ''}
            ${agent.type === 'Agentic Workflow' && agent.backbone && agent.backbone !== '-' ? `<span class="model-backbone-inline">w/ ${agent.backbone}</span>` : ''}
          </div>
          <div class="model-sub-row">
            <span class="model-institution-text">${agent.institution}</span>
            <span class="model-date-text">${formatDate(agent.date)}</span>
          </div>
          ${actionLinks ? `<div class="model-links-row">${actionLinks}</div>` : ''}
        </td>
        <td class="type-cell">
          <span class="type-badge ${agent.type === 'Agentic Workflow' ? 'workflow' : 'model'}">
            ${agent.type === 'Agentic Workflow' ? 'Workflow' : 'Model'}
          </span>
        </td>
        <td class="score-cell avg-score ${agent.avg.p1 === bestValues.best.avg_p1 ? 'best' : ''}${sc('avg_p1')}">${agent.avg.p1.toFixed(1)}</td>
        <td class="score-cell avg-score ${agent.avg.p3 === bestValues.best.avg_p3 ? 'best' : ''}${sc('avg_p3')}">${agent.avg.p3.toFixed(1)}</td>
        ${formatScore(irr, 'irr', bestValues, sortedCol === 'irr')}
        ${formatScore(mtpr, 'mtpr', bestValues, sortedCol === 'mtpr')}
        ${formatScore(frr, 'frr', bestValues, sortedCol === 'frr')}
      </tr>
    `;
  });
  
  html += `
      </tbody>
    </table>
  `;
  
  return html;
}

// Create Efficiency Table
function createEfficiencyTableHTML(data) {
  if (data.length === 0) {
    return '<div class="empty-state"><i class="bi bi-search"></i><p>No agents match the current filters.</p></div>';
  }
  
  // Find best values (for efficiency, lower is better for some metrics)
  const bestStepRatio = Math.min(...data.map(a => a.metrics?.shortTerm?.stepRatio ?? 999).filter(v => v !== 999));
  const bestTime = Math.min(...data.map(a => a.metrics?.shortTerm?.timePerStep ?? 999).filter(v => v !== 999));
  const bestCost = Math.min(...data.map(a => a.metrics?.shortTerm?.costPerStep ?? 999).filter(v => v !== 999 && v !== null));
  
  const sortedCol = getSortedColumnKey();
  const sc = (col) => sortedCol === col ? ' sorted-column' : '';
  
  let html = `
    <table class="leaderboard-table efficiency-table">
      <thead>
        <tr class="header-group">
          <th rowspan="2">Rank</th>
          <th rowspan="2">Model & Date</th>
          <th rowspan="2">Type</th>
          <th colspan="3" class="stm-header">♣ Short-Term (pass@1)</th>
          <th colspan="3" class="ltm-header">♠ Long-Term (pass@3)</th>
        </tr>
        <tr class="header-subgroup">
          <th class="${sc('p1_step')}" title="Step Ratio: actual steps / golden steps">Steps</th>
          <th class="${sc('p1_time')}" title="Average time per step in seconds">Time/Step</th>
          <th class="${sc('p1_cost')}" title="Average API cost per step">Cost/Step</th>
          <th class="${sc('p3_step')}" title="Step Ratio: actual steps / golden steps">Steps</th>
          <th class="${sc('p3_time')}" title="Average time per step in seconds">Time/Step</th>
          <th class="${sc('p3_cost')}" title="Average API cost per step">Cost/Step</th>
        </tr>
      </thead>
      <tbody>
  `;
  
  data.forEach((agent, index) => {
    const stm = agent.metrics?.shortTerm;
    const ltm = agent.metrics?.longTerm;
    const rank = index + 1;
    const isFirst = rank === 1;
    
    // Build tags
    let tags = '';
    if (agent.hasUITree) tags += '<span class="tag tag-uitree" title="Uses UI Tree">🌳</span>';
    if (agent.hasLongTermMemory) tags += '<span class="tag tag-ltm" title="Long-Term Memory">🧠</span>';
    
    const actionLinks = buildAgentActionLinks(agent);
    
    // Display name with backbone for workflow types
    let displayName = agent.name;
    if (agent.type === 'Agentic Workflow' && agent.backbone && agent.backbone !== '-') {
      displayName = `${agent.name} <span class="model-backbone">w/ ${agent.backbone}</span>`;
    }
    
    // Format with delta indicator for p@3 columns
    const formatDelta = (p3Val, p1Val) => {
      if (!p3Val || !p1Val || p1Val === 0) return '';
      const delta = ((p3Val - p1Val) / p1Val) * 100;
      if (Math.abs(delta) < 0.5) return '';
      const sign = delta > 0 ? '+' : '';
      const colorClass = delta < 0 ? 'delta-good' : 'delta-bad';
      return `<span class="delta-indicator ${colorClass}">${sign}${delta.toFixed(0)}%</span>`;
    };
    
    const formatStepRatio = (val, best, isShortTerm = true, p1Val = null) => {
      const colKey = isShortTerm ? 'p1_step' : 'p3_step';
      const sortedClass = (sortedCol === colKey) ? ' sorted-column' : '';
      if (!val) return `<td class="score-cell na${sortedClass}">-</td>`;
      const isBest = Math.abs(val - best) < 0.01;
      const delta = !isShortTerm ? formatDelta(val, p1Val) : '';
      return `<td class="score-cell ${isBest ? 'best-efficiency' : ''} ${val <= 1.0 ? 'good-ratio' : val > 1.2 ? 'bad-ratio' : ''}${sortedClass}">${val.toFixed(2)}${delta}</td>`;
    };
    
    const formatTime = (val, best, isShortTerm = true, p1Val = null) => {
      const colKey = isShortTerm ? 'p1_time' : 'p3_time';
      const sortedClass = (sortedCol === colKey) ? ' sorted-column' : '';
      if (!val) return `<td class="score-cell na${sortedClass}">-</td>`;
      const isBest = Math.abs(val - best) < 0.1;
      const delta = !isShortTerm ? formatDelta(val, p1Val) : '';
      return `<td class="score-cell ${isBest ? 'best-efficiency' : ''}${sortedClass}">${val.toFixed(1)}s${delta}</td>`;
    };
    
    const formatCost = (val, best, isShortTerm = true, p1Val = null) => {
      const colKey = isShortTerm ? 'p1_cost' : 'p3_cost';
      const sortedClass = (sortedCol === colKey) ? ' sorted-column' : '';
      if (!val) return `<td class="score-cell na${sortedClass}">-</td>`;
      const isBest = Math.abs(val - best) < 0.001;
      const delta = !isShortTerm ? formatDelta(val, p1Val) : '';
      return `<td class="score-cell ${isBest ? 'best-efficiency' : ''}${sortedClass}">$${val.toFixed(4)}${delta}</td>`;
    };
    
    // Rank badge class
    const rankBadgeClass = getRankBadgeClass(rank);
    
    if (!stm && !ltm) {
      html += `
        <tr class="no-data ${isFirst ? 'first-rank' : ''}">
          <td class="rank-cell"><span class="rank-badge ${rankBadgeClass}">${rank}</span></td>
          <td class="model-cell">
            <div class="model-name">${displayName}<div class="tags">${tags}</div></div>
            <div class="model-meta">
              <span class="model-institution">${agent.institution}</span>
              <span class="model-date">${formatDate(agent.date)}</span>
            </div>
            <div class="action-links">${actionLinks}</div>
          </td>
          <td class="type-cell"><span class="type-badge ${agent.type === 'Agentic Workflow' ? 'workflow' : 'model'}">${agent.type === 'Agentic Workflow' ? 'Workflow' : 'Model'}</span></td>
          <td colspan="6" class="text-muted">No efficiency data</td>
        </tr>
      `;
      return;
    }
    
    html += `
      <tr class="${isFirst ? 'first-rank' : ''}">
        <td class="rank-cell"><span class="rank-badge ${rankBadgeClass}">${rank}</span></td>
        <td class="model-cell">
          <div class="model-name">${displayName}<div class="tags">${tags}</div></div>
          <div class="model-meta">
            <span class="model-institution">${agent.institution}</span>
            <span class="model-date">${formatDate(agent.date)}</span>
          </div>
          <div class="action-links">${actionLinks}</div>
        </td>
        <td class="type-cell"><span class="type-badge ${agent.type === 'Agentic Workflow' ? 'workflow' : 'model'}">${agent.type === 'Agentic Workflow' ? 'Workflow' : 'Model'}</span></td>
        ${formatStepRatio(stm?.stepRatio, bestStepRatio, true)}
        ${formatTime(stm?.timePerStep, bestTime, true)}
        ${formatCost(stm?.costPerStep, bestCost, true)}
        ${formatStepRatio(ltm?.stepRatio, bestStepRatio, false, stm?.stepRatio)}
        ${formatTime(ltm?.timePerStep, bestTime, false, stm?.timePerStep)}
        ${formatCost(ltm?.costPerStep, bestCost, false, stm?.costPerStep)}
      </tr>
    `;
  });
  
  html += `
      </tbody>
    </table>
  `;
  
  return html;
}

// Create Difficulty Table
function createDifficultyTableHTML(data) {
  if (data.length === 0) {
    return '<div class="empty-state"><i class="bi bi-search"></i><p>No agents match the current filters.</p></div>';
  }
  
  // Find best values for highlighting
  const bestValues = findDifficultyBestValues(data);
  const sortedCol = getSortedColumnKey();
  const sc = (col) => sortedCol === col ? ' sorted-column' : '';
  
  let html = `
    <table class="leaderboard-table difficulty-table">
      <thead>
        <tr class="header-group">
          <th rowspan="2">Rank</th>
          <th rowspan="2">Model & Date</th>
          <th rowspan="2">Type</th>
          <th colspan="3">Easy (${TASK_COUNTS.difficulty.easy} tasks)</th>
          <th colspan="3">Medium (${TASK_COUNTS.difficulty.medium} tasks)</th>
          <th colspan="3">Hard (${TASK_COUNTS.difficulty.hard} tasks)</th>
          <th colspan="3">Avg (${TASK_COUNTS.total} tasks)</th>
        </tr>
        <tr class="header-subgroup">
          <th class="${sc('easy_p1')}">p@1</th><th class="${sc('easy_p3')}">p@3</th><th class="${sc('easy_irr')}">IRR</th>
          <th class="${sc('med_p1')}">p@1</th><th class="${sc('med_p3')}">p@3</th><th class="${sc('med_irr')}">IRR</th>
          <th class="${sc('hard_p1')}">p@1</th><th class="${sc('hard_p3')}">p@3</th><th class="${sc('hard_irr')}">IRR</th>
          <th class="${sc('avg_p1')}">p@1</th><th class="${sc('avg_p3')}">p@3</th><th class="${sc('irr')}">IRR</th>
        </tr>
      </thead>
      <tbody>
  `;
  
  data.forEach((agent, index) => {
    html += createDifficultyRow(agent, bestValues, index + 1, sortedCol);
  });
  
  html += `
      </tbody>
    </table>
  `;
  
  return html;
}

// Helper: Find best values for Difficulty table
function findDifficultyBestValues(data) {
  const metrics = ['easy_p1', 'easy_p3', 'easy_irr', 'med_p1', 'med_p3', 'med_irr', 'hard_p1', 'hard_p3', 'hard_irr'];
  const best = {};
  const second = {};
  
  metrics.forEach(metric => {
    const values = data.map(agent => {
      const [level, type] = metric.split('_');
      const levelKey = level === 'med' ? 'medium' : level;
      if (type === 'p1') {
        return agent.difficulty?.[levelKey]?.p1 ?? null;
      } else if (type === 'p3') {
        return agent.difficulty?.[levelKey]?.p3 ?? null;
      } else if (type === 'irr') {
        return agent.difficulty?.[levelKey]?.irr ?? null;
      }
      return null;
    }).filter(v => v !== null && v > 0).sort((a, b) => b - a);
    
    best[metric] = values[0] || 0;
    second[metric] = values[1] || 0;
  });
  
  return { best, second };
}

// Helper: Create a row for Difficulty table
function createDifficultyRow(agent, bestValues, rank, sortedCol = '') {
  const diff = agent.difficulty;
  const isFirst = rank === 1;
  
  const formatCell = (value, metricKey, colKey) => {
    const isSorted = sortedCol === colKey;
    const sortedClass = isSorted ? ' sorted-column' : '';
    
    if (value === null || value === undefined) {
      return `<td class="score-cell na${sortedClass}">-</td>`;
    }
    if (value === 0) {
      return `<td class="score-cell zero${sortedClass}">0.0</td>`;
    }
    let className = 'score-cell';
    if (value === bestValues.best[metricKey] && value > 0) {
      className += ' best';
    } else if (value === bestValues.second[metricKey] && value > 0) {
      className += ' second';
    }
    className += sortedClass;
    return `<td class="${className}">${value.toFixed(1)}</td>`;
  };
  
  // Build tags
  let tags = '';
  if (agent.hasUITree) tags += '<span class="tag tag-uitree" title="Uses UI Tree">🌳</span>';
  if (agent.hasLongTermMemory) tags += '<span class="tag tag-ltm" title="Long-Term Memory">🧠</span>';
  
  const actionLinks = buildAgentActionLinks(agent);
  
  // Display name with backbone for workflow types
  let displayName = agent.name;
  if (agent.type === 'Agentic Workflow' && agent.backbone && agent.backbone !== '-') {
    displayName = `${agent.name} <span class="model-backbone">w/ ${agent.backbone}</span>`;
  }
  
  // Rank badge class
  const rankBadgeClass = getRankBadgeClass(rank);
  
  // Get avg IRR
  const avgIrr = agent.metrics?.shortTerm?.irr ?? null;
  
  return `
    <tr class="${isFirst ? 'first-rank' : ''}">
      <td class="rank-cell"><span class="rank-badge ${rankBadgeClass}">${rank}</span></td>
      <td class="model-cell">
        <div class="model-name">${displayName}<div class="tags">${tags}</div></div>
        <div class="model-meta">
          <span class="model-institution">${agent.institution}</span>
          <span class="model-date">${formatDate(agent.date)}</span>
        </div>
        <div class="action-links">${actionLinks}</div>
      </td>
      <td class="type-cell">
        <span class="type-badge ${agent.type === 'Agentic Workflow' ? 'workflow' : 'model'}">${agent.type === 'Agentic Workflow' ? 'Workflow' : 'Model'}</span>
      </td>
      ${formatCell(diff?.easy?.p1, 'easy_p1', 'easy_p1')}
      ${formatCell(diff?.easy?.p3, 'easy_p3', 'easy_p3')}
      ${formatCell(diff?.easy?.irr, 'easy_irr', 'easy_irr')}
      ${formatCell(diff?.medium?.p1, 'med_p1', 'med_p1')}
      ${formatCell(diff?.medium?.p3, 'med_p3', 'med_p3')}
      ${formatCell(diff?.medium?.irr, 'med_irr', 'med_irr')}
      ${formatCell(diff?.hard?.p1, 'hard_p1', 'hard_p1')}
      ${formatCell(diff?.hard?.p3, 'hard_p3', 'hard_p3')}
      ${formatCell(diff?.hard?.irr, 'hard_irr', 'hard_irr')}
      <td class="score-cell avg-score${sortedCol === 'avg_p1' ? ' sorted-column' : ''}">${agent.avg.p1.toFixed(1)}</td>
      <td class="score-cell avg-score${sortedCol === 'avg_p3' ? ' sorted-column' : ''}">${agent.avg.p3.toFixed(1)}</td>
      ${formatCell(avgIrr, 'irr', 'irr')}
    </tr>
  `;
}

// Create Cross-App Complexity Table (Table 4 in paper)
function createCrossAppTableHTML(data) {
  if (data.length === 0) {
    return '<div class="empty-state"><i class="bi bi-search"></i><p>No agents match the current filters.</p></div>';
  }
  
  // Find best values for highlighting
  const bestValues = findCrossAppBestValues(data);
  const sortedCol = getSortedColumnKey();
  const sc = (col) => sortedCol === col ? ' sorted-column' : '';
  
  let html = `
    <table class="leaderboard-table crossapp-table">
      <colgroup>
        <col class="crossapp-rank-col">
        <col class="crossapp-model-col">
        <col class="crossapp-type-col">
        ${Array.from({ length: 15 }, () => '<col class="crossapp-score-col">').join('')}
      </colgroup>
      <thead>
        <tr class="header-group">
          <th rowspan="2">Rank</th>
          <th rowspan="2">Model & Date</th>
          <th rowspan="2">Type</th>
          <th colspan="3" title="${TASK_COUNTS.crossApp.app1} tasks">1 App (${TASK_COUNTS.crossApp.app1})</th>
          <th colspan="3" title="${TASK_COUNTS.crossApp.app2} tasks">2 Apps (${TASK_COUNTS.crossApp.app2})</th>
          <th colspan="3" title="${TASK_COUNTS.crossApp.app3} tasks">3 Apps (${TASK_COUNTS.crossApp.app3})</th>
          <th colspan="3" title="${TASK_COUNTS.crossApp.app4} tasks">4 Apps (${TASK_COUNTS.crossApp.app4})</th>
          <th colspan="3" title="${TASK_COUNTS.total} tasks">Avg (${TASK_COUNTS.total})</th>
        </tr>
        <tr class="header-subgroup">
          <th class="${sc('app1_p1')}">p@1</th><th class="${sc('app1_p3')}">p@3</th><th class="${sc('app1_irr')}">IRR</th>
          <th class="${sc('app2_p1')}">p@1</th><th class="${sc('app2_p3')}">p@3</th><th class="${sc('app2_irr')}">IRR</th>
          <th class="${sc('app3_p1')}">p@1</th><th class="${sc('app3_p3')}">p@3</th><th class="${sc('app3_irr')}">IRR</th>
          <th class="${sc('app4_p1')}">p@1</th><th class="${sc('app4_p3')}">p@3</th><th class="${sc('app4_irr')}">IRR</th>
          <th class="${sc('avg_p1')}">p@1</th><th class="${sc('avg_p3')}">p@3</th><th class="${sc('irr')}">IRR</th>
        </tr>
      </thead>
      <tbody>
  `;
  
  data.forEach((agent, index) => {
    html += createCrossAppRow(agent, bestValues, index + 1, sortedCol);
  });
  
  html += `
      </tbody>
    </table>
  `;
  
  return html;
}

// Helper: Find best values for Cross-App table
function findCrossAppBestValues(data) {
  const metrics = ['app1_sr', 'app1_irr', 'app2_sr', 'app2_irr', 'app3_sr', 'app3_irr', 'app4_sr', 'app4_irr',
                   'app1_p3', 'app2_p3', 'app3_p3', 'app4_p3'];
  const best = {};
  const second = {};
  
  metrics.forEach(metric => {
    const values = data.map(agent => {
      const [appKey, type] = metric.split('_');
      const app = appKey.replace('app', 'app');
      if (type === 'sr') {
        return agent.crossApp[app]?.p1 ?? 0;
      } else if (type === 'irr') {
        return agent.crossApp[app]?.irr ?? null;
      } else if (type === 'p3') {
        return agent.crossApp[app]?.p3 ?? 0;
      }
      return 0;
    }).filter(v => v !== null && v > 0).sort((a, b) => b - a);
    
    best[metric] = values[0] || 0;
    second[metric] = values[1] || 0;
  });
  
  return { best, second };
}

// Helper: Create a row for Cross-App table
function createCrossAppRow(agent, bestValues, rank, sortedCol = '') {
  const ca = agent.crossApp;
  const isFirst = rank === 1;
  
  const formatCell = (value, metricKey, colKey) => {
    const isSorted = sortedCol === colKey;
    const sortedClass = isSorted ? ' sorted-column' : '';
    
    if (value === null || value === undefined) {
      return `<td class="score-cell na${sortedClass}">-</td>`;
    }
    if (value === 0) {
      return `<td class="score-cell zero${sortedClass}">0.0</td>`;
    }
    let className = 'score-cell';
    if (value === bestValues.best[metricKey] && value > 0) {
      className += ' best';
    } else if (value === bestValues.second[metricKey] && value > 0) {
      className += ' second';
    }
    className += sortedClass;
    return `<td class="${className}">${value.toFixed(1)}</td>`;
  };
  
  // Build tags
  let tags = '';
  if (agent.hasUITree) tags += '<span class="tag tag-uitree" title="Uses UI Tree">🌳</span>';
  if (agent.hasLongTermMemory) tags += '<span class="tag tag-ltm" title="Long-Term Memory">🧠</span>';
  
  const actionLinks = buildAgentActionLinks(agent);
  
  // Display name with backbone for workflow types
  let displayName = agent.name;
  if (agent.type === 'Agentic Workflow' && agent.backbone && agent.backbone !== '-') {
    displayName = `${agent.name} <span class="model-backbone">w/ ${agent.backbone}</span>`;
  }
  
  // Rank badge class
  const rankBadgeClass = getRankBadgeClass(rank);
  
  return `
    <tr class="${isFirst ? 'first-rank' : ''}">
      <td class="rank-cell"><span class="rank-badge ${rankBadgeClass}">${rank}</span></td>
      <td class="model-cell">
        <div class="model-name"><span class="crossapp-model-label">${displayName}</span><div class="tags">${tags}</div></div>
        <div class="model-meta">
          <span class="model-institution">${agent.institution}</span>
          <span class="model-date">${formatDate(agent.date)}</span>
        </div>
        <div class="action-links">${actionLinks}</div>
      </td>
      <td class="type-cell">
        <span class="type-badge ${agent.type === 'Agentic Workflow' ? 'workflow' : 'model'}">${agent.type === 'Agentic Workflow' ? 'Workflow' : 'Model'}</span>
      </td>
      ${formatCell(ca.app1?.p1, 'app1_sr', 'app1_p1')}
      ${formatCell(ca.app1?.p3, 'app1_p3', 'app1_p3')}
      ${formatCell(ca.app1?.irr, 'app1_irr', 'app1_irr')}
      ${formatCell(ca.app2?.p1, 'app2_sr', 'app2_p1')}
      ${formatCell(ca.app2?.p3, 'app2_p3', 'app2_p3')}
      ${formatCell(ca.app2?.irr, 'app2_irr', 'app2_irr')}
      ${formatCell(ca.app3?.p1, 'app3_sr', 'app3_p1')}
      ${formatCell(ca.app3?.p3, 'app3_p3', 'app3_p3')}
      ${formatCell(ca.app3?.irr, 'app3_irr', 'app3_irr')}
      ${formatCell(ca.app4?.p1, 'app4_sr', 'app4_p1')}
      ${formatCell(ca.app4?.p3, 'app4_p3', 'app4_p3')}
      ${formatCell(ca.app4?.irr, 'app4_irr', 'app4_irr')}
      <td class="score-cell avg-score${sortedCol === 'avg_p1' ? ' sorted-column' : ''}">${agent.avg.p1.toFixed(1)}</td>
      <td class="score-cell avg-score${sortedCol === 'avg_p3' ? ' sorted-column' : ''}">${agent.avg.p3.toFixed(1)}</td>
      ${formatCell(agent.metrics?.shortTerm?.irr, 'irr', 'irr')}
    </tr>
  `;
}

// Get rank badge CSS class
function getRankBadgeClass(rank) {
  if (rank === 1) return 'rank-1';
  if (rank === 2) return 'rank-2';
  if (rank === 3) return 'rank-3';
  if (rank <= 10) return 'rank-top10';
  return '';
}

// Format date
function formatDate(dateStr) {
  const date = new Date(dateStr);
  const options = { year: 'numeric', month: 'short', day: 'numeric' };
  return date.toLocaleDateString('en-US', options);
}
