const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const analyzer = require('../../main/resources/static/js/risk-analyzer.js');

const companies = [
  { id: 1, companyName: 'Alpha', address: '  10 Main St. ', ageInYears: 1, annualRevenue: 100000, numberOfEmployees: 1 },
  { id: 2, companyName: 'Beta', address: '10 MAIN ST', ageInYears: 8, annualRevenue: 10000000, numberOfEmployees: 20 },
  { id: 3, companyName: 'Gamma', address: 'Elsewhere', ageInYears: 3, annualRevenue: 400000, numberOfEmployees: 1 },
];
const relationships = [
  { company: { id: 1, companyName: 'Alpha', address: '10 Main St.' }, director: { id: 7, directorName: 'Dana' } },
  { company: { id: 2, companyName: 'Beta', address: '10 MAIN ST' }, director: { id: 7, directorName: 'Dana' } },
];

test('BFS returns typed address and director paths and tracks companies through a cycle', () => {
  const graph = analyzer.buildGraph(companies, relationships, []);
  const result = analyzer.traverse(graph, 1, 4);
  assert.ok(result.paths.some((path) => path.relationships.includes('shared-address')));
  assert.ok(result.paths.some((path) => path.relationships.includes('company-director')));
  assert.deepEqual(result.visitedCompanies, ['1', '2']);
  assert.equal(result.visitedNodes.filter((node) => node.type === 'director' && node.id === '7').length, 1);
  assert.equal(analyzer.traverse(graph, 1, 0).visitedNodes.length, 1);
  assert.equal(analyzer.traverse(graph, 1, 1).paths.every((path) => path.depth === 1), true);
  assert.equal(analyzer.traverse(graph, 1, 1).discoveredEdges.every((edge) => edge.depth <= 1), true);
  assert.equal(new Set(result.discoveredEdges.map((edge) => `${edge.from}|${edge.to}|${edge.type}`)).size, result.discoveredEdges.length);
});

test('SVG layout keeps the selected company visible at depth zero and reveals only cached BFS levels', () => {
  const graph = analyzer.buildGraph(companies, relationships, []);
  const traversal = analyzer.traverse(graph, 1, 4);
  const start = analyzer.layoutTraversal(traversal, 1, 0);
  assert.deepEqual(start.nodes.map((node) => node.id), ['1']);
  assert.equal(start.edges.length, 0);
  assert.deepEqual(start.positions.get('company:1'), { x: 70, y: 35 });

  const nextLevel = analyzer.layoutTraversal(traversal, 1, 1);
  assert.ok(nextLevel.nodes.some((node) => node.type === 'director' && node.id === '7'));
  assert.ok(nextLevel.edges.some((edge) => edge.type === 'shared-address'));
  assert.ok(nextLevel.edges.every((edge) => edge.depth <= 1));
  for (const point of nextLevel.positions.values()) {
    assert.ok(point.x >= 18 && point.x + 52 <= nextLevel.width);
    assert.ok(point.y >= 18 && point.y + 35 <= nextLevel.height);
  }
});

test('missing traversal produces visible graph fallback text rather than an empty SVG', () => {
  const missing = analyzer.layoutTraversal(null, 99, 0);
  assert.equal(missing.nodes.length, 0);
  assert.match(missing.emptyMessage, /unavailable/i);
  const startMissing = analyzer.layoutTraversal({ visitedNodes: [], nodeDepths: {}, maxDepth: 4, discoveredEdges: [] }, 99, 0);
  assert.match(startMissing.emptyMessage, /selected company/i);
});

test('isolated traversal keeps its start node and provides a visible no-relationships explanation', () => {
  const traversal = analyzer.traverse(analyzer.buildGraph([{ id: 91, companyName: 'Isolated' }]), 91, 4);
  const layout = analyzer.layoutTraversal(traversal, 91, 0);
  assert.deepEqual(layout.nodes.map((node) => node.id), ['91']);
  assert.equal(layout.edges.length, 0);
  assert.match(layout.statusMessage, /no relationships/i);
  assert.match(fs.readFileSync(path.resolve(__dirname, '../../main/resources/static/js/app.js'), 'utf8'), /layout\.statusMessage/);
});

test('dense BFS levels remain legible by wrapping rows into horizontal lanes', () => {
  const denseCompanies = Array.from({ length: 30 }, (_, index) => ({ id: index + 1, companyName: `Peer ${index + 1}`, address: 'Same observable address' }));
  const traversal = analyzer.traverse(analyzer.buildGraph(denseCompanies), 1, 4);
  const layout = analyzer.layoutTraversal(traversal, 1, 1);
  assert.equal(layout.nodes.length, 30);
  assert.equal(layout.edges.length, 29);
  assert.ok(layout.height <= 400);
  for (const [key, point] of layout.positions) {
    const node = layout.nodes.find((candidate) => `${candidate.type}:${candidate.id}` === key);
    assert.ok(point.x - 52 >= 0 && point.x + 52 <= layout.width);
    assert.ok(point.y - 20 >= 0 && point.y + 35 <= layout.height);
    assert.ok(node);
  }
  assert.ok(layout.width > 640, 'overflow should scroll horizontally instead of shrinking node sizes');
});

test('graph deduplicates relationships and ignores unavailable or malformed references', () => {
  const rows = [...relationships, relationships[0], { company: null, director: { id: 99 } }];
  const graph = analyzer.buildGraph(companies, rows, []);
  assert.equal(graph.edges.filter((edge) => edge.type === 'company-director').length, 2);
  assert.equal(analyzer.traverse(graph, 999).visitedNodes.length, 0);
});

test('transactions traverse only from source toward destination', () => {
  const graph = analyzer.buildGraph(companies.map((company) => ({ ...company, address: `Unique ${company.id}` })), [], [{ id: 11, sourceCompany: { id: 1 }, destinationCompany: { id: 2 }, amount: 4 }]);
  assert.ok(analyzer.traverse(graph, 1).visitedCompanies.includes('2'));
  assert.deepEqual(analyzer.traverse(graph, 2).visitedCompanies, ['2']);
  assert.ok(graph.edges.filter((edge) => edge.type.startsWith('transaction-')).every((edge) => edge.directed));
});

test('fuzzy memberships have explicit boundaries and scores are deterministic', () => {
  assert.equal(analyzer.featureMemberships({ ageInYears: 2, annualRevenue: 0, numberOfEmployees: 2 }).ageRisk, 1);
  assert.equal(analyzer.featureMemberships({ ageInYears: 12 }).ageRisk, 0);
  assert.equal(analyzer.featureMemberships({ annualRevenue: 1000000, numberOfEmployees: 1 }).revenueRisk, 0.5);
  const one = analyzer.scoreCompany(companies[0], { sharedAddressCount: 0, sharedDirectorCount: 0, transactions: [] });
  assert.deepEqual(analyzer.scoreCompany(companies[0], { sharedAddressCount: 0, sharedDirectorCount: 0, transactions: [] }), one);
  assert.ok(one.riskScore >= 0 && one.riskScore <= 100);
  assert.ok(['Low', 'Medium', 'High'].includes(one.category));
  assert.equal(analyzer.scoreCompany({ ageInYears: 8, annualRevenue: 0, numberOfEmployees: 4 }).memberships.revenuePerEmployee, 0);
});

test('missing fields, zero revenue and unavailable relationships remain explicit', () => {
  const result = analyzer.scoreCompany({ ageInYears: null, annualRevenue: 0, numberOfEmployees: null }, { addressAvailable: false, directorsAvailable: false, transactionsAvailable: false });
  assert.equal(result.memberships.ageRisk, null);
  assert.equal(result.memberships.revenueRisk, null);
  assert.equal(result.memberships.revenuePerEmployee, null);
  assert.equal(result.memberships.sharedAddress, null);
  assert.equal(result.memberships.directorSharing, null);
  assert.equal(result.memberships.transactionContext, null);
  assert.equal(result.confidence.completeness, 0);
  assert.equal(result.riskScore, 50, 'no evidence produces a neutral score rather than a low-risk default');
  assert.equal(result.category, 'Medium');
  const partialNetwork = analyzer.scoreCompany({ ageInYears: 30, annualRevenue: 100000, numberOfEmployees: 10 }, {
    networkEvidence: { sharedAddressCompanyIds: [], sharedDirectorIds: [], addressAvailable: true, directorsAvailable: false },
    addressAvailable: true, directorsAvailable: false, transactionsAvailable: false,
  });
  assert.equal(partialNetwork.ruleEvidence.sharedResourceStrength, null, 'a missing director read is not converted to zero shared-director evidence');
});

test('address and director reuse share one evidence family instead of stacking', () => {
  const company = { id: 44, ageInYears: 8, annualRevenue: 9000000, numberOfEmployees: 10 };
  const address = analyzer.scoreCompany(company, { sharedAddressCount: 2, sharedDirectorCount: 0 });
  const director = analyzer.scoreCompany(company, { sharedAddressCount: 0, sharedDirectorCount: 2 });
  const both = analyzer.scoreCompany(company, { sharedAddressCount: 2, sharedDirectorCount: 2 });
  assert.equal(both.ruleEvidence.sharedResourceStrength, 1);
  assert.equal(both.riskScore, address.riskScore);
  assert.equal(both.riskScore, director.riskScore);
});

test('High fuzzy risk requires corroboration from independent feature families', () => {
  const onlyAge = analyzer.scoreCompany({ ageInYears: 1, annualRevenue: 100000, numberOfEmployees: 10 }, { sharedAddressCount: 0, sharedDirectorCount: 0 });
  const corroborated = analyzer.scoreCompany({ ageInYears: 1, annualRevenue: 100000, numberOfEmployees: 1 }, { sharedAddressCount: 2, sharedDirectorCount: 0 });
  assert.ok(onlyAge.ruleEvidence.independentFamilies < 2);
  assert.equal(onlyAge.ruleEvidence.independentFamilies < 2 ? onlyAge.ruleEvidence.sharedResourceStrength : null, 0);
  assert.ok(corroborated.ruleEvidence.independentFamilies >= 2);
  assert.equal(onlyAge.category, 'Low');
  assert.equal(analyzer.scoreCompany({ ageInYears: 30, annualRevenue: 20000000, numberOfEmployees: 10 }, { sharedAddressCount: 0, sharedDirectorCount: 0 }).category, 'Low');
  assert.equal(analyzer.scoreCompany({ ageInYears: 1, annualRevenue: 1600000, numberOfEmployees: 1 }, { sharedAddressCount: 2, sharedDirectorCount: 0 }).category, 'High');
});

test('ground-truth-like fields do not change scores and ties preserve input order', () => {
  const a = { ...companies[1], shellCompany: true, flagCorrect: true };
  const b = { ...companies[1], shellCompany: false, flagCorrect: false };
  assert.equal(analyzer.scoreCompany(a).riskScore, analyzer.scoreCompany(b).riskScore);
  const graphCompany = analyzer.buildGraph([a], [], []).nodes.get('company:2').company;
  assert.equal(Object.hasOwn(graphCompany, 'shellCompany'), false);
  const tied = analyzer.rankCompanies([{ ...companies[1], id: 22 }, { ...companies[1], id: 23 }]);
  assert.deepEqual(tied.map((item) => item.company.id), [22, 23]);
  const ranked = analyzer.rankCompanies(companies);
  assert.ok(ranked[0].riskScore >= ranked[ranked.length - 1].riskScore);
});

test('analyzeCompanies sends each company’s own bounded BFS evidence into fuzzy scoring before ranking', () => {
  const sameAttributes = [1, 2, 3].map((id) => ({ id, companyName: `Company ${id}`, address: `Unique ${id}`, ageInYears: 8, annualRevenue: 2000000, numberOfEmployees: 1 }));
  const sharedDirector = [
    { company: { id: 1, address: 'Unique 1' }, director: { id: 70, name: 'Director' } },
    { company: { id: 3, address: 'Unique 3' }, director: { id: 70, name: 'Director' } },
  ];
  const analyzed = analyzer.analyzeCompanies(sameAttributes, [...sharedDirector, sharedDirector[0]], [], { maxDepth: 4 });
  const linked = analyzed.ranked.find((item) => item.company.id === 1);
  const isolated = analyzed.ranked.find((item) => item.company.id === 2);
  assert.equal(analyzed.maxDepth, 4);
  assert.deepEqual(analyzed.networkEvidence['1'].sharedDirectorIds, ['70']);
  assert.equal(analyzed.networkEvidence['1'].multiHopCompanyCount, 1);
  assert.equal(analyzed.networkEvidence['1'].distinctNeighborCompanies, 1);
  assert.equal(analyzed.traversals['1'].discoveredEdges.filter((edge) => edge.type === 'company-director').length, 2);
  assert.equal(linked.memberships.directorSharing, 0.5);
  assert.equal(linked.ruleEvidence.sharedResourceStrength, 0.5);
  assert.ok(linked.riskScore > isolated.riskScore, 'the BFS-discovered shared director activates the grouped network family');
});

test('large network reach alone cannot activate the high fuzzy output', () => {
  const networkCompanies = Array.from({ length: 4 }, (_, index) => ({ id: index + 1, address: `Unique ${index}`, ageInYears: 30, annualRevenue: 100000, numberOfEmployees: 10 }));
  const directorRows = networkCompanies.map((company) => ({ company, director: { id: 81, name: 'Shared' } }));
  const analyzed = analyzer.analyzeCompanies(networkCompanies, directorRows, [], { maxDepth: 4 });
  const score = analyzed.ranked.find((item) => item.company.id === 1);
  assert.equal(analyzed.networkEvidence['1'].distinctNeighborCompanies, 3);
  assert.equal(score.ruleEvidence.independentFamilies, 1);
  assert.notEqual(score.category, 'High');
});

test('dashboard integration stays separate from gameplay and avoids directory labels', () => {
  const root = path.resolve(__dirname, '../../main/resources/static');
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const app = fs.readFileSync(path.join(root, 'js/app.js'), 'utf8');
  assert.match(html, /id="shellRiskAnalyzer"/);
  assert.match(html, /BFS \+ Fuzzy Logic/);
  assert.match(html, /Shell Company Detection Using BFS and Fuzzy Logic/);
  assert.match(html, /Ranked Results/);
  assert.match(html, /js\/risk-analyzer\.js/);
  assert.match(html, /risk-analyzer\.js\?v=bfs-fuzzy-3/);
  assert.match(html, /app\.js\?v=session-clear-2/);
  assert.match(html, /style\.css\?v=dashboard-clear-1/);
  assert.match(app, /api\('\/api\/companies'\)/);
  assert.match(app, /api\('\/api\/transactions'\)/);
  assert.match(app, /api\(`\/api\/company-directors\/company\/\$\{company\.id\}`\)/);
  assert.match(app, /ShellRiskAnalyzer\.analyzeCompanies\(risk\.companies, risk\.relationships, risk\.transactions/);
  assert.match(app, /layout\.edges\.forEach/);
  assert.match(app, /riskTraversalPlay/);
  assert.match(app, /riskTraversalStep/);
  assert.match(app, /riskGraph/);
  assert.match(app, /createElementNS\(svgNs/);
  assert.match(app, /setAttribute\('width'/);
  assert.match(app, /setAttribute\('height'/);
  assert.match(app, /layoutTraversal\(traversal, companyId/);
  assert.doesNotMatch(app, /riskGraph'\)\.innerHTML/);
  assert.doesNotMatch(app.slice(app.indexOf('async function loadRiskAnalyzer'), app.indexOf('async function loadData')), /companies\/directory|shellCompany|flagCorrect/);
  assert.match(html, /id="runLearnedAgents"/);
  assert.match(html, /id="investigatorForm"/);
});
