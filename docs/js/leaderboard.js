// Leaderboard JavaScript
// Note: AGENT_FILES is defined in config.js (loaded before this script)

let leaderboardData = null;
let currentFilters = {
  agentType: 'all',  // 'all', 'workflow', 'model'
  uiTree: 'all',     // 'all', 'with', 'without'
  ltm: 'all',        // 'all', 'with', 'without'
  sortBy: 'avg_p3_desc'
};

// Sort options for each tab
const sortOptions = {
  main: [
    { value: 'avg_p3_desc', label: 'Avg p@3 ↓' },
    { value: 'avg_p1_desc', label: 'Avg p@1 ↓' },
    { value: 'irr_desc', label: 'IRR ↓' },
    { value: 'mtpr_desc', label: 'MTPR ↓' },
    { value: 'frr_desc', label: 'FRR ↓' }
  ],
  crossapp: [
    { value: 'avg_p3_desc', label: 'Avg p@3 ↓' },
    { value: 'avg_p1_desc', label: 'Avg p@1 ↓' },
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
    { value: 'avg_p3_desc', label: 'Avg p@3 ↓' },
    { value: 'avg_p1_desc', label: 'Avg p@1 ↓' },
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

  const shareButton = document.getElementById('shareLeaderboard');
  if (shareButton) {
    shareButton.addEventListener('click', shareLeaderboardSnapshot);
  }
  
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

function inlineSnapshotStyles(source, clone) {
  if (!(source instanceof Element) || !(clone instanceof Element)) return;
  const computed = window.getComputedStyle(source);
  for (let index = 0; index < computed.length; index += 1) {
    const property = computed[index];
    clone.style.setProperty(property, computed.getPropertyValue(property), computed.getPropertyPriority(property));
  }
  if (computed.position === 'sticky' || computed.position === 'fixed') {
    clone.style.position = 'static';
  }
  clone.style.animation = 'none';
  clone.style.transition = 'none';

  const sourceChildren = Array.from(source.children);
  const cloneChildren = Array.from(clone.children);
  sourceChildren.forEach((child, index) => inlineSnapshotStyles(child, cloneChildren[index]));
}

function removeSnapshotExcluded(clone) {
  clone.querySelectorAll('[data-snapshot-exclude]').forEach((node) => node.remove());
}

function selectedOptionText(selectId, fallback = '') {
  const select = document.getElementById(selectId);
  return select?.selectedOptions?.[0]?.textContent?.trim() || fallback;
}

function syncFiltersFromControls() {
  const agentType = document.getElementById('agentTypeFilter');
  const uiTree = document.getElementById('filterUITree');
  const ltm = document.getElementById('filterLTM');
  const sortBy = document.getElementById('sortBy');
  if (agentType) currentFilters.agentType = agentType.value;
  if (uiTree) currentFilters.uiTree = uiTree.value;
  if (ltm) currentFilters.ltm = ltm.value;
  if (sortBy) currentFilters.sortBy = sortBy.value;
}

function activeFilterSummaryParts() {
  const parts = [];
  if (currentFilters.agentType !== 'all') {
    parts.push(`Type: ${selectedOptionText('agentTypeFilter', currentFilters.agentType)}`);
  }
  if (currentFilters.uiTree !== 'all') {
    parts.push(`UI Tree: ${selectedOptionText('filterUITree', currentFilters.uiTree)}`);
  }
  if (currentFilters.ltm !== 'all') {
    parts.push(`LTM: ${selectedOptionText('filterLTM', currentFilters.ltm)}`);
  }
  parts.push(`Sort: ${selectedOptionText('sortBy', currentFilters.sortBy)}`);
  return parts;
}

function snapshotStatusText() {
  const filteredCount = getFilteredData().length;
  const totalCount = leaderboardData?.agents?.length || filteredCount;
  const count = totalCount === filteredCount
    ? `${filteredCount} agents`
    : `Showing ${filteredCount} of ${totalCount} agents`;
  return `${count} · ${activeFilterSummaryParts().join(' · ')}`;
}

function addSnapshotStatus(clone) {
  const status = document.createElement('div');
  status.textContent = snapshotStatusText();
  status.style.margin = '10px 0 14px';
  status.style.padding = '8px 10px';
  status.style.border = '1px solid #dbe4f0';
  status.style.borderRadius = '8px';
  status.style.background = '#f8fafc';
  status.style.color = '#475569';
  status.style.font = '600 13px Arial, sans-serif';
  status.style.lineHeight = '1.35';
  const heading = clone.querySelector('.home-table-heading');
  if (heading) {
    heading.insertAdjacentElement('afterend', status);
  } else {
    clone.insertBefore(status, clone.firstChild);
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = src;
  });
}

function canvasToBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('Failed to create PNG blob'));
    }, 'image/png');
  });
}

async function renderElementToPngBlob(element) {
  const rect = element.getBoundingClientRect();
  const width = Math.ceil(Math.max(element.scrollWidth, rect.width));
  const height = Math.ceil(Math.max(element.scrollHeight, rect.height) + 48);
  const clone = element.cloneNode(true);
  inlineSnapshotStyles(element, clone);
  removeSnapshotExcluded(clone);
  addSnapshotStatus(clone);
  clone.style.width = `${width}px`;
  clone.style.maxWidth = 'none';
  clone.style.margin = '0';
  clone.style.transform = 'none';

  const wrapper = document.createElement('div');
  wrapper.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
  wrapper.style.width = `${width}px`;
  wrapper.style.minHeight = `${height}px`;
  wrapper.style.background = '#ffffff';
  wrapper.appendChild(clone);

  const serialized = new XMLSerializer().serializeToString(wrapper);
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <foreignObject x="0" y="0" width="${width}" height="${height}">${serialized}</foreignObject>
    </svg>`;
  const svgUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const image = await loadImage(svgUrl);
    const scale = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(width * scale);
    canvas.height = Math.ceil(height * scale);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.drawImage(image, 0, 0, width, height);
    return await canvasToBlob(canvas);
  } finally {
    URL.revokeObjectURL(svgUrl);
  }
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function textForSnapshotCell(cell) {
  if (cell.classList.contains('model-cell')) {
    const name = cell.querySelector('.model-name-main, .agent-name-compact, .model-name')?.textContent || '';
    const backbone = cell.querySelector('.model-backbone-inline, .model-backbone')?.textContent || '';
    const institution = cell.querySelector('.model-institution-text, .model-institution')?.textContent || '';
    const date = cell.querySelector('.model-date-text, .model-date')?.textContent || '';
    const lines = [`${name} ${backbone}`.trim()];
    const meta = [institution.trim(), date.trim()].filter(Boolean).join(' · ');
    if (meta) lines.push(meta);
    return lines.filter(Boolean);
  }
  return [cell.textContent.replace(/\s+/g, ' ').trim()].filter(Boolean);
}

function buildSnapshotTableModel(table) {
  const rows = Array.from(table.rows);
  const colWidths = [];
  const rowHeights = [];
  const activeRowspans = [];
  const cells = [];

  rows.forEach((row, rowIndex) => {
    let colIndex = 0;
    while (activeRowspans[colIndex] > 0) colIndex += 1;
    rowHeights[rowIndex] = Math.max(row.getBoundingClientRect().height || 0, 34);

    Array.from(row.cells).forEach((cell) => {
      while (activeRowspans[colIndex] > 0) colIndex += 1;
      const colspan = Number(cell.colSpan) || 1;
      const rowspan = Number(cell.rowSpan) || 1;
      const rect = cell.getBoundingClientRect();
      const width = Math.max(rect.width || 0, cell.scrollWidth || 0, 64);
      const height = Math.max(rect.height || 0, cell.scrollHeight || 0, 34);
      const perCol = Math.max(48, width / colspan);
      const perRow = Math.max(28, height / rowspan);

      for (let offset = 0; offset < colspan; offset += 1) {
        const column = colIndex + offset;
        colWidths[column] = Math.max(colWidths[column] || 0, perCol);
      }
      for (let offset = 0; offset < rowspan; offset += 1) {
        const rowSlot = rowIndex + offset;
        rowHeights[rowSlot] = Math.max(rowHeights[rowSlot] || 0, perRow);
      }
      for (let offset = 0; offset < colspan; offset += 1) {
        activeRowspans[colIndex + offset] = Math.max(activeRowspans[colIndex + offset] || 0, rowspan);
      }

      cells.push({
        cell,
        rowIndex,
        colIndex,
        colspan,
        rowspan,
        isHeader: cell.tagName.toLowerCase() === 'th',
        lines: textForSnapshotCell(cell),
        className: cell.className || '',
        rowClassName: row.className || '',
      });
      colIndex += colspan;
    });

    for (let index = 0; index < activeRowspans.length; index += 1) {
      if (activeRowspans[index] > 0) activeRowspans[index] -= 1;
    }
  });

  return {
    cells,
    colWidths: colWidths.map((width, index) => {
      if (index === 0) return Math.max(58, Math.min(width, 76));
      if (index === 1) return Math.max(240, Math.min(width, 340));
      return Math.max(74, Math.min(width, 126));
    }),
    rowHeights: rowHeights.map((height, index) => Math.max(index < 2 ? 36 : 46, Math.min(height, 72))),
  };
}

function snapshotCellFill(cellInfo) {
  const classes = `${cellInfo.className} ${cellInfo.rowClassName}`;
  if (cellInfo.isHeader) {
    return classes.includes('header-group') ? '#e9eef6' : '#f8fafc';
  }
  if (classes.includes('best') || classes.includes('best-efficiency')) return '#dcfce7';
  if (classes.includes('second')) return '#e0e7ff';
  if (classes.includes('sorted-column')) return '#fff7d6';
  if (classes.includes('first-rank')) return '#fff8db';
  if (classes.includes('zero')) return '#fef2f2';
  return '#ffffff';
}

function snapshotTextColor(cellInfo) {
  const classes = cellInfo.className || '';
  if (classes.includes('na')) return '#94a3b8';
  if (classes.includes('zero')) return '#b91c1c';
  if (cellInfo.isHeader) return '#0f172a';
  return '#1f2937';
}

function fitSnapshotText(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let trimmed = text;
  while (trimmed.length > 1 && ctx.measureText(`${trimmed}...`).width > maxWidth) {
    trimmed = trimmed.slice(0, -1);
  }
  return `${trimmed}...`;
}

function drawSnapshotText(ctx, lines, x, y, width, height, options = {}) {
  const paddingX = options.paddingX ?? 10;
  const lineHeight = options.lineHeight ?? 16;
  const align = options.align || 'center';
  const visibleLines = lines.length ? lines : ['-'];
  const totalHeight = Math.min(visibleLines.length, 2) * lineHeight;
  let textY = y + Math.max(lineHeight, (height - totalHeight) / 2 + lineHeight - 2);

  ctx.textAlign = align;
  ctx.textBaseline = 'alphabetic';
  const textX = align === 'left' ? x + paddingX : x + width / 2;
  const maxWidth = width - paddingX * 2;
  visibleLines.slice(0, 2).forEach((line, index) => {
    ctx.fillText(fitSnapshotText(ctx, line, maxWidth), textX, textY);
    if (index === 0 && visibleLines.length > 1) {
      ctx.font = '400 12px Arial, sans-serif';
      ctx.fillStyle = '#64748b';
    }
    textY += lineHeight;
  });
}

async function renderLeaderboardTableToPngBlob() {
  const table = document.querySelector('.home-result-panel.active table.leaderboard-table');
  if (!table) throw new Error('No active leaderboard table found');

  const model = buildSnapshotTableModel(table);
  const margin = 28;
  const titleHeight = 112;
  const footerHeight = 30;
  const tableWidth = model.colWidths.reduce((sum, width) => sum + width, 0);
  const tableHeight = model.rowHeights.reduce((sum, height) => sum + height, 0);
  const width = Math.ceil(tableWidth + margin * 2);
  const height = Math.ceil(titleHeight + tableHeight + footerHeight + margin);
  const scale = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(width * scale);
  canvas.height = Math.ceil(height * scale);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);

  const viewMeta = resultViewMeta[currentTab] || resultViewMeta.main;
  ctx.fillStyle = '#0f172a';
  ctx.font = '700 28px Arial, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('MemGUI-Bench Leaderboard', margin, 42);
  ctx.fillStyle = '#64748b';
  ctx.font = '400 15px Arial, sans-serif';
  ctx.fillText(`${viewMeta.title} · ${viewMeta.subtitle}`, margin, 67);
  ctx.fillStyle = '#475569';
  ctx.font = '600 13px Arial, sans-serif';
  ctx.fillText(snapshotStatusText(), margin, 92);

  const xOffsets = [margin];
  for (let index = 1; index < model.colWidths.length; index += 1) {
    xOffsets[index] = xOffsets[index - 1] + model.colWidths[index - 1];
  }
  const yOffsets = [titleHeight];
  for (let index = 1; index < model.rowHeights.length; index += 1) {
    yOffsets[index] = yOffsets[index - 1] + model.rowHeights[index - 1];
  }

  model.cells.forEach((cellInfo) => {
    const x = xOffsets[cellInfo.colIndex];
    const y = yOffsets[cellInfo.rowIndex];
    const cellWidth = model.colWidths
      .slice(cellInfo.colIndex, cellInfo.colIndex + cellInfo.colspan)
      .reduce((sum, value) => sum + value, 0);
    const cellHeight = model.rowHeights
      .slice(cellInfo.rowIndex, cellInfo.rowIndex + cellInfo.rowspan)
      .reduce((sum, value) => sum + value, 0);

    ctx.fillStyle = snapshotCellFill(cellInfo);
    ctx.fillRect(x, y, cellWidth, cellHeight);
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, cellWidth, cellHeight);

    ctx.save();
    ctx.beginPath();
    ctx.rect(x + 1, y + 1, cellWidth - 2, cellHeight - 2);
    ctx.clip();
    ctx.fillStyle = snapshotTextColor(cellInfo);
    ctx.font = cellInfo.isHeader ? '700 13px Arial, sans-serif' : '600 13px Arial, sans-serif';
    drawSnapshotText(ctx, cellInfo.lines, x, y, cellWidth, cellHeight, {
      align: cellInfo.className.includes('model-cell') ? 'left' : 'center',
      lineHeight: cellInfo.className.includes('model-cell') ? 16 : 17,
    });
    ctx.restore();
  });

  ctx.fillStyle = '#94a3b8';
  ctx.font = '400 12px Arial, sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(`Generated ${new Date().toISOString().slice(0, 10)}`, width - margin, height - 14);

  return canvasToBlob(canvas);
}

function setShareButtonState(button, text, isBusy = false) {
  const label = button.querySelector('span');
  if (label) label.textContent = text;
  button.disabled = isBusy;
}

async function shareLeaderboardSnapshot() {
  const button = document.getElementById('shareLeaderboard');
  const target = document.querySelector('.home-results-card');
  if (!button || !target) return;

  setShareButtonState(button, 'Generating', true);
  try {
    syncFiltersFromControls();
    renderTables();
    await new Promise((resolve) => requestAnimationFrame(resolve));

    let blob;
    try {
      blob = await renderElementToPngBlob(target);
    } catch (error) {
      console.warn('DOM snapshot failed; falling back to canvas table renderer.', error);
      blob = await renderLeaderboardTableToPngBlob();
    }
    const date = new Date().toISOString().slice(0, 10);
    const fileName = `memgui-bench-${currentTab}-leaderboard-${date}.png`;
    const file = typeof File === 'function' ? new File([blob], fileName, { type: 'image/png' }) : null;
    const title = `MemGUI-Bench ${resultViewMeta[currentTab]?.title || 'Leaderboard'}`;

    if (file && navigator.canShare && navigator.canShare({ files: [file] }) && navigator.share) {
      try {
        await navigator.share({ title, text: title, files: [file] });
        setShareButtonState(button, 'Shared');
        return;
      } catch (error) {
        if (error && error.name === 'AbortError') {
          setShareButtonState(button, 'Canceled');
          return;
        }
        console.warn('Native share failed; falling back to clipboard or download.', error);
      }
    }

    if (navigator.clipboard && window.ClipboardItem) {
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        setShareButtonState(button, 'Copied');
        return;
      } catch (error) {
        console.warn('Clipboard write failed; falling back to download.', error);
      }
    }

    downloadBlob(blob, fileName);
    setShareButtonState(button, 'Downloaded');
  } catch (error) {
    console.error('Failed to generate leaderboard snapshot:', error);
    setShareButtonState(button, 'Failed');
  } finally {
    setTimeout(() => setShareButtonState(button, 'Share LB'), 1600);
  }
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
      
      return agent.avg?.p3 ?? null;
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
  return 'avg_p3';
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
function renderTables() {
  const filteredData = getFilteredData();
  
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
