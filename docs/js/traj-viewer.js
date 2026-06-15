// Static trajectory viewer shared by the homepage and Arena.

(function () {
  const trajCache = new Map();
  const videoCache = new Map();
  const videoSeekQueues = new WeakMap();
  let modalState = null;

  function escHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  async function fetchGzipJson(url, onProgress) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const total = parseInt(resp.headers.get('content-length') || '0', 10);
    let loaded = 0;
    const rawChunks = [];
    const rawReader = resp.body.getReader();
    while (true) {
      const { done, value } = await rawReader.read();
      if (done) break;
      rawChunks.push(value);
      loaded += value.byteLength;
      if (onProgress && total) onProgress(loaded / total);
    }
    const rawBlob = new Blob(rawChunks);
    if (!('DecompressionStream' in window)) {
      throw new Error('This browser does not support gzip decompression');
    }
    const ds = new DecompressionStream('gzip');
    const decompressed = rawBlob.stream().pipeThrough(ds);
    const reader = decompressed.getReader();
    const chunks = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
    }
    return JSON.parse(await new Blob(chunks).text());
  }

  async function getTrajectoryData(trajFile, onProgress) {
    if (trajCache.has(trajFile)) return trajCache.get(trajFile);
    const data = await fetchGzipJson(trajFile, onProgress);
    trajCache.set(trajFile, data);
    return data;
  }

  async function loadVideo(url) {
    if (videoCache.has(url)) return videoCache.get(url);
    const promise = (async () => {
      const video = document.createElement('video');
      video.preload = 'auto';
      video.muted = true;
      video.playsInline = true;
      video.src = url;
      await new Promise((resolve, reject) => {
        video.addEventListener('loadedmetadata', resolve, { once: true });
        video.addEventListener('error', reject, { once: true });
      });
      return video;
    })();
    videoCache.set(url, promise);
    promise.catch(() => videoCache.delete(url));
    return promise;
  }

  function extractFrame(video, frameIndex, fps) {
    const targetTime = (frameIndex + 0.25) / fps;
    const previous = videoSeekQueues.get(video) || Promise.resolve();
    const queued = previous.catch(() => null).then(() => seekVideo(video, targetTime));
    videoSeekQueues.set(video, queued);
    queued.finally(() => {
      if (videoSeekQueues.get(video) === queued) videoSeekQueues.delete(video);
    });
    return queued;
  }

  function seekVideo(video, targetTime) {
    return new Promise((resolve) => {
      if (Math.abs(video.currentTime - targetTime) < 0.01) {
        waitForVideoFrame(video).then(() => resolve(video));
        return;
      }
      const cleanup = () => {
        video.removeEventListener('seeked', onSettled);
        video.removeEventListener('error', onSettled);
      };
      const onSettled = () => {
        cleanup();
        waitForVideoFrame(video).then(() => resolve(video));
      };
      video.addEventListener('seeked', onSettled, { once: true });
      video.addEventListener('error', onSettled, { once: true });
      video.currentTime = targetTime;
    });
  }

  function waitForVideoFrame(video) {
    if (typeof video.requestVideoFrameCallback !== 'function') {
      return new Promise((resolve) => requestAnimationFrame(() => resolve(video)));
    }
    return new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve(video);
      };
      const timeout = setTimeout(finish, 120);
      video.requestVideoFrameCallback(() => {
        clearTimeout(timeout);
        finish();
      });
    });
  }

  function drawActionOverlay(ctx, action, scaleX, scaleY) {
    if (!action) return;
    const actionType = action.action_type;
    if (['click', 'double_tap', 'long_press'].includes(actionType)) {
      const x = Number(action.x) * scaleX;
      const y = Number(action.y) * scaleY;
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      const r = 16 * scaleX;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(239, 68, 68, 0.45)';
      ctx.fill();
      ctx.strokeStyle = '#dc2626';
      ctx.lineWidth = Math.max(2, 2 * scaleX);
      ctx.stroke();
    } else if (actionType === 'drag') {
      const sx = Number(action.start_x) * scaleX;
      const sy = Number(action.start_y) * scaleY;
      const ex = Number(action.end_x) * scaleX;
      const ey = Number(action.end_y) * scaleY;
      if (![sx, sy, ex, ey].every(Number.isFinite)) return;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(ex, ey);
      ctx.strokeStyle = 'rgba(37, 99, 235, 0.75)';
      ctx.lineWidth = Math.max(3, 3 * scaleX);
      ctx.stroke();
      const r = 12 * scaleX;
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(22, 163, 74, 0.65)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(ex, ey, r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(239, 68, 68, 0.65)';
      ctx.fill();
    }
  }

  async function renderScreenshotCanvas(canvas, video, frameIndex, fps, meta, action) {
    await extractFrame(video, frameIndex, fps);
    const dw = meta.display_width;
    const dh = meta.display_height;
    canvas.width = dw;
    canvas.height = dh;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, dw, dh);
    const scaleX = dw / meta.original_width;
    const scaleY = dh / meta.original_height;
    drawActionOverlay(ctx, action, scaleX, scaleY);
  }

  function taskScore(task) {
    if (!task || !task.result) return null;
    const match = String(task.result).match(/score:\s*([\d.]+)/i);
    return match ? Number(match[1]) : null;
  }

  function scoreBadge(task) {
    const score = taskScore(task);
    if (score === 1) return '<span class="traj-result traj-result-pass">Pass</span>';
    if (score === 0) return '<span class="traj-result traj-result-fail">Fail</span>';
    return '';
  }

  function videoUrlFor(trajFile, meta) {
    if (!meta || !meta.video_file) return null;
    const url = meta.video_file.startsWith('http')
      ? meta.video_file
      : trajFile.replace(/[^/]+$/, '') + meta.video_file;
    if (!meta.video_revision) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}v=${encodeURIComponent(meta.video_revision)}`;
  }

  function formatAction(action) {
    if (!action) return 'unknown';
    let label = action.action_type || 'unknown';
    if (action.x !== undefined && action.y !== undefined) label += ` (${action.x}, ${action.y})`;
    if (action.start_x !== undefined && action.end_x !== undefined) {
      label += ` (${action.start_x}, ${action.start_y}) -> (${action.end_x}, ${action.end_y})`;
    }
    if (action.direction) label += ` ${action.direction}`;
    if (action.text) label += `: "${action.text}"`;
    if (action.app_name) label += ` ${action.app_name}`;
    return label;
  }

  function splitPrediction(prediction) {
    const pred = prediction || '';
    const thinkMatch = pred.match(/<think>([\s\S]*?)<\/think>/);
    if (!thinkMatch) return { think: '', response: pred };
    return {
      think: thinkMatch[1].trim(),
      response: pred.slice(thinkMatch.index + thinkMatch[0].length).trim(),
    };
  }

  function renderTaskHtml(task, meta, side = '') {
    if (!task || !Array.isArray(task.traj) || task.traj.length === 0) {
      return '<div class="traj-empty">No trajectory data.</div>';
    }
    const steps = task.traj;
    const goal = steps[0]?.task_goal
      ? `<div class="traj-goal"><span>Task Goal</span>${escHtml(steps[0].task_goal)}</div>`
      : '';
    const body = steps.map((step, i) => {
      const { think, response } = splitPrediction(step.prediction || '');
      const hasFrame = step.frame_index !== undefined && meta && meta.video_file;
      const canvasSide = side ? ` data-side="${escHtml(side)}"` : '';
      const screenshot = hasFrame
        ? `<details class="traj-screenshot-block"><summary>Screenshot</summary><div class="traj-screenshot is-loading"><canvas class="traj-canvas" data-frame="${step.frame_index}" data-step="${i}"${canvasSide}></canvas><div class="traj-screenshot-spinner"><i class="bi bi-arrow-repeat"></i> Loading screenshot...</div></div></details>`
        : '';
      const askUser = step.ask_user_response
        ? `<div class="traj-extra"><span>User Response</span>${escHtml(step.ask_user_response)}</div>`
        : '';
      const toolCall = step.tool_call
        ? `<div class="traj-extra"><span>Tool Call</span><pre>${escHtml(JSON.stringify(step.tool_call, null, 2))}</pre></div>`
        : '';
      return `
        <div class="traj-step" data-step="${i}">
          <div class="traj-step-header">
            <span class="traj-step-num">Step ${step.step || i + 1}</span>
            <span class="traj-action-badge">${escHtml(formatAction(step.action || {}))}</span>
          </div>
          ${screenshot}
          ${think ? `<details class="traj-think"><summary>Thinking</summary><div>${escHtml(think)}</div></details>` : ''}
          ${response ? `<div class="traj-response">${escHtml(response)}</div>` : ''}
          ${askUser}
          ${toolCall}
        </div>`;
    }).join('');

    const usage = task.token_usage
      ? `<div class="traj-token-summary">Token usage: ${(task.token_usage.prompt_tokens || 0).toLocaleString()} prompt · ${(task.token_usage.completion_tokens || 0).toLocaleString()} completion · ${(task.token_usage.total_tokens || 0).toLocaleString()} total</div>`
      : '';
    return goal + body + usage;
  }

  async function renderCanvases(container, task, meta, videoPromise) {
    if (!meta || !videoPromise || !task) return;
    let video = null;
    try {
      video = await videoPromise;
    } catch (error) {
      container.querySelectorAll('.traj-screenshot-spinner').forEach((el) => {
        el.innerHTML = '<i class="bi bi-image"></i> Screenshot unavailable';
      });
      return;
    }
    const canvases = container.querySelectorAll('.traj-canvas');
    for (const canvas of canvases) {
      const frameIndex = parseInt(canvas.dataset.frame, 10);
      const stepIndex = parseInt(canvas.dataset.step, 10);
      const action = task.traj?.[stepIndex]?.action || null;
      await renderScreenshotCanvas(canvas, video, frameIndex, meta.fps, meta, action);
      canvas.parentElement?.classList.remove('is-loading');
    }
  }

  function ensureModal() {
    if (modalState) return modalState;
    const modal = document.createElement('div');
    modal.className = 'traj-modal';
    modal.innerHTML = `
      <div class="traj-modal-backdrop" data-traj-close></div>
      <div class="traj-panel" role="dialog" aria-modal="true" aria-labelledby="trajModalTitle">
        <button class="traj-close" type="button" aria-label="Close" data-traj-close><i class="bi bi-x-lg"></i></button>
        <header class="traj-header">
          <div>
            <h2 id="trajModalTitle">Trajectories</h2>
            <p id="trajModalSubtitle"></p>
          </div>
          <div class="traj-controls">
            <select id="trajTaskSelect" class="form-select form-select-sm"></select>
            <span id="trajResultSlot"></span>
            <button type="button" class="traj-expand-all" id="trajExpandAll">Expand all</button>
          </div>
        </header>
        <div class="traj-body">
          <div class="traj-loading" id="trajLoading">
            <i class="bi bi-arrow-repeat"></i>
            <span id="trajLoadingText">Loading trajectories...</span>
            <div class="traj-progress" id="trajProgress" hidden><div id="trajProgressBar"></div></div>
          </div>
          <div id="trajSteps"></div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', (event) => {
      if (event.target.closest('[data-traj-close]')) closeTrajModal();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && modal.classList.contains('is-active')) closeTrajModal();
    });
    modalState = {
      modal,
      title: modal.querySelector('#trajModalTitle'),
      subtitle: modal.querySelector('#trajModalSubtitle'),
      taskSelect: modal.querySelector('#trajTaskSelect'),
      resultSlot: modal.querySelector('#trajResultSlot'),
      loading: modal.querySelector('#trajLoading'),
      loadingText: modal.querySelector('#trajLoadingText'),
      progress: modal.querySelector('#trajProgress'),
      progressBar: modal.querySelector('#trajProgressBar'),
      steps: modal.querySelector('#trajSteps'),
      expandAll: modal.querySelector('#trajExpandAll'),
    };
    modalState.expandAll.addEventListener('click', () => {
      const blocks = modalState.steps.querySelectorAll('.traj-screenshot-block');
      if (!blocks.length) return;
      const allOpen = [...blocks].every((block) => block.open);
      blocks.forEach((block) => { block.open = !allOpen; });
      updateExpandAll(modalState.steps, modalState.expandAll);
    });
    modalState.steps.addEventListener('toggle', (event) => {
      if (event.target.classList?.contains('traj-screenshot-block')) {
        updateExpandAll(modalState.steps, modalState.expandAll);
      }
    }, true);
    return modalState;
  }

  function updateExpandAll(container, button) {
    const blocks = container.querySelectorAll('.traj-screenshot-block');
    if (!blocks.length) {
      button.hidden = true;
      return;
    }
    button.hidden = false;
    button.textContent = [...blocks].every((block) => block.open) ? 'Collapse all' : 'Expand all';
  }

  async function openTrajModal(trajFile, modelName) {
    const state = ensureModal();
    state.modal.classList.add('is-active');
    state.title.textContent = `${modelName || 'Agent'} Trajectories`;
    state.subtitle.textContent = trajFile;
    state.taskSelect.innerHTML = '';
    state.resultSlot.innerHTML = '';
    state.steps.innerHTML = '';
    state.loading.hidden = false;
    state.loadingText.textContent = 'Downloading trajectory data...';
    state.progress.hidden = false;
    state.progressBar.style.width = '0%';
    state.expandAll.hidden = true;

    let data;
    try {
      data = await getTrajectoryData(trajFile, (pct) => {
        state.progressBar.style.width = `${(pct * 100).toFixed(1)}%`;
      });
    } catch (error) {
      state.loadingText.textContent = `Failed to load: ${error.message}`;
      state.progress.hidden = true;
      return;
    }

    const meta = data._meta || null;
    const taskNames = Object.keys(data).filter((key) => key !== '_meta').sort();
    const videoUrl = videoUrlFor(trajFile, meta);
    let renderGeneration = 0;
    state.loading.hidden = true;

    taskNames.forEach((taskName) => {
      const option = document.createElement('option');
      option.value = taskName;
      option.textContent = taskName;
      state.taskSelect.appendChild(option);
    });

    const renderTask = (taskName) => {
      const task = data[taskName];
      const myGeneration = ++renderGeneration;
      state.resultSlot.innerHTML = scoreBadge(task);
      state.steps.innerHTML = renderTaskHtml(task, meta);
      updateExpandAll(state.steps, state.expandAll);
      if (videoUrl && meta) {
        const videoPromise = loadVideo(videoUrl);
        videoPromise.then(() => {
          if (myGeneration !== renderGeneration) return;
          renderCanvases(state.steps, task, meta, videoPromise);
        }).catch(() => {
          state.steps.querySelectorAll('.traj-screenshot-spinner').forEach((el) => {
            el.innerHTML = '<i class="bi bi-image"></i> Screenshot unavailable';
          });
        });
      }
    };

    state.taskSelect.onchange = () => renderTask(state.taskSelect.value);
    if (taskNames.length > 0) renderTask(taskNames[0]);
  }

  function closeTrajModal() {
    if (modalState) modalState.modal.classList.remove('is-active');
  }

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-traj-file]');
    if (trigger && trigger.dataset.trajFile) {
      event.preventDefault();
      openTrajModal(trigger.dataset.trajFile, trigger.dataset.model || trigger.textContent.trim());
      return;
    }
    const canvas = event.target.closest('.traj-canvas');
    if (!canvas) return;
    const overlay = document.createElement('div');
    overlay.className = 'traj-screenshot-overlay';
    const big = document.createElement('canvas');
    big.width = canvas.width * 2;
    big.height = canvas.height * 2;
    big.getContext('2d').drawImage(canvas, 0, 0, big.width, big.height);
    overlay.appendChild(big);
    overlay.addEventListener('click', () => overlay.remove());
    document.body.appendChild(overlay);
  });

  window.MemGUITraj = {
    escHtml,
    fetchGzipJson,
    getTrajectoryData,
    loadVideo,
    renderTaskHtml,
    renderCanvases,
    taskScore,
    scoreBadge,
    videoUrlFor,
    openTrajModal,
  };
})();
