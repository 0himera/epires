/**
 * EPIRES RESEARCH DASHBOARD // CLIENT LOGIC
 * Zero-dependency, lightweight Swiss/Cybernetic HUD application
 */

(function () {
  'use strict';

  // Application State
  const state = {
    hypotheses: [],
    traces: [],
    gaps: [],
    selectedHypothesisId: null,
    activeFilter: 'ALL',
    activeTab: 'inspector',
    transform: { x: 40, y: 40, scale: 0.9 },
    isDragging: false,
    dragStart: { x: 0, y: 0 },
    pollingInterval: null
  };

  // Status Color Mapping
  const STATUS_COLORS = {
    CONFIRMED: '#10b981',
    FALSIFIED: '#f43f5e',
    IN_PROGRESS: '#f59e0b',
    BLOCKED: '#64748b',
    PROPOSED: '#38bdf8'
  };

  // DOM Elements
  const dom = {
    svg: document.getElementById('dag-svg'),
    canvasContainer: document.getElementById('canvas-container'),
    kpiTotal: document.getElementById('kpi-total'),
    kpiConfirmed: document.getElementById('kpi-confirmed'),
    kpiInProgress: document.getElementById('kpi-in-progress'),
    kpiFalsified: document.getElementById('kpi-falsified'),
    kpiBlocked: document.getElementById('kpi-blocked'),
    kpiFalsificationRate: document.getElementById('kpi-falsification-rate'),
    vsaCapacityText: document.getElementById('vsa-capacity-text'),
    vsaCapacityBar: document.getElementById('vsa-capacity-bar'),
    evidenceSpectrum: document.getElementById('evidence-spectrum'),
    btnRefresh: document.getElementById('btn-refresh'),
    btnZoomIn: document.getElementById('btn-zoom-in'),
    btnZoomOut: document.getElementById('btn-zoom-out'),
    btnZoomReset: document.getElementById('btn-zoom-reset'),
    tabButtons: document.querySelectorAll('.tab-btn'),
    tabContents: document.querySelectorAll('.tab-content'),
    filterPills: document.querySelectorAll('.filter-pill'),
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
  // Data Fetching & Sync
  // --------------------------------------------------------------------------
  async function fetchAllData() {
    try {
      const [hypoRes, tracesRes, gapsRes] = await Promise.all([
        fetch('/hypotheses').then(r => r.json()),
        fetch('/traces?limit=100').then(r => r.json()).catch(() => []),
        fetch('/gaps', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dimensions: ['Model', 'Feature', 'Regime'], min_tested: 1 })
        }).then(r => r.json()).catch(() => [])
      ]);

      state.hypotheses = hypoRes || [];
      state.traces = tracesRes || [];
      state.gaps = gapsRes || [];

      updateKPICards();
      renderDAG();
      renderTraces();
      renderGaps();

      if (state.selectedHypothesisId) {
        renderInspector(state.selectedHypothesisId);
      }
    } catch (err) {
      console.error('Error fetching research data:', err);
    }
  }

  // --------------------------------------------------------------------------
  // KPI Matrix Update
  // --------------------------------------------------------------------------
  function updateKPICards() {
    const total = state.hypotheses.length;
    const confirmed = state.hypotheses.filter(h => h.status === 'CONFIRMED').length;
    const inProg = state.hypotheses.filter(h => h.status === 'IN_PROGRESS' || h.status === 'PROPOSED').length;
    const falsified = state.hypotheses.filter(h => h.status === 'FALSIFIED').length;
    const blocked = state.hypotheses.filter(h => h.status === 'BLOCKED').length;

    dom.kpiTotal.textContent = total;
    dom.kpiConfirmed.textContent = confirmed;
    dom.kpiInProgress.textContent = inProg;
    dom.kpiFalsified.textContent = falsified;
    dom.kpiBlocked.textContent = blocked;

    const falsRate = total > 0 ? ((falsified / total) * 100).toFixed(1) + '%' : '0.0%';
    dom.kpiFalsificationRate.textContent = falsRate;

    // VSA Capacity (C vs C_max = 500)
    dom.vsaCapacityText.textContent = `C=${total} / 500`;
    const capPct = Math.min(100, Math.max(1, (total / 500) * 100));
    dom.vsaCapacityBar.style.width = capPct + '%';

    // Evidence Spectrum E0..E5
    const levels = { E0: 0, E1: 0, E2: 0, E3: 0, E4: 0, E5: 0 };
    state.hypotheses.forEach(h => {
      const lvl = h.current_evidence_level || 'E0';
      if (levels[lvl] !== undefined) levels[lvl]++;
    });

    dom.evidenceSpectrum.innerHTML = Object.keys(levels).map(lvl => {
      const count = levels[lvl];
      const cls = count > 0 ? 'level-pill active' : 'level-pill';
      return `<span class="${cls}" title="${lvl}">${lvl}: ${count}</span>`;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // Epistemic DAG Layout & SVG Rendering
  // --------------------------------------------------------------------------
  function computeDAGLayout(nodes) {
    // Topological layering
    const nodeMap = new Map();
    nodes.forEach(n => nodeMap.set(n.id, { ...n, layer: 0, x: 0, y: 0, inDeg: 0 }));

    // Assign layers based on longest path from roots
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

    // Group nodes by layer
    const layers = [];
    nodeMap.forEach(n => {
      while (layers.length <= n.layer) layers.push([]);
      layers[n.layer].push(n);
    });

    const NODE_WIDTH = 220;
    const NODE_HEIGHT = 80;
    const GAP_X = 70;
    const GAP_Y = 110;

    // Position coordinates
    layers.forEach((layerNodes, layerIdx) => {
      const totalWidth = layerNodes.length * NODE_WIDTH + (layerNodes.length - 1) * GAP_X;
      const startX = Math.max(60, 600 - totalWidth / 2);

      layerNodes.forEach((node, nodeIdx) => {
        node.x = startX + nodeIdx * (NODE_WIDTH + GAP_X);
        node.y = 50 + layerIdx * (NODE_HEIGHT + GAP_Y);
        node.width = NODE_WIDTH;
        node.height = NODE_HEIGHT;
      });
    });

    return { nodeMap, layers, NODE_WIDTH, NODE_HEIGHT };
  }

  function renderDAG() {
    const svg = dom.svg;
    svg.innerHTML = '';

    // Create defs for arrow markers
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="rgba(255,255,255,0.4)" />
      </marker>
      <marker id="arrow-selected" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#38bdf8" />
      </marker>
    `;
    svg.appendChild(defs);

    const filteredNodes = state.activeFilter === 'ALL'
      ? state.hypotheses
      : state.hypotheses.filter(h => h.status === state.activeFilter);

    if (filteredNodes.length === 0) return;

    const { nodeMap, NODE_WIDTH, NODE_HEIGHT } = computeDAGLayout(filteredNodes);

    // Root viewport group for Pan/Zoom
    const gViewport = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gViewport.setAttribute('id', 'dag-viewport');
    gViewport.setAttribute('transform', `translate(${state.transform.x}, ${state.transform.y}) scale(${state.transform.scale})`);

    // 1. Draw Edges
    filteredNodes.forEach(node => {
      const target = nodeMap.get(node.id);
      if (!target) return;

      (node.parent_ids || []).forEach(parentId => {
        const source = nodeMap.get(parentId);
        if (!source) return;

        const x1 = source.x + NODE_WIDTH / 2;
        const y1 = source.y + NODE_HEIGHT;
        const x2 = target.x + NODE_WIDTH / 2;
        const y2 = target.y;

        const midY = (y1 + y2) / 2;
        const pathData = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        path.setAttribute('class', 'edge-path');
        path.setAttribute('marker-end', 'url(#arrow)');
        path.dataset.source = source.id;
        path.dataset.target = target.id;

        gViewport.appendChild(path);
      });
    });

    // 2. Draw Nodes
    filteredNodes.forEach(node => {
      const pos = nodeMap.get(node.id);
      if (!pos) return;

      const gNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      gNode.setAttribute('class', `dag-node-group ${state.selectedHypothesisId === node.id ? 'selected' : ''}`);
      gNode.setAttribute('transform', `translate(${pos.x}, ${pos.y})`);
      gNode.dataset.id = node.id;

      const statusColor = STATUS_COLORS[node.status] || '#38bdf8';
      const truncatedTitle = node.title.length > 32 ? node.title.substring(0, 30) + '...' : node.title;

      gNode.innerHTML = `
        <!-- Main Card Container -->
        <rect class="node-box" width="${NODE_WIDTH}" height="${NODE_HEIGHT}" rx="3" ry="3"
              fill="#131620" stroke="rgba(255,255,255,0.12)" stroke-width="1" />
        
        <!-- Status Indicator Bar -->
        <rect x="0" y="0" width="4" height="${NODE_HEIGHT}" rx="2" ry="2" fill="${statusColor}" />

        <!-- Header Row: ID + Level Pill -->
        <text x="12" y="20" fill="#ffffff" font-family="IBM Plex Mono" font-weight="700" font-size="11" letter-spacing="0.05em">${node.id}</text>
        <rect x="${NODE_WIDTH - 42}" y="10" width="32" height="14" rx="2" fill="rgba(255,255,255,0.06)" />
        <text x="${NODE_WIDTH - 26}" y="20" fill="#9ca3af" font-family="IBM Plex Mono" font-size="8.5" text-anchor="middle">${node.current_evidence_level || 'E0'}</text>

        <!-- Node Title -->
        <text x="12" y="42" fill="#f4f4f6" font-family="Inter" font-size="11" font-weight="500">${truncatedTitle}</text>

        <!-- Status Tag Badge -->
        <text x="12" y="66" fill="${statusColor}" font-family="IBM Plex Mono" font-size="9" font-weight="600">[${node.status}]</text>
        
        <!-- Corner HUD Ticks -->
        <text x="${NODE_WIDTH - 12}" y="${NODE_HEIGHT - 6}" fill="rgba(255,255,255,0.2)" font-family="IBM Plex Mono" font-size="8">⌟</text>
      `;

      gNode.addEventListener('click', (e) => {
        e.stopPropagation();
        selectHypothesis(node.id);
      });

      gViewport.appendChild(gNode);
    });

    svg.appendChild(gViewport);
  }

  // --------------------------------------------------------------------------
  // Hypothesis Selection & Inspector Rendering
  // --------------------------------------------------------------------------
  async function selectHypothesis(id) {
    state.selectedHypothesisId = id;
    renderDAG(); // updates selection highlights

    // Switch to inspector tab if not active
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
    dom.insStatus.className = `status-badge ${node.status}`;
    dom.insLevel.textContent = `LEVEL ${node.current_evidence_level || 'E0'}`;
    dom.insTitle.textContent = node.title;
    dom.insMechanism.textContent = node.a_priori_mechanism || 'No a priori mechanism registered.';
    dom.insFalsification.textContent = node.falsification_criteria || 'No falsification criteria specified.';

    // Cybernetic Flow Steps inference
    dom.insCause.textContent = node.entity_types && node.entity_types.length > 0 ? node.entity_types.join(', ') : 'VSA Superposition';
    dom.insCondition.textContent = node.falsification_criteria.length > 24 ? node.falsification_criteria.substring(0, 24) + '...' : 'Threshold Bound';
    dom.insResult.textContent = node.status === 'FALSIFIED' ? 'Refuted (Pruned)' : 'Active Memory';

    // Parent Dependencies
    if (node.parent_ids && node.parent_ids.length > 0) {
      dom.insParents.innerHTML = node.parent_ids.map(p =>
        `<span class="dep-pill" onclick="window.selectHypothesis('${p}')">${p}</span>`
      ).join('');
    } else {
      dom.insParents.innerHTML = '<span class="text-muted">None (Root Hypothesis)</span>';
    }

    // Fetch Evidence History
    try {
      const res = await fetch(`/hypotheses/${id}`).then(r => r.json());
      const evidence = res.evidence || [];
      dom.insEvidenceCount.textContent = evidence.length;

      if (evidence.length === 0) {
        dom.insEvidenceList.innerHTML = '<div class="empty-evidence">No empirical evidence logged yet. Level: E0 (Theoretical).</div>';
      } else {
        dom.insEvidenceList.innerHTML = evidence.map(ev => `
          <div class="evidence-card">
            <div class="ev-header">
              <span class="mono-value">[${ev.evidence_level}, ${ev.source_confidence}]</span>
              <span class="${ev.falsification_triggered ? 'stat-falsified' : 'text-muted'}">
                ${ev.falsification_triggered ? 'FALSIFICATION TRIGGERED' : 'PASS'}
              </span>
            </div>
            <div class="ev-claim">${ev.claim}</div>
            <div class="ev-meta">
              ${ev.metric_name ? `<span>Metric: ${ev.metric_name}=${ev.metric_value}</span>` : ''}
              ${ev.citation_or_path ? `<span>Ref: ${ev.citation_or_path}</span>` : ''}
            </div>
          </div>
        `).join('');
      }
    } catch (err) {
      dom.insEvidenceList.innerHTML = '<div class="empty-evidence">Failed to load evidence records.</div>';
    }
  }

  // --------------------------------------------------------------------------
  // Agent Traces Rendering
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

    dom.tracesCountText.textContent = `${state.traces.length} entries recorded`;

    if (filtered.length === 0) {
      container.innerHTML = '<div class="empty-evidence">No traces matching query.</div>';
      return;
    }

    container.innerHTML = filtered.map(t => {
      const dateStr = t.timestamp ? t.timestamp.split('T')[1]?.substring(0, 8) || t.timestamp : '';
      return `
        <div class="trace-item">
          <div class="trace-top">
            <span class="trace-action">${t.action}</span>
            <span class="trace-role">${t.agent_role || 'Lead-PI'}</span>
            <span class="trace-time">${dateStr}</span>
          </div>
          <div class="trace-summary">${t.summary}</div>
          ${t.h_tag ? `<div class="trace-htag">H-TAG: ${t.h_tag}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // White Spot Gaps Rendering
  // --------------------------------------------------------------------------
  function renderGaps() {
    const container = dom.gapsMatrixContainer;
    if (state.gaps.length === 0) {
      container.innerHTML = `
        <div class="empty-evidence">
          No white spot gaps found with min_tested=1. All currently declared dimensions have coverage or evidence is in baseline stage.
        </div>
      `;
      return;
    }

    container.innerHTML = state.gaps.map(g => `
      <div class="gap-card">
        <div class="gap-dims">${JSON.stringify(g.combination || g)}</div>
        <span class="gap-badge">UNTESTED (0 runs)</span>
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
  // Pan & Zoom Controls
  // --------------------------------------------------------------------------
  function setupPanZoom() {
    const container = dom.canvasContainer;

    container.addEventListener('mousedown', (e) => {
      state.isDragging = true;
      state.dragStart = { x: e.clientX - state.transform.x, y: e.clientY - state.transform.y };
    });

    window.addEventListener('mousemove', (e) => {
      if (!state.isDragging) return;
      state.transform.x = e.clientX - state.dragStart.x;
      state.transform.y = e.clientY - state.dragStart.y;
      updateTransform();
    });

    window.addEventListener('mouseup', () => {
      state.isDragging = false;
    });

    container.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      state.transform.scale = Math.max(0.2, Math.min(3.0, state.transform.scale * zoomFactor));
      updateTransform();
    }, { passive: false });

    dom.btnZoomIn.addEventListener('click', () => {
      state.transform.scale = Math.min(3.0, state.transform.scale * 1.2);
      updateTransform();
    });

    dom.btnZoomOut.addEventListener('click', () => {
      state.transform.scale = Math.max(0.2, state.transform.scale * 0.8);
      updateTransform();
    });

    dom.btnZoomReset.addEventListener('click', () => {
      state.transform = { x: 40, y: 40, scale: 0.9 };
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
  // Event Listeners & Initialization
  // --------------------------------------------------------------------------
  function init() {
    setupPanZoom();

    // Tab buttons
    dom.tabButtons.forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Filter pills
    dom.filterPills.forEach(pill => {
      pill.addEventListener('click', () => {
        dom.filterPills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        state.activeFilter = pill.dataset.status;
        renderDAG();
      });
    });

    // Refresh button
    dom.btnRefresh.addEventListener('click', fetchAllData);

    // Search input
    dom.tracesSearch.addEventListener('input', renderTraces);

    // Expose selectHypothesis globally for inline clicks
    window.selectHypothesis = selectHypothesis;

    // Initial Fetch & Start Polling (every 2.5s)
    fetchAllData();
    state.pollingInterval = setInterval(fetchAllData, 2500);
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
