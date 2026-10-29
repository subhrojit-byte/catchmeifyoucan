const state = { companies: [], companyDirectoryStatuses: {}, transactions: [], scenarioTransactions: null, sharedCompanyIds: {}, scenario: null, scenarioRevision: 0, scenarioDisplayCleared: { summary: false, flow: false, network: false }, scenarioCreationPending: false, agentRunStarting: false, agentRunMode: null, sourceSelectionInvalid: false, sourceSelectionScenarioId: null, activities: [], chart: null, agentRun: null, agentSeenEvents: 0, agentPollTimer: null, agentAutoTimer: null, historicalEvaluation: null, risk: { loaded: false, loading: false, companies: [], transactions: [], relationships: [], failures: 0, selectedId: null, ranked: [] } };

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? 'N/A').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const companyName = (company) => company?.companyName || company?.name || 'Unknown company';
const money = (value) => value === null || value === undefined || value === '' ? 'N/A' : new Intl.NumberFormat('en-IN', { style:'currency', currency:'INR', maximumFractionDigits:2 }).format(Number(value));
const dateText = (value) => value ? new Date(value).toLocaleString([], { dateStyle:'medium', timeStyle:'short' }) : 'N/A';

function showAlert(message, type = 'danger') {
  $('alertArea').innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert"><i class="bi bi-${type === 'success' ? 'check-circle' : 'exclamation-triangle'} me-2"></i>${esc(message)}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
}
function logActivity(message) {
  state.activities.unshift({ time: new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' }), message });
  $('activityBody').innerHTML = state.activities.map((item) => `<div class="activity-item"><span class="activity-time">${esc(item.time)}</span><i class="bi bi-dot"></i><span>${esc(item.message)}</span></div>`).join('');
}
function updateTurnUI() {
  const scenario = state.scenario;
  const scenarioActive = scenario?.status === 'ACTIVE';
  const fraudsterTurn = scenarioActive && scenario?.turn === 'FRAUDSTER';
  const investigatorTurn = scenarioActive && scenario?.turn === 'INVESTIGATOR';
  const agentsDriving = state.agentRunStarting || ['RUNNING','PAUSED'].includes(state.agentRun?.status);
  const humanFraudsterTurn = state.agentRunMode === 'HUMAN_FRAUDSTER'
    && state.agentRun?.status === 'PAUSED' && fraudsterTurn;
  const controlsLocked = agentsDriving || state.scenarioCreationPending;
  const fraudsterControlsLocked = state.scenarioCreationPending || state.agentRunStarting || (agentsDriving && !humanFraudsterTurn);
  const investigatorRemaining = Number(scenario?.investigatorActionsRemaining ?? 0);
  document.querySelectorAll('.fraudster-control').forEach((control) => { control.disabled = fraudsterControlsLocked || !fraudsterTurn; control.classList.toggle('turn-disabled', fraudsterControlsLocked || !fraudsterTurn); });
  const selectedSourceId = String($('sourcePosition')?.value || '');
  const selectedSourceIsFunded = (scenario?.positions || []).some((position) =>
    String(position.id) === selectedSourceId && Number(position.amount) > 0);
  const fraudSubmit = $('fraudForm').querySelector('button[type="submit"]');
  if (fraudSubmit) fraudSubmit.disabled = fraudsterControlsLocked || !fraudsterTurn || !selectedSourceIsFunded;
  document.querySelectorAll('.investigator-control').forEach((control) => { control.disabled = controlsLocked || !(investigatorTurn && investigatorRemaining > 0); control.classList.toggle('turn-disabled', controlsLocked || !investigatorTurn || investigatorRemaining === 0); });
  $('scenarioForm').querySelectorAll('input,select,button').forEach((control) => { control.disabled = controlsLocked; });
  const fraudIndicator = $('fraudsterTurnIndicator'); const investigatorIndicator = $('investigatorTurnIndicator');
  fraudIndicator.classList.toggle('active', fraudsterTurn && !fraudsterControlsLocked); fraudIndicator.classList.toggle('inactive', !fraudsterTurn || fraudsterControlsLocked);
  investigatorIndicator.classList.toggle('active', investigatorTurn && investigatorRemaining > 0 && !controlsLocked); investigatorIndicator.classList.toggle('inactive', !investigatorTurn || investigatorRemaining === 0 || controlsLocked);
  fraudIndicator.querySelector('strong').textContent = `Current turn: ${scenario ? scenario.turn : 'None'}`;
  fraudIndicator.querySelector('small').textContent = fraudsterTurn ? (humanFraudsterTurn ? 'Your move — human controlled' : 'Make one move') : 'Wait for investigation';
  investigatorIndicator.querySelector('strong').textContent = `Actions remaining: ${investigatorRemaining}`;
  investigatorIndicator.querySelector('small').textContent = !scenario || fraudsterTurn ? 'Wait for a fraudster move' : investigatorRemaining ? 'Choose an investigation action' : 'Fraudster turn resumes';
  $('investigatorCount').textContent = investigatorRemaining;
  renderAgentRunPanel();
}
async function api(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type':'application/json', ...(options.headers || {}) }, ...options });
  const raw = await response.text(); let data = null;
  if (raw) { try { data = JSON.parse(raw); } catch { data = raw; } }
  if (!response.ok) throw new Error(data?.message || data?.error || `Request failed (${response.status})`);
  return data;
}
function publicCompany(company) {
  if (!company) return null;
  return { id: company.id, companyName: company.companyName, registrationNumber: company.registrationNumber, industry: company.industry, address: company.address, ageInYears: company.ageInYears, registrationDate: company.registrationDate, annualRevenue: company.annualRevenue, numberOfEmployees: company.numberOfEmployees };
}
function isScenarioSnapshot(scenario) {
  if (!scenario) return false;
  const idIsValid = (typeof scenario.id === 'number' && Number.isSafeInteger(scenario.id) && scenario.id > 0)
    || (typeof scenario.id === 'string' && /^[1-9]\d*$/.test(scenario.id)
      && Number.isSafeInteger(Number(scenario.id)));
  return idIsValid && typeof scenario.status === 'string' && Array.isArray(scenario.positions);
}
function canStartLearnedRun(scenario, run) {
  return isScenarioSnapshot(scenario) && scenario.status === 'ACTIVE'
    && !state.scenarioCreationPending && !state.agentRunStarting
    && !['RUNNING','PAUSED'].includes(run?.status);
}
function isHumanFraudsterTurn() {
  return state.agentRunMode === 'HUMAN_FRAUDSTER' && state.agentRun?.status === 'PAUSED'
    && state.scenario?.status === 'ACTIVE' && state.scenario?.turn === 'FRAUDSTER';
}
function synchronizeScenario(scenario) {
  const previousId = state.scenario?.id;
  const newScenario = String(previousId ?? '') !== String(scenario?.id ?? '');
  state.scenario = scenario;
  if (newScenario) {
    state.scenarioRevision += 1;
    state.scenarioTransactions = [];
    state.scenarioDisplayCleared = { summary: false, flow: false, network: false };
    if ($('gameTransactions')) $('gameTransactions').innerHTML = '<div class="game-empty">No scenario transfers have been recorded yet.</div>';
    if ($('gamePositions')) $('gamePositions').innerHTML = '<div class="game-empty">Position balances appear here.</div>';
  }
  if (isScenarioSnapshot(scenario)) {
    try { localStorage.setItem('catchme-scenario-id', String(scenario.id)); } catch (_) { /* Storage may be unavailable. */ }
  }
  updateSavedScenarioAction();
  renderScenario();
  updateTurnUI();
}
function clearScenarioSummary() {
  state.scenarioDisplayCleared.summary = true;
  renderScenario();
}
function clearScenarioFlow() {
  state.scenarioDisplayCleared.flow = true;
  renderFlow();
}
function clearScenarioNetwork() {
  state.scenarioDisplayCleared.network = true;
  $('gameTransactions').innerHTML = '<div class="game-empty">Displayed network data cleared. The scenario and its stored transactions are unchanged.</div>';
  $('gamePositions').innerHTML = '<div class="game-empty">Displayed balances cleared. The scenario state is unchanged.</div>';
}
function renderSourcePositions(scenario) {
  const selector = $('sourcePosition');
  const scenarioId = scenario?.id ?? null;
  const sameScenario = state.sourceSelectionScenarioId === scenarioId;
  const previousId = sameScenario ? String(selector.value || '') : '';
  if (!sameScenario) {
    state.sourceSelectionScenarioId = scenarioId;
    state.sourceSelectionInvalid = false;
  }
  const positions = (scenario?.positions || []).filter((position) =>
    Number.isSafeInteger(Number(position.id)) && Number(position.id) > 0
      && Number.isSafeInteger(Number(position.company?.id)) && Number(position.company.id) > 0
      && Number.isFinite(Number(position.amount)) && Number(position.amount) > 0);
  const retained = positions.some((position) => String(position.id) === previousId);
  if (retained) state.sourceSelectionInvalid = false;
  else if (previousId) state.sourceSelectionInvalid = true;
  const selectedId = retained ? previousId
    : (!previousId && !state.sourceSelectionInvalid ? String(positions[0]?.id || '') : '');
  selector.innerHTML = `<option value="">Choose a funded source company…</option>${positions.map((position) =>
    `<option value="${esc(position.id)}" data-company-id="${esc(position.company.id)}">${esc(companyName(position.company))} · ${esc(money(position.amount))}</option>`
  ).join('')}`;
  selector.value = selectedId;
  const hint = $('sourcePositionHint');
  if (state.sourceSelectionInvalid) {
    hint.textContent = 'The previously selected source no longer has funds. Choose another funded company to continue.';
  } else if (!positions.length) {
    hint.textContent = 'No companies currently have funds available for a transfer.';
  } else {
    hint.textContent = 'Choose a company with a positive current balance. Balances refresh from the scenario.';
  }
}
function revealAgentRunPanel() {
  const panel = $('agentRunPanel');
  const runButton = $('runLearnedAgents');
  if (!isScenarioSnapshot(state.scenario) || panel?.classList.contains('d-none') || !runButton) return;
  runButton.scrollIntoView({ behavior:'smooth', block:'center' });
}
function applyScenarioState(response) {
  if (!response) return;
  if (response.id && response.positions) {
    synchronizeScenario(response);
    return;
  }
  if (response.scenarioId && state.scenario?.id === response.scenarioId) {
    synchronizeScenario({ ...state.scenario,
      step: response.currentStep ?? state.scenario.step,
      turn: response.turn ?? state.scenario.turn,
      investigatorActionsRemaining: response.investigatorActionsRemaining ?? state.scenario.investigatorActionsRemaining,
      status: response.status ?? state.scenario.status,
      financialObjectiveAchieved: response.financialObjectiveAchieved ?? state.scenario.financialObjectiveAchieved
    });
  }
}
function companyOptions(selected = '') {
  const options = state.companies.map((company) => `<option value="${esc(company.id)}" ${String(company.id) === String(selected) ? 'selected' : ''}>${esc(companyName(company))} · #${esc(company.id)}</option>`).join('');
  ['scenarioSource','scenarioTarget','investigatorCompany'].forEach((id) => { if ($(id)) $(id).innerHTML = `<option value="">Select company…</option>${options}`; });
}
function availableTransactions() { return Array.isArray(state.scenarioTransactions) ? state.scenarioTransactions : state.transactions; }
function transactionOptions() { $('investigatorTransaction').innerHTML = `<option value="">Select transaction…</option>${availableTransactions().map((t) => `<option value="${esc(t.id)}">#${esc(t.id)} · ${esc(companyName(t.sourceCompany))} → ${esc(companyName(t.destinationCompany))} · ${esc(money(t.amount))}</option>`).join('')}`; }

document.getElementById('openShellRiskAnalyzer')?.addEventListener?.('click', () => loadRiskAnalyzer());
 $('openSavedScenario')?.addEventListener?.('click', () => restoreInitialScenario());
 $('clearScenarioData')?.addEventListener?.('click', clearScenarioSummary);
 $('clearFlowData')?.addEventListener?.('click', clearScenarioFlow);
 $('clearNetworkData')?.addEventListener?.('click', clearScenarioNetwork);
function renderRiskAnalyzer() {
  const risk = state.risk;
  if (!risk.loaded) return;
  risk.ranked = risk.analysis?.ranked || [];
  $('riskTable').innerHTML = risk.ranked.length ? risk.ranked.map((item) => `<tr class="risk-row ${String(item.company.id) === String(risk.selectedId) ? 'selected' : ''}"><td><button type="button" class="risk-select" data-risk-company="${esc(item.company.id)}">${esc(companyName(item.company))}</button><small>#${esc(item.company.id)}</small></td><td><strong>${item.riskScore}</strong>/100</td><td><span class="risk-category risk-${item.category.toLowerCase()}">${item.category}</span></td><td>${esc(item.signals.slice(0, 2).join(' · '))}</td></tr>`).join('') : '<tr><td colspan="4" class="empty-state">No companies are available to analyze.</td></tr>';
  document.querySelectorAll('[data-risk-company]').forEach((button) => button.addEventListener('click', () => { if (risk.animationTimer) clearTimeout(risk.animationTimer); risk.animationTimer = null; risk.selectedId = button.dataset.riskCompany; risk.animationDepth = 0; renderRiskAnalyzer(); }));
  if (risk.selectedId) renderRiskCompanyDetails(risk.selectedId);
}
function renderRiskCompanyDetails(companyId) {
  const risk = state.risk, company = risk.companies.find((item) => String(item.id) === String(companyId));
  if (!company) return;
  $('riskDetailTitle').textContent = companyName(company);
  const graph = risk.analysis.graph;
  const result = risk.analysis?.traversals?.[String(companyId)];
  const network = risk.analysis?.networkEvidence?.[String(companyId)] || { distinctNeighborCompanies: 0, sharedAddressCompanyIds: [], sharedDirectorIds: [], multiHopCompanyCount: 0 };
  const summary = risk.ranked.find((entry) => String(entry.company.id) === String(companyId));
  const networkPrefix = risk.relationshipFailures ? 'At least ' : '';
  const addressCountText = network.addressAvailable === false ? 'Unavailable' : network.sharedAddressCompanyIds.length;
  const directorCountText = network.directorsAvailable === false ? 'Unavailable' : network.sharedDirectorIds.length;
  $('riskDetailBody').classList.remove('empty-state');
  const age = summary.memberships.ageRisk === null ? 'Unavailable' : `${company.ageInYears} years · membership ${summary.memberships.ageRisk.toFixed(2)}`;
  const revenue = summary.memberships.revenueRisk === null ? 'Unavailable' : `${money(summary.memberships.revenuePerEmployee)} per employee · membership ${summary.memberships.revenueRisk.toFixed(2)}`;
  $('riskDetailBody').innerHTML = `<div class="risk-stages"><span>1 · BFS Network Traversal</span><span>2 · Network Evidence</span><span>3 · Fuzzy Logic Risk Scoring</span><span>4 · Ranked Results</span></div><section class="risk-stage-panel"><div class="risk-stage-heading"><h4>BFS Network Traversal</h4><span id="riskTraversalMeta"></span></div><div class="risk-traversal-controls"><button id="riskTraversalPlay" type="button" class="btn btn-sm btn-outline-primary">Play</button><button id="riskTraversalStep" type="button" class="btn btn-sm btn-outline-secondary">Step</button><span>Bounded to ${result?.maxDepth ?? 4} edges · transaction paths follow source → destination</span></div><div class="risk-graph-legend"><span class="company">Company</span><span class="director">Director</span><span class="transaction">Transaction</span></div><svg id="riskGraph" class="risk-graph" role="img" aria-label="Selected company's breadth-first network traversal"></svg></section><section class="risk-stage-panel"><h4>Network Evidence</h4><div class="risk-evidence-grid"><div><small>Distinct neighboring companies</small><strong>${networkPrefix}${network.distinctNeighborCompanies}</strong></div><div><small>Shared-address companies</small><strong>${addressCountText}</strong></div><div><small>Shared directors</small><strong>${directorCountText}</strong></div><div><small>Multi-hop companies</small><strong>${networkPrefix}${network.multiHopCompanyCount}</strong></div></div><p class="risk-method-note">Network size and multi-hop reach are context only. The grouped shared-resource membership is ${summary.ruleEvidence.sharedResourceStrength?.toFixed(2) ?? 'Unavailable'}; address and director evidence count as one family.</p></section><section class="risk-stage-panel"><h4>Fuzzy Logic Risk Scoring</h4><div class="risk-evidence-grid"><div><small>Company age evidence</small><strong>${esc(age)}</strong></div><div><small>Revenue per employee evidence</small><strong>${esc(revenue)}</strong></div><div><small>Network family strength</small><strong>${summary.ruleEvidence.sharedResourceStrength?.toFixed(2) ?? 'Unavailable'}</strong></div></div><div class="risk-score-summary"><strong>Shell-company risk estimate: ${summary.riskScore}/100 · ${summary.category}</strong><span>${summary.confidence.label} data completeness (${summary.confidence.completeness}%)</span></div><p class="small text-muted">${summary.signals.map(esc).join(' · ')}</p></section><p class="risk-method-note">Ranked Results appear in the table alongside this detail. Relationship reads unavailable: ${risk.relationshipFailures}.</p>`;
  $('riskTraversalPlay').addEventListener('click', () => toggleRiskTraversal(companyId));
  $('riskTraversalStep').addEventListener('click', () => stepRiskTraversal(companyId));
  renderRiskTraversal(companyId);
}
function renderRiskTraversal(companyId) {
  const risk = state.risk, traversal = risk.analysis?.traversals?.[String(companyId)];
  const layout = ShellRiskAnalyzer.layoutTraversal(traversal, companyId, risk.animationDepth ?? 0);
  const svg = $('riskGraph'), svgNs = 'http://www.w3.org/2000/svg';
  if (!svg) return;
  const addSvg = (parent, tag, attributes = {}, value = null) => {
    const element = document.createElementNS(svgNs, tag);
    Object.entries(attributes).forEach(([name, content]) => element.setAttribute(name, String(content)));
    if (value !== null) element.textContent = value;
    parent.appendChild(element);
    return element;
  };
  svg.setAttribute('viewBox', `0 0 ${layout.width} ${layout.height}`);
  svg.setAttribute('width', String(layout.width));
  svg.setAttribute('height', String(layout.height));
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.replaceChildren();
  if (layout.emptyMessage) {
    addSvg(svg, 'text', { x: layout.width / 2, y: layout.height / 2, 'text-anchor': 'middle', class: 'risk-graph-message' }, layout.emptyMessage);
  } else {
    const defs = addSvg(svg, 'defs');
    const marker = addSvg(defs, 'marker', { id: 'riskArrow', viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse' });
    addSvg(marker, 'path', { d: 'M 0 0 L 10 5 L 0 10 z' });
    layout.edges.forEach((edge) => {
      const from = layout.positions.get(edge.from), to = layout.positions.get(edge.to);
      const line = addSvg(svg, 'line', { class: `risk-edge ${edge.type.startsWith('transaction') ? 'transaction-edge' : ''} ${edge.depth === layout.depth && layout.depth > 0 ? 'active' : ''}`, x1: from.x, y1: from.y, x2: to.x, y2: to.y, ...(edge.directed ? { 'marker-end': 'url(#riskArrow)' } : {}) });
      addSvg(line, 'title', {}, `${edge.type} · depth ${edge.depth}`);
    });
    layout.nodes.forEach((node) => {
      const point = layout.positions.get(`${node.type}:${node.id}`), depth = layout.nodeDepth(node);
      const label = node.type === 'company' ? companyName(node.company) : node.type === 'director' ? (node.director?.name || `Director ${node.id}`) : `Transaction ${node.transaction?.id ?? node.id}`;
      const active = depth === layout.depth;
      const group = addSvg(svg, 'g', { class: `risk-node ${node.type} ${active ? 'active' : ''}` });
      if (node.type === 'company') addSvg(group, 'rect', { x: point.x - 52, y: point.y - 17, width: 104, height: 34, rx: 8 });
      else if (node.type === 'director') addSvg(group, 'circle', { cx: point.x, cy: point.y, r: 18 });
      else addSvg(group, 'polygon', { points: `${point.x},${point.y - 20} ${point.x + 22},${point.y} ${point.x},${point.y + 20} ${point.x - 22},${point.y}` });
      addSvg(group, 'text', { x: point.x, y: point.y + (node.type === 'director' ? 34 : 4), 'text-anchor': 'middle' }, label.slice(0, 24));
      addSvg(group, 'title', {}, `${node.type} ${node.id} · depth ${depth}`);
    });
    if (layout.statusMessage) addSvg(svg, 'text', { x: Math.max(165, layout.width / 2), y: layout.height - 16, 'text-anchor': 'middle', class: 'risk-graph-message' }, layout.statusMessage);
  }
  const selectedCompany = risk.companies.find((item) => String(item.id) === String(companyId));
  $('riskTraversalMeta').textContent = `Start: ${companyName(selectedCompany)} · depth ${layout.depth}/${traversal?.maxDepth ?? 0} · ${layout.nodes.length}/${traversal?.visitedNodes?.length ?? 0} nodes · ${layout.edges.length}/${traversal?.discoveredEdges?.length ?? 0} relationships`;
  $('riskTraversalPlay').textContent = risk.animationTimer ? 'Pause' : layout.depth >= (traversal?.maxDepth ?? 0) ? 'Replay' : 'Play';
}
function stepRiskTraversal(companyId) {
  const traversal = state.risk.analysis?.traversals?.[String(companyId)];
  if (!traversal) { renderRiskTraversal(companyId); return; }
  if (state.risk.animationTimer) { clearTimeout(state.risk.animationTimer); state.risk.animationTimer = null; }
  state.risk.animationDepth = (state.risk.animationDepth ?? 0) >= traversal.maxDepth ? 0 : (state.risk.animationDepth ?? 0) + 1;
  renderRiskTraversal(companyId);
}
function toggleRiskTraversal(companyId) {
  if (state.risk.animationTimer) { clearTimeout(state.risk.animationTimer); state.risk.animationTimer = null; renderRiskTraversal(companyId); return; }
  const traversal = state.risk.analysis?.traversals?.[String(companyId)];
  if (!traversal) { renderRiskTraversal(companyId); return; }
  if ((state.risk.animationDepth ?? 0) >= traversal.maxDepth) state.risk.animationDepth = 0;
  const advance = () => {
    if (state.risk.animationDepth >= traversal.maxDepth) { state.risk.animationTimer = null; renderRiskTraversal(companyId); return; }
    state.risk.animationDepth += 1;
    state.risk.animationTimer = setTimeout(advance, 650);
    renderRiskTraversal(companyId);
  };
  advance();
}
async function loadRiskAnalyzer(force = false) {
  const risk = state.risk;
  if (risk.loading || (risk.loaded && !force)) return;
  if (risk.animationTimer) clearTimeout(risk.animationTimer);
  risk.animationTimer = null;
  risk.loading = true;
  $('riskStatus').textContent = 'Loading public company and transaction observations…';
  $('riskTable').innerHTML = '<tr><td colspan="4" class="empty-state">Loading analyzer data…</td></tr>';
  try {
    const [companies, transactionResult] = await Promise.all([api('/api/companies'), api('/api/transactions').then((value) => ({ value, failed: false })).catch(() => ({ value: [], failed: true }))]);
    if (!Array.isArray(companies)) throw new Error('Company observations were unavailable.');
    const transactions = transactionResult.value;
    risk.companies = companies; risk.transactions = Array.isArray(transactions) ? transactions : [];
    const outcomes = await Promise.all(companies.map(async (company) => {
      try { const rows = await api(`/api/company-directors/company/${company.id}`); return { rows: Array.isArray(rows) ? rows : [], failed: false }; }
      catch (_) { return { rows: [], failed: true }; }
    }));
    risk.relationships = outcomes.flatMap((outcome) => outcome.rows);
    risk.transactionFailure = transactionResult.failed;
    risk.relationshipFailures = outcomes.filter((outcome) => outcome.failed).length + (transactionResult.failed ? 1 : 0);
    risk.analysis = ShellRiskAnalyzer.analyzeCompanies(risk.companies, risk.relationships, risk.transactions, {
      maxDepth: 4, addressAvailable: true,
      directorsAvailable: outcomes.every((outcome) => !outcome.failed),
      transactionsAvailable: !transactionResult.failed,
    });
    risk.loaded = true;
    if (!risk.selectedId && companies.length) risk.selectedId = String(companies[0].id);
    $('riskStatus').textContent = risk.relationshipFailures ? `Partial data: ${companies.length} companies, ${risk.transactions.length} transactions; ${risk.relationshipFailures} relationship or transaction reads unavailable. Scores show data completeness.` : `Analysis ready: ${companies.length} companies, ${risk.transactions.length} transactions. All scoring uses observable data.`;
    renderRiskAnalyzer();
  } catch (error) {
    $('riskStatus').textContent = `Unable to load analyzer data. ${error.message}`;
    $('riskTable').innerHTML = '<tr><td colspan="4" class="empty-state">Analyzer data unavailable. Use Refresh analysis to try again.</td></tr>';
  } finally { risk.loading = false; }
}

async function loadData() {
  try {
    const [companies, transactions] = await Promise.all([api('/api/companies'), api('/api/transactions')]);
    state.companies = Array.isArray(companies) ? companies : [];
    state.transactions = Array.isArray(transactions) ? transactions : [];
    await loadCompanyDirectoryStatuses();
    const shared = await Promise.all(state.companies.map(async (company) => [company.id,
      await api(`/api/company-directors/eligible/${company.id}`)]));
    state.sharedCompanyIds = Object.fromEntries(shared);
    $('companyCount').textContent = state.companies.length;
    $('transactionCount').textContent = state.transactions.length;
    companyOptions(); transactionOptions(); renderCompanies(); renderTransactions(); renderChart(); renderScenario(); targetsFor($('fraudType').value); updateTurnUI();
  } catch (error) {
    showAlert(`Unable to load environment data. ${error.message}`);
    $('companyTable').innerHTML = '<tr><td colspan="6" class="empty-state">Company data unavailable.</td></tr>';
    $('transactionTable').innerHTML = '<tr><td colspan="5" class="empty-state">Transaction data unavailable.</td></tr>';
    updateTurnUI();
  }
}
async function loadCompanyDirectoryStatuses() {
  try {
    const statuses = await api('/api/companies/directory');
    state.companyDirectoryStatuses = Object.fromEntries(
      (Array.isArray(statuses) ? statuses : [])
        .filter((item) => item && (typeof item.id === 'number' || typeof item.id === 'string'))
        .map((item) => [String(item.id), item.shellCompany]),
    );
  } catch (_) {
    state.companyDirectoryStatuses = {};
  }
}
function renderCompanies() {
  const query = ($('companySearch').value || '').toLowerCase();
  const visible = state.companies.filter((c) => {
    const matchesSearch = [companyName(c), c.industry, c.address, c.registrationNumber]
      .some((v) => String(v || '').toLowerCase().includes(query));
    return matchesSearch;
  });
  $('companyTable').innerHTML = visible.length ? visible.map((c) => {
    const status = state.companyDirectoryStatuses[String(c.id)];
    const label = status === true ? 'SHELL COMPANY' : status === false ? 'LEGITIMATE COMPANY' : 'STATUS UNAVAILABLE';
    const badgeClass = status === true ? 'text-bg-danger' : status === false ? 'text-bg-success' : 'text-bg-secondary';
    return `<tr><td><div class="company-name">${esc(companyName(c))}</div><div class="company-id">Registration ${esc(c.registrationNumber)}</div></td><td>${esc(c.industry)}</td><td>${esc(c.address)}</td><td>${esc(c.numberOfEmployees)}</td><td><span class="badge ${badgeClass}">${label}</span></td><td class="text-end"><button class="btn btn-sm btn-light view-company" data-id="${esc(c.id)}">View</button></td></tr>`;
  }).join('') : '<tr><td colspan="6" class="empty-state">No matching companies.</td></tr>';
  document.querySelectorAll('.view-company').forEach((button) => button.addEventListener('click', () => selectCompany(button.dataset.id)));
}
function selectCompany(id) {
  const company = state.companies.find((c) => String(c.id) === String(id)); if (!company) return;
  $('detailsTitle').textContent = companyName(company); $('detailsBody').classList.remove('empty-state');
  const details = [['Registration number', company.registrationNumber],['Industry', company.industry],['Address', company.address],['Age', company.ageInYears === null || company.ageInYears === undefined ? 'N/A' : `${company.ageInYears} years`],['Registration date', company.registrationDate],['Annual revenue', money(company.annualRevenue)],['Employees', company.numberOfEmployees]];
  $('detailsBody').innerHTML = `<div class="detail-grid">${details.map(([label,value]) => `<div><div class="detail-label">${esc(label)}</div><div class="detail-value">${esc(value)}</div></div>`).join('')}</div>`;
  $('investigatorCompany').value = String(id); $('scenarioSource').value = String(id); document.querySelector('#investigatorActions').scrollIntoView({ behavior:'smooth', block:'center' });
}
function renderTransactions() {
  const rows = availableTransactions().slice().sort((a,b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)).slice(0, 35);
  $('transactionTable').innerHTML = rows.length ? rows.map((t) => `<tr><td>#${esc(t.id)}</td><td class="route">${esc(companyName(t.sourceCompany))}<small>→ ${esc(companyName(t.destinationCompany))}</small></td><td>${esc(money(t.amount))}</td><td><span class="badge text-bg-light">${esc(t.channel)}</span></td><td>${esc(t.timestamp ? new Date(t.timestamp).toLocaleDateString() : 'N/A')}</td></tr>`).join('') : '<tr><td colspan="5" class="empty-state">No transactions available.</td></tr>';
  const channels = [...new Set(state.transactions.map((t) => t.channel).filter(Boolean))]; $('channelCount').textContent = `Channels ${channels.length}`;
}
function renderChart() {
  if (!window.Chart) return; const counts = {}; state.transactions.forEach((t) => { if (t.channel) counts[t.channel] = (counts[t.channel] || 0) + 1; });
  if (state.chart) state.chart.destroy(); state.chart = new Chart($('channelChart'), { type:'doughnut', data:{ labels:Object.keys(counts), datasets:[{ data:Object.values(counts), backgroundColor:['#3867d6','#7956d8','#18a877','#e4a52d','#e06a82'], borderWidth:0 }] }, options:{ responsive:true, maintainAspectRatio:false, plugins:{ legend:{ position:'bottom', labels:{ boxWidth:10, font:{ size:10 } } } } } });
}
function renderScenario() {
  const scenario = isScenarioSnapshot(state.scenario) ? state.scenario : null; const objective = scenario?.financialObjectiveAchieved === true;
  const summaryCleared = state.scenarioDisplayCleared.summary;
  $('scenarioStatus').textContent = scenario && !summaryCleared ? `${scenario.status || 'ACTIVE'} · Step ${scenario.step ?? 0}${objective ? ' · Transfer objective achieved' : ''}` : 'None'; $('fraudHint').textContent = scenario ? (objective ? 'Transfer objective achieved. Complete the final investigator turn.' : 'Select a source position and configure the next action.') : 'Create a scenario to enable fraudster actions.';
  if (summaryCleared) $('fraudHint').textContent = 'Scenario display cleared; the backend session is unchanged.';
  $('scenarioSummary').classList.toggle('d-none', !scenario || summaryCleared); $('agentRunPanel').classList.remove('d-none');
  if (!scenario || summaryCleared) { $('scenarioSummary').innerHTML = ''; renderSourcePositions(scenario); renderFlow(); if (!scenario) renderAgentRunPanel(); return; }
  const objectiveMessage = scenario.status === 'COMPLETED'
    ? '<br><span class="badge text-bg-success">Fraud detected · Investigation completed</span>'
    : objective ? '<br><span class="badge text-bg-warning">Transfer achieved · Investigation continues</span>' : '';
  $('scenarioSummary').innerHTML = `<div class="d-flex justify-content-between"><span><strong>Scenario #${esc(scenario.id)}</strong><br>${esc(companyName(scenario.sourceCompany))} → ${esc(companyName(scenario.targetCompany))}</span><span class="text-end"><strong>${esc(money(scenario.targetAmount))}</strong><br><span class="badge text-bg-success">${esc(scenario.status)}</span>${objectiveMessage}</span></div>`;
  renderSourcePositions(scenario); renderFlow();
}
function agentActionText(event) {
  const action = event?.action || {}; const details = [];
  if (action.company_id != null) details.push(`company #${action.company_id}`);
  if (action.transaction_id != null) details.push(`transaction #${action.transaction_id}`);
  if (action.source_position_id != null) details.push(`position #${action.source_position_id}`);
  return [String(action.action_type || 'Action').replaceAll('_',' '), ...details].join(' · ');
}
function displayMetric(value, percentage = false) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unavailable';
  return percentage ? `${(value * 100).toFixed(1)}%` : String(value);
}
function metricCards(metrics) {
  const fields = [['Precision','precision',true],['Recall','recall',true],['F1','f1',true],['TP','tp',false],['FP','fp',false],['TN','tn',false],['FN','fn',false]];
  return `<div class="analytics-metrics">${fields.map(([label,key,pct]) => `<div><span>${label}</span><strong>${esc(displayMetric(metrics?.[key], pct))}</strong></div>`).join('')}</div>`;
}
function renderEvaluationReport(report, file = {}) {
  const output = $('evaluationAnalytics');
  if (!report || typeof report !== 'object' || Array.isArray(report) || typeof report.policy_name !== 'string') {
    output.textContent = 'Report unavailable: the selected JSON is not a recognized evaluation report.';
    return;
  }
  const metrics = report.fraud_path_detection_metrics || report.discovered_candidate_metrics || report.detection_metrics;
  const provenance = report.checkpoint_provenance || {};
  const executionMode = provenance.execution_mode || 'not recorded';
  const managed = String(executionMode).toLowerCase().includes('managed');
  const checkpointInputs = provenance.checkpoint_compatibility_validation_inputs || {};
  const loadedRecords = Array.isArray(provenance.loaded_checkpoint_records) ? provenance.loaded_checkpoint_records : [];
  const checkpointText = managed
    ? 'Effective server checkpoints unavailable: managed API does not return loaded paths.'
    : loadedRecords.length
      ? loadedRecords.map((item) => `${item.role}: ${item.file_name || 'file unavailable'} · SHA-256 ${item.sha256 || 'unavailable'} · compatibility ${item.compatibility_status || 'unavailable'} · steps ${item.training_steps ?? 'unavailable'}`).join(' · ')
      : Object.entries(checkpointInputs).filter(([, value]) => typeof value === 'string' && value)
        .map(([role, value]) => `${role} validation input: ${String(value).split(/[\\/]/).pop()}`).join(' · ') || 'Checkpoint identity unavailable in report.';
  const scenarioIds = Array.isArray(report.scenario_ids) ? report.scenario_ids.filter((id) => Number.isSafeInteger(id) && id > 0) : [];
  const runIds = Array.isArray(report.episodes) ? [...new Set(report.episodes.map((episode) => episode?.managed_run_id).filter((id) => typeof id === 'string' && id))] : [];
  const financial = report.financial_simulation_outcome?.objective_achievement_rate ?? report.objective_success_rate;
  const actions = report.actions_attempted || {};
  output.innerHTML = `<div class="analytics-provenance"><strong>Historical report: ${esc(file.name || 'selected JSON')}</strong><span>Policy: ${esc(report.policy_name)}</span><span>File date: ${esc(file.lastModified ? new Date(file.lastModified).toLocaleString() : 'Unavailable')}</span><span>Execution: ${esc(executionMode)}</span><span>Scenario IDs: ${scenarioIds.length ? esc(scenarioIds.join(', ')) : 'Unavailable'}</span><span>Managed run IDs: ${runIds.length ? esc(runIds.join(', ')) : 'Unavailable'}</span><span>Recorded checkpoint input: ${esc(checkpointText)}</span><span>File SHA-256 / loaded metadata: unavailable unless recorded in this report.</span><span>This historical report is not linked to the current run.</span></div><h4>${esc(metrics?.metric_scope || 'Detection metrics')}</h4>${metrics ? metricCards(metrics) : '<p>Detection metrics unavailable.</p>'}<div class="analytics-metrics"><div><span>Financial objective rate</span><strong>${esc(displayMetric(financial, true))}</strong></div><div><span>Average episode length</span><strong>${esc(displayMetric(report.average_episode_length))}</strong></div><div><span>Median episode length</span><strong>${esc(displayMetric(report.median_episode_length ?? actions.median))}</strong></div><div><span>Episodes observed</span><strong>${esc(displayMetric(actions.observed_episode_count ?? report.executed_episode_count))}</strong></div></div>`;
}
function renderAgentAnalytics() {
  const live = $('liveAgentAnalytics');
  if (!live) return;
  const run = state.agentRun;
  if (!run) live.innerHTML = '<p>No managed run selected. Live run metrics are unavailable.</p>';
  else {
    const scenarioId = run.scenarioId ?? 'Unavailable';
    const finalStatus = run.finalState?.status;
    const outcome = finalStatus === 'COMPLETED' ? 'Investigator detected and correctly reported fraud'
      : finalStatus === 'MAX_TURNS_REACHED' ? 'No correct detection before the turn limit'
        : run.status === 'FAILED' ? `Run failed: ${run.message || 'reason unavailable'}` : 'Outcome unavailable until terminal state';
    const checkpointEvent = [...(run.events || [])].reverse().find((event) => event.event_type === 'checkpoint_provenance');
    const checkpoints = checkpointEvent?.checkpoints;
    const checkpointHtml = Array.isArray(checkpoints) && checkpoints.length
      ? checkpoints.map((item) => `<li>${esc(item.role)}: ${esc(item.file_name)} · SHA-256 ${esc(item.sha256 || 'unavailable')} · compatibility ${esc(item.compatibility_status || 'unavailable')} · training steps ${esc(displayMetric(item.training_steps))}${item.compatibility ? `<br><small>${esc(Object.entries(item.compatibility).map(([key,value]) => `${key}=${value}`).join(' · '))}</small>` : ''}${item.training_metadata && Object.keys(item.training_metadata).length ? `<br><small>Training metadata: ${esc(JSON.stringify(item.training_metadata))}</small>` : ''}</li>`).join('')
      : '<li>Loaded checkpoint provenance unavailable from this run.</li>';
    const financialOutcome = typeof run.finalState?.financialObjectiveAchieved === 'boolean'
      ? (run.finalState.financialObjectiveAchieved ? 'Achieved' : 'Not achieved') : 'Unavailable';
    live.innerHTML = `<div class="analytics-provenance"><span>Mode: ${esc(state.agentRunMode || 'Unavailable')}</span><span>Status: ${esc(run.status || 'Unavailable')}</span><span>Run ID: ${esc(run.runId || 'Unavailable')}</span><span>Scenario ID: ${esc(scenarioId)}</span><span>Actions taken: ${esc(displayMetric(run.actionsAttempted))}</span><span>Latest investigator outcome: ${esc(outcome)}</span><span>Financial objective: ${esc(financialOutcome)} (separate measure)</span></div><h4>Verified loaded checkpoint provenance</h4><ul>${checkpointHtml}</ul><p class="analytics-note">Live episode counts are not aggregate detection metrics. Precision, recall, F1, TP, FP, TN and FN are unavailable until an evaluation report is imported.</p>`;
  }
  const heuristicPolicies = (run?.events || []).find((event) => event.event_type === 'heuristic_policy_metadata')?.policies;
  const target = $('heuristicPolicyAnalytics');
  if (!target) return;
  if (!Array.isArray(heuristicPolicies) || !heuristicPolicies.length) {
    target.innerHTML = '<p>Heuristic parameter values unavailable until the current run supplies policy metadata.</p>';
    return;
  }
  target.innerHTML = `${heuristicPolicies.map(({ policy, configuration }) => `<article class="heuristic-policy"><h4>${esc(policy || 'Heuristic policy')}</h4><p>Source: ${esc(configuration?.source || 'Unavailable')}</p>${Array.isArray(configuration?.parameters) && configuration.parameters.length ? `<div class="table-responsive"><table class="table table-sm"><thead><tr><th>Parameter</th><th>Actual value</th><th>Meaning and decision effect</th></tr></thead><tbody>${configuration.parameters.map((item) => `<tr><td>${esc(item.name)}</td><td>${esc(item.value)}</td><td>${esc(item.meaning)} ${esc(item.effect)}</td></tr>`).join('')}</tbody></table></div>` : '<p>No numeric tunable parameters; policy is rule-based.</p>'}<h5>Selection rules</h5><ul>${(configuration?.selection_rules || []).map((rule) => `<li>${esc(rule)}</li>`).join('')}</ul></article>`).join('')}<p class="analytics-note">These are policy rules, not measured performance. One episode is not an aggregate benchmark.</p>`;
}
async function importEvaluationReport(event) {
  const file = event?.target?.files?.[0];
  if (!file) return;
  try {
    const report = JSON.parse(await file.text());
    state.historicalEvaluation = { report, name: file.name, lastModified: file.lastModified };
    renderEvaluationReport(report, state.historicalEvaluation);
  } catch (_) {
    $('evaluationAnalytics').textContent = 'Report unavailable: the selected file could not be parsed as evaluation JSON.';
  }
}
function renderAgentRunPanel() {
  if (!$('agentRunPanel')) return;
  const run = state.agentRun; const status = run?.status || 'READY'; const scenario = isScenarioSnapshot(state.scenario) ? state.scenario : null;
  const activeRun = ['RUNNING','PAUSED'].includes(status);
  $('runLearnedAgents').disabled = !canStartLearnedRun(scenario, run);
  $('runHeuristicSearch').disabled = !canStartLearnedRun(scenario, run);
  $('runHumanFraudster').disabled = !canStartLearnedRun(scenario, run);
  $('runLearnedAgents').textContent = state.agentRunStarting ? 'Starting Agents...' : status === 'RUNNING' ? 'Agents Running...' : 'Run Learned Agents';
  const humanMode = state.agentRunMode === 'HUMAN_FRAUDSTER';
  const heuristicMode = state.agentRunMode === 'HEURISTIC_SEARCH';
  $('runHeuristicSearch').textContent = state.agentRunStarting && heuristicMode
    ? 'Starting Heuristic Search...' : status === 'RUNNING' && heuristicMode ? 'Heuristic Search Running...' : 'Heuristic Search';
  $('gameMovesTitle').textContent = heuristicMode ? 'Heuristic Search · Action history'
    : humanMode ? 'Human Fraudster vs Bot · Action history' : 'Match moves';
  $('fraudsterRoleTitle').textContent = heuristicMode ? 'Heuristic Fraudster' : humanMode ? 'You · Human Fraudster' : 'Fraudster Agent';
  $('fraudsterRoleDescription').textContent = heuristicMode ? 'Existing heuristic policy uses legal backend actions.'
    : humanMode ? 'You choose each legal move; the backend executes it.' : 'Moves money through the scenario';
  $('investigatorAgentCard').querySelector('h3').textContent = heuristicMode ? 'Heuristic Investigator'
    : humanMode ? 'Learned Investigator Bot' : 'Investigator Agent';
  $('continueRound').classList.toggle('d-none', status !== 'PAUSED' || humanMode);
  $('autoContinue').disabled = humanMode;
  $('cancelAgentRun').classList.toggle('d-none', !activeRun);
  $('continueRound').disabled = status !== 'PAUSED'; $('cancelAgentRun').disabled = !activeRun;
  $('agentRunStatus').textContent = status === 'PAUSED' ? (humanMode ? 'YOUR TURN · Human Fraudster' : `PAUSED - Round ${run.pausedAfterRound ?? ''} complete`)
    : status === 'RUNNING' && run.currentAgent ? `RUNNING - ${heuristicMode ? 'Heuristic ' : ''}${run.currentAgent === 'FRAUDSTER' ? 'Fraudster acting' : 'Investigator acting'}` : status;
  $('agentRunStatus').className = `game-status-pill ${String(status).toLowerCase()}`;
  const step = Number(scenario?.step ?? 0);
  $('gameRound').textContent = status === 'PAUSED' && run.pausedAfterRound != null ? String(run.pausedAfterRound + 1) : String(Math.max(1, step + 1));
  $('gameActiveAgent').textContent = status === 'PAUSED' ? (humanMode ? 'You · Human Fraudster' : 'Paused before Fraudster')
    : status === 'RUNNING' && run.currentAgent ? `${heuristicMode ? 'Heuristic ' : ''}${run.currentAgent === 'FRAUDSTER' ? 'Fraudster' : 'Investigator'}`
      : scenario?.status === 'ACTIVE' ? (scenario.turn === 'FRAUDSTER' ? 'Fraudster' : 'Investigator') : 'None';
  $('gameScenarioStatus').textContent = scenario?.status || 'No scenario';
  const atRisk = (scenario?.positions || []).reduce((sum, position) => sum + Number(position.amount || 0), 0);
  $('gameMoneyAtRisk').textContent = scenario ? money(atRisk) : '-';
  $('fraudsterAgentCard').classList.toggle('active', status === 'RUNNING' && run.currentAgent === 'FRAUDSTER');
  $('investigatorAgentCard').classList.toggle('active', status === 'RUNNING' && run.currentAgent === 'INVESTIGATOR');
  const remaining = Number(scenario?.investigatorActionsRemaining ?? 3);
  const used = scenario?.turn === 'INVESTIGATOR' ? 3 - remaining : (step > 0 ? 3 : 0);
  const progress = $('roundProgress').querySelectorAll('.round-step');
  progress[0].classList.toggle('active', scenario?.turn === 'FRAUDSTER');
  [1,2,3].forEach((n, index) => progress[index + 1].classList.toggle('active', index < used));
  progress[4].classList.toggle('active', status === 'PAUSED');
  $('roundProgressText').textContent = status === 'PAUSED' ? (humanMode ? 'Your fraudster turn — choose a legal move below' : 'Investigator phase complete - waiting for Continue Round')
    : scenario?.turn === 'INVESTIGATOR' ? `${3 - remaining} of 3 investigator actions used`
      : scenario?.turn === 'FRAUDSTER' ? 'Fraudster turn' : 'Create a scenario to begin';
  const allEvents = run?.events || [];
  const selected = [...allEvents].reverse().find((event) => event.event_type === 'action_started'
    && !allEvents.some((completed) => completed.event_type === 'action' && completed.action_number === event.action_number));
  const latestMove = [...allEvents].reverse().find((event) => event.event_type === 'action');
  let details = status === 'RUNNING' && selected
    ? `Selected: ${heuristicMode ? 'Heuristic ' : ''}${selected.agent === 'FRAUDSTER' ? 'Fraudster' : 'Investigator'} - ${agentActionText(selected)}`
    : status === 'RUNNING' && latestMove ? `Last completed: ${heuristicMode ? 'Heuristic ' : ''}${latestMove.agent === 'FRAUDSTER' ? 'Fraudster' : 'Investigator'} - ${agentActionText(latestMove)}`
    : run?.actionsAttempted != null ? `${run.actionsAttempted} actions completed.` : 'Create a scenario, then choose a game mode.';
  if (run?.message) details = run.message;
  if (status === 'PAUSED' && humanMode) details = 'Your move: choose a legal fraudster action below. The learned investigator responds after it executes.';
  else if (status === 'PAUSED' && $('autoContinue').checked) details = `Auto-continue in ${Math.max(1, Number($('continueDelay').value) || 5)} seconds.`;
  $('agentRunDetails').textContent = details;
  const terminal = scenario?.status === 'COMPLETED' || scenario?.status === 'MAX_TURNS_REACHED';
  const final = $('gameFinalResult'); final.classList.toggle('d-none', !terminal && status !== 'FAILED');
  final.classList.toggle('failure', status === 'FAILED' || scenario?.status === 'MAX_TURNS_REACHED');
  final.textContent = status === 'FAILED' ? `${heuristicMode ? 'Heuristic Search' : 'Match'} failed: ${run?.message || 'Runner error.'}`
    : scenario?.status === 'COMPLETED' ? `${heuristicMode ? 'Heuristic Search: ' : ''}Investigator detected and correctly reported the fraud. Scenario complete.`
      : scenario?.status === 'MAX_TURNS_REACHED' ? `${heuristicMode ? 'Heuristic Search: ' : ''}Turn limit reached without correct detection. Scenario ended.` : '';
  const actions = (run?.events || []).filter((event) => event.event_type === 'action');
  $('agentRunEvents').innerHTML = actions.length ? actions.map((event, index) => {
    const result = event.state || {};
    const positions = (result.positions || []).map((position) => `${esc(companyName(position.company))}: ${esc(money(position.amount))}`).join(' | ');
    const actor = event.agent === 'FRAUDSTER'
      ? (heuristicMode ? 'Heuristic Fraudster' : humanMode ? 'You · Human Fraudster' : 'Fraudster Agent')
      : (heuristicMode ? 'Heuristic Investigator' : humanMode ? 'Learned Investigator Bot' : 'Investigator Agent');
    return `<article class="game-move"><div class="game-move-heading"><span>Move ${index + 1} - ${esc(actor)}</span><span>${esc(agentActionText(event))}</span></div><div class="game-move-outcome">${esc(result.status || 'State refreshed')}${positions ? ` | ${positions}` : ''}</div></article>`;
  }).join('') : '<div class="game-empty">The chronological action log appears here.</div>';
  const transactions = state.scenarioDisplayCleared.network ? [] : state.scenarioTransactions || [];
  const newestTransactions = transactions.slice().sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)).slice(0, 10);
  $('gameTransactions').innerHTML = newestTransactions.length ? newestTransactions.map((transaction) =>
    `<div class="game-transaction"><div><strong>${esc(companyName(transaction.sourceCompany))}</strong><small>${esc(money(transaction.amount))}</small></div><i class="bi bi-arrow-right"></i><div><strong>${esc(companyName(transaction.destinationCompany))}</strong><small>${esc(transaction.channel || 'Transfer')}</small></div></div>`
  ).join('') : state.scenarioDisplayCleared.network
    ? '<div class="game-empty">Displayed network data cleared. The scenario and its stored transactions are unchanged.</div>'
    : '<div class="game-empty">No scenario transfers have been recorded yet.</div>';
  $('gamePositions').innerHTML = state.scenarioDisplayCleared.network
    ? '<div class="game-empty">Displayed balances cleared. The scenario state is unchanged.</div>'
    : (scenario?.positions || []).length ? scenario.positions.map((position) =>
    `<div class="game-position"><span>${esc(companyName(position.company))}</span><strong>${esc(money(position.amount))}</strong></div>`
  ).join('') : '<div class="game-empty">No scenario positions are available.</div>';
  renderAgentAnalytics();
  renderCompanies();
}

async function refreshScenarioData() {
  if (!state.scenario?.id) return;
  const scenarioId = state.scenario.id;
  const revision = state.scenarioRevision;
  const scenario = await api(`/api/fraud/scenarios/${scenarioId}`);
  if (state.scenario?.id !== scenarioId || state.scenarioRevision !== revision) return;
  if (!isScenarioSnapshot(scenario) || Number(scenario.id) !== Number(scenarioId)) {
    throw new Error('Scenario refresh returned an invalid or mismatched scenario.');
  }
  synchronizeScenario(scenario);
  try {
    const transactions = await api(`/api/transactions/scenario/${scenarioId}`);
    if (state.scenario?.id !== scenarioId || state.scenarioRevision !== revision) return;
    state.scenarioTransactions = Array.isArray(transactions) ? transactions : [];
    transactionOptions(); renderTransactions(); renderAgentRunPanel();
  } catch (error) {
    // Scenario state is authoritative and already rendered; transaction history is auxiliary.
    console.warn(`Scenario ${scenarioId} transaction history refresh failed.`, error);
  }
}
function consumeAgentEvents(run) {
  const events = run?.events || [];
  for (const event of events.slice(state.agentSeenEvents)) {
    if (event.event_type !== 'action') continue;
    const actor = state.agentRunMode === 'HEURISTIC_SEARCH'
      ? (event.agent === 'FRAUDSTER' ? 'Heuristic fraudster' : 'Heuristic investigator')
      : (event.agent === 'FRAUDSTER' ? 'Learned fraudster' : 'Learned investigator');
    logActivity(`${actor}: ${agentActionText(event)}`);
    if (event.agent === 'INVESTIGATOR' && event.evidence) renderEvidence(event.evidence);
  }
  state.agentSeenEvents = events.length;
  transactionOptions(); renderTransactions();
}
function scheduleAutoContinue(runId) {
  if (state.agentRunMode === 'HUMAN_FRAUDSTER' || state.agentRun?.status !== 'PAUSED' || !$('autoContinue').checked) {
    if (state.agentAutoTimer) clearTimeout(state.agentAutoTimer);
    state.agentAutoTimer = null;
    return;
  }
  if (state.agentAutoTimer) return;
  const seconds = Math.min(60, Math.max(1, Number($('continueDelay').value) || 5));
  state.agentAutoTimer = setTimeout(() => continueLearnedRound(runId), seconds * 1000);
}
async function pollAgentRun(runId) {
  const revision = state.scenarioRevision;
  try {
    const run = await api(`/api/agent-runs/${encodeURIComponent(runId)}`);
    if (revision !== state.scenarioRevision || state.agentRun?.runId !== runId
      || String(state.scenario?.id) !== String(run?.scenarioId)) return;
    state.agentRun = run;
    consumeAgentEvents(state.agentRun);
    if (state.scenario?.id === state.agentRun.scenarioId) await refreshScenarioData();
    renderAgentRunPanel(); updateTurnUI();
    if (state.agentRun.status === 'RUNNING' || state.agentRun.status === 'PAUSED') {
      scheduleAutoContinue(runId);
      state.agentPollTimer = setTimeout(() => pollAgentRun(runId), 700);
    } else if (state.agentRun.status === 'FAILED') {
      if (state.agentAutoTimer) clearTimeout(state.agentAutoTimer);
      sessionStorage.removeItem('catchme-agent-run');
      showAlert(state.agentRun.message || 'Learned-agent run failed.');
    } else if (state.agentRun.status === 'COMPLETED') {
      if (state.agentAutoTimer) clearTimeout(state.agentAutoTimer);
    }
  } catch (error) {
    if (revision !== state.scenarioRevision || state.agentRun?.runId !== runId) return;
    $('agentRunDetails').textContent = `Unable to refresh learned-agent status. ${error.message}`;
    state.agentPollTimer = setTimeout(() => pollAgentRun(runId), 1500);
  }
}
async function startAgentRun(mode = 'INFERENCE') {
  if (!canStartLearnedRun(state.scenario, state.agentRun)) return;
  state.agentRunStarting = true;
  renderAgentRunPanel(); updateTurnUI();
  try {
    const run = await api('/api/agent-runs', {
      method:'POST', body:JSON.stringify({ scenarioId:state.scenario.id, mode }),
    });
    state.agentRun = run; state.agentSeenEvents = 0; state.agentRunMode = mode;
    sessionStorage.setItem('catchme-agent-run', JSON.stringify({ runId:run.runId, scenarioId:run.scenarioId, mode }));
    renderAgentRunPanel(); updateTurnUI();
    if (state.agentPollTimer) clearTimeout(state.agentPollTimer);
    pollAgentRun(run.runId);
  } catch (error) {
    showAlert(`Unable to start ${mode === 'HEURISTIC_SEARCH' ? 'Heuristic Search' : 'learned-agent run'}. ${error.message}`);
  } finally {
    state.agentRunStarting = false;
    renderAgentRunPanel(); updateTurnUI();
  }
}
async function startLearnedAgents() { return startAgentRun('INFERENCE'); }
async function startHeuristicSearch() { return startAgentRun('HEURISTIC_SEARCH'); }
async function startHumanFraudsterMatch() { return startAgentRun('HUMAN_FRAUDSTER'); }
async function continueLearnedRound(runId = state.agentRun?.runId) {
  if (!runId || state.agentRun?.status !== 'PAUSED') return;
  if (state.agentAutoTimer) clearTimeout(state.agentAutoTimer);
  state.agentAutoTimer = null;
  try {
    state.agentRun = await api(`/api/agent-runs/${encodeURIComponent(runId)}/continue`, { method:'POST' });
    renderAgentRunPanel(); updateTurnUI();
    pollAgentRun(runId);
  } catch (error) {
    showAlert(`Unable to continue learned-agent match. ${error.message}`);
  }
}
async function cancelLearnedRun() {
  const runId = state.agentRun?.runId;
  if (!runId || !['RUNNING','PAUSED'].includes(state.agentRun?.status)) return;
  if (state.agentAutoTimer) clearTimeout(state.agentAutoTimer);
  state.agentAutoTimer = null;
  try {
    state.agentRun = await api(`/api/agent-runs/${encodeURIComponent(runId)}/cancel`, { method:'POST' });
    sessionStorage.removeItem('catchme-agent-run');
    renderAgentRunPanel(); updateTurnUI();
  } catch (error) {
    showAlert(`Unable to cancel learned-agent match. ${error.message}`);
  }
}
async function restoreLearnedAgentRun() {
  if (state.scenarioCreationPending) return;
  const revision = state.scenarioRevision;
  try {
    const saved = JSON.parse(sessionStorage.getItem('catchme-agent-run') || 'null');
    if (!saved?.runId || !saved?.scenarioId) return;
    const [run, scenario] = await Promise.all([
      api(`/api/agent-runs/${encodeURIComponent(saved.runId)}`),
      api(`/api/fraud/scenarios/${saved.scenarioId}`),
    ]);
    if (state.scenarioCreationPending || revision !== state.scenarioRevision || state.scenario) return;
    if (!isScenarioSnapshot(scenario) || Number(scenario.id) !== Number(saved.scenarioId)
      || Number(run?.scenarioId) !== Number(saved.scenarioId)) {
      throw new Error('Stored learned-agent run did not match its scenario.');
    }
    state.agentRun = run; state.agentSeenEvents = 0; state.agentRunMode = saved.mode || 'INFERENCE';
    synchronizeScenario(scenario);
    if (run.status === 'RUNNING' || run.status === 'PAUSED') pollAgentRun(run.runId);
    else consumeAgentEvents(run);
  } catch (_) {
    if (!state.scenarioCreationPending && revision === state.scenarioRevision) {
      sessionStorage.removeItem('catchme-agent-run');
    }
  }
}
async function restoreSelectedScenario() {
  if (state.scenarioCreationPending || state.scenario) return;
  let savedId;
  try { savedId = localStorage.getItem('catchme-scenario-id'); } catch (_) { return; }
  if (!savedId || !/^[1-9]\d*$/.test(savedId) || !Number.isSafeInteger(Number(savedId))) return;

  const revision = state.scenarioRevision;
  try {
    const scenario = await api(`/api/fraud/scenarios/${encodeURIComponent(savedId)}`);
    if (state.scenarioCreationPending || revision !== state.scenarioRevision || state.scenario) return;
    if (!isScenarioSnapshot(scenario) || Number(scenario.id) !== Number(savedId)) {
      throw new Error('Saved scenario response was invalid or did not match its ID.');
    }
    synchronizeScenario(scenario);
    const restoredRevision = state.scenarioRevision;
    try {
      const transactions = await api(`/api/transactions/scenario/${encodeURIComponent(savedId)}`);
      if (state.scenario?.id !== scenario.id || state.scenarioRevision !== restoredRevision) return;
      state.scenarioTransactions = Array.isArray(transactions) ? transactions : [];
      transactionOptions(); renderTransactions(); renderAgentRunPanel();
    } catch (error) {
      console.warn(`Scenario ${savedId} transaction history refresh failed.`, error);
    }
  } catch (error) {
    if (!state.scenarioCreationPending && revision === state.scenarioRevision && !state.scenario) {
      showAlert(`Unable to restore saved scenario #${savedId}. ${error.message}`);
    }
  }
}
async function restoreInitialScenario() {
  await restoreLearnedAgentRun();
  if (!state.scenario) await restoreSelectedScenario();
  if (state.scenario) revealAgentRunPanel();
}
function updateSavedScenarioAction() {
  const button = $('openSavedScenario');
  if (!button) return;
  let available = false;
  try {
    const savedId = localStorage.getItem('catchme-scenario-id');
    const savedRun = JSON.parse(sessionStorage.getItem('catchme-agent-run') || 'null');
    available = Boolean((savedId && /^[1-9]\d*$/.test(savedId)) || (savedRun?.runId && savedRun?.scenarioId));
  } catch (_) { /* Storage may be unavailable. */ }
  button.classList.toggle('d-none', !available || Boolean(state.scenario));
}
function initializeDashboard() {
  updateSavedScenarioAction();
  return loadData();
}
function renderFlow() {
  if (state.scenarioDisplayCleared.flow) { $('flowMeta').textContent = 'No active scenario'; $('flowCanvas').innerHTML = 'Create a scenario to visualize movement.'; $('flowCanvas').classList.add('empty-state'); return; }
  const positions = state.scenario?.positions || []; $('flowMeta').textContent = state.scenario ? `Target ${money(state.scenario.targetAmount)} · ${state.scenario.status}` : 'No active scenario';
  if (!positions.length) { $('flowCanvas').innerHTML = 'Create a scenario to visualize movement.'; $('flowCanvas').classList.add('empty-state'); return; } $('flowCanvas').classList.remove('empty-state'); $('flowCanvas').innerHTML = `<div class="flow-grid">${positions.map((p,i) => `${i ? '<div class="flow-arrow"><i class="bi bi-arrow-right"></i></div>' : ''}<div class="flow-node"><div class="node-name">${esc(companyName(p.company))}</div><div class="node-amount">${esc(money(p.amount))}</div></div>`).join('')}</div><div class="form-hint mt-2"><i class="bi bi-info-circle me-1"></i>Positions reflect the latest response from the existing fraudster execution layer.</div>`;
}
function targetsFor(type) { const count = type === 'SPLIT_TRANSFER' ? 2 : type === 'ROUTE_TRANSFER' ? 1 : 0; const sourceId = Number($('sourcePosition')?.selectedOptions[0]?.dataset.companyId || $('sourcePosition')?.value); const targetId = Number(state.scenario?.targetCompany?.id); const eligibleIds = new Set((state.sharedCompanyIds[sourceId] || []).filter((id) => Number(id) !== targetId)); const html = `<div class="d-flex justify-content-between align-items-center"><div class="field-label mb-0">Destination target${count > 1 ? 's' : ''}</div>${type === 'SPLIT_TRANSFER' ? '<button type="button" id="addTarget" class="btn btn-sm btn-link p-0 fraudster-control">+ Add target</button>' : ''}</div><div id="targetList"></div>`; if (count && !eligibleIds.size) { $('targetRows').innerHTML = '<div class="form-hint">No eligible intermediate companies share a director with this source.</div>'; updateTurnUI(); return; } $('targetRows').innerHTML = count ? html : `<div class="form-hint">${type === 'DIRECT_TRANSFER' ? 'DIRECT_TRANSFER sends the full available balance to the scenario target company.' : 'WAIT advances the scenario step without destinations.'}</div>`; if (count) { for (let i=0;i<count;i++) addTargetRow(type === 'SPLIT_TRANSFER', eligibleIds); $('addTarget')?.addEventListener('click', () => addTargetRow(true, eligibleIds)); } }
function addTargetRow(needsAmount = true, eligibleIds = new Set()) { const list = $('targetList'); const row = document.createElement('div'); row.className = 'target-row'; const companies = state.companies.filter((company) => eligibleIds.size === 0 || eligibleIds.has(Number(company.id))); row.innerHTML = `<select class="form-select destination-company fraudster-control" required><option value="">Destination company…</option>${companies.map((c) => `<option value="${esc(c.id)}">${esc(companyName(c))}</option>`).join('')}</select>${needsAmount ? '<input class="form-control target-amount fraudster-control" type="number" min="0.01" step="0.01" placeholder="Amount" required>' : ''}<button type="button" class="btn btn-outline-secondary remove-target fraudster-control">×</button>`; row.querySelector('.remove-target').addEventListener('click', () => { if (list.children.length > (state.scenario && $('fraudType').value === 'SPLIT_TRANSFER' ? 2 : 1)) row.remove(); }); list.appendChild(row); updateTurnUI(); }
async function createScenario(event) {
  event.preventDefault();
  if (state.scenarioCreationPending) return;
  if (['RUNNING','PAUSED'].includes(state.agentRun?.status)) return showAlert('Wait for the learned-agent run to finish.');
  const source = Number($('scenarioSource').value), target = Number($('scenarioTarget').value), amount = Number($('scenarioAmount').value);
  if (!source || !target) return showAlert('Source and target companies are required.');
  if (source === target) return showAlert('Source and target companies must be different.');
  if (!(amount > 0)) return showAlert('Target amount must be greater than zero.');

  const revision = ++state.scenarioRevision;
  state.scenarioCreationPending = true;
  updateTurnUI();
  let created;
  try {
    created = await api('/api/fraud/scenarios', {
      method: 'POST', body: JSON.stringify({ sourceCompanyId:source, targetCompanyId:target, amount }),
    });
  } catch (error) {
    if (revision === state.scenarioRevision) {
      state.scenarioCreationPending = false;
      updateTurnUI();
      showAlert(`Unable to create fraud scenario. ${error.message}`);
    }
    return;
  }
  if (revision !== state.scenarioRevision) return;

  state.scenarioCreationPending = false;
  state.agentRun = null;
  state.agentSeenEvents = 0;
  state.scenarioTransactions = [];
  sessionStorage.removeItem('catchme-agent-run');
  synchronizeScenario(created);
  revealAgentRunPanel();
  logActivity('Fraud scenario created');
  showAlert(`Scenario #${state.scenario?.id ?? 'created'} is ready.`, 'success');
  try {
    await refreshScenarioData();
  } catch (error) {
    showAlert(`Scenario #${state.scenario?.id} was created, but its latest state could not be refreshed. ${error.message}`);
  }
}
async function executeFraud(event) { event.preventDefault(); const humanMatchMove = isHumanFraudsterTurn(); if (['RUNNING','PAUSED'].includes(state.agentRun?.status) && !humanMatchMove) return showAlert('Learned agents are controlling this scenario.'); if (!state.scenario?.id) return showAlert('Create a fraud scenario first.'); const type = $('fraudType').value, targets = [...document.querySelectorAll('.target-row')].map((row) => ({ destinationCompanyId:Number(row.querySelector('.destination-company').value), amount:row.querySelector('.target-amount') ? Number(row.querySelector('.target-amount').value) : null })); if (type === 'SPLIT_TRANSFER' && targets.some((t) => !t.destinationCompanyId || !(t.amount > 0))) return showAlert('Each fraudster target needs a destination and an amount greater than zero.'); if (type === 'ROUTE_TRANSFER' && targets.some((t) => !t.destinationCompanyId)) return showAlert('Choose an intermediate destination.'); try { const action = await api('/api/fraud/actions', { method:'POST', body:JSON.stringify({ scenarioId:state.scenario.id, actionType:type, sourcePositionId:Number($('sourcePosition').value), targets:type === 'WAIT' ? [] : targets }) }); const next = await api(`/api/fraud/actions/${action?.id}/execute`, { method:'POST' }); applyScenarioState(next); logActivity(`${type.replaceAll('_',' ').toLowerCase()} executed${humanMatchMove ? ' by you' : ''}`); showAlert('Fraudster action executed by the backend.', 'success'); await refreshScenarioData(); await loadData(); const terminal = ['COMPLETED','MAX_TURNS_REACHED'].includes(state.scenario?.status); if (humanMatchMove && (state.scenario?.turn === 'INVESTIGATOR' || terminal)) await continueLearnedRound(); } catch (error) { showAlert(`Unable to execute fraudster action. ${error.message}`); updateTurnUI(); } }
async function investigatorAction(type) { if (['RUNNING','PAUSED'].includes(state.agentRun?.status)) return showAlert('Learned agents are controlling this scenario.'); if (!state.scenario?.id) return showAlert('Create a fraud scenario first.'); const companyId = Number($('investigatorCompany').value), transactionId = Number($('investigatorTransaction').value); if (['OBSERVE_COMPANY','INVESTIGATE_DIRECTORS','FLAG_COMPANY'].includes(type) && !companyId) return showAlert('Select a company for this investigator action.'); if (type === 'TRACE_TRANSACTION' && !transactionId) return showAlert('Select a transaction to trace.'); try { const result = await api('/api/investigator/actions', { method:'POST', body:JSON.stringify({ scenarioId:state.scenario.id, actionType:type, companyId:companyId || null, transactionId:transactionId || null }) }); applyScenarioState(result); logActivity(type.replaceAll('_',' ').toLowerCase()); renderEvidence(result); await refreshScenarioData(); showAlert('Investigator action recorded.', 'success'); } catch (error) { showAlert(`Unable to complete investigator action. ${error.message}`); updateTurnUI(); } }
function renderEvidence(result) { const observation = result?.observation, investigation = result?.directorInvestigation, trace = result?.transactionTrace; if (investigation) { $('evidenceBody').innerHTML = `<div class="mb-3"><div class="detail-label">Company under investigation</div><h3 class="h5 mt-1">${esc(companyName(investigation.company))}</h3></div>${(investigation.directors || []).map((d) => `<div class="director-card"><div class="director-name"><i class="bi bi-person-badge me-2 text-primary"></i>${esc(d.directorName)}</div><div class="connected-list">${(d.associatedCompanies || []).map((c) => `<span class="connected-company"><i class="bi bi-building me-1"></i>${esc(companyName(c))}</span>`).join('') || '<span class="text-muted small">No associated companies returned.</span>'}</div></div>`).join('') || '<div class="empty-state">No director relationships returned.</div>'}`; } else if (trace) { $('evidenceBody').innerHTML = `<div class="detail-grid mb-4"><div><div class="detail-label">Transaction</div><div class="detail-value">#${esc(trace.id)}</div></div><div><div class="detail-label">Amount</div><div class="detail-value">${esc(money(trace.amount))}</div></div><div><div class="detail-label">Channel</div><div class="detail-value">${esc(trace.channel)}</div></div><div><div class="detail-label">Timestamp</div><div class="detail-value">${esc(dateText(trace.timestamp))}</div></div></div><div class="trace-chain"><div class="trace-node">${esc(companyName(trace.sourceCompany))}</div><span class="trace-arrow">→</span><div class="trace-node">${esc(companyName(trace.destinationCompany))}</div></div>`; } else if (observation) { const safe = publicCompany(observation); $('evidenceBody').innerHTML = `<div class="mb-3"><div class="detail-label">Observed company</div><h3 class="h5 mt-1">${esc(companyName(safe))}</h3></div><div class="detail-grid">${[['Registration number',safe.registrationNumber],['Industry',safe.industry],['Address',safe.address],['Age',safe.ageInYears == null ? 'N/A' : `${safe.ageInYears} years`],['Registration date',safe.registrationDate],['Annual revenue',money(safe.annualRevenue)],['Employees',safe.numberOfEmployees]].map(([label,value]) => `<div><div class="detail-label">${esc(label)}</div><div class="detail-value">${esc(value)}</div></div>`).join('')}</div>`; } else { $('evidenceBody').innerHTML = `<div class="alert alert-warning mb-0">${result?.actionType === 'FLAG_COMPANY' ? 'Company flag submitted. Evaluation remains inside the environment.' : 'The action was accepted, but no additional observation data was returned.'}</div>`; } $('investigationOutput').scrollIntoView({ behavior:'smooth', block:'center' }); }

 $('companySearch').addEventListener('input', renderCompanies); $('evaluationReportFile').addEventListener('change', importEvaluationReport); $('refreshBtn').addEventListener('click', loadData); $('riskRefresh').addEventListener('click', () => loadRiskAnalyzer(true)); $('shellRiskAnalyzer').addEventListener('mouseenter', () => loadRiskAnalyzer()); $('scenarioForm').addEventListener('submit', createScenario); $('fraudForm').addEventListener('submit', executeFraud); $('fraudType').addEventListener('change', () => targetsFor($('fraudType').value)); $('sourcePosition').addEventListener('change', () => { if ($('sourcePosition').value) { state.sourceSelectionInvalid = false; $('sourcePositionHint').textContent = 'Selected source has funds; balance is refreshed from the scenario.'; } targetsFor($('fraudType').value); updateTurnUI(); }); $('runHeuristicSearch').addEventListener('click', startHeuristicSearch); $('runLearnedAgents').addEventListener('click', startLearnedAgents); $('runHumanFraudster').addEventListener('click', startHumanFraudsterMatch); $('continueRound').addEventListener('click', () => continueLearnedRound()); $('cancelAgentRun').addEventListener('click', cancelLearnedRun); $('autoContinue').addEventListener('change', () => { if (state.agentRun?.status === 'PAUSED') scheduleAutoContinue(state.agentRun.runId); renderAgentRunPanel(); }); $('continueDelay').addEventListener('change', () => { if (state.agentAutoTimer) clearTimeout(state.agentAutoTimer); state.agentAutoTimer = null; if (state.agentRun?.status === 'PAUSED' && $('autoContinue').checked) scheduleAutoContinue(state.agentRun.runId); }); document.querySelectorAll('.investigator-btn').forEach((button) => button.addEventListener('click', () => investigatorAction(button.dataset.action))); targetsFor('DIRECT_TRANSFER'); updateTurnUI(); initializeDashboard();
