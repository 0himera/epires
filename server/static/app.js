/**
 * EPIRES HYPERGRAPH ENGINE // CLIENT CONTROLLER
 * Archival Paper Theme with Pretext Balanced Typography, 3-Zone Architecture, and Popperian Evidence Ladder
 */

(function () {
  'use strict';

  // Popperian Evidence Maturity Hierarchy Definitions
  // Canonical ladder from README / epires_core.models. Keep this copy local so
  // the atlas remains legible when the API is unavailable.
  const MATURITY_CRITERIA = {
    E0: 'E0: Speculative hypothesis — a priori mechanism registered in the VSA DAG.',
    E1: 'E1: Mechanism implementation evidence recorded.',
    E2: 'E2: Deterministic local replay evidence recorded.',
    E3: 'E3: Statistically significant gain on a targeted validation holdout.',
    E4: 'E4: Repeated out-of-time validation with 95% bootstrap CI; strictly superior.',
    E5: 'E5: Final verification recorded on an unobserved partition or in production.'
  };
  const MATURITY_LEVELS = Object.keys(MATURITY_CRITERIA);

  // Application State
  const state = {
    config: {},
    hypotheses: [],
    traces: [],
    gaps: [],
    selectedHypothesisId: null,
    activeFilter: 'ALL',
    activeLevelFilter: null,
    showGhosts: false,
    activeTab: 'inspector',
    theme: localStorage.getItem('epires_theme') || 'paper',
    transform: { x: 60, y: 50, scale: 0.95 },
    isDraggingCanvas: false,
    dragStart: { x: 0, y: 0 },
    nodePositions: new Map(), // { id: { x, y, width, height } }
    draggingNode: null,
    dragNodeStart: { mouseX: 0, mouseY: 0, nodeX: 0, nodeY: 0 },
    hasMovedNode: false,
    lastSyncTime: null,
    searchSelectedIndex: 0,
    atlasMode: 'atlas',
    atlasSnapshot: {},
    relations: [],
    stratigraphy: [],
    coverage: {},
    endpointStatus: {},
    evidenceByHypothesis: new Map(),
    fetchGeneration: 0,
    inspectorGeneration: 0,
    dataVersion: null,
    lastGraphFingerprint: null,
    wsConnected: false
  };

  // Dimensions for Organic Voronoi Pebble Facets
  const NODE_WIDTH = 270;
  const NODE_HEIGHT = 100;
  const GAP_X = 52;
  const GAP_Y = 92;

  // DOM Elements
  const dom = {
    svg: document.getElementById('dag-svg'),
    canvasContainer: document.getElementById('canvas-container'),
    noiseCanvas: document.getElementById('noise-canvas'),
    projectName: document.getElementById('project-name'),
    projectMetric: document.getElementById('project-metric'),
    hdrTaskDesc: document.getElementById('hdr-task-desc'),
    dotTask: document.getElementById('dot-task'),
    hdrProjectDomain: document.getElementById('hdr-project-domain'),
    btnThemeToggle: document.getElementById('btn-theme-toggle'),
    themeLabel: document.getElementById('theme-label'),
    btnRefresh: document.getElementById('btn-refresh'),
    syncStatusDot: document.getElementById('sync-status-dot'),
    syncStatusLabel: document.getElementById('sync-status-label'),
    syncTimeText: document.getElementById('sync-time-text'),
    kpiTotal: document.getElementById('kpi-total'),
    kpiConfirmed: document.getElementById('kpi-confirmed'),
    kpiInProgress: document.getElementById('kpi-in-progress'),
    kpiFalsified: document.getElementById('kpi-falsified'),
    kpiCells: document.querySelectorAll('.kpi-cell[data-filter]'),
    evidenceSpectrum: document.getElementById('evidence-spectrum'),
    ladderActiveHint: document.getElementById('ladder-active-hint'),
    btnZoomIn: document.getElementById('btn-zoom-in'),
    btnZoomOut: document.getElementById('btn-zoom-out'),
    btnZoomReset: document.getElementById('btn-zoom-reset'),
    zoomLevelText: document.getElementById('zoom-level-text'),
    btnToggleGhosts: document.getElementById('btn-toggle-ghosts'),
    dagFilterGroup: document.getElementById('dag-filter-group'),
    canvasTools: document.querySelector('.canvas-tools'),
    tabButtons: document.querySelectorAll('.m-tab'),
    tabContents: document.querySelectorAll('.tab-pane'),
    tabBadgeTraces: document.getElementById('tab-badge-traces'),
    tabBadgeGaps: document.getElementById('tab-badge-gaps'),
    filterButtons: document.querySelectorAll('.f-pill'),
    inspectorEmpty: document.getElementById('inspector-empty'),
    inspectorBody: document.getElementById('inspector-body'),
    insId: document.getElementById('ins-id'),
    insStatus: document.getElementById('ins-status'),
    insLevel: document.getElementById('ins-level'),
    insTitle: document.getElementById('ins-title'),
    insMechanism: document.getElementById('ins-mechanism'),
    insFalsification: document.getElementById('ins-falsification'),
    insParents: document.getElementById('ins-parents'),
    insLedgerCount: document.getElementById('ins-ledger-count'),
    insEvidenceList: document.getElementById('ins-evidence-list'),
    btnCopyId: document.getElementById('btn-copy-id'),
    btnFocusNode: document.getElementById('btn-focus-node'),
    btnFilterTraces: document.getElementById('btn-filter-traces'),
    tracesStreamContainer: document.getElementById('traces-stream-container'),
    tracesCountText: document.getElementById('traces-count-text'),
    tracesSearch: document.getElementById('traces-search'),
    gapsMatrixContainer: document.getElementById('gaps-matrix-container'),
    btnOpenSearch: document.getElementById('btn-open-search'),
    searchModal: document.getElementById('search-modal'),
    cmdKInput: document.getElementById('cmd-k-input'),
    cmdKResults: document.getElementById('cmd-k-results'),
    atlasModeButtons: document.querySelectorAll('.atlas-mode-btn'),
    atlasModeViews: document.querySelectorAll('.atlas-mode-view'),
    stratigraphyContainer: document.getElementById('stratigraphy-container'),
    stratigraphySummary: document.getElementById('stratigraphy-summary'),
    ledgerAtlasContainer: document.getElementById('ledger-atlas-container'),
    ledgerSummary: document.getElementById('ledger-summary'),
    coverageAtlasContainer: document.getElementById('coverage-atlas-container'),
    coverageSummary: document.getElementById('coverage-summary'),
    atlasProvenanceStrip: document.getElementById('atlas-provenance-strip')
  };

  function makeElement(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clearElement(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function asArray(value) {
    if (Array.isArray(value)) return value;
    if (!value || typeof value !== 'object') return [];
    return value.items || value.entries || value.results || value.data || value.hypotheses || value.traces || value.cells || [];
  }

  function displayValue(value, fallback = '—') {
    if (value === undefined || value === null || value === '') return fallback;
    if (typeof value === 'object') {
      try { return JSON.stringify(value); } catch (_) { return fallback; }
    }
    return String(value);
  }

  function escapeSvgText(value) {
    return displayValue(value, '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'
    }[char]));
  }

  function safeFetchJson(url, options) {
    return fetch(url, options).then(response => {
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return response.json();
    });
  }

  function setSyncState(kind, detail) {
    if (dom.syncStatusDot) dom.syncStatusDot.className = `sync-dot${kind === 'loading' ? ' spinning' : kind === 'error' ? ' error' : ''}`;
    if (dom.syncStatusLabel) dom.syncStatusLabel.textContent = kind === 'error' ? 'STALE' : 'SYNC';
    if (dom.syncTimeText) {
      dom.syncTimeText.textContent = kind === 'error'
        ? `STALE${detail ? ` · ${detail}` : ''}`
        : (state.lastSyncTime || '--:--');
    }
  }

  // Keep endpoint health separate from payload contents. An empty projection is
  // a valid observation and must not be reported as a transport failure.
  function fetchEndpoint(url, options) {
    return safeFetchJson(url, options)
      .then(data => ({ available: true, data, error: null }))
      .catch(error => ({
        available: false,
        data: null,
        error: error && error.message ? error.message : String(error)
      }));
  }

  // --------------------------------------------------------------------------
  // Pretext Measurement Canvas for Balanced Multi-Line Layout
  // --------------------------------------------------------------------------
  const textMeasureCanvas = document.createElement('canvas');
  const textMeasureCtx = textMeasureCanvas.getContext('2d');
  textMeasureCtx.font = '500 11.5px Inter, -apple-system, sans-serif';

  function formatBalancedTitleSVG(text, maxWidth = 218, startX = 24, startY = 48, maxLines = 2) {
    const words = text.split(/\s+/);
    const lines = [];
    let curLine = '';

    for (let i = 0; i < words.length; i++) {
      const test = curLine ? `${curLine} ${words[i]}` : words[i];
      const width = textMeasureCtx.measureText(test).width;
      if (width > maxWidth && curLine) {
        lines.push(curLine);
        curLine = words[i];
        if (lines.length >= maxLines - 1) {
          let remainder = words.slice(i).join(' ');
          while (textMeasureCtx.measureText(remainder + '…').width > maxWidth && remainder.length > 5) {
            remainder = remainder.substring(0, remainder.lastIndexOf(' '));
          }
          curLine = remainder ? `${remainder}…` : `${words[i]}…`;
          break;
        }
      } else {
        curLine = test;
      }
    }
    if (curLine && lines.length < maxLines) {
      lines.push(curLine);
    }

    return lines.map((l, idx) => {
      const y = startY + idx * 15;
      return `<text x="${startX}" y="${y}" fill="var(--ink-primary)" font-family="Inter, -apple-system, sans-serif" font-size="11.5" font-weight="500">${escapeSvgText(l)}</text>`;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // Mathematical Smooth Filleted Polygon Path Generator (16px Filleted Corners)
  // --------------------------------------------------------------------------
  function createFilletedPolygonPath(rawPoints, radius = 16) {
    const n = rawPoints.length;
    if (n < 3) return '';

    let path = '';
    for (let i = 0; i < n; i++) {
      const prev = rawPoints[(i - 1 + n) % n];
      const curr = rawPoints[i];
      const next = rawPoints[(i + 1) % n];

      const dx1 = prev[0] - curr[0];
      const dy1 = prev[1] - curr[1];
      const len1 = Math.hypot(dx1, dy1) || 1;

      const dx2 = next[0] - curr[0];
      const dy2 = next[1] - curr[1];
      const len2 = Math.hypot(dx2, dy2) || 1;

      const r = Math.min(radius, len1 / 2.3, len2 / 2.3);

      const startX = curr[0] + (dx1 / len1) * r;
      const startY = curr[1] + (dy1 / len1) * r;

      const endX = curr[0] + (dx2 / len2) * r;
      const endY = curr[1] + (dy2 / len2) * r;

      if (i === 0) {
        path += `M ${startX.toFixed(1)} ${startY.toFixed(1)} `;
      } else {
        path += `L ${startX.toFixed(1)} ${startY.toFixed(1)} `;
      }

      path += `Q ${curr[0].toFixed(1)} ${curr[1].toFixed(1)} ${endX.toFixed(1)} ${endY.toFixed(1)} `;
    }

    path += 'Z';
    return path;
  }

  // --------------------------------------------------------------------------
  // Polyhedral Voronoi Organic Geometry (6 Distinct Faceted Morphologies)
  // --------------------------------------------------------------------------
  function getVoronoiPebbleGeometry(id, w = 270, h = 100) {
    let hash = 0;
    const str = String(id || '');
    for (let i = 0; i < str.length; i++) {
      hash = (hash * 31 + str.charCodeAt(i)) >>> 0;
    }
    const variant = hash % 6;

    let rawOuter;
    switch (variant) {
      case 0: // Smooth Pebble Hexagon (Pointed lateral apexes)
        rawOuter = [[28, 0], [w - 28, 0], [w, h * 0.48], [w - 24, h], [24, h], [0, h * 0.52]];
        break;
      case 1: // Organic Facet with Asymmetric Shoulder (Slanted top-right & bottom-left)
        rawOuter = [[18, 0], [w - 36, 0], [w, h * 0.38], [w - 18, h], [32, h], [0, h * 0.65]];
        break;
      case 2: // Pointed Lateral Capsule-Diamond
        rawOuter = [[34, 0], [w - 18, 0], [w, h * 0.6], [w - 32, h], [16, h], [0, h * 0.4]];
        break;
      case 3: // Slanted Crystallographic Parallelogram Pebble
        rawOuter = [[30, 0], [w, 0], [w - 16, h * 0.5], [w - 30, h], [0, h], [16, h * 0.5]];
        break;
      case 4: // Soft Rounded Pentagonal Lobe
        rawOuter = [[20, 0], [w - 20, 0], [w, h * 0.55], [w - 26, h], [12, h], [0, h * 0.45]];
        break;
      case 5: // Curved Isogrid Facet
      default:
        rawOuter = [[14, 0], [w - 30, 0], [w, h * 0.45], [w - 16, h], [24, h], [0, h * 0.55]];
        break;
    }

    return createFilletedPolygonPath(rawOuter, 16);
  }

  // --------------------------------------------------------------------------
  // Animated Vector-Memory Calibration Instrument Canvas
  // --------------------------------------------------------------------------
  function initHeaderFieldAnimation() {
    const canvas = document.getElementById('header-matrix-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const width = 240;
    const height = 52;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    const count = 26;
    const nodes = [];
    for (let i = 0; i < count; i++) {
      const theta = (i / count) * Math.PI * 2;
      const phi = Math.acos((i / (count - 1)) * 2 - 1);
      nodes.push({ theta, phi, radius: 17 + (i % 3) * 3, speed: 0.007 + (i % 4) * 0.003 });
    }

    let angle = 0;
    let isHovered = false;

    canvas.addEventListener('mouseenter', () => { isHovered = true; });
    canvas.addEventListener('mouseleave', () => { isHovered = false; });

    function draw() {
      ctx.clearRect(0, 0, width, height);
      const isNoir = document.documentElement.getAttribute('data-theme') === 'noir';
      const primaryColor = isNoir ? '244, 243, 238' : '18, 19, 22';

      const cx = width / 2;
      const cy = height / 2;
      angle += isHovered ? 0.024 : 0.010;

      // Projected 3D points
      const projected = nodes.map((n) => {
        const currentTheta = n.theta + angle * n.speed * 40;
        const x3d = n.radius * Math.sin(n.phi) * Math.cos(currentTheta);
        const y3d = n.radius * Math.cos(n.phi);
        const z3d = n.radius * Math.sin(n.phi) * Math.sin(currentTheta);

        const pitch = 0.30;
        const yRot = y3d * Math.cos(pitch) - z3d * Math.sin(pitch);
        const zRot = y3d * Math.sin(pitch) + z3d * Math.cos(pitch);

        const scale = 1 / (1 - zRot / 70);
        const px = cx + x3d * scale;
        const py = cy + yRot * scale;
        const depthAlpha = Math.max(0.18, Math.min(0.85, (zRot + 20) / 40));

        return { x: px, y: py, z: zRot, alpha: depthAlpha };
      });

      // Filaments between nearby nodes
      ctx.lineWidth = 0.65;
      for (let i = 0; i < projected.length; i++) {
        for (let j = i + 1; j < projected.length; j++) {
          const dx = projected[i].x - projected[j].x;
          const dy = projected[i].y - projected[j].y;
          const dist = Math.hypot(dx, dy);
          if (dist < 32) {
            const edgeAlpha = (1 - dist / 32) * projected[i].alpha * projected[j].alpha * 0.45;
            ctx.strokeStyle = `rgba(${primaryColor}, ${edgeAlpha})`;
            ctx.beginPath();
            ctx.moveTo(projected[i].x, projected[i].y);
            ctx.lineTo(projected[j].x, projected[j].y);
            ctx.stroke();
          }
        }
      }

      // Nodes
      projected.forEach(p => {
        ctx.fillStyle = `rgba(${primaryColor}, ${p.alpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.z > 0 ? 1.4 : 0.9, 0, Math.PI * 2);
        ctx.fill();
      });

      // Registration ticks
      ctx.strokeStyle = `rgba(${primaryColor}, 0.25)`;
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      ctx.moveTo(12, cy); ctx.lineTo(22, cy);
      ctx.moveTo(width - 22, cy); ctx.lineTo(width - 12, cy);
      ctx.stroke();

      requestAnimationFrame(draw);
    }

    requestAnimationFrame(draw);
  }

  // --------------------------------------------------------------------------
  // Full-Screen Procedural Paper Grain Shader Canvas
  // --------------------------------------------------------------------------
  function initNoiseShader() {
    const canvas = dom.noiseCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      generateNoise();
    }

    function generateNoise() {
      const w = canvas.width;
      const h = canvas.height;
      if (w === 0 || h === 0) return;

      const imgData = ctx.createImageData(w, h);
      const data = imgData.data;
      const len = data.length;

      for (let i = 0; i < len; i += 4) {
        const val = (Math.random() * 255) | 0;
        data[i] = val;
        data[i + 1] = val;
        data[i + 2] = val;
        data[i + 3] = 45;
      }

      ctx.putImageData(imgData, 0, 0);
    }

    window.addEventListener('resize', resize);
    resize();
  }

  // --------------------------------------------------------------------------
  // Theme Management (Paper / Noir)
  // --------------------------------------------------------------------------
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('epires_theme', theme);
    if (dom.themeLabel) {
      dom.themeLabel.textContent = theme.toUpperCase();
    }
  }

  function toggleTheme() {
    const nextTheme = state.theme === 'paper' ? 'noir' : 'paper';
    applyTheme(nextTheme);
  }

  // --------------------------------------------------------------------------
  // Data Fetching & Dynamic 3-Zone Header Binding
  // --------------------------------------------------------------------------
  async function fetchAllData() {
    const generation = ++state.fetchGeneration;
    try {
      setSyncState('loading');

      const [configResult, hypoResult, tracesResult, gapsResult, snapshotResult, stratigraphyResult, coverageResult, provenanceResult] = await Promise.all([
        fetchEndpoint('/config'),
        fetchEndpoint('/hypotheses'),
        fetchEndpoint('/traces?limit=100'),
        fetchEndpoint('/gaps', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dimensions: ['Model', 'Feature', 'Regime'], min_tested: 1 })
        }),
        fetchEndpoint('/atlas/snapshot'),
        fetchEndpoint('/atlas/stratigraphy'),
        fetchEndpoint('/atlas/coverage?dimensions=Model,Feature,Regime'),
        fetchEndpoint('/atlas/provenance')
      ]);

      // A slower refresh must never overwrite a newer one.
      if (generation !== state.fetchGeneration) return;

      const endpointResults = {
        config: configResult,
        hypotheses: hypoResult,
        traces: tracesResult,
        gaps: gapsResult,
        snapshot: snapshotResult,
        stratigraphy: stratigraphyResult,
        coverage: coverageResult,
        provenance: provenanceResult
      };
      state.endpointStatus = Object.fromEntries(Object.entries(endpointResults).map(([name, result]) => [name, {
        available: result.available,
        error: result.error
      }]));

      // The canvas can use either the primary hypothesis feed or the Atlas
      // snapshot. If neither is readable, retain the previous data and expose
      // a visible stale state instead of presenting an empty graph as current.
      const coreUnavailable = !hypoResult.available && !snapshotResult.available;
      if (coreUnavailable) {
        const detail = [hypoResult.error, snapshotResult.error].filter(Boolean).join(' / ');
        setSyncState('error', detail || 'core data unavailable');
        return;
      }

      const configRes = configResult.data;
      const hypoRes = hypoResult.data;
      const tracesRes = tracesResult.data;
      const gapsRes = gapsResult.data;
      const snapshotRes = snapshotResult.data;
      const stratigraphyRes = stratigraphyResult.data;
      const coverageRes = coverageResult.data;
      const provenanceRes = provenanceResult.data;

      state.config = configRes || {};
      state.atlasSnapshot = snapshotRes || {};
      const snapshotHypotheses = asArray(state.atlasSnapshot.hypotheses || state.atlasSnapshot.specimens);
      const snapshotTraces = asArray(state.atlasSnapshot.traces);
      const snapshotGaps = asArray(state.atlasSnapshot.gaps || state.atlasSnapshot.white_spots);
      // A successful empty response is authoritative. Fall back only when the
      // primary endpoint is unavailable, never merely because its list is empty.
      state.hypotheses = hypoResult.available ? asArray(hypoRes) : snapshotHypotheses;
      state.traces = tracesResult.available ? asArray(tracesRes) : snapshotTraces;
      state.gaps = gapsResult.available ? asArray(gapsRes) : snapshotGaps;
      state.relations = asArray(state.atlasSnapshot.relations);
      state.stratigraphy = stratigraphyResult.available ? asArray(stratigraphyRes && (stratigraphyRes.events || stratigraphyRes.items || stratigraphyRes)) : [];
      state.coverage = coverageResult.available ? (coverageRes || {}) : {};
      state.provenance = provenanceResult.available ? (provenanceRes || {}) : {};
      state.evidenceByHypothesis.clear();
      hydrateSnapshotEvidence(state.atlasSnapshot);

      bindDynamicConfig();
      updateKPISummary();
      renderDAG();
      renderTraces();
      renderGaps();
      renderAtlasViews();

      if (state.selectedHypothesisId) {
        renderInspector(state.selectedHypothesisId);
      }

      // Record stable sync time
      const now = new Date();
      state.lastSyncTime = now.toTimeString().substring(0, 5);
      setSyncState('ready');

      // Update badge counts on tabs
      if (dom.tabBadgeTraces) dom.tabBadgeTraces.textContent = state.traces.length;
      if (dom.tabBadgeGaps) dom.tabBadgeGaps.textContent = state.gaps.length;
    } catch (err) {
      console.error('Epires fetch error:', err);
      setSyncState('error', err && err.message ? err.message : 'sync failed');
    }
  }

  // --------------------------------------------------------------------------
  // Lightweight Conditional Sync (Ultra-Low Overhead Version Check)
  // --------------------------------------------------------------------------
  async function syncDataIfChanged(force = false) {
    if (force) {
      return fetchAllData();
    }
    try {
      const vRes = await fetchEndpoint('/atlas/version');
      if (vRes.available && vRes.data && vRes.data.version) {
        if (vRes.data.version === state.dataVersion) {
          // Version is identical, nothing changed on server!
          const now = new Date();
          state.lastSyncTime = now.toTimeString().substring(0, 5);
          setSyncState('ready');
          return;
        }
        state.dataVersion = vRes.data.version;
      }
      return fetchAllData();
    } catch (_) {
      return fetchAllData();
    }
  }

  // --------------------------------------------------------------------------
  // Real-Time WebSocket Streaming Push Hub
  // --------------------------------------------------------------------------
  function initWebSocketSync() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    let ws = null;

    function connect() {
      try {
        ws = new WebSocket(wsUrl);
        ws.onopen = () => {
          state.wsConnected = true;
          console.log('[EPIRES] Real-time WebSocket channel active.');
        };
        ws.onmessage = (event) => {
          if (event.data === 'pong') return;
          syncDataIfChanged(true);
        };
        ws.onclose = () => {
          state.wsConnected = false;
          setTimeout(connect, 6000);
        };
        ws.onerror = () => {
          if (ws) ws.close();
        };
      } catch (_) {
        setTimeout(connect, 6000);
      }
    }
    connect();

    // Heartbeat ping every 25s to keep local tunnel/socket alive
    setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 25000);
  }

  function hydrateSnapshotEvidence(snapshot) {
    const source = snapshot && (snapshot.evidence_by_hypothesis || snapshot.evidence || snapshot.ledger);
    if (!source) return;
    if (Array.isArray(source)) {
      source.forEach(ev => {
        const id = ev.hypothesis_id || ev.h_id || ev.specimen_id;
        if (!id) return;
        const list = state.evidenceByHypothesis.get(id) || [];
        list.push(ev);
        state.evidenceByHypothesis.set(id, list);
      });
      return;
    }
    if (typeof source === 'object') {
      Object.keys(source).forEach(id => {
        const value = source[id];
        state.evidenceByHypothesis.set(id, asArray(value));
      });
    }
  }

  function showAtlasMode(mode) {
    const next = ['atlas', 'stratigraphy', 'ledger', 'coverage'].includes(mode) ? mode : 'atlas';
    state.atlasMode = next;
    dom.atlasModeButtons.forEach(btn => {
      const active = btn.dataset.atlasMode === next;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
      btn.setAttribute('tabindex', active ? '0' : '-1');
    });
    dom.atlasModeViews.forEach(view => {
      const active = view.dataset.atlasView === next;
      view.classList.toggle('active', active);
      view.hidden = !active;
    });
    const atlasControlsVisible = next === 'atlas';
    [dom.dagFilterGroup, dom.canvasTools].forEach(control => {
      if (control) control.hidden = !atlasControlsVisible;
    });
    if (next === 'stratigraphy' || next === 'ledger' || next === 'coverage') renderAtlasViews();
    if (next === 'atlas') {
      // Rendering after a mode switch restores SVG measurements in browsers
      // that had the canvas hidden while auto-fitting.
      requestAnimationFrame(() => { updateTransform(); });
    }
  }

  function renderAtlasViews() {
    renderStratigraphy();
    renderLedgerAtlas();
    renderCoverageAtlas();
    renderProvenanceStrip();
  }

  function normalizeTraceItems() {
    const stratigraphyUnavailable = state.endpointStatus.stratigraphy && state.endpointStatus.stratigraphy.available === false;
    const source = stratigraphyUnavailable ? state.traces : state.stratigraphy;
    return asArray(source).map((item, index) => {
      const hypothesisId = item.hypothesis_id || item.h_id || item.specimen_id || item.h_tag || item.hypothesis;
      const kind = String(item.kind || '').trim().toUpperCase();
      const isTrace = kind === 'TRACE' || (!kind && Boolean(item.action || item.agent_role || item.agent));
      return {
        id: item.id || item.trace_id || `TRACE-${String(index + 1).padStart(3, '0')}`,
        timestamp: item.timestamp || item.created_at || item.time || item.date || '',
        agent: item.agent_role || item.agent || item.actor || (isTrace ? 'SYSTEM' : 'STORE'),
        action: kind || String(item.action || item.event || item.stage || 'OBSERVATION').toUpperCase(),
        summary: item.title || item.claim || item.summary || item.description || item.message || '',
        hypothesisId: hypothesisId,
        status: item.status || item.verdict || ''
      };
    }).sort((a, b) => {
      const aTime = Date.parse(a.timestamp);
      const bTime = Date.parse(b.timestamp);
      if (Number.isFinite(aTime) && Number.isFinite(bTime)) return aTime - bTime;
      if (Number.isFinite(aTime)) return -1;
      if (Number.isFinite(bTime)) return 1;
      return String(a.timestamp).localeCompare(String(b.timestamp));
    });
  }

  function makeLink(text, className, handler) {
    const link = makeElement('button', className || 'atlas-link', text);
    link.type = 'button';
    link.addEventListener('click', handler);
    return link;
  }

  function renderStratigraphy() {
    const container = dom.stratigraphyContainer;
    if (!container) return;
    clearElement(container);
    const rows = normalizeTraceItems();
    if (!rows.length) {
      const unavailable = state.endpointStatus.stratigraphy && state.endpointStatus.stratigraphy.available === false;
      const message = unavailable
        ? 'Stratigraphy endpoint unavailable. Trace history will appear when a readable trace feed is available.'
        : 'No chronology returned. Trace history will appear as agents produce observations.';
      container.appendChild(makeElement('div', 'empty-evidence', message));
      if (dom.stratigraphySummary) dom.stratigraphySummary.textContent = unavailable ? 'Endpoint unavailable.' : 'No trace chronology available.';
      return;
    }
    const agents = [...new Set(rows.map(row => row.agent))];
    const fallbackNote = state.endpointStatus.stratigraphy && state.endpointStatus.stratigraphy.available === false ? ' · trace fallback' : '';
    if (dom.stratigraphySummary) dom.stratigraphySummary.textContent = `${rows.length} observations · ${agents.length} agent lane${agents.length === 1 ? '' : 's'}${fallbackNote}`;
    const timeline = makeElement('div', 'stratigraphy-rows');
    rows.forEach((row, index) => {
      const item = makeElement('article', 'stratigraphy-row');
      const marker = makeElement('span', 'stratigraphy-index', String(index + 1).padStart(2, '0'));
      const meta = makeElement('div', 'stratigraphy-meta');
      meta.appendChild(makeElement('span', 'stratigraphy-agent', row.agent));
      meta.appendChild(makeElement('span', 'stratigraphy-time', displayValue(row.timestamp, 'TIME UNSET')));
      const body = makeElement('div', 'stratigraphy-body');
      const heading = makeElement('div', 'stratigraphy-event');
      heading.appendChild(makeElement('span', 'stratigraphy-action', row.action));
      heading.appendChild(makeElement('span', 'stratigraphy-trace-id', row.id));
      body.appendChild(heading);
      body.appendChild(makeElement('p', 'stratigraphy-summary', displayValue(row.summary, 'No summary recorded.')));
      if (row.hypothesisId) {
        const linked = state.hypotheses.find(h => h.id === row.hypothesisId);
        const label = linked ? `${row.hypothesisId} · ${linked.title}` : row.hypothesisId;
        body.appendChild(makeLink(`↳ ${label}`, 'stratigraphy-hypothesis-link', () => selectHypothesis(row.hypothesisId)));
      }
      item.appendChild(marker);
      item.appendChild(meta);
      item.appendChild(body);
      timeline.appendChild(item);
    });
    container.appendChild(timeline);
  }

  function evidenceForHypothesis(hypothesis) {
    const local = state.evidenceByHypothesis.get(hypothesis.id);
    if (local && local.length) return local;
    return asArray(hypothesis.evidence || hypothesis.evidence_ledger || hypothesis.ledger);
  }

  function ledgerObservationState(evidence) {
    if (evidence.some(item => item && item.falsification_triggered)) return 'REFUTED';
    if (evidence.length) return 'OBSERVED';
    return state.endpointStatus.snapshot && state.endpointStatus.snapshot.available === false
      ? 'SNAPSHOT UNAVAILABLE'
      : 'NO EVIDENCE';
  }

  function renderLedgerAtlas() {
    const container = dom.ledgerAtlasContainer;
    if (!container) return;
    clearElement(container);
    if (!state.hypotheses.length) {
      container.appendChild(makeElement('div', 'empty-evidence', 'No hypotheses returned.'));
      return;
    }
    const table = makeElement('table', 'ledger-atlas-table');
    const thead = makeElement('thead');
    const headRow = makeElement('tr');
    ['SPECIMEN', 'STATUS', 'LEVEL', 'EVIDENCE RECORDS', 'EVIDENCE STATE', 'METRIC / Δ BASELINE', 'CI95', 'CONF', 'CITATION / ARTIFACT'].forEach(label => headRow.appendChild(makeElement('th', '', label)));
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = makeElement('tbody');
    state.hypotheses.forEach(hypothesis => {
      const evidence = evidenceForHypothesis(hypothesis);
      const latest = evidence[evidence.length - 1] || {};
      const row = makeElement('tr');
      const specimenCell = makeElement('td', 'ledger-specimen-cell');
      specimenCell.appendChild(makeLink(hypothesis.id, 'atlas-link ledger-specimen-link', () => selectHypothesis(hypothesis.id)));
      specimenCell.appendChild(makeElement('span', 'ledger-title-inline', displayValue(hypothesis.title, 'Untitled hypothesis')));
      row.appendChild(specimenCell);
      row.appendChild(makeElement('td', `ledger-status ${String(hypothesis.status || '').toLowerCase()}`, displayValue(hypothesis.status, 'UNKNOWN')));
      row.appendChild(makeElement('td', 'ledger-level', hypothesis.current_evidence_level || 'E0'));
      row.appendChild(makeElement('td', 'ledger-count', String(evidence.length)));
      const observationState = ledgerObservationState(evidence);
      const observationClass = observationState === 'REFUTED'
        ? 'refuted fail'
        : observationState === 'OBSERVED'
          ? 'observed'
          : observationState === 'SNAPSHOT UNAVAILABLE'
            ? 'unavailable'
            : 'empty';
      row.appendChild(makeElement('td', `ledger-verdict ${observationClass}`, observationState));
      const metric = latest.metric_name || latest.metric || '—';
      const delta = latest.delta_vs_baseline === undefined ? '' : ` · Δ ${displayValue(latest.delta_vs_baseline)}`;
      row.appendChild(makeElement('td', 'ledger-metric', `${metric}${delta}`));
      const ci95 = latest.ci_95_lower !== undefined || latest.ci_95_upper !== undefined
        ? `${displayValue(latest.ci_95_lower, '—')} → ${displayValue(latest.ci_95_upper, '—')}`
        : '—';
      row.appendChild(makeElement('td', 'ledger-metric', ci95));
      row.appendChild(makeElement('td', 'ledger-metric', displayValue(latest.source_confidence, '—')));
      const provenance = latest.citation_or_path || latest.artifact_hash || 'UNTRACED';
      row.appendChild(makeElement('td', 'ledger-provenance', displayValue(provenance)));
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    container.appendChild(table);
    if (dom.ledgerSummary) {
      const snapshotUnavailable = state.endpointStatus.snapshot && state.endpointStatus.snapshot.available === false;
      dom.ledgerSummary.textContent = snapshotUnavailable
        ? `Snapshot unavailable${state.endpointStatus.snapshot.error ? ` (${state.endpointStatus.snapshot.error})` : ''}; ledger states may be incomplete.`
        : `${state.hypotheses.length} specimens · ${state.hypotheses.reduce((n, h) => n + evidenceForHypothesis(h).length, 0)} evidence records`;
    }
  }

  function coverageCells() {
    const raw = state.coverage && (state.coverage.matrix || state.coverage.cells || state.coverage.data || state.coverage);
    if (Array.isArray(raw)) return raw;
    const listed = asArray(raw);
    if (listed.length) return listed;
    if (raw && typeof raw === 'object') {
      return Object.entries(raw).map(([key, value]) => {
        if (value && typeof value === 'object' && !Array.isArray(value)) return { ...value, combination: value.combination || key };
        return { combination: key, presence: value ? 'PRESENT' : 'ABSENT', count: value };
      });
    }
    return [];
  }

  function renderCoverageAtlas() {
    const container = dom.coverageAtlasContainer;
    if (!container) return;
    clearElement(container);
    const coverageUnavailable = state.endpointStatus.coverage && state.endpointStatus.coverage.available === false;
    const cells = coverageCells();
    if (!cells.length) {
      const message = coverageUnavailable
        ? `Coverage endpoint unavailable${state.endpointStatus.coverage.error ? ` (${state.endpointStatus.coverage.error})` : ''}. Basis: hypothesis-entity declarations.`
        : 'No declared hypothesis-entity intersections were returned.';
      container.appendChild(makeElement('div', 'empty-evidence', message));
      if (dom.coverageSummary) dom.coverageSummary.textContent = coverageUnavailable ? 'Endpoint unavailable.' : 'No declaration intersections returned.';
      return;
    }
    const dimensions = ['Model', 'Feature', 'Regime'];
    const grouped = new Map();
    cells.forEach(cell => {
      const combination = cell.combination || cell.key || cell.name;
      const combinationValues = Array.isArray(combination)
        ? combination
        : (typeof combination === 'string' ? combination.split(/\s*[×|,]\s*/) : []);
      const key = dimensions.map((dim, index) => {
        const value = combination && typeof combination === 'object' && !Array.isArray(combination)
          ? combination[dim] || combination[dim.toLowerCase()]
          : null;
        return value || cell[dim] || cell[dim.toLowerCase()] || cell[`${dim.toLowerCase()}_name`] || combinationValues[index] || '—';
      }).join(' × ');
      grouped.set(key, cell);
    });
    const table = makeElement('table', 'coverage-atlas-table');
    const head = makeElement('tr');
    [...dimensions, 'DECLARED', 'PRESENCE', 'HYPOTHESES', 'BASIS'].forEach(label => head.appendChild(makeElement('th', '', label)));
    const thead = makeElement('thead'); thead.appendChild(head); table.appendChild(thead);
    const body = makeElement('tbody');
    grouped.forEach((cell, key) => {
      const values = key.split(' × ');
      const row = makeElement('tr');
      values.forEach(value => row.appendChild(makeElement('td', 'coverage-dimension', value)));
      const hypothesisCount = Number(cell.hypothesis_count !== undefined ? cell.hypothesis_count : (cell.count || 0));
      const declared = String(cell.presence || (hypothesisCount > 0 ? 'PRESENT' : 'ABSENT')).toUpperCase() === 'PRESENT';
      const presence = declared ? 'PRESENT' : 'WHITE SPOT';
      row.appendChild(makeElement('td', `coverage-tested ${declared ? 'declared' : 'empty'}`, declared ? 'YES' : 'NO'));
      row.appendChild(makeElement('td', `coverage-status ${declared ? 'covered' : 'white-spot'}`, presence));
      row.appendChild(makeElement('td', 'coverage-evidence', String(hypothesisCount)));
      row.appendChild(makeElement('td', 'coverage-evidence', 'HYPOTHESIS ENTITIES'));
      body.appendChild(row);
    });
    table.appendChild(body); container.appendChild(table);
    const coveredCount = [...grouped.values()].filter(cell => {
      const hCount = Number(cell.hypothesis_count !== undefined ? cell.hypothesis_count : (cell.count || 0));
      return String(cell.presence || '').toUpperCase() === 'PRESENT' || hCount > 0;
    }).length;
    const coverageNote = coveredCount === grouped.size ? ' · NO WHITE SPOTS' : '';
    if (dom.coverageSummary) dom.coverageSummary.textContent = `Basis: hypothesis-entity declarations · ${grouped.size} intersections · ${coveredCount} declared${coverageNote}`;
  }

  function renderProvenanceStrip() {
    if (!dom.atlasProvenanceStrip) return;
    clearElement(dom.atlasProvenanceStrip);
    const p = state.provenance || {};
    const provenanceUnavailable = state.endpointStatus.provenance && state.endpointStatus.provenance.available === false;
    const items = [
      ['SOURCE', p.source || p.database || (provenanceUnavailable ? `PROVENANCE ENDPOINT UNAVAILABLE${state.endpointStatus.provenance.error ? ` (${state.endpointStatus.provenance.error})` : ''}` : 'SQLite / live snapshot')],
      ['GENERATED', p.generated_at || state.atlasSnapshot.generated_at || '—'],
      ['UPDATED', p.updated_at || p.timestamp || state.lastSyncTime || '—'],
      ['TRACES', p.trace_count !== undefined ? p.trace_count : state.traces.length],
      ['ARTIFACTS', p.artifact_count !== undefined ? p.artifact_count : '—']
    ];
    items.forEach(([label, value]) => {
      const item = makeElement('span', 'atlas-provenance-item');
      item.appendChild(makeElement('span', 'atlas-provenance-label', label));
      item.appendChild(makeElement('span', 'atlas-provenance-value', displayValue(value)));
      dom.atlasProvenanceStrip.appendChild(item);
    });
  }

  function bindDynamicConfig() {
    const conf = state.config || {};

    // 1. Zone 1: Domain & Breadcrumbs (100% Dynamic)
    if (dom.hdrProjectDomain) {
      dom.hdrProjectDomain.textContent = conf.domain || 'Autonomous Empirical Research & Hypothesis Governance';
    }

    if (dom.projectName) {
      if (conf.project_name) {
        dom.projectName.textContent = conf.project_name;
        dom.projectName.style.display = 'inline';
      } else {
        dom.projectName.style.display = 'none';
      }
    }

    if (dom.projectMetric) {
      if (conf.primary_metric) {
        const goal = conf.metric_goal ? ` (${conf.metric_goal})` : '';
        dom.projectMetric.textContent = `${conf.primary_metric}${goal}`;
        dom.projectMetric.style.display = 'inline';
      } else {
        dom.projectMetric.style.display = 'none';
      }
    }

    if (dom.hdrTaskDesc) {
      if (conf.task_description) {
        dom.hdrTaskDesc.textContent = conf.task_description;
        dom.hdrTaskDesc.style.display = 'inline';
        if (dom.dotTask) dom.dotTask.style.display = conf.primary_metric ? 'inline' : 'none';
      } else {
        dom.hdrTaskDesc.style.display = 'none';
        if (dom.dotTask) dom.dotTask.style.display = 'none';
      }
    }
  }

  // --------------------------------------------------------------------------
  // KPI Summary Strip & Popperian Ladder
  // --------------------------------------------------------------------------
  function updateKPISummary() {
    const total = state.hypotheses.length;
    const confirmed = state.hypotheses.filter(h => h.status === 'CONFIRMED').length;
    // PROPOSED is a registered E0 specimen, not active investigation work.
    const inProg = state.hypotheses.filter(h => h.status === 'IN_PROGRESS').length;
    const falsified = state.hypotheses.filter(h => h.status === 'FALSIFIED').length;

    dom.kpiTotal.textContent = String(total).padStart(2, '0');
    dom.kpiConfirmed.textContent = String(confirmed).padStart(2, '0');
    dom.kpiInProgress.textContent = String(inProg).padStart(2, '0');
    dom.kpiFalsified.textContent = String(falsified).padStart(2, '0');

    // Update active filter underline
    dom.kpiCells.forEach(cell => {
      cell.classList.toggle('active-filter', cell.dataset.filter === state.activeFilter);
      cell.setAttribute('aria-pressed', cell.dataset.filter === state.activeFilter ? 'true' : 'false');
    });

    // Popperian Evidence Maturity Spectrum
    const levels = { E0: 0, E1: 0, E2: 0, E3: 0, E4: 0, E5: 0 };
    state.hypotheses.forEach(h => {
      const lvl = h.current_evidence_level || 'E0';
      if (levels[lvl] !== undefined) levels[lvl]++;
    });

    dom.evidenceSpectrum.innerHTML = Object.keys(levels).map(lvl => {
      const count = levels[lvl];
      const isLevelActive = state.activeLevelFilter === lvl;
      const isPopulated = count > 0;
      const cls = `s-pill ${isLevelActive ? 'active' : ''} ${isPopulated ? 'populated' : ''}`;
      return `<span class="${cls}" data-level="${lvl}" title="${MATURITY_CRITERIA[lvl]}">${lvl} ${count}</span>`;
    }).join('');

    // Attach hover & click listeners to ladder pills
    dom.evidenceSpectrum.querySelectorAll('.s-pill').forEach(pill => {
      const lvl = pill.dataset.level;
      pill.addEventListener('mouseenter', () => {
        if (dom.ladderActiveHint) dom.ladderActiveHint.textContent = MATURITY_CRITERIA[lvl];
      });
      pill.addEventListener('mouseleave', () => {
        if (dom.ladderActiveHint) {
          dom.ladderActiveHint.textContent = state.activeLevelFilter
            ? MATURITY_CRITERIA[state.activeLevelFilter]
            : 'Hover to inspect Popperian criteria';
        }
      });
      pill.addEventListener('click', () => {
        if (state.activeLevelFilter === lvl) {
          state.activeLevelFilter = null;
        } else {
          state.activeLevelFilter = lvl;
        }
        updateKPISummary();
        renderDAG();
      });
    });
  }

  // --------------------------------------------------------------------------
  // Organic Isogrid Topological Layout Algorithm
  // --------------------------------------------------------------------------
  function initializeLayoutIfEmpty(nodes) {
    const nodeMap = new Map();
    nodes.forEach(n => nodeMap.set(n.id, { ...n, layer: 0 }));

    let changed = true;
    let iterations = 0;
    while (changed && iterations < 50) {
      changed = false;
      iterations++;
      nodes.forEach(n => {
        const item = nodeMap.get(n.id);
        (n.parent_ids || []).forEach(pId => {
          if (nodeMap.has(pId)) {
            const pItem = nodeMap.get(pId);
            if (item.layer <= pItem.layer) {
              item.layer = pItem.layer + 1;
              changed = true;
            }
          }
        });
      });
    }

    const layers = [];
    nodeMap.forEach(n => {
      while (layers.length <= n.layer) layers.push([]);
      layers[n.layer].push(n);
    });

    layers.forEach((layerNodes, layerIdx) => {
      const totalWidth = layerNodes.length * NODE_WIDTH + (layerNodes.length - 1) * GAP_X;
      const staggerX = (layerIdx % 2 === 1) ? 28 : 0;
      const startX = Math.max(60, 580 - totalWidth / 2) + staggerX;

      layerNodes.forEach((node, nodeIdx) => {
        if (!state.nodePositions.has(node.id)) {
          state.nodePositions.set(node.id, {
            x: startX + nodeIdx * (NODE_WIDTH + GAP_X),
            y: 60 + layerIdx * (NODE_HEIGHT + GAP_Y),
            width: NODE_WIDTH,
            height: NODE_HEIGHT
          });
        }
      });
    });
  }

  // --------------------------------------------------------------------------
  // SVG Organic Voronoi Pebble DAG Rendering
  // --------------------------------------------------------------------------
  const DAG_RELATION_TYPES = new Set(['DEPENDS_ON', 'BLOCKS', 'REFINES', 'FALSIFIES', 'PRODUCES', 'GATED_BY']);

  function normalizeRelation(relation) {
    if (!relation) return null;
    const relationType = String(relation.relation_type || relation.relation || '').toUpperCase();
    const sourceId = relation.source_id || relation.source || relation.from;
    const targetId = relation.target_id || relation.target || relation.to;
    if (!sourceId || !targetId || !DAG_RELATION_TYPES.has(relationType)) return null;
    return { source_id: String(sourceId), target_id: String(targetId), relation_type: relationType };
  }

  function dagRelations() {
    const relationSet = new Set();
    const result = [];

    function addRel(src, tgt, type) {
      if (!src || !tgt) return;
      const key = `${src}->${tgt}:${type}`;
      if (!relationSet.has(key)) {
        relationSet.add(key);
        result.push({ source_id: String(src), target_id: String(tgt), relation_type: type });
      }
    }

    // 1. Explicit relations from relations table
    (state.relations || []).forEach(rel => {
      const norm = normalizeRelation(rel);
      if (norm) addRel(norm.source_id, norm.target_id, norm.relation_type);
    });

    // 2. Parent-child dependencies from hypotheses
    (state.hypotheses || []).forEach(hypothesis => {
      (hypothesis.parent_ids || []).forEach(parentId => {
        addRel(hypothesis.id, parentId, 'DEPENDS_ON');
      });
    });

    return result;
  }

  function dagEdgeEndpoints(relation) {
    // DEPENDS_ON is stored child -> prerequisite, but the atlas has always
    // drawn prerequisites above their dependent child.
    if (relation.relation_type === 'DEPENDS_ON') {
      return { sourceId: relation.target_id, targetId: relation.source_id };
    }
    return { sourceId: relation.source_id, targetId: relation.target_id };
  }

  function edgeDomId(relation) {
    const endpoints = dagEdgeEndpoints(relation);
    return `edge-${domIdPart(endpoints.sourceId)}-${domIdPart(endpoints.targetId)}-${domIdPart(relation.relation_type)}`;
  }

  // External record IDs are data, not DOM syntax. Keep generated SVG IDs
  // predictable while preventing punctuation in an imported ID from altering
  // selectors or fragment references.
  function domIdPart(value) {
    return String(value).replace(/[^A-Za-z0-9_-]/g, char => `_${char.codePointAt(0).toString(16)}_`);
  }

  function computeGraphFingerprint(nodes, relations, filter, levelFilter, ghosts, selectedId) {
    const nodeStr = nodes.map(n => `${n.id}:${n.status}:${n.current_evidence_level}:${n.title}`).join(';');
    const relStr = (relations || []).map(r => `${r.source_id}->${r.target_id}:${r.relation_type}`).join(';');
    return `${filter}|${levelFilter}|${ghosts}|${selectedId}|${nodes.length}|${nodeStr}|${relStr}`;
  }

  function renderDAG() {
    const svg = dom.svg;

    let filteredNodes = state.hypotheses;
    if (state.activeFilter !== 'ALL') {
      filteredNodes = filteredNodes.filter(h => h.status === state.activeFilter);
    }
    if (state.activeLevelFilter) {
      filteredNodes = filteredNodes.filter(h => (h.current_evidence_level || 'E0') === state.activeLevelFilter);
    }

    if (filteredNodes.length === 0 && !state.showGhosts) {
      state.lastGraphFingerprint = null;
      svg.innerHTML = `
        <text x="50%" y="50%" text-anchor="middle" fill="var(--ink-muted)" font-family="IBM Plex Mono" font-size="14">
          [ No specimens matching filter: ${state.activeFilter}${state.activeLevelFilter ? ' / ' + state.activeLevelFilter : ''} ]
        </text>
      `;
      return;
    }

    const currentFingerprint = computeGraphFingerprint(
      filteredNodes,
      state.relations,
      state.activeFilter,
      state.activeLevelFilter,
      state.showGhosts,
      state.selectedHypothesisId
    );
    if (state.lastGraphFingerprint === currentFingerprint && document.getElementById('dag-viewport')) {
      return;
    }
    state.lastGraphFingerprint = currentFingerprint;

    svg.innerHTML = '';

    // Arrow markers
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 2 L 8 5 L 0 8 z" fill="currentColor" style="color: var(--svg-edge-stroke);" />
      </marker>
      <marker id="arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 2 L 8 5 L 0 8 z" fill="currentColor" style="color: var(--svg-edge-highlight);" />
      </marker>
    `;
    svg.appendChild(defs);

    initializeLayoutIfEmpty(state.hypotheses);

    const gViewport = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gViewport.setAttribute('id', 'dag-viewport');
    gViewport.setAttribute('transform', `translate(${state.transform.x}, ${state.transform.y}) scale(${state.transform.scale})`);

    // 1. Edges Layer (Rendered strictly UNDER nodes)
    const gEdges = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gEdges.setAttribute('id', 'dag-edges-layer');
    gViewport.appendChild(gEdges);

    const visibleIds = new Set(filteredNodes.map(node => String(node.id)));
    dagRelations().forEach(relation => {
      const { sourceId, targetId } = dagEdgeEndpoints(relation);
      // Never draw an orphan edge when a status/level filter hides either end.
      if (!visibleIds.has(sourceId) || !visibleIds.has(targetId)) return;
      const sourcePos = state.nodePositions.get(sourceId);
      const targetPos = state.nodePositions.get(targetId);
      if (!sourcePos || !targetPos) return;

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('id', edgeDomId(relation));
      path.setAttribute('class', `edge-path relation-${domIdPart(String(relation.relation_type).toLowerCase())}`);
      path.dataset.relationType = relation.relation_type;
      path.setAttribute('aria-label', relation.relation_type.replaceAll('_', ' '));
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = relation.relation_type.replaceAll('_', ' ');
      path.appendChild(title);

      const isRelated = state.selectedHypothesisId &&
        (state.selectedHypothesisId === relation.source_id || state.selectedHypothesisId === relation.target_id);

      if (isRelated) path.classList.add('highlighted');
      path.setAttribute('marker-end', isRelated ? 'url(#arrow-active)' : 'url(#arrow)');

      updateEdgePath(path, sourcePos, targetPos);
      gEdges.appendChild(path);
    });

    // 2. Generative Voronoi Pebble Specimen Nodes
    filteredNodes.forEach(node => {
      const pos = state.nodePositions.get(node.id);
      if (!pos) return;

      const isSelected = state.selectedHypothesisId === node.id;
      const isFalsified = node.status === 'FALSIFIED';
      const isConfirmed = node.status === 'CONFIRMED';
      const statusClass = `status-${String(node.status || 'PROPOSED').toLowerCase().replaceAll('_', '-')}`;

      const gNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      gNode.setAttribute('class', `dag-node-group ${statusClass} ${isSelected ? 'selected' : ''} ${isFalsified ? 'falsified' : ''} ${isConfirmed ? 'confirmed' : ''}`);
      gNode.setAttribute('id', `node-group-${domIdPart(node.id)}`);
      gNode.setAttribute('transform', `translate(${pos.x}, ${pos.y})`);
      gNode.setAttribute('tabindex', '0');
      gNode.setAttribute('role', 'button');
      gNode.setAttribute('aria-label', `${node.id}: ${node.title}. ${node.status}, ${node.current_evidence_level || 'E0'}. Open dossier.`);
      gNode.dataset.id = node.id;

      const pebblePath = getVoronoiPebbleGeometry(node.id, NODE_WIDTH, NODE_HEIGHT);
      const titleLinesSVG = formatBalancedTitleSVG(node.title, 218, 24, 46, 2);
      const currentLevel = node.current_evidence_level || 'E0';
      const targetLevel = node.target_evidence_level || 'E3';

      const statusRaw = String(node.status || 'PROPOSED').toLowerCase().replace('_', ' ');

      gNode.innerHTML = `
        <path class="node-plate" d="${pebblePath}" />
        <text class="node-id" x="24" y="24">${escapeSvgText(node.id)}</text>
        <text class="node-level" x="${NODE_WIDTH - 24}" y="24" text-anchor="end">${escapeSvgText(currentLevel)} / ${escapeSvgText(targetLevel)}</text>
        ${titleLinesSVG}
        <g class="node-status-cluster" transform="translate(24, 82)">
          <text class="node-status-dot" x="0" y="0">●</text>
          <text class="node-status-text" x="8" y="0">${escapeSvgText(statusRaw)}</text>
        </g>
      `;

      gNode.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        startDraggingNode(node.id, e);
      });
      gNode.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        selectHypothesis(node.id);
      });

      gViewport.appendChild(gNode);
    });

    // 3. Optional White Spot Ghost Nodes
    if (state.showGhosts) {
      state.gaps.slice(0, 4).forEach((gap, idx) => {
        const ghostId = `GHOST-${idx + 1}`;
        const ghostX = 60 + idx * (NODE_WIDTH + GAP_X);
        const ghostY = 380;

        const gGhost = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        gGhost.setAttribute('class', 'dag-node-group ghost-node');
        gGhost.setAttribute('transform', `translate(${ghostX}, ${ghostY})`);

        const pebblePath = getVoronoiPebbleGeometry(ghostId, NODE_WIDTH, NODE_HEIGHT);
        const gapTitle = JSON.stringify(gap.combination || gap).substring(0, 30);

        gGhost.innerHTML = `
          <path class="node-plate" d="${pebblePath}" />
          <text class="node-id" x="24" y="24">⚡ WHITE SPOT GAP</text>
          <text class="node-ghost-title" x="24" y="46">${escapeSvgText(gapTitle)}</text>
          <g class="node-status-cluster" transform="translate(24, 82)">
            <text class="node-status-dot" x="0" y="0">○</text>
            <text class="node-status-text" x="8" y="0">untested</text>
          </g>
        `;
        gViewport.appendChild(gGhost);
      });
    }

    svg.appendChild(gViewport);
  }

  // --------------------------------------------------------------------------
  // Drag & Drop Vector Controller
  // --------------------------------------------------------------------------
  function startDraggingNode(nodeId, e) {
    state.draggingNode = nodeId;
    state.hasMovedNode = false;
    const pos = state.nodePositions.get(nodeId);

    state.dragNodeStart = {
      mouseX: e.clientX,
      mouseY: e.clientY,
      nodeX: pos.x,
      nodeY: pos.y
    };

    window.addEventListener('mousemove', onNodeMouseMove);
    window.addEventListener('mouseup', onNodeMouseUp);
  }

  function onNodeMouseMove(e) {
    if (!state.draggingNode) return;

    const dx = (e.clientX - state.dragNodeStart.mouseX) / state.transform.scale;
    const dy = (e.clientY - state.dragNodeStart.mouseY) / state.transform.scale;

    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      state.hasMovedNode = true;
    }

    const pos = state.nodePositions.get(state.draggingNode);
    pos.x = state.dragNodeStart.nodeX + dx;
    pos.y = state.dragNodeStart.nodeY + dy;

    const gNode = document.getElementById(`node-group-${domIdPart(state.draggingNode)}`);
    if (gNode) {
      gNode.setAttribute('transform', `translate(${pos.x}, ${pos.y})`);
    }

    recalculateConnectedEdges(state.draggingNode);
  }

  function onNodeMouseUp() {
    window.removeEventListener('mousemove', onNodeMouseMove);
    window.removeEventListener('mouseup', onNodeMouseUp);

    if (!state.hasMovedNode && state.draggingNode) {
      selectHypothesis(state.draggingNode);
    }
    state.draggingNode = null;
  }

  function recalculateConnectedEdges(nodeId) {
    dagRelations().forEach(relation => {
      const { sourceId, targetId } = dagEdgeEndpoints(relation);
      if (sourceId !== String(nodeId) && targetId !== String(nodeId)) return;
      const edge = document.getElementById(edgeDomId(relation));
      const srcPos = state.nodePositions.get(sourceId);
      const tgtPos = state.nodePositions.get(targetId);
      if (edge && srcPos && tgtPos) updateEdgePath(edge, srcPos, tgtPos);
    });
  }

  function updateEdgePath(pathElem, srcPos, tgtPos) {
    const x1 = srcPos.x + NODE_WIDTH / 2;
    const y1 = srcPos.y + NODE_HEIGHT;
    const x2 = tgtPos.x + NODE_WIDTH / 2;
    const y2 = tgtPos.y;

    const midY = (y1 + y2) / 2;
    pathElem.setAttribute('d', `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`);
  }

  // --------------------------------------------------------------------------
  // Auto-Fit Canvas with Safe Inset Bounds
  // --------------------------------------------------------------------------
  function autoFitCanvas() {
    if (state.hypotheses.length === 0) return;

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    state.nodePositions.forEach(pos => {
      minX = Math.min(minX, pos.x);
      maxX = Math.max(maxX, pos.x + NODE_WIDTH);
      minY = Math.min(minY, pos.y);
      maxY = Math.max(maxY, pos.y + NODE_HEIGHT);
    });

    const containerW = dom.canvasContainer.clientWidth || 900;
    const containerH = dom.canvasContainer.clientHeight || 600;

    const contentW = maxX - minX + 120;
    const contentH = maxY - minY + 120;

    const scaleX = containerW / contentW;
    const scaleY = containerH / contentH;
    const scale = Math.max(0.35, Math.min(1.15, Math.min(scaleX, scaleY)));

    state.transform.scale = scale;
    state.transform.x = (containerW - (maxX - minX) * scale) / 2 - minX * scale;
    state.transform.y = Math.max(40, (containerH - (maxY - minY) * scale) / 2 - minY * scale);

    updateTransform();
    renderDAG();
  }

  // --------------------------------------------------------------------------
  // Smooth Fly-To Node Navigation
  // --------------------------------------------------------------------------
  function flyToNode(id) {
    const pos = state.nodePositions.get(id);
    if (!pos) return;

    const containerW = dom.canvasContainer.clientWidth || 900;
    const containerH = dom.canvasContainer.clientHeight || 600;

    const targetX = containerW / 2 - (pos.x + NODE_WIDTH / 2) * state.transform.scale;
    const targetY = containerH / 2 - (pos.y + NODE_HEIGHT / 2) * state.transform.scale;

    state.transform.x = targetX;
    state.transform.y = targetY;
    updateTransform();
    selectHypothesis(id);
  }

  // --------------------------------------------------------------------------
  // Specimen Dossier (Inspector)
  // --------------------------------------------------------------------------
  async function selectHypothesis(id) {
    state.selectedHypothesisId = id;
    renderDAG();

    if (state.activeTab !== 'inspector') {
      switchTab('inspector');
    }

    renderInspector(id);
  }

  async function renderInspector(id) {
    const inspectorGeneration = ++state.inspectorGeneration;
    const node = state.hypotheses.find(h => h.id === id);
    if (!node) {
      dom.inspectorEmpty.style.display = 'flex';
      dom.inspectorBody.style.display = 'none';
      return;
    }

    dom.inspectorEmpty.style.display = 'none';
    dom.inspectorBody.style.display = 'block';

    dom.insId.textContent = node.id;
    dom.insStatus.textContent = node.status;
    dom.insStatus.className = `spec-badge ${node.status}`;
    dom.insLevel.textContent = `LEVEL ${node.current_evidence_level || 'E0'}`;
    dom.insTitle.textContent = node.title;
    dom.insMechanism.textContent = node.a_priori_mechanism || 'No mathematical mechanism registered.';
    dom.insFalsification.textContent = node.falsification_criteria || 'No Popperian boundary registered.';

    // Dependencies
    if (node.parent_ids && node.parent_ids.length > 0) {
      clearElement(dom.insParents);
      node.parent_ids.forEach(p => {
        dom.insParents.appendChild(makeLink(`↑ ${p}`, 'dep-node-pill', () => flyToNode(p)));
      });
    } else {
      clearElement(dom.insParents);
      dom.insParents.appendChild(makeElement('span', 'ink-muted', 'Root Hypothesis (A Priori Origin)'));
    }

    // Evidence
    try {
      const res = await safeFetchJson(`/hypotheses/${encodeURIComponent(id)}`);
      if (inspectorGeneration !== state.inspectorGeneration) return;
      const evidence = asArray(res.evidence || res.evidence_ledger || res.ledger);
      state.evidenceByHypothesis.set(id, evidence);
      dom.insLedgerCount.textContent = evidence.length;
      clearElement(dom.insEvidenceList);

      if (evidence.length === 0) {
        dom.insEvidenceList.appendChild(makeElement('div', 'empty-evidence', `No evidence records registered yet. ${MATURITY_CRITERIA.E0}`));
      } else {
        evidence.forEach(ev => {
          const isFail = ev.falsification_triggered;
          const verdictClass = isFail ? 'fail' : 'pass';
          const verdictText = isFail ? 'REFUTED' : 'OBSERVED';
          const card = makeElement('div', 'ledger-item-card');
          const header = makeElement('div', 'ledger-row-header');
          header.appendChild(makeElement('span', 'ledger-level-tag', `[${ev.evidence_level || 'E1'}]`));
          header.appendChild(makeElement('span', 'ledger-metric-name', ev.metric_name || 'EMPIRICAL'));
          header.appendChild(makeElement('span', `ledger-verdict-badge ${verdictClass}`, verdictText));
          card.appendChild(header);
          card.appendChild(makeElement('div', 'ledger-claim-prose', ev.claim || ev.summary || 'No claim recorded.'));
          const details = makeElement('div', 'ledger-evidence-details');
          const ci95 = ev.ci_95_lower !== undefined || ev.ci_95_upper !== undefined
            ? `${displayValue(ev.ci_95_lower, '—')} → ${displayValue(ev.ci_95_upper, '—')}`
            : undefined;
          const values = [
            ['VALUE', ev.metric_value !== undefined ? ev.metric_value : ev.value],
            ['DELTA', ev.delta_vs_baseline],
            ['CI95', ci95],
            ['CONFIDENCE', ev.source_confidence],
            ['CITATION', ev.citation_or_path],
            ['ARTIFACT', ev.artifact_hash],
            ['TIMESTAMP', ev.timestamp || ev.created_at]
          ].filter(([, value]) => value !== undefined && value !== null && value !== '');
          values.forEach(([label, value]) => {
            const detail = makeElement('span', 'ledger-evidence-detail');
            detail.appendChild(makeElement('b', '', `${label} `));
            detail.appendChild(document.createTextNode(displayValue(value)));
            details.appendChild(detail);
          });
          if (values.length) card.appendChild(details);
          dom.insEvidenceList.appendChild(card);
        });
      }
    } catch (err) {
      if (inspectorGeneration !== state.inspectorGeneration) return;
      clearElement(dom.insEvidenceList);
      const fallback = evidenceForHypothesis(node);
      if (fallback.length) {
        state.evidenceByHypothesis.set(id, fallback);
        fallback.forEach(ev => {
          const card = makeElement('div', 'ledger-item-card');
          card.appendChild(makeElement('div', 'ledger-row-header', `[${ev.evidence_level || 'E1'}] ${ev.metric_name || 'EMPIRICAL'}`));
          card.appendChild(makeElement('div', 'ledger-claim-prose', ev.claim || ev.summary || 'No claim recorded.'));
          dom.insEvidenceList.appendChild(card);
        });
        dom.insLedgerCount.textContent = fallback.length;
      } else {
        dom.insEvidenceList.appendChild(makeElement('div', 'empty-evidence', 'Empirical ledger unavailable for this specimen.'));
      }
    }
  }

  // --------------------------------------------------------------------------
  // Operational Trace Feed
  // --------------------------------------------------------------------------
  function renderTraces() {
    const container = dom.tracesStreamContainer;
    const filter = dom.tracesSearch.value.trim().toLowerCase();

    const filtered = state.traces.filter(t => {
      if (!filter) return true;
      return String(t.action || '').toLowerCase().includes(filter) ||
             String(t.summary || t.description || '').toLowerCase().includes(filter) ||
             String(t.h_tag || t.hypothesis_id || t.h_id || '').toLowerCase().includes(filter);
    });

    dom.tracesCountText.textContent = `${state.traces.length} entries`;
    clearElement(container);
    if (filtered.length === 0) {
      container.appendChild(makeElement('div', 'empty-evidence', 'No matching traces.'));
      return;
    }

    filtered.forEach(t => {
      const timeStr = t.timestamp ? t.timestamp.split('T')[1]?.substring(0, 8) || t.timestamp : '';
      const card = makeElement('article', 'trace-card');
      const header = makeElement('div', 'tr-head');
      header.appendChild(makeElement('span', 'tr-action', `${t.action || 'OBSERVATION'} // ${t.agent_role || t.agent || 'Lead-PI'}`));
      header.appendChild(makeElement('span', 'tr-time', timeStr));
      card.appendChild(header);
      card.appendChild(makeElement('div', 'tr-summary', t.summary || t.description || ''));
      const hypothesisId = t.hypothesis_id || t.h_id || t.specimen_id || t.h_tag || t.hypothesis;
      if (hypothesisId) {
        const hypothesis = state.hypotheses.find(h => h.id === hypothesisId);
        card.appendChild(makeLink(`↳ ${hypothesisId}${hypothesis ? ` · ${hypothesis.title}` : ''}`, 'trace-hypothesis-link', () => selectHypothesis(hypothesisId)));
      }
      container.appendChild(card);
    });
  }

  // --------------------------------------------------------------------------
  // White Spot Gaps
  // --------------------------------------------------------------------------
  function renderGaps() {
    const container = dom.gapsMatrixContainer;
    clearElement(container);
    if (state.gaps.length === 0) {
      const unavailable = state.endpointStatus.gaps && state.endpointStatus.gaps.available === false;
      container.appendChild(makeElement('div', 'empty-evidence', unavailable
        ? `Gap endpoint unavailable${state.endpointStatus.gaps.error ? ` (${state.endpointStatus.gaps.error})` : ''}.`
        : 'No white spot gaps detected. All primary combinations are declared.'));
      return;
    }

    state.gaps.forEach(g => {
      const item = makeElement('div', 'gap-pill-item');
      item.appendChild(makeElement('span', 'gap-lbl-text', displayValue(g.combination || g)));
      item.appendChild(makeElement('span', 'gap-tag', 'WHITE SPOT'));
      container.appendChild(item);
    });
  }

  // --------------------------------------------------------------------------
  // Command Palette / Search Modal (⌘K)
  // --------------------------------------------------------------------------
  function openSearchModal() {
    dom.searchModal.style.display = 'flex';
    dom.cmdKInput.value = '';
    dom.cmdKInput.focus();
    state.searchSelectedIndex = 0;
    renderSearchResults('');
  }

  function closeSearchModal() {
    dom.searchModal.style.display = 'none';
  }

  function renderSearchResults(query) {
    const q = query.trim().toLowerCase();
    const matches = state.hypotheses.filter(h => {
      if (!q) return true;
      return h.id.toLowerCase().includes(q) ||
             h.title.toLowerCase().includes(q) ||
             h.status.toLowerCase().includes(q);
    });

    clearElement(dom.cmdKResults);
    if (matches.length === 0) {
      dom.cmdKResults.appendChild(makeElement('div', 'empty-evidence', 'No matching specimens.'));
      return;
    }

    matches.forEach((m, idx) => {
      const item = makeElement('div', `cmd-k-result-item ${idx === state.searchSelectedIndex ? 'selected' : ''}`);
      item.dataset.id = m.id;
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', idx === state.searchSelectedIndex ? 'true' : 'false');
      item.setAttribute('tabindex', '0');
      const left = makeElement('div', 'cmd-k-item-left');
      left.appendChild(makeElement('span', 'cmd-k-item-id', `${m.id} · Level ${m.current_evidence_level || 'E0'}`));
      left.appendChild(makeElement('span', 'cmd-k-item-title', m.title));
      item.appendChild(left);
      item.appendChild(makeElement('span', `cmd-k-item-badge spec-badge ${m.status}`, m.status));
      item.addEventListener('click', () => {
        const id = item.dataset.id;
        closeSearchModal();
        flyToNode(id);
      });
      item.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        item.click();
      });
      dom.cmdKResults.appendChild(item);
    });
  }

  // --------------------------------------------------------------------------
  // Tab Switching
  // --------------------------------------------------------------------------
  function switchTab(tabName) {
    state.activeTab = tabName;
    dom.tabButtons.forEach(btn => {
      const active = btn.dataset.tab === tabName;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    dom.tabContents.forEach(content => {
      const active = content.id === `tab-${tabName}`;
      content.classList.toggle('active', active);
      content.hidden = !active;
    });
  }

  // --------------------------------------------------------------------------
  // Pan & Zoom
  // --------------------------------------------------------------------------
  function setupPanZoom() {
    const container = dom.canvasContainer;

    container.addEventListener('mousedown', (e) => {
      if (e.target.closest('.dag-node-group')) return;
      state.isDraggingCanvas = true;
      state.dragStart = { x: e.clientX - state.transform.x, y: e.clientY - state.transform.y };
    });

    window.addEventListener('mousemove', (e) => {
      if (!state.isDraggingCanvas) return;
      state.transform.x = e.clientX - state.dragStart.x;
      state.transform.y = e.clientY - state.dragStart.y;
      updateTransform();
    });

    window.addEventListener('mouseup', () => {
      state.isDraggingCanvas = false;
    });

    container.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
      state.transform.scale = Math.max(0.2, Math.min(2.5, state.transform.scale * zoomFactor));
      updateTransform();
    }, { passive: false });

    dom.btnZoomIn.addEventListener('click', () => {
      state.transform.scale = Math.min(2.5, state.transform.scale * 1.15);
      updateTransform();
    });

    dom.btnZoomOut.addEventListener('click', () => {
      state.transform.scale = Math.max(0.2, state.transform.scale * 0.85);
      updateTransform();
    });

    dom.btnZoomReset.addEventListener('click', autoFitCanvas);
  }

  function updateTransform() {
    const g = document.getElementById('dag-viewport');
    if (g) {
      g.setAttribute('transform', `translate(${state.transform.x}, ${state.transform.y}) scale(${state.transform.scale})`);
    }
    if (dom.zoomLevelText) {
      dom.zoomLevelText.textContent = `${Math.round(state.transform.scale * 100)}%`;
    }
  }

  // --------------------------------------------------------------------------
  // Initialization
  // --------------------------------------------------------------------------
  function init() {
    applyTheme(state.theme);
    initNoiseShader();
    initHeaderFieldAnimation();
    setupPanZoom();

    dom.tabButtons.forEach(btn => {
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-controls', `tab-${btn.dataset.tab}`);
    });
    dom.tabContents.forEach(content => {
      content.setAttribute('role', 'tabpanel');
      content.setAttribute('tabindex', '0');
    });
    switchTab(state.activeTab);

    dom.btnThemeToggle.addEventListener('click', toggleTheme);

    // Research atlas modes are observational views only. The DAG remains the
    // default and existing filters/actions continue to work inside ATLAS.
    dom.atlasModeButtons.forEach((btn, index) => {
      btn.addEventListener('click', () => showAtlasMode(btn.dataset.atlasMode));
      btn.addEventListener('keydown', (event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        const nextIndex = (index + (event.key === 'ArrowRight' ? 1 : -1) + dom.atlasModeButtons.length) % dom.atlasModeButtons.length;
        const next = dom.atlasModeButtons[nextIndex];
        showAtlasMode(next.dataset.atlasMode);
        next.focus();
      });
    });

    // KPI Cell Click Filters
    dom.kpiCells.forEach(cell => {
      cell.setAttribute('role', 'button');
      cell.setAttribute('tabindex', '0');
      cell.setAttribute('aria-pressed', cell.dataset.filter === state.activeFilter ? 'true' : 'false');
      cell.addEventListener('click', () => {
        state.activeFilter = cell.dataset.filter;
        state.activeLevelFilter = null;
        dom.filterButtons.forEach(b => {
          b.classList.toggle('active', b.dataset.status === state.activeFilter);
          if (b.id !== 'btn-toggle-ghosts') b.setAttribute('aria-pressed', b.dataset.status === state.activeFilter ? 'true' : 'false');
        });
        updateKPISummary();
        renderDAG();
      });
      cell.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        cell.click();
      });
    });

    // Canvas Filter Buttons
    dom.filterButtons.forEach(btn => {
      if (btn.id === 'btn-toggle-ghosts') return;
      btn.setAttribute('aria-pressed', btn.classList.contains('active') ? 'true' : 'false');
      btn.addEventListener('click', () => {
        dom.filterButtons.forEach(b => {
          if (b.id !== 'btn-toggle-ghosts') b.classList.remove('active');
        });
        btn.classList.add('active');
        dom.filterButtons.forEach(b => {
          if (b.id !== 'btn-toggle-ghosts') b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
        });
        state.activeFilter = btn.dataset.status;
        state.activeLevelFilter = null;
        updateKPISummary();
        renderDAG();
      });
    });

    // White Spot Ghost Toggle
    if (dom.btnToggleGhosts) {
      dom.btnToggleGhosts.setAttribute('aria-pressed', 'false');
      dom.btnToggleGhosts.addEventListener('click', () => {
        state.showGhosts = !state.showGhosts;
        dom.btnToggleGhosts.classList.toggle('active', state.showGhosts);
        dom.btnToggleGhosts.setAttribute('aria-pressed', state.showGhosts ? 'true' : 'false');
        renderDAG();
      });
    }

    // Tab buttons
    dom.tabButtons.forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Dossier Actions
    if (dom.btnCopyId) {
      dom.btnCopyId.addEventListener('click', async () => {
        if (!state.selectedHypothesisId) return;
        const originalLabel = dom.btnCopyId.textContent;
        try {
          if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
            throw new Error('Clipboard API unavailable');
          }
          await navigator.clipboard.writeText(state.selectedHypothesisId);
          dom.btnCopyId.textContent = 'COPIED!';
        } catch (error) {
          console.warn('Unable to copy hypothesis ID:', error);
          dom.btnCopyId.textContent = 'COPY FAILED';
        }
        setTimeout(() => { dom.btnCopyId.textContent = originalLabel; }, 1500);
      });
    }

    if (dom.btnFocusNode) {
      dom.btnFocusNode.addEventListener('click', () => {
        if (state.selectedHypothesisId) {
          flyToNode(state.selectedHypothesisId);
        }
      });
    }

    if (dom.btnFilterTraces) {
      dom.btnFilterTraces.addEventListener('click', () => {
        if (state.selectedHypothesisId) {
          switchTab('traces');
          dom.tracesSearch.value = state.selectedHypothesisId;
          renderTraces();
        }
      });
    }

    dom.btnRefresh.addEventListener('click', () => syncDataIfChanged(true));
    dom.tracesSearch.addEventListener('input', renderTraces);

    // Command Palette Events
    if (dom.btnOpenSearch) {
      dom.btnOpenSearch.addEventListener('click', openSearchModal);
    }
    if (dom.cmdKInput) {
      dom.cmdKInput.addEventListener('input', (e) => {
        state.searchSelectedIndex = 0;
        renderSearchResults(e.target.value);
      });
      dom.cmdKInput.addEventListener('keydown', event => {
        const items = [...dom.cmdKResults.querySelectorAll('[role="option"]')];
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          if (!items.length) return;
          event.preventDefault();
          const delta = event.key === 'ArrowDown' ? 1 : -1;
          state.searchSelectedIndex = (state.searchSelectedIndex + delta + items.length) % items.length;
          renderSearchResults(dom.cmdKInput.value);
          dom.cmdKResults.querySelectorAll('[role="option"]')[state.searchSelectedIndex]?.focus();
        } else if (event.key === 'Enter' && items[state.searchSelectedIndex]) {
          event.preventDefault();
          items[state.searchSelectedIndex].click();
        }
      });
    }
    if (dom.searchModal) {
      dom.searchModal.addEventListener('click', (e) => {
        if (e.target === dom.searchModal) closeSearchModal();
      });
    }

    // Global Keybindings (⌘K, Escape)
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (dom.searchModal.style.display === 'none' || !dom.searchModal.style.display) {
          openSearchModal();
        } else {
          closeSearchModal();
        }
      } else if (e.key === 'Escape') {
        closeSearchModal();
      } else if (!e.metaKey && !e.ctrlKey && !e.altKey && (e.key === '1' || e.key === '2' || e.key === '3' || e.key === '4')) {
        const mode = ['atlas', 'stratigraphy', 'ledger', 'coverage'][Number(e.key) - 1];
        if (mode) showAtlasMode(mode);
      }
    });

    window.selectHypothesis = selectHypothesis;
    window.flyToNode = flyToNode;

    initWebSocketSync();

    fetchAllData().then(() => {
      autoFitCanvas();
      renderAtlasViews();
    });

    // 30-second low-overhead passive version sync
    setInterval(() => syncDataIfChanged(false), 30000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
