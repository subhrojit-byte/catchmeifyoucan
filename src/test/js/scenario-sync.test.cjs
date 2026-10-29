const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const appPath = path.resolve(__dirname, '../../main/resources/static/js/app.js');
const appSource = fs.readFileSync(appPath, 'utf8');
const htmlPath = path.resolve(__dirname, '../../main/resources/static/index.html');
const htmlSource = fs.readFileSync(htmlPath, 'utf8');
const bootstrapStart = appSource.lastIndexOf("\n $('companySearch').addEventListener");
assert.notEqual(bootstrapStart, -1, 'frontend bootstrap boundary should be found');

function classList() {
  const values = new Set();
  return {
    add: (name) => values.add(name),
    remove: (name) => values.delete(name),
    contains: (name) => values.has(name),
    toggle(name, force = !values.has(name)) {
      if (force) values.add(name); else values.delete(name);
      return force;
    },
  };
}

function createHarness(fetchImpl = async () => response({}), savedScenario = null, savedRun = { runId: 'old-run', scenarioId: 275 }) {
  const elements = new Map();
  const scrollCalls = [];
  const makeElement = (id) => ({
    id, innerHTML: '', textContent: '', value: '', checked: false, disabled: false,
    className: '', classList: classList(), selectedOptions: [], dataset: {},
    listeners: {}, addEventListener(type, listener) { this.listeners[type] = listener; },
    click() { return this.listeners.click?.(); },
    querySelectorAll: () => [], querySelector: (name) => getElementById(`${id}:${name}`),
    scrollIntoView: (options) => scrollCalls.push({ id, options }),
  });
  const getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };
  const progressSteps = Array.from({ length: 5 }, (_, index) => makeElement(`progress-${index}`));
  getElementById('roundProgress').querySelectorAll = () => progressSteps;
  const storage = new Map(savedRun ? [['catchme-agent-run', JSON.stringify(savedRun)]] : []);
  const localStorage = new Map(savedScenario ? [['catchme-scenario-id', String(savedScenario)]] : []);
  const context = {
    document: { getElementById, querySelectorAll: () => [], querySelector: () => makeElement('query') },
    window: {},
    fetch: fetchImpl,
    sessionStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
    localStorage: {
      getItem: (key) => localStorage.get(key) ?? null,
      setItem: (key, value) => localStorage.set(key, String(value)),
      removeItem: (key) => localStorage.delete(key),
    },
    console: { warn() {}, log() {} },
    setTimeout, clearTimeout,
  };
  vm.createContext(context);
  vm.runInContext(`${appSource.slice(0, bootstrapStart)}\nglobalThis.__scenarioTest = { state, synchronizeScenario, renderScenario, renderFlow, renderAgentRunPanel, clearScenarioSummary, clearScenarioFlow, clearScenarioNetwork, refreshScenarioData, renderCompanies, loadCompanyDirectoryStatuses, renderAgentAnalytics, renderEvaluationReport, canStartLearnedRun, createScenario, startLearnedAgents, startHumanFraudsterMatch, executeFraud, pollAgentRun, restoreLearnedAgentRun, restoreSelectedScenario, restoreInitialScenario, updateSavedScenarioAction, initializeDashboard };`, context, { filename: appPath });
  return { app: context.__scenarioTest, elements, storage, localStorage, scrollCalls, element: getElementById };
}

function response(value, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(value) };
}

function scenario(id, status = 'ACTIVE') {
  return {
    id, status, turn: 'FRAUDSTER', step: 0, investigatorActionsRemaining: 3,
    sourceCompany: { id: 10, companyName: 'Source' },
    targetCompany: { id: 11, companyName: 'Target' }, targetAmount: 100,
    positions: [{ id: 1, company: { id: 10, companyName: 'Source' }, amount: 100 }],
  };
}

test('successful create renders both scenario views even if auxiliary transaction refresh fails', async () => {
  const created = scenario(276);
  const harness = createHarness(async (url, options = {}) => {
    if (url === '/api/fraud/scenarios' && options.method === 'POST') return response(created);
    if (url === '/api/fraud/scenarios/276') return response(created);
    if (url === '/api/transactions/scenario/276') return response({ message: 'unavailable' }, 503);
    throw new Error(`Unexpected request ${url}`);
  });
  harness.element('scenarioSource').value = '10';
  harness.element('scenarioTarget').value = '11';
  harness.element('scenarioAmount').value = '100';

  await harness.app.createScenario({ preventDefault() {} });

  assert.match(harness.element('scenarioSummary').innerHTML, /Scenario #276/);
  assert.equal(harness.element('scenarioSummary').classList.contains('d-none'), false);
  assert.equal(harness.element('agentRunPanel').classList.contains('d-none'), false);
  assert.equal(harness.element('runLearnedAgents').disabled, false);
  assert.equal(harness.element('runHeuristicSearch').disabled, false);
  assert.equal(harness.element('runHumanFraudster').disabled, false);
  assert.equal(harness.app.state.scenario.id, 276);
  assert.equal(harness.localStorage.get('catchme-scenario-id'), '276');
  assert.equal(harness.scrollCalls.length, 1);
  assert.equal(harness.scrollCalls[0].id, 'runLearnedAgents');
  assert.equal(harness.scrollCalls[0].options.behavior, 'smooth');
  assert.equal(harness.scrollCalls[0].options.block, 'center');
});

test('scenario summary distinguishes completed detection from an achieved objective still under investigation', () => {
  const harness = createHarness(undefined, null, null);

  harness.app.synchronizeScenario({ ...scenario(276), financialObjectiveAchieved: true });
  assert.match(harness.element('scenarioSummary').innerHTML, /Transfer achieved · Investigation continues/);

  harness.app.synchronizeScenario({ ...scenario(276, 'COMPLETED'), financialObjectiveAchieved: true });
  assert.match(harness.element('scenarioSummary').innerHTML, /Fraud detected · Investigation completed/);
  assert.doesNotMatch(harness.element('scenarioSummary').innerHTML, /Transfer achieved · Investigation continues/);

  harness.app.synchronizeScenario({ ...scenario(276, 'MAX_TURNS_REACHED'), financialObjectiveAchieved: true });
  assert.match(harness.element('scenarioSummary').innerHTML, /Transfer achieved · Investigation continues/);
});

test('historical evaluation metrics retain their own provenance and null metrics stay unavailable', () => {
  const harness = createHarness(undefined, null, null);
  harness.app.renderEvaluationReport({
    policy_name: 'learned_investigator',
    scenario_ids: [901, 902],
    episodes: [{ managed_run_id: 'historical-run-1' }],
    fraud_path_detection_metrics: { metric_scope: 'fraud_path_shell_detection', precision: null, recall: 0, f1: null, tp: 0, fp: 2, tn: 4, fn: 1 },
    objective_success_rate: 1,
    average_episode_length: 8,
    median_episode_length: 7,
    checkpoint_provenance: {
      execution_mode: 'managed AgentRun per scenario',
      checkpoint_compatibility_validation_inputs: { investigator: 'rl-agents/requested.json' },
    },
  }, { name: 'historical.json', lastModified: 1000 });

  const html = harness.element('evaluationAnalytics').innerHTML;
  assert.match(html, /Historical report/);
  assert.match(html, /learned_investigator/);
  assert.match(html, /901, 902/);
  assert.match(html, /historical-run-1/);
  assert.match(html, /Effective server checkpoints unavailable/);
  assert.match(html, /Unavailable/);
  assert.match(html, /0\.0%/);
  assert.match(html, /financial objective rate/i);
  assert.match(html, /not linked to the current run/i);
});

test('heuristic analytics shows runner-sourced policy rules without presenting them as performance', () => {
  const harness = createHarness(undefined, null, null);
  harness.app.state.agentRun = { events: [{
    event_type: 'heuristic_policy_metadata',
    policies: [
      { policy: 'FraudsterBot', configuration: { source: 'fraudster_bot.py', parameters: [], selection_rules: ['Uses DIRECT_TRANSFER.'] } },
      { policy: 'InvestigatorBot', configuration: { source: 'investigator_bot.py', parameters: [{ name: 'SUSPICION_THRESHOLD', value: 4, meaning: 'Threshold', effect: 'Selects flags.' }], selection_rules: ['Ranks by score.'] } },
    ],
  }] };
  harness.app.renderAgentAnalytics();
  const html = harness.element('heuristicPolicyAnalytics').innerHTML;
  assert.match(html, /FraudsterBot/);
  assert.match(html, /No numeric tunable parameters/);
  assert.match(html, /SUSPICION_THRESHOLD/);
  assert.match(html, /one episode is not an aggregate benchmark/i);
  assert.doesNotMatch(html, /Q-value|shellCompany|flagCorrect/);
});

test('Companies Explorer displays statuses from the separate localhost directory data source', async () => {
  const requested = [];
  const harness = createHarness(async (url) => {
    requested.push(url);
    if (url === '/api/companies/directory') return response([
      { id: 10, shellCompany: true }, { id: 11, shellCompany: false },
    ]);
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.state.companies = [
    { id: 10, companyName: 'Observed Co', industry: 'Trade' },
    { id: 11, companyName: 'Other Co', industry: 'Services' },
  ];
  await harness.app.loadCompanyDirectoryStatuses();
  harness.app.renderCompanies();
  const html = harness.element('companyTable').innerHTML;
  assert.deepEqual(requested, ['/api/companies/directory']);
  assert.match(html, /SHELL COMPANY/);
  assert.match(html, /LEGITIMATE COMPANY/);
  assert.doesNotMatch(html, /Hidden in shared view|Current run signal|Not flagged in completed run/);
});

test('frontend loads a versioned app script so cached code cannot leave new controls disabled', () => {
  assert.match(htmlSource, /<script src="\/js\/app\.js\?v=[^"]+"><\/script>/);
});

test('dashboard startup leaves prior scenarios empty and preserves them for an explicit open', async () => {
  const requested = [];
  const harness = createHarness(async (url) => {
    requested.push(url);
    if (url === '/api/companies' || url === '/api/transactions' || url === '/api/companies/directory') return response([]);
    throw new Error(`Unexpected startup request ${url}`);
  }, 276, { runId: 'saved-run', scenarioId: 276 });

  await harness.app.initializeDashboard();

  assert.equal(harness.app.state.scenario, null);
  assert.equal(harness.element('scenarioSummary').innerHTML, '');
  assert.equal(harness.element('scenarioSummary').classList.contains('d-none'), true);
  assert.equal(harness.element('scenarioStatus').textContent, 'None');
  assert.equal(harness.element('flowCanvas').innerHTML, 'Create a scenario to visualize movement.');
  assert.match(harness.element('gameTransactions').innerHTML, /No scenario transfers/);
  assert.ok(!requested.some((url) => url.startsWith('/api/fraud/scenarios/') || url.startsWith('/api/agent-runs/')));
  assert.equal(harness.localStorage.get('catchme-scenario-id'), '276');
  assert.equal(harness.storage.get('catchme-agent-run'), JSON.stringify({ runId: 'saved-run', scenarioId: 276 }));
  assert.equal(harness.element('openSavedScenario').classList.contains('d-none'), false);
});

test('explicit Open saved scenario action restores the prior scenario through read-only endpoints', async () => {
  const saved = scenario(276);
  const requested = [];
  const harness = createHarness(async (url) => {
    requested.push(url);
    if (url === '/api/fraud/scenarios/276') return response(saved);
    if (url === '/api/transactions/scenario/276') return response([{ id: 8 }]);
    throw new Error(`Unexpected request ${url}`);
  }, 276, null);

  harness.app.updateSavedScenarioAction();
  await harness.element('openSavedScenario').click();

  assert.deepEqual(requested, ['/api/fraud/scenarios/276', '/api/transactions/scenario/276']);
  assert.equal(harness.app.state.scenario.id, 276);
  assert.equal(harness.app.state.scenarioTransactions.length, 1);
  assert.equal(harness.app.state.scenarioTransactions[0].id, 8);
  assert.match(harness.element('scenarioSummary').innerHTML, /Scenario #276/);
  assert.equal(harness.element('scenarioSummary').classList.contains('d-none'), false);
  assert.equal(harness.element('agentRunPanel').classList.contains('d-none'), false);
  assert.equal(harness.element('runLearnedAgents').disabled, false);
  assert.equal(harness.scrollCalls.length, 1);
  assert.equal(harness.scrollCalls[0].id, 'runLearnedAgents');
  assert.equal(harness.scrollCalls[0].options.behavior, 'smooth');
  assert.equal(harness.scrollCalls[0].options.block, 'center');
});

test('ordinary scenario renders do not trigger viewport scrolling', () => {
  const harness = createHarness();
  harness.app.synchronizeScenario(scenario(276));
  harness.app.renderScenario();

  assert.equal(harness.scrollCalls.length, 0);
});

test('new scenario clears prior network data and an older transaction response cannot restore it', async () => {
  let finishOldTransactions;
  const harness = createHarness(async (url) => {
    if (url === '/api/fraud/scenarios/276') return response(scenario(276));
    if (url === '/api/transactions/scenario/276') return new Promise((resolve) => { finishOldTransactions = resolve; });
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.synchronizeScenario(scenario(276));
  harness.app.state.scenarioTransactions = [{ id: 'old-transfer' }];
  const refresh = harness.app.refreshScenarioData();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(finishOldTransactions, 'old transaction request should be pending');

  harness.app.synchronizeScenario(scenario(277));
  assert.deepEqual(Array.from(harness.app.state.scenarioTransactions), []);
  assert.match(harness.element('gameTransactions').innerHTML, /No scenario transfers/);
  finishOldTransactions(response([{ id: 'old-transfer' }]));
  await refresh;

  assert.equal(harness.app.state.scenario.id, 277);
  assert.deepEqual(Array.from(harness.app.state.scenarioTransactions), []);
  assert.doesNotMatch(harness.element('gameTransactions').innerHTML, /old-transfer/);
});

test('an in-flight agent response from an older scenario cannot replace the current run state', async () => {
  let finishOldRun;
  const harness = createHarness(async (url) => {
    if (url === '/api/agent-runs/old-run') return new Promise((resolve) => { finishOldRun = resolve; });
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.synchronizeScenario(scenario(276));
  harness.app.state.agentRun = { runId: 'old-run', scenarioId: 276, status: 'RUNNING', events: [] };
  const polling = harness.app.pollAgentRun('old-run');
  await new Promise((resolve) => setTimeout(resolve, 0));

  harness.app.state.agentRun = null;
  harness.app.synchronizeScenario(scenario(277));
  finishOldRun(response({ runId: 'old-run', scenarioId: 276, status: 'COMPLETED', events: [] }));
  await polling;

  assert.equal(harness.app.state.scenario.id, 277);
  assert.equal(harness.app.state.agentRun, null);
});

test('clear controls hide only their session display and remain cleared on same-scenario refreshes', () => {
  const harness = createHarness(undefined, null, null);
  const current = scenario(276, 'COMPLETED');
  harness.app.synchronizeScenario(current);
  harness.app.state.scenarioTransactions = [{ id: 91, sourceCompany: { companyName: 'Source' }, destinationCompany: { companyName: 'Target' }, amount: 100 }];
  harness.app.state.agentRun = { runId: 'active-run', scenarioId: 276, status: 'RUNNING', events: [] };
  harness.app.renderAgentRunPanel();
  assert.match(harness.element('gameTransactions').innerHTML, /Source/);
  assert.match(harness.element('scenarioSummary').innerHTML, /COMPLETED/);
  assert.match(harness.element('flowCanvas').innerHTML, /flow-node/);

  harness.app.clearScenarioSummary();
  harness.app.clearScenarioFlow();
  harness.app.clearScenarioNetwork();
  harness.app.synchronizeScenario({ ...current, step: 1 });
  harness.app.renderAgentRunPanel();

  assert.equal(harness.app.state.scenario.id, 276, 'clearing is display-only');
  assert.equal(harness.app.state.agentRun.status, 'RUNNING', 'active backend run state is retained');
  assert.equal(harness.app.state.scenarioTransactions.length, 1, 'cached transaction data is retained');
  assert.equal(harness.element('scenarioSummary').classList.contains('d-none'), true);
  assert.equal(harness.element('scenarioSummary').innerHTML, '');
  assert.equal(harness.element('scenarioStatus').textContent, 'None');
  assert.equal(harness.element('flowMeta').textContent, 'No active scenario');
  assert.equal(harness.element('flowCanvas').innerHTML, 'Create a scenario to visualize movement.');
  assert.match(harness.element('gameTransactions').innerHTML, /Displayed network data cleared/);
  assert.match(harness.element('gamePositions').innerHTML, /Displayed balances cleared/);

  harness.app.synchronizeScenario(scenario(277));
  assert.deepEqual({ ...harness.app.state.scenarioDisplayCleared }, { summary: false, flow: false, network: false });
  assert.equal(harness.element('scenarioSummary').classList.contains('d-none'), false);
  assert.match(harness.element('flowCanvas').innerHTML, /flow-node/);
  assert.match(harness.element('gameTransactions').innerHTML, /No scenario transfers/);
});

test('dashboard removes navbar status chrome and keeps concise analyzer essentials and clear controls', () => {
  assert.doesNotMatch(htmlSource, /class="brand-mark"|class="status-pill"|Environment Online/);
  assert.match(htmlSource, /id="clearScenarioData"[^>]*>Clear Data/);
  assert.match(htmlSource, /id="clearFlowData"[^>]*>Clear Data/);
  assert.match(htmlSource, /id="clearNetworkData"[^>]*>Clear Data/);
  assert.match(htmlSource, /Shell Company Detection Using BFS and Fuzzy Logic/);
  assert.match(htmlSource, /Observable-data shell-company risk estimate · not a calibrated probability\./);
  assert.doesNotMatch(htmlSource, /Open the analyzer to load public company, director relationship and transaction data\./);
});

test('shared observation fields cannot override separate Company Directory status', () => {
  const harness = createHarness();
  harness.app.state.companies = [{
    id: 91,
    companyName: 'Observable Company',
    registrationNumber: 'REG-91',
    industry: 'Retail',
    address: 'Public address',
    numberOfEmployees: 12,
    shellCompany: true,
    flagCorrect: true,
    privateShellCompanyIds: [91],
  }];

  harness.app.state.companyDirectoryStatuses = { '91': false };
  harness.app.renderCompanies();

  const markup = harness.element('companyTable').innerHTML;
  assert.match(markup, /LEGITIMATE COMPANY/);
  assert.doesNotMatch(markup, /flagCorrect|privateShellCompanyIds/);
});

test('saved scenario restoration cannot replace a scenario selected while the GET is pending', async () => {
  let finishRequest;
  const harness = createHarness(() => new Promise((resolve) => { finishRequest = resolve; }), 275);
  const restore = harness.app.restoreSelectedScenario();

  harness.app.synchronizeScenario(scenario(276));
  finishRequest(response(scenario(275)));
  await restore;

  assert.equal(harness.app.state.scenario.id, 276);
  assert.equal(harness.localStorage.get('catchme-scenario-id'), '276');
});

test('late session restoration cannot overwrite a scenario created while its reads were pending', async () => {
  const requests = new Map();
  const harness = createHarness((url) => new Promise((resolve) => requests.set(url, resolve)));
  const restore = harness.app.restoreLearnedAgentRun();
  assert.equal(requests.size, 2);

  harness.app.synchronizeScenario(scenario(276));
  requests.get('/api/agent-runs/old-run')(response({ runId: 'old-run', scenarioId: 275, status: 'COMPLETED', events: [] }));
  requests.get('/api/fraud/scenarios/275')(response(scenario(275)));
  await restore;

  assert.equal(harness.app.state.scenario.id, 276);
  assert.match(harness.element('scenarioSummary').innerHTML, /Scenario #276/);
  assert.equal(harness.element('agentRunPanel').classList.contains('d-none'), false);
  assert.equal(harness.app.state.agentRun, null);
});

test('learned-run control requires a valid active scenario and no active run', () => {
  const { app } = createHarness();
  assert.equal(app.canStartLearnedRun(scenario(276), null), true);
  assert.equal(app.canStartLearnedRun(scenario(276, 'COMPLETED'), null), false);
  assert.equal(app.canStartLearnedRun({ id: 0, status: 'ACTIVE', positions: [] }, null), false);
  assert.equal(app.canStartLearnedRun({ id: true, status: 'ACTIVE', positions: [] }, null), false);
  assert.equal(app.canStartLearnedRun({ id: 276, status: 'ACTIVE' }, null), false);
  assert.equal(app.canStartLearnedRun(scenario(276), { status: 'RUNNING' }), false);
  assert.equal(app.canStartLearnedRun(scenario(276), { status: 'PAUSED' }), false);
  app.state.scenarioCreationPending = true;
  assert.equal(app.canStartLearnedRun(scenario(276), null), false);
  app.state.scenarioCreationPending = false;
  app.state.agentRunStarting = true;
  assert.equal(app.canStartLearnedRun(scenario(276), null), false);
});

test('Agent Match remains visible without a scenario while its run button stays disabled', () => {
  const harness = createHarness();
  harness.app.renderScenario();

  const panelMarkup = htmlSource.match(/<section id="agentRunPanel" class="([^"]+)"/);
  assert.ok(panelMarkup, 'Agent Match panel should exist in the page');
  assert.equal(panelMarkup[1].split(/\s+/).includes('d-none'), false);
  assert.match(htmlSource, /<button id="runLearnedAgents"[^>]*\sdisabled(?:[\s>])/);
  assert.equal(harness.element('agentRunPanel').classList.contains('d-none'), false);
  assert.equal(harness.element('agentRunStatus').textContent, 'READY');
  assert.match(harness.element('agentRunDetails').textContent, /Create a scenario/);
  assert.equal(harness.element('runLearnedAgents').disabled, true);
});

test('Run Learned Agents uses the existing API, shows loading, and renders terminal run events and scenario state', async () => {
  let finishStart;
  let finishPoll;
  const requests = [];
  const finalScenario = scenario(276, 'COMPLETED');
  finalScenario.turn = 'INVESTIGATOR';
  const finalRun = {
    runId: 'run-276', scenarioId: 276, status: 'COMPLETED', actionsAttempted: 1,
    events: [{ event_type: 'action', action_number: 1, agent: 'FRAUDSTER',
      action: { action_type: 'DIRECT_TRANSFER' },
      state: { status: 'ACTIVE', positions: finalScenario.positions } }],
  };
  const harness = createHarness(async (url, options = {}) => {
    requests.push({ url, options });
    if (url === '/api/agent-runs' && options.method === 'POST') return new Promise((resolve) => { finishStart = resolve; });
    if (url === '/api/agent-runs/run-276') return new Promise((resolve) => { finishPoll = resolve; });
    if (url === '/api/fraud/scenarios/276') return response(finalScenario);
    if (url === '/api/transactions/scenario/276') return response([]);
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.synchronizeScenario(scenario(276));

  const starting = harness.app.startLearnedAgents();
  assert.equal(harness.element('runLearnedAgents').disabled, true);
  assert.equal(harness.element('runLearnedAgents').textContent, 'Starting Agents...');
  assert.equal(harness.app.state.agentRunStarting, true);

  finishStart(response({ runId: 'run-276', scenarioId: 276, status: 'RUNNING', events: [] }));
  await starting;
  assert.equal(requests[0].url, '/api/agent-runs');
  assert.deepEqual(JSON.parse(requests[0].options.body), { scenarioId: 276, mode: 'INFERENCE' });
  assert.equal(harness.element('runLearnedAgents').disabled, true);
  assert.equal(harness.element('runLearnedAgents').textContent, 'Agents Running...');

  finishPoll(response(finalRun));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(harness.app.state.agentRun.status, 'COMPLETED');
  assert.equal(harness.app.state.scenario.status, 'COMPLETED');
  assert.match(harness.element('agentRunEvents').innerHTML, /Fraudster Agent/);
  assert.match(harness.element('agentRunEvents').innerHTML, /DIRECT TRANSFER/);
  assert.match(harness.element('gamePositions').innerHTML, /Source/);
  assert.equal(harness.element('agentRunStatus').textContent, 'COMPLETED');
  assert.match(harness.element('gameFinalResult').textContent, /Scenario complete/);
  assert.equal(harness.element('runLearnedAgents').disabled, true);
  assert.ok(requests.some((request) => request.url === '/api/fraud/scenarios/276'));
});

test('human fraudster match requests its dedicated mode and preserves the mode for restore', async () => {
  const requests = [];
  const harness = createHarness(async (url, options = {}) => {
    requests.push({ url, options });
    if (url === '/api/agent-runs' && options.method === 'POST') {
      return response({ runId: 'human-run', scenarioId: 276, status: 'RUNNING', events: [] });
    }
    if (url === '/api/agent-runs/human-run') {
      return response({ runId: 'human-run', scenarioId: 276, status: 'COMPLETED', events: [] });
    }
    if (url === '/api/fraud/scenarios/276') return response(scenario(276, 'COMPLETED'));
    if (url === '/api/transactions/scenario/276') return response([]);
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.synchronizeScenario(scenario(276));

  await harness.app.startHumanFraudsterMatch();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(JSON.parse(requests[0].options.body), { scenarioId: 276, mode: 'HUMAN_FRAUDSTER' });
  assert.equal(JSON.parse(harness.storage.get('catchme-agent-run')).mode, 'HUMAN_FRAUDSTER');
  assert.equal(harness.element('fraudsterRoleTitle').textContent, 'You · Human Fraudster');
  assert.equal(harness.element('investigatorAgentCard:h3').textContent, 'Learned Investigator Bot');
});

test('human move uses the manual fraudster endpoints and resumes the investigator worker', async () => {
  const requests = [];
  const afterMove = { ...scenario(276), turn: 'INVESTIGATOR' };
  const harness = createHarness(async (url, options = {}) => {
    requests.push({ url, options });
    if (url === '/api/fraud/actions' && options.method === 'POST') return response({ id: 91 });
    if (url === '/api/fraud/actions/91/execute' && options.method === 'POST') return response(afterMove);
    if (url === '/api/agent-runs/human-run/continue') {
      return response({ runId: 'human-run', scenarioId: 276, status: 'RUNNING', events: [] });
    }
    if (url === '/api/agent-runs/human-run') {
      return response({ runId: 'human-run', scenarioId: 276, status: 'COMPLETED', events: [] });
    }
    if (url === '/api/fraud/scenarios/276') return response(afterMove);
    if (url === '/api/transactions/scenario/276' || url === '/api/transactions' || url === '/api/companies') return response([]);
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.synchronizeScenario(scenario(276));
  harness.app.state.agentRunMode = 'HUMAN_FRAUDSTER';
  harness.app.state.agentRun = { runId: 'human-run', scenarioId: 276, status: 'PAUSED', events: [] };
  harness.element('fraudType').value = 'WAIT';

  await harness.app.executeFraud({ preventDefault() {} });
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(requests.slice(0, 2).map(({ url }) => url), [
    '/api/fraud/actions', '/api/fraud/actions/91/execute',
  ]);
  assert.ok(requests.some(({ url }) => url === '/api/agent-runs/human-run/continue'));
  assert.equal(harness.app.state.scenario.turn, 'INVESTIGATOR');
});

test('human can chain a transfer from a funded intermediate source after scenario refreshes', async () => {
  const requests = [];
  const afterSplit = {
    ...scenario(277), step: 1,
    positions: [
      { id: 1, company: { id: 10, companyName: 'Source' }, amount: 0 },
      { id: 2, company: { id: 22, companyName: 'Intermediate A' }, amount: 60 },
      { id: 3, company: { id: 23, companyName: 'Intermediate B' }, amount: 40 },
    ],
  };
  const afterChainedTransfer = {
    ...afterSplit, step: 2, turn: 'INVESTIGATOR',
    positions: [
      afterSplit.positions[0],
      { ...afterSplit.positions[1], amount: 0 },
      { ...afterSplit.positions[2], amount: 100 },
    ],
  };
  const harness = createHarness(async (url, options = {}) => {
    requests.push({ url, options });
    if (url === '/api/fraud/actions' && options.method === 'POST') return response({ id: 92 });
    if (url === '/api/fraud/actions/92/execute' && options.method === 'POST') return response(afterChainedTransfer);
    if (url === '/api/agent-runs/human-run/continue') {
      return response({ runId: 'human-run', scenarioId: 277, status: 'RUNNING', events: [] });
    }
    if (url === '/api/agent-runs/human-run') {
      return response({ runId: 'human-run', scenarioId: 277, status: 'COMPLETED', events: [] });
    }
    if (url === '/api/fraud/scenarios/277') return response(afterChainedTransfer);
    if (url === '/api/transactions/scenario/277' || url === '/api/transactions' || url === '/api/companies') return response([]);
    throw new Error(`Unexpected request ${url}`);
  }, null, null);

  harness.app.synchronizeScenario(scenario(277));
  assert.equal(harness.element('sourcePosition').value, '1');
  harness.app.synchronizeScenario(afterSplit);
  assert.equal(harness.element('sourcePosition').value, '');
  assert.match(harness.element('sourcePositionHint').textContent, /previously selected source no longer has funds/);
  harness.element('sourcePosition').value = '2';
  harness.app.synchronizeScenario(afterSplit);
  assert.equal(harness.element('sourcePosition').value, '2');
  assert.match(harness.element('sourcePosition').innerHTML, /Intermediate A/);
  assert.match(harness.element('sourcePosition').innerHTML, /₹60/);

  harness.app.state.agentRunMode = 'HUMAN_FRAUDSTER';
  harness.app.state.agentRun = { runId: 'human-run', scenarioId: 277, status: 'PAUSED', events: [] };
  harness.element('fraudType').value = 'DIRECT_TRANSFER';
  await harness.app.executeFraud({ preventDefault() {} });
  await new Promise((resolve) => setTimeout(resolve, 0));

  const createRequest = requests.find(({ url }) => url === '/api/fraud/actions');
  assert.equal(JSON.parse(createRequest.options.body).sourcePositionId, 2);
  assert.equal(harness.element('sourcePosition').value, '');
  assert.match(harness.element('sourcePositionHint').textContent, /previously selected source no longer has funds/);
  assert.ok(requests.some(({ url }) => url === '/api/agent-runs/human-run/continue'));
});

test('failed run start reports an error and clears the loading guard', async () => {
  const harness = createHarness(async (url) => {
    if (url === '/api/agent-runs') return response({ message: 'runner unavailable' }, 503);
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.synchronizeScenario(scenario(276));

  await harness.app.startLearnedAgents();

  assert.equal(harness.app.state.agentRunStarting, false);
  assert.equal(harness.element('runLearnedAgents').disabled, false);
  assert.match(harness.element('alertArea').innerHTML, /Unable to start learned-agent run/);
  assert.match(harness.element('alertArea').innerHTML, /runner unavailable/);
});

test('runner failure is shown, saved run state is cleared, and an active scenario can be retried', async () => {
  const harness = createHarness(async (url, options = {}) => {
    if (url === '/api/agent-runs' && options.method === 'POST') {
      return response({ runId: 'run-failed', scenarioId: 276, status: 'RUNNING', events: [] });
    }
    if (url === '/api/agent-runs/run-failed') {
      return response({ runId: 'run-failed', scenarioId: 276, status: 'FAILED', message: 'Runner exited unexpectedly.', events: [] });
    }
    if (url === '/api/fraud/scenarios/276') return response(scenario(276));
    if (url === '/api/transactions/scenario/276') return response([]);
    throw new Error(`Unexpected request ${url}`);
  }, null, null);
  harness.app.synchronizeScenario(scenario(276));

  await harness.app.startLearnedAgents();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(harness.app.state.agentRun.status, 'FAILED');
  assert.equal(harness.element('agentRunStatus').textContent, 'FAILED');
  assert.match(harness.element('gameFinalResult').textContent, /Runner exited unexpectedly/);
  assert.match(harness.element('alertArea').innerHTML, /Runner exited unexpectedly/);
  assert.equal(harness.storage.has('catchme-agent-run'), false);
  assert.equal(harness.element('runLearnedAgents').disabled, false);
});
