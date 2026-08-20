/**
 * EPIRES HYPERGRAPH ENGINE // CLIENT CONTROLLER
 * Monotone Swiss Brutalist & Technical Cybernetic HUD Interface
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
    transform: { x: 50, y: 50, scale: 0.88 },
    isDragging: false,
    dragStart: { x: 0, y: 0 },
    pollingInterval: null
  };

  // Status Styling Colors (Monotone & Crisp Accents)
  const STATUS_CONFIG = {
    CONFIRMED: { color: '#34d399', label: 'CONFIRMED' },
    FALSIFIED: { color: '#f43f5e', label: 'FALSIFIED' },
    IN_PROGRESS: { color: '#f59e0b', label: 'IN_PROGRESS' },
    BLOCKED: { color: '#64748b', label: 'BLOCKED' },
    PROPOSED: { color: '#ecebe6', label: 'PROPOSED' }
  };

  // DOM Elements
  const dom = {
    svg: document.getElementById('dag-svg'),
    canvasContainer: document.getElementById('canvas-container'),
    kpiTotal: document.getElementById('kpi-total'),
    kpiConfirmed: document.getElementById('kpi-confirmed'),
    kpiInProgress: document.getElementById('kpi-in-progress'),
    kpiFalsified: document.getElementById('kpi-falsified'),
    kpiFalsificationRate: document.getElementById('kpi-falsification-rate'),
    vsaCapacityText: document.getElementById('vsa-capacity-text'),
    evidenceSpectrum: document.getElementById('evidence-spectrum'),
    btnRefresh: document.getElementById('btn-refresh'),
    btnZoomIn: document.getElementById('btn-zoom-in'),
    btnZoomOut: document.getElementById('btn-zoom-out'),
    btnZoomReset: document.getElementById('btn-zoom-reset'),
    tabButtons: document.querySelectorAll('.d-tab-btn'),
    tabContents: document.querySelectorAll('.dossier-body'),
    filterButtons: document.querySelectorAll('.filter-btn'),
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
  // Data Fetching & State Synchronization
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

      updateMastheadAndKPIs();
      renderDAG();
      renderTraces();
      renderGaps();

      if (state.selectedHypothesisId) {
        renderInspector(state.selectedHypothesisId);
      }
    } catch (err) {
      console.error('Data fetch error:', err);
    }
  }

  // --------------------------------------------------------------------------
  // KPI Metrics & Spectrum Bar
  // --------------------------------------------------------------------------
  function updateMastheadAndKPIs() {
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

    dom.vsaCapacityText.textContent = `C=${total} / 500 (SNR ~ 1.0 boundary)`;

    // Evidence Spectrum E0..E5
    const levels = { E0: 0, E1: 0, E2: 0, E3: 0, E4: 0, E5: 0 };
    state.hypotheses.forEach(h => {
      const lvl = h.current_evidence_level || 'E0';
      if (levels[lvl] !== undefined) levels[lvl]++;
    });

    dom.evidenceSpectrum.innerHTML = Object.keys(levels).map(lvl => {
      const count = levels[lvl];
      const cls = count > 0 ? 'spec-step active' : 'spec-step';
      return `<div class="${cls}"><span>${lvl}</span><br><b>${count}</b></div>`;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // Epistemic DAG Layout & Wireframe Rendering
  // --------------------------------------------------------------------------
  function computeDAGLayout(nodes) {
    const nodeMap = new Map();
    nodes.forEach(n => nodeMap.set(n.id, { ...n, layer: 0, x: 0, y: 0 }));

    // Layer assignment based on topological distance
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

    const NODE_WIDTH = 240;
    const NODE_HEIGHT = 84;
    const GAP_X = 64;
    const GAP_Y = 100;

    layers.forEach((layerNodes, layerIdx) => {
      const totalWidth = layerNodes.length * NODE_WIDTH + (layerNodes.length - 1) * GAP_X;
      const startX = Math.max(50, 620 - totalWidth / 2);

      layerNodes.forEach((node, nodeIdx) => {
        node.x = startX + nodeIdx * (NODE_WIDTH + GAP_X);
        node.y = 50 + layerIdx * (NODE_HEIGHT + GAP_Y);
        node.width = NODE_WIDTH;
        node.height = NODE_HEIGHT;
      });
    });

    return { nodeMap, NODE_WIDTH, NODE_HEIGHT };
  }

  function renderDAG() {
    const svg = dom.svg;
    svg.innerHTML = '';

    // Arrow markers
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 2 L 8 5 L 0 8 z" fill="rgba(255,255,255,0.3)" />
      </marker>
      <marker id="arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 2 L 8 5 L 0 8 z" fill="#ffffff" />
      </marker>
    `;
    svg.appendChild(defs);

    const filteredNodes = state.activeFilter === 'ALL'
      ? state.hypotheses
      : state.hypotheses.filter(h => h.status === state.activeFilter);

    if (filteredNodes.length === 0) return;

    const { nodeMap, NODE_WIDTH, NODE_HEIGHT } = computeDAGLayout(filteredNodes);

    const gViewport = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gViewport.setAttribute('id', 'dag-viewport');
    gViewport.setAttribute('transform', `translate(${state.transform.x}, ${state.transform.y}) scale(${state.transform.scale})`);

    // 1. Draw Connection Lines
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

        const isRelated = state.selectedHypothesisId && (state.selectedHypothesisId === node.id || state.selectedHypothesisId === parentId);

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        path.setAttribute('class', `edge-path ${isRelated ? 'highlighted' : ''}`);
        path.setAttribute('marker-end', isRelated ? 'url(#arrow-active)' : 'url(#arrow)');

        gViewport.appendChild(path);
      });
    });

    // 2. Draw Technical Specimen Node Badges
    filteredNodes.forEach(node => {
      const pos = nodeMap.get(node.id);
      if (!pos) return;

      const isSelected = state.selectedHypothesisId === node.id;
      const statusCfg = STATUS_CONFIG[node.status] || { color: '#ffffff', label: node.status };

      const gNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      gNode.setAttribute('class', `dag-node-group ${isSelected ? 'selected' : ''}`);
      gNode.setAttribute('transform', `translate(${pos.x}, ${pos.y})`);
      gNode.dataset.id = node.id;

      const truncatedTitle = node.title.length > 34 ? node.title.substring(0, 32) + '…' : node.title;

      gNode.innerHTML = `
        <!-- Main Card Plate -->
        <rect class="node-plate" width="${NODE_WIDTH}" height="${NODE_HEIGHT}" rx="2" ry="2" />

        <!-- Top Left Corner Cutout Accent -->
        <path d="M 0 0 L 8 0 L 0 8 Z" fill="${statusCfg.color}" />

        <!-- Header Row: ID + Level -->
        <text x="14" y="20" fill="#ffffff" font-family="IBM Plex Mono" font-weight="700" font-size="12" letter-spacing="0.04em">${node.id}</text>
        <text x="${NODE_WIDTH - 12}" y="20" fill="#9ea0a8" font-family="IBM Plex Mono" font-size="9" font-weight="600" text-anchor="end">${node.current_evidence_level || 'E0'}</text>

        <!-- Divider Line -->
        <line x1="12" y1="28" x2="${NODE_WIDTH - 12}" y2="28" stroke="rgba(255,255,255,0.08)" stroke-width="1" />

        <!-- Title -->
        <text x="12" y="46" fill="#ecebe6" font-family="Inter" font-size="11" font-weight="500">${truncatedTitle}</text>

        <!-- Status Tag & Mini Barcode -->
        <text x="12" y="70" fill="${statusCfg.color}" font-family="IBM Plex Mono" font-size="9.5" font-weight="700">[ ${statusCfg.label} ]</text>
        <text x="${NODE_WIDTH - 12}" y="70" fill="rgba(255,255,255,0.2)" font-family="IBM Plex Mono" font-size="8" text-anchor="end">|| | ||</text>
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
    dom.insStatus.className = `badge-status-pill ${node.status}`;
    dom.insLevel.textContent = `LEVEL ${node.current_evidence_level || 'E0'}`;
    dom.insTitle.textContent = node.title;
    dom.insMechanism.textContent = node.a_priori_mechanism || 'No mathematical mechanism provided.';
    dom.insFalsification.textContent = node.falsification_criteria || 'No Popperian boundary registered.';

    // Cybernetic Flow Plate Inference
    dom.insCause.textContent = node.entity_types && node.entity_types.length > 0 ? node.entity_types.join(', ') : 'VSA Superposition';
    dom.insCondition.textContent = node.falsification_criteria.length > 26 ? node.falsification_criteria.substring(0, 24) + '…' : 'Refutation Gate';
    dom.insResult.textContent = node.status === 'FALSIFIED' ? 'Refuted / Pruned' : 'Active Hypothesis';

    // Parent Connections
    if (node.parent_ids && node.parent_ids.length > 0) {
      dom.insParents.innerHTML = node.parent_ids.map(p =>
        `<span class="dep-stamp" onclick="window.selectHypothesis('${p}')">↑ ${p}</span>`
      ).join('');
    } else {
      dom.insParents.innerHTML = '<span class="type-muted">Root Hypothesis (No Antecedents)</span>';
    }

    // Load Empirical Evidence
    try {
      const res = await fetch(`/hypotheses/${id}`).then(r => r.json());
      const evidence = res.evidence || [];
      dom.insEvidenceCount.textContent = evidence.length;

      if (evidence.length === 0) {
        dom.insEvidenceList.innerHTML = '<div class="empty-entry">No empirical passes recorded. Level: E0 (A Priori).</div>';
      } else {
        dom.insEvidenceList.innerHTML = evidence.map(ev => `
          <div class="evidence-entry">
            <div class="entry-head">
              <span class="entry-tag">[${ev.evidence_level}, ${ev.source_confidence}] // ${ev.metric_name || 'EMPID'}</span>
              <span class="entry-status ${ev.falsification_triggered ? 'falsified' : ''}">
                ${ev.falsification_triggered ? 'REFUTATION TRIGGERED' : 'EMPIRICAL PASS'}
              </span>
            </div>
            <div class="entry-claim">${ev.claim}</div>
          </div>
        `).join('');
      }
    } catch (err) {
      dom.insEvidenceList.innerHTML = '<div class="empty-entry">Error loading evidence log.</div>';
    }
  }

  // --------------------------------------------------------------------------
  // Operational Log Rendering
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
      container.innerHTML = '<div class="empty-entry">No log entries matching filter.</div>';
      return;
    }

    container.innerHTML = filtered.map(t => {
      const timeStr = t.timestamp ? t.timestamp.split('T')[1]?.substring(0, 8) || t.timestamp : '';
      return `
        <div class="log-row">
          <div class="log-meta-row">
            <span class="log-action-tag">${t.action} // ${t.agent_role || 'Lead-PI'}</span>
            <span class="log-time">${timeStr}</span>
          </div>
          <div class="log-body">${t.summary}</div>
          ${t.h_tag ? `<div class="log-tag-badge">TARGET: ${t.h_tag}</div>` : ''}
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
        <div class="empty-entry">
          White spot scan clear: all active dimensions currently covered by baseline hypotheses.
        </div>
      `;
      return;
    }

    container.innerHTML = state.gaps.map(g => `
      <div class="gap-item">
        <div class="gap-spec">${JSON.stringify(g.combination || g)}</div>
        <span class="gap-status-stamp">0 EXPERIMENTS</span>
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
  // Viewport Pan & Zoom
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
      state.transform = { x: 50, y: 50, scale: 0.88 };
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
    setupPanZoom();

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
