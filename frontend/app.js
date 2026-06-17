/**
 * Cascading Waterfall Pipeline — Frontend Logic
 * Handles SSE consumption, tree building, node expansion, and validation display.
 */

// ── Stage metadata ──────────────────────────────────────────────
const STAGES = {
    atomics: { icon: '🔬', color: '#06d6a0' },
    br:      { icon: '💼', color: '#f59e0b' },
    hlfr:    { icon: '📋', color: '#3b82f6' },
    llfr:    { icon: '⚙️', color: '#8b5cf6' },
    tr:      { icon: '🧪', color: '#06d6a0' },
    tc:      { icon: '📄', color: '#ec4899' },
};

const STAGE_ORDER = ['atomics', 'br', 'hlfr', 'llfr', 'tr', 'tc'];

// ── Global State ────────────────────────────────────────────────
const state = {
    isRunning: false,
    treeNodes: {},     // id -> { el, data, stage, parentId }
    prunedNodes: {},   // id -> { parentData, stage }
    lastInput: '',     // original input text for resume
    lastRunId: null,   // run_id from last completed pipeline for JSON export
};

// ── DOM Elements ────────────────────────────────────────────────
const DOM = {
    healthStatus: document.getElementById('health-status'),
    runBtn: document.getElementById('run-btn'),
    exportBtn: document.getElementById('export-btn'),
    exportJsonBtn: document.getElementById('export-json-btn'),
    btnText: document.querySelector('.btn-text'),
    loader: document.querySelector('.loader'),
    prompt: document.getElementById('prompt-input'),
    fileInput: document.getElementById('file-upload'),
    fileName: document.getElementById('file-name'),
    progress: document.getElementById('pipeline-progress'),
    treeContainer: document.getElementById('tree-container'),
    treeRoot: document.getElementById('tree-root'),
    emptyState: document.getElementById('empty-state'),
    validationSummary: document.getElementById('validation-summary'),
    summaryDuration: document.getElementById('summary-duration'),
    summaryGateA: document.getElementById('summary-gate-a'),
    summaryGateB: document.getElementById('summary-gate-b'),
    summaryGates: document.getElementById('summary-gates'),
    continueBtn: document.getElementById('continue-btn'),
    historyBtn: document.getElementById('history-btn'),
    historySidebar: document.getElementById('history-sidebar'),
    historyCloseBtn: document.getElementById('history-close-btn'),
    historyList: document.getElementById('history-list'),
    historyOverlay: document.getElementById('history-overlay'),
};

// ── Initialization ──────────────────────────────────────────────
function init() {
    checkHealth();
    bindEvents();
    const saved = localStorage.getItem('waterfall_input');
    if (saved) DOM.prompt.value = saved;
}

function bindEvents() {
    DOM.fileInput.addEventListener('change', (e) => {
        DOM.fileName.textContent = e.target.files.length > 0 ? e.target.files[0].name : '';
    });
    DOM.prompt.addEventListener('input', (e) => {
        localStorage.setItem('waterfall_input', e.target.value);
    });
    DOM.runBtn.addEventListener('click', startPipeline);
    DOM.exportBtn.addEventListener('click', exportCleanPDF);
    if (DOM.exportJsonBtn) DOM.exportJsonBtn.addEventListener('click', exportJSON);
    if (DOM.continueBtn) DOM.continueBtn.addEventListener('click', continuePipeline);
    if (DOM.historyBtn) DOM.historyBtn.addEventListener('click', openHistory);
    if (DOM.historyCloseBtn) DOM.historyCloseBtn.addEventListener('click', closeHistory);
    if (DOM.historyOverlay) DOM.historyOverlay.addEventListener('click', closeHistory);
}

// ── Health Check ────────────────────────────────────────────────
async function checkHealth() {
    try {
        const resp = await fetch('/api/health');
        const data = await resp.json();
        if (data.gemini_connected || data.ollama_connected) {
            DOM.healthStatus.className = 'status-indicator success';
            DOM.healthStatus.textContent = `Gemini API Connected — ${data.available_models.join(', ')}`;
        } else {
            DOM.healthStatus.className = 'status-indicator error';
            DOM.healthStatus.textContent = 'Gemini API Disconnected';
        }
    } catch {
        DOM.healthStatus.className = 'status-indicator error';
        DOM.healthStatus.textContent = 'Backend Unreachable';
    }
}

// ── Pipeline Execution ──────────────────────────────────────────
async function startPipeline() {
    if (!DOM.prompt.value.trim() && DOM.fileInput.files.length === 0) {
        alert('Please provide input text or a file.');
        return;
    }

    // Reset UI
    state.isRunning = true;
    state.treeNodes = {};
    state.prunedNodes = {};
    DOM.runBtn.disabled = true;
    DOM.btnText.textContent = 'Running Pipeline...';
    DOM.loader.classList.remove('hidden');
    DOM.emptyState.classList.add('hidden');
    DOM.treeRoot.classList.remove('hidden');
    DOM.treeRoot.innerHTML = '';
    DOM.validationSummary.classList.add('hidden');
    DOM.exportBtn.classList.add('hidden');
    if (DOM.exportJsonBtn) DOM.exportJsonBtn.classList.add('hidden');
    if (DOM.continueBtn) DOM.continueBtn.classList.add('hidden');
    resetProgress();

    state.lastInput = DOM.prompt.value;

    const formData = new FormData();
    formData.append('input_text', DOM.prompt.value);
    if (DOM.fileInput.files.length > 0) {
        formData.append('file', DOM.fileInput.files[0]);
    }

    try {
        const response = await fetch('/api/run-with-file', {
            method: 'POST',
            body: formData,
        });
        await handleStream(response.body.getReader());
    } catch (err) {
        console.error('Pipeline error:', err);
        alert('Pipeline execution failed.');
    } finally {
        resetRunState();
    }
}

async function handleStream(reader) {
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        buffer = buffer.replace(/\r\n/g, '\n');

        const events = buffer.split('\n\n');
        buffer = events.pop();

        for (const chunk of events) {
            if (chunk.trim() === '') continue;

            const eventLine = chunk.split('\n').find(l => l.startsWith('event:'));
            const dataLine = chunk.split('\n').find(l => l.startsWith('data:'));

            if (eventLine && dataLine) {
                const event = eventLine.replace('event:', '').trim();
                const dataStr = dataLine.replace('data:', '').trim();
                try {
                    const data = JSON.parse(dataStr);
                    processEvent(event, data);
                } catch (err) {
                    console.warn('Parse error:', dataStr, err);
                }
            }
        }
    }
}

// ── Event Processing ────────────────────────────────────────────
function processEvent(event, data) {
    switch (event) {
        case 'stage_start':
            setProgressActive(data.stage);
            break;

        case 'stage_chunk':
            // Streaming text — could show on an active node indicator
            break;

        case 'stage_complete':
            setProgressDone(data.stage);
            if (data.stage === 'atomics' && data.requirements) {
                renderAtomics(data.requirements, data.gate_a);
            }
            break;

        case 'node_complete':
            addTreeNode(data);
            break;

        case 'node_pruned':
            addPrunedNode(data);
            break;

        case 'pipeline_complete':
            renderPipelineComplete(data);
            break;

        case 'pipeline_error':
            // DON'T reset the tree — keep what we have so user can see partial results
            resetRunState();
            if (DOM.continueBtn) DOM.continueBtn.classList.remove('hidden');
            alert('Pipeline paused due to rate limiting. Wait a moment and click "Continue Generating" to resume.');
            break;
    }
}

// ── Progress Bar ────────────────────────────────────────────────
function resetProgress() {
    document.querySelectorAll('.progress-stage').forEach(el => {
        el.classList.remove('active', 'done');
    });
}

function setProgressActive(stage) {
    const el = document.querySelector(`.progress-stage[data-stage="${stage}"]`);
    if (el) {
        el.classList.remove('done');
        el.classList.add('active');
    }
}

function setProgressDone(stage) {
    const el = document.querySelector(`.progress-stage[data-stage="${stage}"]`);
    if (el) {
        el.classList.remove('active');
        el.classList.add('done');
    }
}

// ── Atomics Display ─────────────────────────────────────────────
function renderAtomics(requirements, gateA) {
    const container = document.createElement('div');
    container.className = 'atomics-container';

    const header = document.createElement('div');
    header.style.cssText = 'display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;';
    header.innerHTML = `
        <span style="font-size:0.8rem; font-weight:600; color:var(--text-primary)">
            🔬 Atomic Requirements (${requirements.length})
        </span>
        ${gateA ? `<span class="tree-score-badge ${gateA >= 0.55 ? 'pass' : 'fail'}">🔗 ${gateA.toFixed(2)}</span>` : ''}
    `;
    container.appendChild(header);

    requirements.forEach((req, i) => {
        const chip = document.createElement('div');
        chip.className = 'atomic-chip';
        chip.innerHTML = `<strong>AR-${i + 1}:</strong> ${escapeHtml(req)}`;
        container.appendChild(chip);
    });

    DOM.treeRoot.appendChild(container);
}

// ── Tree Node Creation ──────────────────────────────────────────
function addTreeNode(data) {
    const { stage, id, parent_id, data: nodeData, gate_a, gate_b, passed, label } = data;
    
    // Deduplication: if node exists, remove it first (prevents duplicates on 'Continue')
    const existing = document.getElementById(`node-${id}`);
    if (existing) existing.remove();

    const meta = STAGES[stage] || { icon: '📦', color: '#999' };
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.id = `node-${id}`;
    node.dataset.stage = stage;
    node.dataset.id = id;

    // Gate B info
    const gbScore = gate_b && typeof gate_b === 'object' ? gate_b.score : (gate_b || 0);

    node.innerHTML = `
        <div class="tree-node-header" onclick="toggleNode('${id}')">
            <span class="tree-toggle">▶</span>
            <span class="tree-icon">${meta.icon}</span>
            <span class="tree-label" title="${escapeHtml(label || id)}">${escapeHtml(label || id)}</span>
            <span class="tree-badges">
                <span class="tree-score-badge ${gate_a >= 0.45 ? 'pass' : 'fail'}" title="Semantic Similarity">🔗 ${gate_a.toFixed(2)}</span>
                <span class="tree-score-badge ${gbScore >= 7 ? 'pass' : 'fail'}" title="LLM Critic Score">🧠 ${gbScore}/10</span>
            </span>
        </div>
        <div class="tree-node-content hidden" id="content-${id}">
            ${renderNodeDetail(nodeData, gate_b)}
        </div>
        <div class="tree-children" id="children-${id}"></div>
    `;

    const parentContainer = parent_id === 'root'
        ? DOM.treeRoot
        : document.getElementById(`children-${parent_id}`);

    if (parentContainer) {
        parentContainer.appendChild(node);
    } else {
        DOM.treeRoot.appendChild(node);
    }

    state.treeNodes[id] = { el: node, data: nodeData, stage, id, parent_id, parentId: parent_id };
}

function addPrunedNode(data) {
    const { stage, id, parent_id, label, parent_data } = data;

    // Deduplication
    const existing = document.getElementById(`node-${id}`);
    if (existing) existing.remove();

    const meta = STAGES[stage] || { icon: '📦', color: '#999' };
    const node = document.createElement('div');
    node.className = 'tree-node pruned';
    node.id = `node-${id}`;
    node.dataset.stage = stage;
    node.dataset.id = id;

    node.innerHTML = `
        <div class="tree-node-header">
            <span class="tree-toggle">⏭️</span>
            <span class="tree-icon">${meta.icon}</span>
            <span class="tree-label">${escapeHtml(label || id)}</span>
        </div>
        <button class="expand-on-demand-btn" onclick="expandPrunedNode('${id}', '${stage}')">
            ▶ Generate
        </button>
    `;

    const parentContainer = parent_id === 'root'
        ? DOM.treeRoot
        : document.getElementById(`children-${parent_id}`);

    if (parentContainer) {
        parentContainer.appendChild(node);
    } else {
        DOM.treeRoot.appendChild(node);
    }

    state.prunedNodes[id] = { parentData: parent_data, stage };
}

// ── Node Detail Rendering ───────────────────────────────────────
function renderNodeDetail(data, gateB) {
    if (!data || typeof data !== 'object') return `<pre>${escapeHtml(String(data))}</pre>`;

    let html = '<div class="detail-rows">';

    for (const [key, value] of Object.entries(data)) {
        if (key.endsWith('_id') || key.startsWith('parent_')) continue; // Skip IDs

        const label = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

        if (Array.isArray(value)) {
            html += `<div class="detail-row"><span class="detail-key">${label}:</span></div>`;
            html += `<ul class="detail-list">`;
            value.forEach(item => {
                html += `<li>${escapeHtml(String(item))}</li>`;
            });
            html += `</ul>`;
        } else if (typeof value === 'object' && value !== null) {
            html += `<div class="detail-row"><span class="detail-key">${label}:</span></div>`;
            html += `<pre style="margin-left:1rem; color:var(--text-primary)">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
        } else {
            html += `<div class="detail-row">
                <span class="detail-key">${label}:</span>
                <span class="detail-value">${escapeHtml(String(value))}</span>
            </div>`;
        }
    }

    // Critic feedback
    if (gateB && typeof gateB === 'object') {
        html += `<div class="critic-feedback">`;
        html += `<div class="critic-label">🧠 LLM Critic Feedback (${gateB.score || 0}/10 — ${gateB.verdict || 'unknown'})</div>`;
        if (gateB.issues && gateB.issues.length > 0) {
            gateB.issues.forEach(issue => {
                html += `<div class="critic-issue">⚠️ ${escapeHtml(issue)}</div>`;
            });
        }
        if (gateB.missing_elements && gateB.missing_elements.length > 0) {
            gateB.missing_elements.forEach(el => {
                html += `<div class="critic-issue">❌ Missing: ${escapeHtml(el)}</div>`;
            });
        }
        if ((!gateB.issues || gateB.issues.length === 0) && (!gateB.missing_elements || gateB.missing_elements.length === 0)) {
            html += `<div class="critic-issue" style="color:var(--success)">✅ No issues detected</div>`;
        }
        html += `</div>`;
    }

    html += '</div>';
    return html;
}

// ── Toggle Node Expand/Collapse ─────────────────────────────────
function toggleNode(id) {
    const node = document.getElementById(`node-${id}`);
    const content = document.getElementById(`content-${id}`);
    if (!node || !content) return;

    if (node.classList.contains('expanded')) {
        node.classList.remove('expanded');
        content.classList.add('hidden');
    } else {
        node.classList.add('expanded');
        content.classList.remove('hidden');
    }
}

// ── On-Demand Expansion ─────────────────────────────────────────
async function expandPrunedNode(nodeId, stage) {
    const prunedData = state.prunedNodes[nodeId];
    if (!prunedData) return;

    const nodeEle = document.getElementById(`node-${nodeId}`);
    const btn = nodeEle ? nodeEle.querySelector('.expand-on-demand-btn') : null;
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Generating...';
    }

    try {
        const response = await fetch('/api/expand', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                parent_data: prunedData.parentData,
                stage: prunedData.stage,
            }),
        });

        const node = document.getElementById(`node-${nodeId}`);
        if (node) {
            node.classList.remove('pruned');
            // Add a children container
            let childrenDiv = document.getElementById(`children-${nodeId}`);
            if (!childrenDiv) {
                childrenDiv = document.createElement('div');
                childrenDiv.className = 'tree-children';
                childrenDiv.id = `children-${nodeId}`;
                node.appendChild(childrenDiv);
            }
        }

        // Remove the expand button
        if (btn) btn.remove();

        // Handle the SSE stream
        const reader = response.body.getReader();
        await handleExpandStream(reader, nodeId);

    } catch (err) {
        console.error('Expand error:', err);
        if (btn) {
            btn.disabled = false;
            btn.textContent = '▶ Generate (retry)';
        }
    }
}

async function handleExpandStream(reader, parentNodeId) {
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        buffer = buffer.replace(/\r\n/g, '\n');

        const events = buffer.split('\n\n');
        buffer = events.pop();

        for (const chunk of events) {
            if (chunk.trim() === '') continue;

            const eventLine = chunk.split('\n').find(l => l.startsWith('event:'));
            const dataLine = chunk.split('\n').find(l => l.startsWith('data:'));

            if (eventLine && dataLine) {
                const event = eventLine.replace('event:', '').trim();
                const dataStr = dataLine.replace('data:', '').trim();
                try {
                    const data = JSON.parse(dataStr);
                    if (event === 'node_complete') {
                        // Override parent_id to attach to the expanded node
                        data.parent_id = parentNodeId;
                        addTreeNode(data);
                    }
                } catch (err) {
                    console.warn('Expand parse error:', err);
                }
            }
        }
    }
}

// ── Pipeline Complete ───────────────────────────────────────────
function renderPipelineComplete(data) {
    DOM.validationSummary.classList.remove('hidden');
    if(DOM.exportBtn) DOM.exportBtn.classList.remove('hidden');
    if(DOM.exportJsonBtn) DOM.exportJsonBtn.classList.remove('hidden');

    // Track run_id for JSON export
    if (data.run_id) state.lastRunId = data.run_id;

    DOM.summaryDuration.textContent = `${(data.duration_ms / 1000).toFixed(1)}s`;
    DOM.summaryGateA.textContent = data.avg_gate_a ? data.avg_gate_a.toFixed(3) : '—';
    DOM.summaryGateB.textContent = data.avg_gate_b ? `${data.avg_gate_b.toFixed(1)}/10` : '—';
    DOM.summaryGates.textContent = `${data.gates_passed}/${data.gates_total}`;

    if (data.stats) {
        const s = data.stats;
        const ids = ['stat-atomics', 'stat-brs', 'stat-hlfrs', 'stat-llfrs', 'stat-trs', 'stat-tcs'];
        const vals = [s.atomics, s.brs, s.hlfrs, s.llfrs, s.trs, s.tcs];
        ids.forEach((id, i) => {
            const el = document.getElementById(id);
            if (el) el.textContent = vals[i] || 0;
        });
    }
}

// ── Export JSON ─────────────────────────────────────────────────
function exportJSON() {
    if (!state.lastRunId) {
        // Fallback: fetch the most recent history run and download it
        fetch('/api/history')
            .then(r => r.json())
            .then(data => {
                const latest = data.runs && data.runs[0];
                if (!latest) { alert('No completed run found to export.'); return; }
                triggerJsonDownload(latest.id);
            })
            .catch(() => alert('Could not retrieve history for export.'));
        return;
    }
    triggerJsonDownload(state.lastRunId);
}

function triggerJsonDownload(runId) {
    const a = document.createElement('a');
    a.href = `/api/history/${runId}/export-json`;
    a.download = `pipeline_run_${runId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// ── Export Clean PDF ────────────────────────────────────────────
function exportCleanPDF() {
    const printContainer = document.getElementById('print-container');
    printContainer.innerHTML = '';

    const dateStr = new Date().toLocaleString();
    
    // 1. Cover Page
    const coverPage = document.createElement('div');
    coverPage.className = 'print-cover';
    coverPage.innerHTML = `
        <div class="print-cover-inner">
            <h1 class="print-title">System Requirements Specification</h1>
            <p class="print-subtitle">Automated Cascade Generation Report</p>
            <div class="print-meta">
                <p><strong>Generated On:</strong> ${dateStr}</p>
                <p><strong>Engine:</strong> Vertical Dual-Gate Model</p>
            </div>
            
            <div class="print-summary-box">
                <h2>Executive Summary</h2>
                <div class="print-stats-grid">
                    <div class="print-stat">
                        <span class="stat-lbl">Time</span>
                        <span class="stat-val">${DOM.summaryDuration.textContent || '—'}</span>
                    </div>
                    <div class="print-stat">
                        <span class="stat-lbl">Gates Passed</span>
                        <span class="stat-val">${DOM.summaryGates.textContent || '—'}</span>
                    </div>
                    <div class="print-stat">
                        <span class="stat-lbl">Avg Semantic</span>
                        <span class="stat-val">${DOM.summaryGateA.textContent || '—'}</span>
                    </div>
                    <div class="print-stat">
                        <span class="stat-lbl">Avg Critic</span>
                        <span class="stat-val">${DOM.summaryGateB.textContent || '—'}</span>
                    </div>
                </div>
                <h3>Original Input Source</h3>
                <div class="print-input-quote">${escapeHtml(state.lastInput || 'Uploaded Document / Text Input')}</div>
            </div>
        </div>
    `;
    printContainer.appendChild(coverPage);

    // 2. Atomic Requirements Section
    const atomicsChips = document.querySelectorAll('.atomic-chip');
    if (atomicsChips.length > 0) {
        const atomicsSection = document.createElement('div');
        atomicsSection.className = 'print-section';
        atomicsSection.innerHTML = `<h2>1. Atomic Requirements</h2>`;
        const atomicsList = document.createElement('ul');
        atomicsList.className = 'print-atomics-list';
        atomicsChips.forEach(chip => {
            const li = document.createElement('li');
            li.innerHTML = chip.innerHTML;
            atomicsList.appendChild(li);
        });
        atomicsSection.appendChild(atomicsList);
        printContainer.appendChild(atomicsSection);
    }

    // 3. Feature Specifications Section
    const sysHeader = document.createElement('div');
    sysHeader.className = 'print-section';
    sysHeader.innerHTML = `<h2>2. Feature Specifications</h2>`;
    printContainer.appendChild(sysHeader);

    // Helper: find children of a given parent by ID and stage
    function findChildren(parentId, stage) {
        return Object.entries(state.treeNodes)
            .filter(([_, n]) => (n.parent_id || n.parentId) === parentId && n.stage === stage)
            .map(([key, n]) => ({ ...n, _key: key, id: n.id || key }));
    }

    const brNodes = Object.entries(state.treeNodes)
        .filter(([_, n]) => n.stage === 'br')
        .map(([key, n]) => ({ ...n, _key: key, id: n.id || key }));
    
    brNodes.forEach((brNode) => {
        const brWrapper = document.createElement('div');
        brWrapper.className = 'print-stage-br print-card';
        
        brWrapper.innerHTML = `
            <div class="print-card-header br-bg">
                <span class="stage-badge">BR</span>
                <strong>${escapeHtml(brNode.data.business_objective || brNode.label || '')}</strong>
            </div>
            <div class="print-card-body">
                <p><strong>Stakeholder:</strong> ${escapeHtml(brNode.data.stakeholder || '')}</p>
                <p><strong>Rule:</strong> ${escapeHtml(brNode.data.business_rule || '')}</p>
                <p><strong>Priority:</strong> ${escapeHtml(brNode.data.priority || '')}</p>
                <p><strong>Acceptance:</strong> ${escapeHtml(brNode.data.acceptance_criteria || '')}</p>
            </div>
        `;

        const hlfrNodes = findChildren(brNode._key, 'hlfr');
        hlfrNodes.forEach(hlfrNode => {
            const hlfrWrapper = document.createElement('div');
            hlfrWrapper.className = 'print-stage-hlfr print-card';
            hlfrWrapper.innerHTML = `
                <div class="print-card-header hlfr-bg">
                    <span class="stage-badge">HLFR</span>
                    <strong>${escapeHtml(hlfrNode.data.function_name || hlfrNode.label || '')}</strong>
                </div>
                <div class="print-card-body">
                    <p>${escapeHtml(hlfrNode.data.description || '')}</p>
                    <p><strong>Trigger:</strong> ${escapeHtml(hlfrNode.data.trigger || '')}</p>
                    <p><strong>Expected:</strong> ${escapeHtml(hlfrNode.data.expected_behavior || '')}</p>
                </div>
            `;
            brWrapper.appendChild(hlfrWrapper);

            const llfrNodes = findChildren(hlfrNode._key, 'llfr');
            llfrNodes.forEach(llfrNode => {
                const llfrWrapper = document.createElement('div');
                llfrWrapper.className = 'print-stage-llfr print-card';
                llfrWrapper.innerHTML = `
                    <div class="print-card-header llfr-bg">
                        <span class="stage-badge">LLFR</span>
                        <strong>${escapeHtml(llfrNode.data.title || llfrNode.label || '')}</strong>
                    </div>
                `;
                
                const behaviors = Array.isArray(llfrNode.data.detailed_behavior) ? llfrNode.data.detailed_behavior : [llfrNode.data.detailed_behavior];
                if (behaviors.length > 0) {
                    const bList = document.createElement('ol');
                    behaviors.forEach(b => { if(b) bList.innerHTML += `<li>${escapeHtml(b)}</li>`; });
                    const body = document.createElement('div');
                    body.className = 'print-card-body';
                    body.appendChild(bList);
                    llfrWrapper.appendChild(body);
                }
                brWrapper.appendChild(llfrWrapper);

                const trNodes = findChildren(llfrNode._key, 'tr');
                trNodes.forEach(trNode => {
                    const trWrapper = document.createElement('div');
                    trWrapper.className = 'print-stage-tr print-card';
                    trWrapper.innerHTML = `
                        <div class="print-card-header tr-bg">
                            <span class="stage-badge">TR</span>
                            <strong>${escapeHtml(trNode.data.test_type || 'Test')}</strong>: ${escapeHtml(trNode.data.test_objective || trNode.label || '')}
                        </div>
                    `;
                    brWrapper.appendChild(trWrapper);

                    const tcNodes = findChildren(trNode._key, 'tc');
                    tcNodes.forEach(tcNode => {
                        const tcWrapper = document.createElement('div');
                        tcWrapper.className = 'print-stage-tc print-card';
                        tcWrapper.innerHTML = `
                            <div class="print-card-header tc-bg">
                                <span class="stage-badge">TC</span>
                                <strong>${escapeHtml(tcNode.data.title || tcNode.label || '')}</strong>
                            </div>
                        `;
                        
                        const tcBody = document.createElement('div');
                        tcBody.className = 'print-card-body';
                        
                        const steps = Array.isArray(tcNode.data.test_steps) ? tcNode.data.test_steps : [tcNode.data.test_steps];
                        if (steps.length > 0) {
                            tcBody.innerHTML += `<p><strong>Steps:</strong></p>`;
                            const stepList = document.createElement('ol');
                            steps.forEach(s => { if(s) stepList.innerHTML += `<li>${escapeHtml(s)}</li>`; });
                            tcBody.appendChild(stepList);
                        }
                        
                        const results = Array.isArray(tcNode.data.expected_result) ? tcNode.data.expected_result : [tcNode.data.expected_result];
                        if (results.length > 0) {
                            tcBody.innerHTML += `<p><strong>Expected:</strong></p>`;
                            const rList = document.createElement('ul');
                            results.forEach(r => { if(r) rList.innerHTML += `<li>${escapeHtml(r)}</li>`; });
                            tcBody.appendChild(rList);
                        }
                        
                        tcWrapper.appendChild(tcBody);
                        brWrapper.appendChild(tcWrapper);
                    });
                });
            });
        });
        printContainer.appendChild(brWrapper);
    });

    setTimeout(() => { window.print(); }, 100);
}

// ── Utilities ───────────────────────────────────────────────────
function resetRunState() {
    state.isRunning = false;
    DOM.runBtn.disabled = false;
    DOM.btnText.textContent = 'Run Pipeline';
    DOM.loader.classList.add('hidden');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Continue Generating ─────────────────────────────────────────
async function continuePipeline() {
    if (!state.lastInput) {
        alert('No previous input to continue from.');
        return;
    }

    state.isRunning = true;
    DOM.runBtn.disabled = true;
    DOM.btnText.textContent = 'Continuing...';
    DOM.loader.classList.remove('hidden');
    if (DOM.continueBtn) DOM.continueBtn.classList.add('hidden');

    const formData = new FormData();
    formData.append('input_text', state.lastInput);
    if (DOM.fileInput.files.length > 0) {
        formData.append('file', DOM.fileInput.files[0]);
    }

    try {
        const response = await fetch('/api/run-with-file', {
            method: 'POST',
            body: formData,
        });
        await handleStream(response.body.getReader());
    } catch (err) {
        console.error('Continue pipeline error:', err);
        if (DOM.continueBtn) DOM.continueBtn.classList.remove('hidden');
        alert('Resume failed. Try again in a moment.');
    } finally {
        resetRunState();
    }
}

// ── History Sidebar ─────────────────────────────────────────────
async function openHistory() {
    if (DOM.historySidebar) DOM.historySidebar.classList.remove('hidden');
    if (DOM.historyOverlay) DOM.historyOverlay.classList.remove('hidden');
    
    try {
        const resp = await fetch('/api/history');
        const data = await resp.json();
        renderHistoryList(data.runs || []);
    } catch (err) {
        console.error('Failed to load history:', err);
        DOM.historyList.innerHTML = '<p class="empty-sub">Failed to load history</p>';
    }
}

function closeHistory() {
    if (DOM.historySidebar) DOM.historySidebar.classList.add('hidden');
    if (DOM.historyOverlay) DOM.historyOverlay.classList.add('hidden');
}

function renderHistoryList(runs) {
    if (!runs.length) {
        DOM.historyList.innerHTML = '<p class="empty-sub">No past generations yet. Run the pipeline to create history.</p>';
        return;
    }

    DOM.historyList.innerHTML = '';
    runs.forEach(run => {
        const item = document.createElement('div');
        item.className = 'history-item';
        item.onclick = () => loadHistoryRun(run.id);

        const stats = run.stats || {};
        const statsText = `${stats.atomics || 0} AR → ${stats.brs || 0} BR → ${stats.hlfrs || 0} HLFR → ${stats.llfrs || 0} LLFR → ${stats.trs || 0} TR → ${stats.tcs || 0} TC`;

        item.innerHTML = `
            <div class="history-item-time">${run.timestamp}</div>
            <div class="history-item-preview">${escapeHtml(run.input_preview)}</div>
            <div class="history-item-stats">${statsText}</div>
        `;
        DOM.historyList.appendChild(item);
    });
}

async function loadHistoryRun(runId) {
    closeHistory();

    try {
        const resp = await fetch(`/api/history/${runId}`);
        const data = await resp.json();

        if (data.error) {
            alert('Failed to load run: ' + data.error);
            return;
        }

        // Reset the UI
        state.treeNodes = {};
        state.prunedNodes = {};
        DOM.treeRoot.innerHTML = '';
        DOM.treeRoot.classList.remove('hidden');
        DOM.emptyState.classList.add('hidden');
        DOM.validationSummary.classList.add('hidden');
        DOM.exportBtn.classList.add('hidden');
        if (DOM.continueBtn) DOM.continueBtn.classList.add('hidden');
        resetProgress();

        // Set the prompt text
        if (data.input_text) {
            DOM.prompt.value = data.input_text;
            state.lastInput = data.input_text;
        }

        // Replay all events
        for (const event of (data.events || [])) {
            processEvent(event.event, event.data);
        }

    } catch (err) {
        console.error('Failed to load history run:', err);
        alert('Failed to load history run.');
    }
}

// ── Start ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
