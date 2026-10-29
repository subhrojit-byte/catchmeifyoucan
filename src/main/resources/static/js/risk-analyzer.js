(function (root, factory) {
  const analyzer = factory();
  if (typeof module === 'object' && module.exports) module.exports = analyzer;
  else root.ShellRiskAnalyzer = analyzer;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const MAX_DEPTH = 4;
  // Observable memberships: age risk ramps 1→0 from 2→12 years; revenue-per-employee risk ramps 0→1 from ₹500k→₹1.5m; shared resources saturate at two linked companies/directors. Output sets are Low shoulder 15–55, Medium triangle 20/50/80, High shoulder 55–85, evaluated at integer scores 0–100.
  const number = (value) => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  const id = (value) => value === null || value === undefined ? null : String(value);
  const addressKey = (value) => String(value || '').normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const nodeKey = (type, value) => `${type}:${id(value)}`;
  const safeCompany = (company) => company && ({ id: company.id, companyName: company.companyName, name: company.name, address: company.address, industry: company.industry, registrationNumber: company.registrationNumber, ageInYears: company.ageInYears, registrationDate: company.registrationDate, annualRevenue: company.annualRevenue, numberOfEmployees: company.numberOfEmployees });

  function buildGraph(companies = [], relationships = [], transactions = []) {
    const nodes = new Map(), edges = new Map(), byAddress = new Map();
    const addNode = (type, key, data = {}) => { if (key === null) return null; const nodeId = String(key); const keyValue = nodeKey(type, nodeId); if (!nodes.has(keyValue)) nodes.set(keyValue, { type, id: nodeId, ...data }); return keyValue; };
    const addEdge = (from, to, type, data = {}, directed = false) => {
      if (!from || !to || from === to) return;
      const key = `${from}|${directed ? '>' : '-'}|${to}|${type}|${data.id ?? ''}`;
      if (edges.has(key)) return;
      const edge = { from, to, type, directed, ...data }; edges.set(key, edge);
    };
    for (const company of Array.isArray(companies) ? companies : []) {
      if (id(company?.id) === null) continue;
      const key = addNode('company', company.id, { company: safeCompany(company) });
      const address = addressKey(company.address);
      if (address) { if (!byAddress.has(address)) byAddress.set(address, []); byAddress.get(address).push(key); }
    }
    for (const group of byAddress.values()) {
      for (let i = 0; i < group.length; i++) for (let j = i + 1; j < group.length; j++) addEdge(group[i], group[j], 'shared-address');
    }
    for (const relation of Array.isArray(relationships) ? relationships : []) {
      const company = relation?.company, director = relation?.director;
      if (id(company?.id) === null || id(director?.id) === null) continue;
      const companyNode = addNode('company', company.id, { company: safeCompany(company) });
      const directorNode = addNode('director', director.id, { director: { id: director.id, name: director.name } });
      addEdge(companyNode, directorNode, 'company-director');
    }
    for (const transaction of Array.isArray(transactions) ? transactions : []) {
      const source = transaction?.sourceCompany, destination = transaction?.destinationCompany;
      if (id(source?.id) === null || id(destination?.id) === null) continue;
      const sourceNode = addNode('company', source.id, { company: safeCompany(source) });
      const destinationNode = addNode('company', destination.id, { company: safeCompany(destination) });
      const transactionNode = addNode('transaction', transaction.id ?? `${source.id}-${destination.id}-${transaction.timestamp ?? ''}`, { transaction: { id: transaction.id, amount: transaction.amount, channel: transaction.channel, timestamp: transaction.timestamp } });
      addEdge(sourceNode, transactionNode, 'transaction-source', { transactionId: transaction.id }, true);
      addEdge(transactionNode, destinationNode, 'transaction-destination', { transactionId: transaction.id }, true);
    }
    const edgeList = [...edges.values()], adjacency = new Map([...nodes.keys()].map((key) => [key, []]));
    for (const edge of edgeList) {
      adjacency.get(edge.from)?.push({ edge, next: edge.to });
      if (!edge.directed) adjacency.get(edge.to)?.push({ edge, next: edge.from });
    }
    return { nodes, edges: edgeList, adjacency };
  }

  function traverse(graph, startCompanyId, maxDepth = MAX_DEPTH) {
    const start = nodeKey('company', startCompanyId), visited = new Set(), visitedCompanies = new Set(), paths = [], queue = [], discoveredEdges = new Map(), nodeDepths = {};
    if (!graph.nodes.has(start)) return { paths, visitedCompanies: [], visitedNodes: [], discoveredEdges: [], nodeDepths, maxDepth };
    queue.push({ key: start, depth: 0, path: [] });
    while (queue.length) {
      const current = queue.shift();
      if (visited.has(current.key)) continue;
      visited.add(current.key);
      nodeDepths[current.key] = current.depth;
      const node = graph.nodes.get(current.key);
      if (node?.type === 'company') visitedCompanies.add(node.id);
      if (current.path.length) paths.push({ node: node.type, nodeId: node.id, depth: current.depth, relationships: current.path.map((edge) => edge.type), path: [start, ...current.path.map((edge) => edge.to)] });
      if (current.depth >= Math.max(0, Number(maxDepth) || 0)) continue;
      for (const { edge, next } of graph.adjacency?.get(current.key) || []) {
        const edgeKey = `${edge.from}|${edge.directed ? '>' : '-'}|${edge.to}|${edge.type}|${edge.transactionId ?? ''}`;
        if (!discoveredEdges.has(edgeKey)) discoveredEdges.set(edgeKey, { ...edge, depth: current.depth + 1 });
        if (visited.has(next)) continue;
        queue.push({ key: next, depth: current.depth + 1, path: [...current.path, { ...edge, to: next }] });
      }
    }
    return { paths, visitedCompanies: [...visitedCompanies], visitedNodes: [...visited].map((key) => graph.nodes.get(key)), discoveredEdges: [...discoveredEdges.values()], nodeDepths, maxDepth };
  }

  function layoutTraversal(traversal, startCompanyId, currentDepth = 0) {
    if (!traversal || !Array.isArray(traversal.visitedNodes) || !traversal.nodeDepths) {
      return { width: 640, height: 100, depth: 0, nodes: [], edges: [], positions: new Map(), emptyMessage: 'BFS traversal data is unavailable.' };
    }
    const maxDepth = Math.max(0, Number(traversal.maxDepth) || 0);
    const depth = Math.max(0, Math.min(maxDepth, Number(currentDepth) || 0));
    const root = traversal.visitedNodes.find((node) => node.type === 'company' && String(node.id) === String(startCompanyId));
    if (!root) return { width: 640, height: 100, depth, nodes: [], edges: [], positions: new Map(), emptyMessage: 'The selected company is missing from the BFS traversal.' };
    const nodeDepth = (node) => traversal.nodeDepths[`${node.type}:${node.id}`];
    const nodes = traversal.visitedNodes.filter((node) => Number.isFinite(Number(nodeDepth(node))) && Number(nodeDepth(node)) <= depth);
    if (!nodes.includes(root)) nodes.unshift(root);
    const levels = new Map();
    nodes.forEach((node) => {
      const level = Number(nodeDepth(node)) || 0;
      if (!levels.has(level)) levels.set(level, []);
      levels.get(level).push(node);
    });
    const rowsPerLane = 5;
    const height = Math.max(220, ...[...levels.values()].map((levelNodes) => Math.min(rowsPerLane, levelNodes.length) * 68 + 60));
    const positions = new Map();
    let xOffset = 70;
    [...levels.entries()].sort(([a], [b]) => a - b).forEach(([, levelNodes]) => {
      const laneCount = Math.ceil(levelNodes.length / rowsPerLane);
      levelNodes.forEach((node, index) => {
        const lane = Math.floor(index / rowsPerLane), row = index % rowsPerLane;
        positions.set(`${node.type}:${node.id}`, { x: xOffset + lane * 145, y: 35 + row * 68 });
      });
      xOffset += laneCount * 145 + 55;
    });
    const width = Math.max(300, xOffset + 60);
    const seenEdges = new Set();
    const edges = (Array.isArray(traversal.discoveredEdges) ? traversal.discoveredEdges : []).filter((edge) => {
      const key = `${edge.from}|${edge.to}|${edge.type}|${edge.transactionId ?? ''}`;
      if (seenEdges.has(key) || Number(edge.depth) > depth || !positions.has(edge.from) || !positions.has(edge.to)) return false;
      seenEdges.add(key);
      return true;
    });
    const onlyStartNode = traversal.visitedNodes.length === 1 && traversal.discoveredEdges.length === 0;
    return { width, height, depth, nodes, edges, positions, nodeDepth, emptyMessage: nodes.length ? null : 'No BFS nodes were found.', statusMessage: onlyStartNode ? 'No relationships were found in the available observable data.' : null };
  }

  function deriveNetworkEvidence(graph, traversal, startCompanyId) {
    const start = nodeKey('company', startCompanyId);
    const addressNeighbors = new Set(), directorIds = new Set(), directorNeighbors = new Set();
    const discovered = traversal?.discoveredEdges || [];
    for (const edge of discovered) {
      if (edge.type === 'shared-address' && (edge.from === start || edge.to === start)) {
        addressNeighbors.add(graph.nodes.get(edge.from === start ? edge.to : edge.from)?.id);
      }
      if (edge.type === 'company-director') {
        if (edge.from === start || edge.to === start) {
          const directorKey = edge.from === start ? edge.to : edge.from;
          const director = graph.nodes.get(directorKey);
          if (director?.type === 'director') directorIds.add(director.id);
        }
      }
    }
    for (const edge of discovered) {
      if (edge.type !== 'company-director') continue;
      const directorKey = graph.nodes.get(edge.from)?.type === 'director' ? edge.from
        : graph.nodes.get(edge.to)?.type === 'director' ? edge.to : null;
      if (!directorKey || !directorIds.has(graph.nodes.get(directorKey)?.id)) continue;
      const otherKey = edge.from === directorKey ? edge.to : edge.from;
      const other = graph.nodes.get(otherKey);
      if (other?.type === 'company' && otherKey !== start) directorNeighbors.add(other.id);
    }
    const sharedDirectorIds = new Set();
    for (const directorId of directorIds) {
      const key = nodeKey('director', directorId);
      if (discovered.some((edge) => edge.type === 'company-director' && (edge.from === key || edge.to === key)
        && (edge.from === start || edge.to === start))) {
        const hasOtherCompany = discovered.some((edge) => edge.type === 'company-director'
          && (edge.from === key || edge.to === key)
          && graph.nodes.get(edge.from === key ? edge.to : edge.from)?.type === 'company'
          && (edge.from === key ? edge.to : edge.from) !== start);
        if (hasOtherCompany) sharedDirectorIds.add(directorId);
      }
    }
    const multiHopCompanies = new Set((traversal?.paths || [])
      .filter((path) => path.node === 'company' && path.depth >= 2).map((path) => String(path.nodeId)));
    const transactions = (traversal?.visitedNodes || []).filter((node) => node.type === 'transaction').map((node) => node.transaction);
    const sharedAddressCount = addressNeighbors.size;
    const sharedDirectorCount = sharedDirectorIds.size;
    const resourceStrength = Math.max(Math.min(1, sharedAddressCount / 2), Math.min(1, sharedDirectorCount / 2));
    return {
      distinctNeighborCompanies: Math.max(0, (traversal?.visitedCompanies || []).filter((companyId) => String(companyId) !== String(startCompanyId)).length),
      sharedAddressCompanyIds: [...addressNeighbors].filter((value) => value !== undefined),
      sharedDirectorIds: [...sharedDirectorIds],
      sharedDirectorNeighborCompanyIds: [...directorNeighbors],
      multiHopCompanyIds: [...multiHopCompanies],
      multiHopCompanyCount: multiHopCompanies.size,
      transactionCount: transactions.length,
      transactions,
      resourceStrength,
    };
  }

  // Left/right shoulder and triangular memberships use linear ramps at documented breakpoints.
  const rampDown = (x, full, zero) => Math.max(0, Math.min(1, (zero - x) / (zero - full)));
  const rampUp = (x, zero, full) => Math.max(0, Math.min(1, (x - zero) / (full - zero)));
  const triangle = (x, left, peak, right) => x <= left || x >= right ? 0 : x === peak ? 1 : x < peak ? (x - left) / (peak - left) : (right - x) / (right - peak);
  function featureMemberships(company, relationshipData = {}) {
    const age = number(company?.ageInYears), revenue = number(company?.annualRevenue), employees = number(company?.numberOfEmployees);
    const ageRisk = age === null ? null : rampDown(age, 2, 12);
    const ratio = revenue !== null && employees !== null && employees > 0 ? revenue / employees : null;
    // Generator ranges overlap; this is a weak observable signal with broad ramps.
    const revenueRisk = ratio === null ? null : rampUp(ratio, 500000, 1500000);
    const network = relationshipData.networkEvidence || null;
    const addressCount = network ? network.sharedAddressCompanyIds.length : relationshipData.sharedAddressCount;
    const directorCount = network ? network.sharedDirectorIds.length : relationshipData.sharedDirectorCount;
    const address = relationshipData.addressAvailable === false ? null : number(addressCount) === null ? null : Math.min(1, addressCount / 2);
    const director = relationshipData.directorsAvailable === false ? null : number(directorCount) === null ? null : Math.min(1, directorCount / 2);
    const transactions = relationshipData.transactionsAvailable === false ? null : Array.isArray(relationshipData.transactions) ? relationshipData.transactions : null;
    let transactionContext = null;
    if (transactions) {
      const amounts = transactions.map((t) => number(t.amount)).filter((x) => x !== null && x >= 0);
      const totalAmount = amounts.reduce((sum, amount) => sum + amount, 0);
      const annualRevenue = number(company?.annualRevenue);
      transactionContext = { count: amounts.length, totalAmount, revenueRatio: annualRevenue > 0 ? totalAmount / annualRevenue : null, available: true };
    }
    const resourceEvidenceComplete = network
      ? network.addressAvailable !== false && network.directorsAvailable !== false
      : address !== null && director !== null;
    const knownResourceSignals = [address, director].filter((value) => value !== null);
    const knownResourceStrength = knownResourceSignals.length ? Math.max(...knownResourceSignals) : null;
    // A partial family can contribute observed positive evidence, but missing components never become assumed zeros.
    const resourceEvidenceStrength = resourceEvidenceComplete || (knownResourceStrength !== null && knownResourceStrength > 0)
      ? knownResourceStrength : null;
    return { ageRisk, revenuePerEmployee: ratio, revenueRisk, sharedAddress: address, directorSharing: director, networkEvidence: network, resourceEvidenceComplete, resourceEvidenceStrength, transactionContext };
  }

  function scoreCompany(company, relationshipData = {}) {
    const signals = featureMemberships(company, relationshipData);
    const availableWeight = [signals.ageRisk === null ? 0 : 1, signals.revenueRisk === null ? 0 : 1,
      signals.resourceEvidenceStrength === null ? 0 : signals.resourceEvidenceComplete ? 1 : 0.5,
      signals.transactionContext?.available ? 1 : 0].reduce((sum, weight) => sum + weight, 0);
    const resource = signals.resourceEvidenceStrength;
    const families = [signals.ageRisk, signals.revenueRisk, resource].filter((v) => v !== null);
    // Mamdani rules: weak single-family evidence is low/medium; High requires two independent families.
    const independent = families.filter((v) => v >= 0.5).length;
    const low = families.length ? Math.max(0.15, ...families.map((v) => 1 - v)) : 0;
    const medium = families.length ? Math.max(...families.map((v) => triangle(v, 0.15, 0.55, 0.95))) : 0;
    const highEvidence = independent >= 2 ? Math.min(...families.filter((v) => v >= 0.5).slice(0, 2)) : 0;
    const high = highEvidence;
    // Centroid of the max-aggregated output sets on the 0..100 universe.
    let weighted = 0, area = 0;
    for (let x = 0; x <= 100; x++) {
      const degree = Math.max(Math.min(low, rampDown(x, 15, 55)), Math.min(medium, triangle(x, 20, 50, 80)), Math.min(high, rampUp(x, 55, 85)));
      weighted += x * degree; area += degree;
    }
    const riskScore = area ? Math.round(weighted / area) : 50;
    const category = riskScore < 35 ? 'Low' : riskScore < 65 ? 'Medium' : 'High';
    const signalsText = [];
    if (signals.ageRisk !== null && signals.ageRisk >= 0.25) signalsText.push(`Relatively young (${number(company.ageInYears)} years)`);
    if (signals.revenueRisk !== null && signals.revenueRisk >= 0.25) signalsText.push('High revenue per employee');
    if (resource !== null && resource >= 0.25) signalsText.push(`Shared resources: ${signals.sharedAddress ? 'address' : ''}${signals.sharedAddress && signals.directorSharing ? ' and ' : ''}${signals.directorSharing ? 'director' : ''}`);
    if (signals.transactionContext?.available) signalsText.push(`${signals.transactionContext.count} transaction records in context${signals.transactionContext.revenueRatio === null ? '' : `; observed transaction amount-to-revenue context ${Math.round(signals.transactionContext.revenueRatio * 10000) / 100}%`}; ratio is not class-specific`);
    const completeness = Math.round((availableWeight / 4) * 100);
    return { riskScore, category, signals: signalsText.length ? signalsText : [availableWeight ? 'No elevated observable signals' : 'Observable evidence unavailable'], memberships: signals, confidence: { completeness, label: completeness >= 75 ? 'Higher' : completeness >= 50 ? 'Moderate' : 'Limited', availableFeatures: availableWeight, totalFeatures: 4 }, ruleEvidence: { independentFamilies: independent, sharedResourceStrength: resource } };
  }

  function rankCompanies(companies, relationshipData = {}) {
    return (Array.isArray(companies) ? companies : []).map((company, index) => ({ company, ...scoreCompany(company, relationshipData[String(company.id)] || {}), originalIndex: index }))
      .sort((a, b) => b.riskScore - a.riskScore || a.originalIndex - b.originalIndex);
  }

  function analyzeCompanies(companies = [], relationships = [], transactions = [], options = {}) {
    const maxDepth = options.maxDepth ?? MAX_DEPTH;
    const graph = buildGraph(companies, relationships, transactions);
    const traversals = {}, networkEvidence = {}, relationshipData = {};
    for (const company of Array.isArray(companies) ? companies : []) {
      if (id(company?.id) === null) continue;
      const traversal = traverse(graph, company.id, maxDepth);
      const evidence = deriveNetworkEvidence(graph, traversal, company.id);
      const key = String(company.id);
      traversals[key] = traversal;
      networkEvidence[key] = evidence;
      relationshipData[key] = {
        networkEvidence: evidence,
        addressAvailable: options.addressAvailable !== false && Boolean(company.address && addressKey(company.address)),
        directorsAvailable: options.directorsAvailable !== false,
        transactionsAvailable: options.transactionsAvailable !== false,
        transactions: evidence.transactions,
      };
      evidence.addressAvailable = relationshipData[key].addressAvailable;
      evidence.directorsAvailable = relationshipData[key].directorsAvailable;
      const addressStrength = evidence.addressAvailable ? Math.min(1, evidence.sharedAddressCompanyIds.length / 2) : null;
      const directorStrength = evidence.directorsAvailable ? Math.min(1, evidence.sharedDirectorIds.length / 2) : null;
      const knownStrengths = [addressStrength, directorStrength].filter((value) => value !== null);
      evidence.resourceStrength = knownStrengths.length && (evidence.addressAvailable && evidence.directorsAvailable || knownStrengths.some((value) => value > 0))
        ? Math.max(...knownStrengths) : null;
    }
    return { graph, traversals, networkEvidence, ranked: rankCompanies(companies, relationshipData), maxDepth };
  }

  return { MAX_DEPTH, buildGraph, traverse, layoutTraversal, deriveNetworkEvidence, featureMemberships, scoreCompany, rankCompanies, analyzeCompanies, addressKey };
});
