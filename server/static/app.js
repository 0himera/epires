/**
 * EPIRES HYPERGRAPH ENGINE // CLIENT CONTROLLER
 * Monotone Swiss Editorial Paper Theme with Interactive Vector Dragging & 3D Dither Sphere Radar
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
    transform: { x: 50, y: 50, scale: 0.88 },
    isDraggingCanvas: false,
    dragStart: { x: 0, y: 0 },
    nodePositions: new Map(), // Stores { id: { x, y, width, height } }
    draggingNode: null,
    dragNodeStart: { mouseX: 0, mouseY: 0, nodeX: 0, nodeY: 0 },
    hasMovedNode: false,
    pollingInterval: null,
    sphereAngle: { x: 0.4, y: 0.6 }
  };

  const NODE_WIDTH = 240;
  const NODE_HEIGHT = 84;
  const GAP_X = 60;
  const GAP_Y = 100;

  // DOM Elements
  const dom = {
    svg: document.getElementById('dag-svg'),
    canvasContainer: document.getElementById('canvas-container'),
    caliperCoords: document.getElementById('caliper-coords'),
    sphereCanvas: document.getElementById('dither-sphere-canvas'),
    projectName: document.getElementById('project-name'),
    projectMetric: document.getElementById('project-metric'),
    hdrProjectDomain: document.getElementById('hdr-project-domain'),
    hdrTaskDesc: document.getElementById('hdr-task-desc'),
    vsaCapacityText: document.getElementById('vsa-capacity-text'),
    btnThemeToggle: document.getElementById('btn-theme-toggle'),
    themeLabel: document.getElementById('theme-label'),
    kpiTotal: document.getElementById('kpi-total'),
    kpiConfirmed: document.getElementById('kpi-confirmed'),
    kpiInProgress: document.getElementById('kpi-in-progress'),
    kpiFalsified: document.getElementById('kpi-falsified'),
    kpiFalsificationRate: document.getElementById('kpi-falsification-rate'),
    evidenceSpectrum: document.getElementById('evidence-spectrum'),
    btnRefresh: document.getElementById('btn-refresh'),
    btnZoomIn: document.getElementById('btn-zoom-in'),
    btnZoomOut: document.getElementById('btn-zoom-out'),
    btnZoomReset: document.getElementById('btn-zoom-reset'),
    tabButtons: document.querySelectorAll('.m-tab'),
    tabContents: document.querySelectorAll('.tab-pane'),
    filterButtons: document.querySelectorAll('.f-btn'),
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
    insCause: document.getElementById('ins-cause'),
    insCondition: document.getElementById('ins-condition'),
    insResult: document.getElementById('ins-result'),
    tracesStreamContainer: document.getElementById('traces-stream-container'),
    tracesCountText: document.getElementById('traces-count-text'),
    tracesSearch: document.getElementById('traces-search'),
    gapsMatrixContainer: document.getElementById('gaps-matrix-container')
  };

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
  // 3D Dither Sphere Radar Renderer (Canvas)
  // --------------------------------------------------------------------------
  function initDitherSphere() {
    const canvas = dom.sphereCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const radius = 22;
    const cx = canvas.width / 2;
    const cy = canvas.height / 2;

    function renderSphere() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const isDark = document.documentElement.getAttribute('data-theme') === 'noir';
      ctx.fillStyle = isDark ? '#ecebe6' : '#111216';

      state.sphereAngle.x += 0.008;
      state.sphereAngle.y += 0.005;

      const numRings = 7;
      const pointsPerRing = 16;

      for (let i = 0; i < numRings; i++) {
        const phi = (Math.PI * (i + 1)) / (numRings + 1) - Math.PI / 2;
        const ringRadius = radius * Math.cos(phi);
        const y0 = radius * Math.sin(phi);

        for (let j = 0; j < pointsPerRing; j++) {
          const theta = (2 * Math.PI * j) / pointsPerRing;
          let x = ringRadius * Math.cos(theta);
          let y = y0;
          let z = ringRadius * Math.sin(theta);

          // Rotate Y
          const cosY = Math.cos(state.sphereAngle.x);
          const sinY = Math.sin(state.sphereAngle.x);
          const x1 = x * cosY - z * sinY;
          const z1 = x * sinY + z * cosY;

          // Rotate X
          const cosX = Math.cos(state.sphereAngle.y);
          const sinX = Math.sin(state.sphereAngle.y);
          const y2 = y * cosX - z1 * sinX;
          const z2 = y * sinX + z1 * cosX;

          // Orthographic projection + Dither dot size
          if (z2 > -5) {
            const screenX = cx + x1;
            const screenY = cy + y2;
            const size = z2 > 5 ? 1.4 : 0.8;
            ctx.fillRect(screenX, screenY, size, size);
          }
        }
      }

      requestAnimationFrame(renderSphere);
    }

    renderSphere();
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

      bindConfigToMasthead();
      updateProgramMetrics();
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

  function bindConfigToMasthead() {
    const conf = state.config;
    if (dom.projectName && conf.project_name) {
      dom.projectName.textContent = conf.project_name;
    }
    if (dom.hdrProjectDomain && conf.domain) {
      dom.hdrProjectDomain.textContent = conf.domain;
    }
    if (dom.hdrTaskDesc && conf.task_description) {
      dom.hdrTaskDesc.textContent = conf.task_description;
    }
    if (dom.projectMetric && conf.primary_metric) {
      const goalStr = conf.metric_goal ? ` (${conf.metric_goal})` : '';
      dom.projectMetric.textContent = `${conf.primary_metric}${goalStr}`;
    }
  }

  // --------------------------------------------------------------------------
  // Program Metric Ribbon Update
  // --------------------------------------------------------------------------
  function updateProgramMetrics() {
    const total = state.hypotheses.length;
    const confirmed = state.hypotheses.filter(h => h.status === 'CONFIRMED').length;
    const inProg = state.hypotheses.filter(h => h.status === 'IN_PROGRESS' || h.status === 'PROPOSED').length;
    const falsified = state.hypotheses.filter(h => h.status === 'FALSIFIED').length;

    dom.kpiTotal.textContent = String(total).padStart(2, '0');
    dom.kpiConfirmed.textContent = String(confirmed).padStart(2, '0');
    dom.kpiInProgress.textContent = String(inProg).padStart(2, '0');
    dom.kpiFalsified.textContent = String(falsified).padStart(2, '0');

    const falsRate = total > 0 ? ((falsified / total) * 100).toFixed(1) + '%' : '0.0%';
    dom.kpiFalsificationRate.textContent = `${falsRate} Refutation Rate`;

    dom.vsaCapacityText.textContent = `C=${total} / 500 (SNR boundary)`;

    // Evidence Maturity Ladder E0..E5
    const levels = { E0: 0, E1: 0, E2: 0, E3: 0, E4: 0, E5: 0 };
    state.hypotheses.forEach(h => {
      const lvl = h.current_evidence_level || 'E0';
      if (levels[lvl] !== undefined) levels[lvl]++;
    });

    dom.evidenceSpectrum.innerHTML = Object.keys(levels).map(lvl => {
      const count = levels[lvl];
      const cls = count > 0 ? 'spectrum-cell active' : 'spectrum-cell';
      return `<div class="${cls}"><span>${lvl}</span><br><b>${count}</b></div>`;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // Topological DAG Layout Algorithm
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
      const startX = Math.max(50, 600 - totalWidth / 2);

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
  // SVG Vector DAG Rendering with Interactive Drag Support
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

    // 1. Group for edges
    const gEdges = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gEdges.setAttribute('id', 'dag-edges-layer');
    gViewport.appendChild(gEdges);

    // 2. Draw Edges
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

    // 3. Draw Nodes (Draggable Groups)
    filteredNodes.forEach(node => {
      const pos = state.nodePositions.get(node.id);
      if (!pos) return;

      const isSelected = state.selectedHypothesisId === node.id;
      const gNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      gNode.setAttribute('class', `dag-node-group ${isSelected ? 'selected' : ''}`);
      gNode.setAttribute('id', `node-group-${node.id}`);
      gNode.setAttribute('transform', `translate(${pos.x}, ${pos.y})`);
      gNode.dataset.id = node.id;

      const truncatedTitle = node.title.length > 32 ? node.title.substring(0, 30) + '…' : node.title;

      gNode.innerHTML = `
        <!-- Main Card Plate with Edge Filter -->
        <rect class="node-plate" width="${NODE_WIDTH}" height="${NODE_HEIGHT}" rx="2" ry="2" />

        <!-- Corner Hatch Accent -->
        <polygon points="0,0 12,0 0,12" fill="var(--ink-primary)" opacity="0.8" />

        <!-- Header Row: ID + Level -->
        <text x="14" y="20" fill="var(--ink-primary)" font-family="IBM Plex Mono" font-weight="700" font-size="12" letter-spacing="0.04em">${node.id}</text>
        <text x="${NODE_WIDTH - 12}" y="20" fill="var(--ink-muted)" font-family="IBM Plex Mono" font-size="9" font-weight="600" text-anchor="end">${node.current_evidence_level || 'E0'}</text>

        <!-- Divider Line -->
        <line x1="12" y1="28" x2="${NODE_WIDTH - 12}" y2="28" stroke="var(--rule-crisp)" stroke-width="1" />

        <!-- Title -->
        <text x="12" y="46" fill="var(--ink-primary)" font-family="Inter" font-size="11" font-weight="500">${truncatedTitle}</text>

        <!-- Status Tag -->
        <text x="12" y="70" fill="var(--ink-secondary)" font-family="IBM Plex Mono" font-size="9" font-weight="700">[ ${node.status} ]</text>
        <text x="${NODE_WIDTH - 12}" y="70" fill="var(--ink-faint)" font-family="IBM Plex Mono" font-size="8" text-anchor="end">|| | ||</text>
      `;

      // Node Drag Listeners
      gNode.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        startDraggingNode(node.id, e);
      });

      gViewport.appendChild(gNode);
    });

    svg.appendChild(gViewport);
  }

  // --------------------------------------------------------------------------
  // Vector Node Dragging & Real-time Edge Updates
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

    // Update node translation
    const gNode = document.getElementById(`node-group-${state.draggingNode}`);
    if (gNode) {
      gNode.setAttribute('transform', `translate(${pos.x}, ${pos.y})`);
    }

    // Update all connected edges in real-time
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
      // 1. Edges where this node is the target (h is target, parents are source)
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

      // 2. Edges where this node is the parent (pId is this node, h is target)
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
    dom.insStatus.className = `spec-state ink-stamp ${node.status}`;
    dom.insLevel.textContent = `LEVEL ${node.current_evidence_level || 'E0'}`;
    dom.insTitle.textContent = node.title;
    dom.insMechanism.textContent = node.a_priori_mechanism || 'No mathematical mechanism registered.';
    dom.insFalsification.textContent = node.falsification_criteria || 'No Popperian boundary registered.';

    // Cybernetic Flow Step Extraction
    dom.insCause.textContent = node.entity_types && node.entity_types.length > 0 ? node.entity_types.join(', ') : 'VSA Superposition';
    dom.insCondition.textContent = node.falsification_criteria.length > 24 ? node.falsification_criteria.substring(0, 22) + '…' : 'Refutation Gate';
    dom.insResult.textContent = node.status === 'FALSIFIED' ? 'Refuted / Pruned' : 'Active State';

    // Antecedents
    if (node.parent_ids && node.parent_ids.length > 0) {
      dom.insParents.innerHTML = node.parent_ids.map(p =>
        `<span class="dep-card" onclick="window.selectHypothesis('${p}')">↑ ${p}</span>`
      ).join('');
    } else {
      dom.insParents.innerHTML = '<span class="ink-muted">Root Hypothesis (No Antecedents)</span>';
    }

    // Evidence Claims
    try {
      const res = await fetch(`/hypotheses/${id}`).then(r => r.json());
      const evidence = res.evidence || [];
      dom.insEvidenceCount.textContent = evidence.length;

      if (evidence.length === 0) {
        dom.insEvidenceList.innerHTML = '<div class="empty-entry">No empirical passes recorded. Level: E0 (A Priori).</div>';
      } else {
        dom.insEvidenceList.innerHTML = evidence.map(ev => `
          <div class="evidence-row">
            <div class="ev-top">
              <span class="ev-tag">[${ev.evidence_level}, ${ev.source_confidence}] // ${ev.metric_name || 'EMPID'}</span>
              <span class="ev-status ${ev.falsification_triggered ? 'refuted' : ''}">
                ${ev.falsification_triggered ? 'REFUTATION TRIGGERED' : 'EMPIRICAL PASS'}
              </span>
            </div>
            <div class="ev-claim-text">${ev.claim}</div>
          </div>
        `).join('');
      }
    } catch (err) {
      dom.insEvidenceList.innerHTML = '<div class="empty-entry">Error loading evidence ledger.</div>';
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

    dom.tracesCountText.textContent = `${state.traces.length} ENTRIES`;

    if (filtered.length === 0) {
      container.innerHTML = '<div class="empty-entry">No entries matching search query.</div>';
      return;
    }

    container.innerHTML = filtered.map(t => {
      const timeStr = t.timestamp ? t.timestamp.split('T')[1]?.substring(0, 8) || t.timestamp : '';
      return `
        <div class="trace-row-item">
          <div class="trace-row-meta">
            <span class="trace-row-action">${t.action} // ${t.agent_role || 'Lead-PI'}</span>
            <span class="trace-row-time">${timeStr}</span>
          </div>
          <div class="trace-row-summary">${t.summary}</div>
          ${t.h_tag ? `<div class="trace-row-htag">TARGET: ${t.h_tag}</div>` : ''}
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
        <div class="empty-entry">
          White spot scan clear: active dimensions covered by baseline hypotheses.
        </div>
      `;
      return;
    }

    container.innerHTML = state.gaps.map(g => `
      <div class="gap-specimen-card">
        <div class="gap-code">${JSON.stringify(g.combination || g)}</div>
        <span class="gap-status-pill">0 EXPERIMENTS</span>
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
  // Viewport Pan, Zoom & Caliper Coordinate Tracking
  // --------------------------------------------------------------------------
  function setupPanZoom() {
    const container = dom.canvasContainer;

    container.addEventListener('mousemove', (e) => {
      const rect = container.getBoundingClientRect();
      const rawX = (e.clientX - rect.left - state.transform.x) / state.transform.scale;
      const rawY = (e.clientY - rect.top - state.transform.y) / state.transform.scale;
      if (dom.caliperCoords) {
        dom.caliperCoords.textContent = `X: ${Math.round(rawX)} | Y: ${Math.round(rawY)}`;
      }
    });

    container.addEventListener('mousedown', (e) => {
      // Only pan canvas if clicked directly on background (not a node)
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
      state.nodePositions.clear(); // Recalculate clean topological layout
      state.transform = { x: 50, y: 50, scale: 0.88 };
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
    setupPanZoom();
    initDitherSphere();

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
