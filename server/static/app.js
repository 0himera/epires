/**
 * EPIRES HYPERGRAPH ENGINE // CLIENT CONTROLLER
 * Archival Paper Theme with Pretext Balanced Typography & Organic Voronoi Pebble Geometry
 */

(function () {
  'use strict';

  // Application State
  const state = {
    config: {},
    hypotheses: [],
    traces: [],
    gaps: [],
    selectedHypothesisId: null,
    activeFilter: 'ALL',
    activeTab: 'inspector',
    theme: localStorage.getItem('epires_theme') || 'paper',
    transform: { x: 60, y: 50, scale: 0.95 },
    isDraggingCanvas: false,
    dragStart: { x: 0, y: 0 },
    nodePositions: new Map(), // { id: { x, y, width, height } }
    draggingNode: null,
    dragNodeStart: { mouseX: 0, mouseY: 0, nodeX: 0, nodeY: 0 },
    hasMovedNode: false,
    pollingInterval: null
  };

  // Dimensions for Organic Voronoi Pebble Facets
  const NODE_WIDTH = 270;
  const NODE_HEIGHT = 100;
  const GAP_X = 54;
  const GAP_Y = 96;

  // DOM Elements
  const dom = {
    svg: document.getElementById('dag-svg'),
    canvasContainer: document.getElementById('canvas-container'),
    noiseCanvas: document.getElementById('noise-canvas'),
    projectName: document.getElementById('project-name'),
    projectMetric: document.getElementById('project-metric'),
    sepMetric: document.getElementById('sep-metric'),
    hdrTaskDesc: document.getElementById('hdr-task-desc'),
    sepTask: document.getElementById('sep-task'),
    hdrProjectDomain: document.getElementById('hdr-project-domain'),
    btnThemeToggle: document.getElementById('btn-theme-toggle'),
    themeLabel: document.getElementById('theme-label'),
    kpiTotal: document.getElementById('kpi-total'),
    kpiConfirmed: document.getElementById('kpi-confirmed'),
    kpiInProgress: document.getElementById('kpi-in-progress'),
    kpiFalsified: document.getElementById('kpi-falsified'),
    evidenceSpectrum: document.getElementById('evidence-spectrum'),
    btnRefresh: document.getElementById('btn-refresh'),
    btnZoomIn: document.getElementById('btn-zoom-in'),
    btnZoomOut: document.getElementById('btn-zoom-out'),
    btnZoomReset: document.getElementById('btn-zoom-reset'),
    tabButtons: document.querySelectorAll('.m-tab'),
    tabContents: document.querySelectorAll('.tab-pane'),
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
    insEvidenceCount: document.getElementById('ins-evidence-count'),
    insEvidenceList: document.getElementById('ins-evidence-list'),
    tracesStreamContainer: document.getElementById('traces-stream-container'),
    tracesCountText: document.getElementById('traces-count-text'),
    tracesSearch: document.getElementById('traces-search'),
    gapsMatrixContainer: document.getElementById('gaps-matrix-container')
  };

  // --------------------------------------------------------------------------
  // Pretext Measurement Canvas for Intelligent Balanced Multi-Line Layout
  // --------------------------------------------------------------------------
  const textMeasureCanvas = document.createElement('canvas');
  const textMeasureCtx = textMeasureCanvas.getContext('2d');
  textMeasureCtx.font = '500 12px Inter, -apple-system, sans-serif';

  function formatBalancedTitleSVG(text, maxWidth = 220, startX = 24, startY = 46, maxLines = 2) {
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
          // Add remainder
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
      const y = startY + idx * 16;
      return `<text x="${startX}" y="${y}" fill="var(--ink-primary)" font-family="Inter" font-size="12" font-weight="500">${l}</text>`;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // Mathematical Smooth Filleted Polygon Path Generator (Continuous Curvature)
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
  // Procedural Organic Voronoi Pebble Geometry (6 Clean Facet Profiles)
  // --------------------------------------------------------------------------
  function getVoronoiPebbleGeometry(id, w = 270, h = 100) {
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
    }
    const variant = hash % 6;

    let rawOuter;

    switch (variant) {
      case 0: // Smooth Pebble Hexagon
        rawOuter = [[28, 0], [w - 28, 0], [w, h * 0.48], [w - 24, h], [24, h], [0, h * 0.52]];
        break;
      case 1: // Organic Facet with Asymmetric Shoulder
        rawOuter = [[18, 0], [w - 36, 0], [w, h * 0.38], [w - 18, h], [32, h], [0, h * 0.65]];
        break;
      case 2: // Elongated Voronoi Capsule-Diamond
        rawOuter = [[34, 0], [w - 18, 0], [w, h * 0.6], [w - 32, h], [16, h], [0, h * 0.4]];
        break;
      case 3: // Slanted Crystallographic Pebble
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
  // Data Fetching & Dynamic Config Binding
  // --------------------------------------------------------------------------
  async function fetchAllData() {
    try {
      const [configRes, hypoRes, tracesRes, gapsRes] = await Promise.all([
        fetch('/config').then(r => r.json()).catch(() => ({})),
        fetch('/hypotheses').then(r => r.json()),
        fetch('/traces?limit=100').then(r => r.json()).catch(() => []),
        fetch('/gaps', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dimensions: ['Model', 'Feature', 'Regime'], min_tested: 1 })
        }).then(r => r.json()).catch(() => [])
      ]);

      state.config = configRes || {};
      state.hypotheses = hypoRes || [];
      state.traces = tracesRes || [];
      state.gaps = gapsRes || [];

      bindDynamicConfig();
      updateKPISummary();
      renderDAG();
      renderTraces();
      renderGaps();

      if (state.selectedHypothesisId) {
        renderInspector(state.selectedHypothesisId);
      }
    } catch (err) {
      console.error('Epires fetch error:', err);
    }
  }

  function bindDynamicConfig() {
    const conf = state.config;

    // 1. Domain Headline
    if (dom.hdrProjectDomain) {
      dom.hdrProjectDomain.textContent = conf.domain || 'Autonomous Research & Hypothesis Governance';
    }

    // 2. Project Name
    if (dom.projectName) {
      dom.projectName.textContent = conf.project_name || 'research_project';
    }

    // 3. Primary Metric & Goal
    if (dom.projectMetric) {
      if (conf.primary_metric) {
        const goal = conf.metric_goal ? ` (${conf.metric_goal})` : '';
        dom.projectMetric.textContent = `${conf.primary_metric}${goal}`;
        dom.projectMetric.style.display = 'inline';
        if (dom.sepMetric) dom.sepMetric.style.display = 'inline';
      } else {
        dom.projectMetric.style.display = 'none';
        if (dom.sepMetric) dom.sepMetric.style.display = 'none';
      }
    }

    // 4. Task Description
    if (dom.hdrTaskDesc) {
      if (conf.task_description) {
        dom.hdrTaskDesc.textContent = conf.task_description;
        dom.hdrTaskDesc.style.display = 'inline';
        if (dom.sepTask) dom.sepTask.style.display = 'inline';
      } else {
        dom.hdrTaskDesc.style.display = 'none';
        if (dom.sepTask) dom.sepTask.style.display = 'none';
      }
    }
  }

  // --------------------------------------------------------------------------
  // KPI Summary Strip
  // --------------------------------------------------------------------------
  function updateKPISummary() {
    const total = state.hypotheses.length;
    const confirmed = state.hypotheses.filter(h => h.status === 'CONFIRMED').length;
    const inProg = state.hypotheses.filter(h => h.status === 'IN_PROGRESS' || h.status === 'PROPOSED').length;
    const falsified = state.hypotheses.filter(h => h.status === 'FALSIFIED').length;

    dom.kpiTotal.textContent = String(total).padStart(2, '0');
    dom.kpiConfirmed.textContent = String(confirmed).padStart(2, '0');
    dom.kpiInProgress.textContent = String(inProg).padStart(2, '0');
    dom.kpiFalsified.textContent = String(falsified).padStart(2, '0');

    // Evidence Maturity Spectrum
    const levels = { E0: 0, E1: 0, E2: 0, E3: 0, E4: 0, E5: 0 };
    state.hypotheses.forEach(h => {
      const lvl = h.current_evidence_level || 'E0';
      if (levels[lvl] !== undefined) levels[lvl]++;
    });

    dom.evidenceSpectrum.innerHTML = Object.keys(levels).map(lvl => {
      const count = levels[lvl];
      const cls = count > 0 ? 's-pill active' : 's-pill';
      return `<span class="${cls}">${lvl} ${count}</span>`;
    }).join('');
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
      const startX = Math.max(40, 560 - totalWidth / 2) + staggerX;

      layerNodes.forEach((node, nodeIdx) => {
        if (!state.nodePositions.has(node.id)) {
          state.nodePositions.set(node.id, {
            x: startX + nodeIdx * (NODE_WIDTH + GAP_X),
            y: 40 + layerIdx * (NODE_HEIGHT + GAP_Y),
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
  function renderDAG() {
    const svg = dom.svg;
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

    const filteredNodes = state.activeFilter === 'ALL'
      ? state.hypotheses
      : state.hypotheses.filter(h => h.status === state.activeFilter);

    if (filteredNodes.length === 0) return;

    initializeLayoutIfEmpty(filteredNodes);

    const gViewport = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gViewport.setAttribute('id', 'dag-viewport');
    gViewport.setAttribute('transform', `translate(${state.transform.x}, ${state.transform.y}) scale(${state.transform.scale})`);

    // 1. Edges Layer (Rendered strictly UNDER nodes)
    const gEdges = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gEdges.setAttribute('id', 'dag-edges-layer');
    gViewport.appendChild(gEdges);

    filteredNodes.forEach(node => {
      const targetPos = state.nodePositions.get(node.id);
      if (!targetPos) return;

      (node.parent_ids || []).forEach(parentId => {
        const sourcePos = state.nodePositions.get(parentId);
        if (!sourcePos) return;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('id', `edge-${parentId}-${node.id}`);
        path.setAttribute('class', 'edge-path');

        const isRelated = state.selectedHypothesisId &&
          (state.selectedHypothesisId === node.id || state.selectedHypothesisId === parentId);

        if (isRelated) path.classList.add('highlighted');
        path.setAttribute('marker-end', isRelated ? 'url(#arrow-active)' : 'url(#arrow)');

        updateEdgePath(path, sourcePos, targetPos);
        gEdges.appendChild(path);
      });
    });

    // 2. Smooth Filleted Voronoi Pebble Nodes
    filteredNodes.forEach(node => {
      const pos = state.nodePositions.get(node.id);
      if (!pos) return;

      const isSelected = state.selectedHypothesisId === node.id;
      const isFalsified = node.status === 'FALSIFIED';
      const isConfirmed = node.status === 'CONFIRMED';

      const gNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      gNode.setAttribute('class', `dag-node-group ${isSelected ? 'selected' : ''} ${isFalsified ? 'falsified' : ''} ${isConfirmed ? 'confirmed' : ''}`);
      gNode.setAttribute('id', `node-group-${node.id}`);
      gNode.setAttribute('transform', `translate(${pos.x}, ${pos.y})`);
      gNode.dataset.id = node.id;

      let statusColor = 'var(--ink-secondary)';
      if (isFalsified) statusColor = 'var(--pastel-falsified-ink)';
      if (isConfirmed) statusColor = 'var(--pastel-confirmed-ink)';
      if (node.status === 'IN_PROGRESS') statusColor = 'var(--pastel-in-progress-ink)';

      // Generate clean filleted Voronoi pebble path
      const pebblePath = getVoronoiPebbleGeometry(node.id, NODE_WIDTH, NODE_HEIGHT);

      // Balanced Pretext-formatted multiline title
      const titleLinesSVG = formatBalancedTitleSVG(node.title, 220, 24, 48, 2);

      gNode.innerHTML = `
        <!-- Outer Filleted Voronoi Pebble Plate -->
        <path class="node-plate" d="${pebblePath}" />

        <!-- Header: ID + Level -->
        <text x="24" y="26" fill="var(--ink-primary)" font-family="IBM Plex Mono" font-weight="700" font-size="13">${node.id}</text>
        <text x="${NODE_WIDTH - 24}" y="26" fill="var(--ink-muted)" font-family="IBM Plex Mono" font-size="10" font-weight="600" text-anchor="end">${node.current_evidence_level || 'E0'}</text>

        <!-- Balanced Multiline Title -->
        ${titleLinesSVG}

        <!-- Status Tag -->
        <text x="24" y="84" fill="${statusColor}" font-family="IBM Plex Mono" font-size="9.5" font-weight="700">[ ${node.status} ]</text>
      `;

      // Drag listener
      gNode.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        startDraggingNode(node.id, e);
      });

      gViewport.appendChild(gNode);
    });

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

    const gNode = document.getElementById(`node-group-${state.draggingNode}`);
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
    state.hypotheses.forEach(h => {
      if (h.id === nodeId) {
        (h.parent_ids || []).forEach(pId => {
          const edge = document.getElementById(`edge-${pId}-${nodeId}`);
          const srcPos = state.nodePositions.get(pId);
          const tgtPos = state.nodePositions.get(nodeId);
          if (edge && srcPos && tgtPos) {
            updateEdgePath(edge, srcPos, tgtPos);
          }
        });
      }

      if ((h.parent_ids || []).includes(nodeId)) {
        const edge = document.getElementById(`edge-${nodeId}-${h.id}`);
        const srcPos = state.nodePositions.get(nodeId);
        const tgtPos = state.nodePositions.get(h.id);
        if (edge && srcPos && tgtPos) {
          updateEdgePath(edge, srcPos, tgtPos);
        }
      }
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
      dom.insParents.innerHTML = node.parent_ids.map(p =>
        `<span class="dep-node-pill" onclick="window.selectHypothesis('${p}')">↑ ${p}</span>`
      ).join('');
    } else {
      dom.insParents.innerHTML = '<span class="ink-muted">Root Hypothesis</span>';
    }

    // Evidence
    try {
      const res = await fetch(`/hypotheses/${id}`).then(r => r.json());
      const evidence = res.evidence || [];
      dom.insEvidenceCount.textContent = evidence.length;

      if (evidence.length === 0) {
        dom.insEvidenceList.innerHTML = '<div class="empty-evidence">No empirical tests registered yet. Level: E0 (A Priori).</div>';
      } else {
        dom.insEvidenceList.innerHTML = evidence.map(ev => `
          <div class="evidence-card">
            <div class="ev-header">
              <span class="ev-source">[${ev.evidence_level}] ${ev.metric_name || 'EMP'}</span>
              <span class="ev-status-text ${ev.falsification_triggered ? 'refuted' : ''}">
                ${ev.falsification_triggered ? 'REFUTED' : 'PASS'}
              </span>
            </div>
            <div class="ev-claim-body">${ev.claim}</div>
          </div>
        `).join('');
      }
    } catch (err) {
      dom.insEvidenceList.innerHTML = '<div class="empty-evidence">Error loading evidence.</div>';
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
      return (t.action && t.action.toLowerCase().includes(filter)) ||
             (t.summary && t.summary.toLowerCase().includes(filter)) ||
             (t.h_tag && t.h_tag.toLowerCase().includes(filter));
    });

    dom.tracesCountText.textContent = `${state.traces.length} entries`;

    if (filtered.length === 0) {
      container.innerHTML = '<div class="empty-evidence">No matching traces.</div>';
      return;
    }

    container.innerHTML = filtered.map(t => {
      const timeStr = t.timestamp ? t.timestamp.split('T')[1]?.substring(0, 8) || t.timestamp : '';
      return `
        <div class="trace-card">
          <div class="tr-head">
            <span class="tr-action">${t.action} // ${t.agent_role || 'Lead-PI'}</span>
            <span class="tr-time">${timeStr}</span>
          </div>
          <div class="tr-summary">${t.summary}</div>
        </div>
      `;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // White Spot Gaps
  // --------------------------------------------------------------------------
  function renderGaps() {
    const container = dom.gapsMatrixContainer;
    if (state.gaps.length === 0) {
      container.innerHTML = `
        <div class="empty-evidence">
          No white spot gaps detected. All primary dimensions covered.
        </div>
      `;
      return;
    }

    container.innerHTML = state.gaps.map(g => `
      <div class="gap-pill-item">
        <span class="gap-lbl-text">${JSON.stringify(g.combination || g)}</span>
        <span class="gap-tag">UNTESTED</span>
      </div>
    `).join('');
  }

  // --------------------------------------------------------------------------
  // Tab Switching
  // --------------------------------------------------------------------------
  function switchTab(tabName) {
    state.activeTab = tabName;
    dom.tabButtons.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    dom.tabContents.forEach(content => {
      content.classList.toggle('active', content.id === `tab-${tabName}`);
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

    dom.btnZoomReset.addEventListener('click', () => {
      state.nodePositions.clear();
      state.transform = { x: 60, y: 50, scale: 0.95 };
      renderDAG();
      updateTransform();
    });
  }

  function updateTransform() {
    const g = document.getElementById('dag-viewport');
    if (g) {
      g.setAttribute('transform', `translate(${state.transform.x}, ${state.transform.y}) scale(${state.transform.scale})`);
    }
  }

  // --------------------------------------------------------------------------
  // Initialization
  // --------------------------------------------------------------------------
  function init() {
    applyTheme(state.theme);
    initNoiseShader();
    setupPanZoom();

    dom.btnThemeToggle.addEventListener('click', toggleTheme);

    dom.tabButtons.forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    dom.filterButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        dom.filterButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.activeFilter = btn.dataset.status;
        renderDAG();
      });
    });

    dom.btnRefresh.addEventListener('click', fetchAllData);
    dom.tracesSearch.addEventListener('input', renderTraces);

    window.selectHypothesis = selectHypothesis;

    fetchAllData();
    state.pollingInterval = setInterval(fetchAllData, 2500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
