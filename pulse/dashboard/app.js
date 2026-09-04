// PULSE Real-time Dashboard Client

let ws = null;
let reconnectTimer = null;
let transactionHistory = [];
let auditHistory = [];

const API_BASE = window.location.origin;

// Initialize on page load
window.addEventListener('DOMContentLoaded', () => {
  connectWebSocket();
  fetchInitialData();
});

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

  const wsStatus = document.getElementById('ws-status');
  const wsText = document.getElementById('ws-text');

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      wsStatus.style.borderColor = 'rgba(16, 185, 129, 0.4)';
      wsText.textContent = 'LIVE WEBSOCKET: 100ms';
      if (reconnectTimer) {
        clearInterval(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        renderDashboard(payload);
      } catch (e) {
        console.error('Error parsing telemetry frame:', e);
      }
    };

    ws.onclose = () => {
      wsStatus.style.borderColor = 'rgba(239, 68, 68, 0.4)';
      wsText.textContent = 'DISCONNECTED (RETRYING...)';
      if (!reconnectTimer) {
        reconnectTimer = setInterval(connectWebSocket, 2000);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch (err) {
    console.error('WebSocket connection failed:', err);
    if (!reconnectTimer) {
      reconnectTimer = setInterval(connectWebSocket, 2000);
    }
  }
}

function fetchInitialData() {
  fetch(`${API_BASE}/api/v1/routes`)
    .then(r => r.json())
    .then(renderRoutes)
    .catch(() => {});
}

function renderDashboard(data) {
  const { system_state, operating_mode, snapshot, canary_state, active_incident } = data;

  // 1. System State Badge
  const stateBadge = document.getElementById('system-state-badge');
  const fsmStateText = document.getElementById('fsm-state');
  fsmStateText.textContent = system_state;

  stateBadge.className = 'fsm-badge';
  if (['DEGRADED', 'ROLLED_BACK'].includes(system_state)) {
    stateBadge.classList.add('degraded');
  } else if (['CANARY', 'DIAGNOSING', 'EVALUATING'].includes(system_state)) {
    stateBadge.classList.add('canary');
  }

  // 2. Operating Mode Buttons
  ['observe', 'assisted', 'autonomous'].forEach(m => {
    const btn = document.getElementById(`btn-mode-${m}`);
    if (btn) {
      if (m.toUpperCase() === operating_mode) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    }
  });

  // 3. Top KPI Cards
  if (snapshot) {
    const sr = (snapshot.success_rate * 100).toFixed(1);
    document.getElementById('val-sr').textContent = `${sr}%`;

    if (snapshot.success_rate_ci) {
      const low = (snapshot.success_rate_ci.lower * 100).toFixed(1);
      const high = (snapshot.success_rate_ci.upper * 100).toFixed(1);
      document.getElementById('val-wilson').textContent = `95% CI: [${low}% – ${high}%]`;
    }

    const p95 = snapshot.latency ? Math.round(snapshot.latency.p95_ms) : 0;
    const timeoutRate = (snapshot.timeout_rate * 100).toFixed(1);
    document.getElementById('val-latency').textContent = `${p95}ms`;
    document.getElementById('val-timeouts').textContent = `Timeout Rate: ${timeoutRate}%`;

    // Render Routes
    if (snapshot.route_health) {
      renderRouteHealth(snapshot.route_health);
    }
  }

  // 4. Revenue Accountant & Exposure
  if (active_incident) {
    const risk = Math.round(active_incident.revenue_at_risk_inr || 0);
    const recovered = Math.round(active_incident.recovered_revenue_inr || 0);
    document.getElementById('val-risk').textContent = `₹${risk.toLocaleString('en-IN')}`;
    document.getElementById('val-projections').textContent = `1h: ₹${(risk * 12).toLocaleString('en-IN')} | 24h: ₹${(risk * 288).toLocaleString('en-IN')}`;
    document.getElementById('val-recovered').textContent = `₹${recovered.toLocaleString('en-IN')}`;
  } else {
    document.getElementById('val-risk').textContent = '₹0';
    document.getElementById('val-projections').textContent = '1h: ₹0 | 24h: ₹0';
  }

  // 5. Canary Safety Controller
  renderCanary(canary_state);

  // 6. AI Doctor Diagnosis
  renderDoctor(active_incident);
}

function renderRoutes(routes) {
  const container = document.getElementById('routes-grid');
  if (!container) return;
  container.innerHTML = '';

  routes.forEach(route => {
    const card = document.createElement('div');
    card.className = 'route-card';
    card.id = `route-${route.route_id}`;

    const health = route.health || {};
    const status = health.status || 'ACTIVE';
    const sr = health.success_rate ? (health.success_rate * 100).toFixed(1) + '%' : '99.2%';
    const p95 = health.p95_latency_ms ? Math.round(health.p95_latency_ms) + 'ms' : '140ms';

    card.innerHTML = `
      <div class="route-header">
        <span class="route-name">${route.name}</span>
        <span class="route-pill ${status}" id="status-${route.route_id}">${status}</span>
      </div>
      <div class="route-stats">
        <div>
          <div class="stat-label">SUCCESS RATE</div>
          <div class="stat-val" id="sr-${route.route_id}">${sr}</div>
        </div>
        <div>
          <div class="stat-label">p95 LATENCY</div>
          <div class="stat-val" id="lat-${route.route_id}">${p95}</div>
        </div>
        <div>
          <div class="stat-label">FEE</div>
          <div class="stat-val">₹${route.cost_per_txn_inr}/txn</div>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderRouteHealth(routeHealthMap) {
  Object.keys(routeHealthMap).forEach(routeId => {
    const health = routeHealthMap[routeId];
    const statusEl = document.getElementById(`status-${routeId}`);
    const srEl = document.getElementById(`sr-${routeId}`);
    const latEl = document.getElementById(`lat-${routeId}`);

    if (statusEl) {
      statusEl.className = `route-pill ${health.status}`;
      statusEl.textContent = health.status;
    }
    if (srEl) srEl.textContent = `${(health.success_rate * 100).toFixed(1)}%`;
    if (latEl) latEl.textContent = `${Math.round(health.p95_latency_ms)}ms`;
  });
}

function renderCanary(canaryState) {
  const primaryBar = document.getElementById('split-primary');
  const candidateBar = document.getElementById('split-candidate');
  const primaryLabel = document.getElementById('split-primary-label');
  const candidateLabel = document.getElementById('split-candidate-label');
  const statusBadge = document.getElementById('canary-status-badge');

  if (!canaryState) {
    primaryBar.style.width = '100%';
    candidateBar.style.width = '0%';
    primaryLabel.textContent = 'Normal Routing (100%)';
    candidateLabel.textContent = '';
    statusBadge.textContent = 'STANDBY';
    statusBadge.className = 'badge';
    resetGates();
    return;
  }

  const candidatePct = canaryState.current_traffic_percentage;
  const primaryPct = 100 - candidatePct;

  primaryBar.style.width = `${primaryPct}%`;
  candidateBar.style.width = `${candidatePct}%`;
  primaryLabel.textContent = `Fallback (${primaryPct}%)`;
  candidateLabel.textContent = `Canary ${canaryState.target_route_id} (${candidatePct}%)`;

  statusBadge.textContent = `STAGE ${canaryState.stage_index}: ${candidatePct}%`;
  statusBadge.className = 'badge badge-canary';

  // Render Gate evaluation badges
  const gates = canaryState.gates_evaluated || {};
  Object.keys(gates).forEach(gateKey => {
    const passed = gates[gateKey];
    const el = document.getElementById(`gate-${gateKey.toLowerCase()}`);
    const valEl = document.getElementById(`gate-${gateKey.toLowerCase()}-val`);
    if (el && valEl) {
      el.className = `gate-card ${passed ? 'passed' : 'failed'}`;
      valEl.textContent = passed ? 'PASSED ✓' : 'BREACH ✗';
    }
  });
}

function resetGates() {
  ['sample', 'sr', 'wilson', 'lat', 'er'].forEach(g => {
    const el = document.getElementById(`gate-${g}`);
    const val = document.getElementById(`gate-${g}-val`);
    if (el) el.className = 'gate-card';
    if (val) val.textContent = 'Standby';
  });
}

function renderDoctor(incident) {
  const title = document.getElementById('diag-title');
  const confVal = document.getElementById('diag-conf-val');
  const confFill = document.getElementById('diag-conf-fill');
  const action = document.getElementById('diag-action');
  const exp = document.getElementById('diag-explanation');
  const precedentBox = document.getElementById('diag-precedent');
  const precedentText = document.getElementById('diag-precedent-text');
  const evidenceList = document.getElementById('evidence-items');

  if (!incident || incident.is_resolved) {
    title.textContent = 'SYSTEM NOMINAL — All routes operating within SLOs';
    confVal.textContent = '100%';
    confFill.style.width = '100%';
    action.textContent = 'NO_ACTION';
    exp.textContent = 'Statistical metrics indicate healthy payment throughput.';
    precedentBox.style.display = 'none';
    evidenceList.innerHTML = '<li class="evidence-item empty">No active degradation evidence</li>';
    return;
  }

  title.textContent = `INCIDENT DETECTED: ${incident.root_cause}`;
  const hyp = (incident.hypotheses && incident.hypotheses[0]) || {};
  const conf = Math.round((hyp.confidence_score || 0.95) * 100);
  confVal.textContent = `${conf}%`;
  confFill.style.width = `${conf}%`;

  const recAction = hyp.recommended_action || 'SPLIT_TRAFFIC_CANARY';
  action.textContent = recAction;
  exp.textContent = hyp.description || 'AI Doctor diagnosed active operational anomaly.';

  if (incident.historical_precedent) {
    precedentBox.style.display = 'block';
    precedentText.textContent = incident.historical_precedent;
  } else {
    precedentBox.style.display = 'none';
  }

  // Evidence
  if (hyp.supporting_evidence && hyp.supporting_evidence.length > 0) {
    evidenceList.innerHTML = '';
    hyp.supporting_evidence.forEach(evi => {
      const li = document.createElement('li');
      li.className = 'evidence-item';
      li.textContent = `${evi.metric_name}: observed ${evi.observed_value} (SLO limit: ${evi.threshold_value}) — ${evi.description}`;
      evidenceList.appendChild(li);
    });
  }
}

// Operating Mode Change
function setMode(mode) {
  fetch(`${API_BASE}/api/v1/control/mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: mode }),
  })
  .then(r => r.json())
  .then(res => {
    addAuditLog('OPERATOR', `Operating mode set to ${res.mode}`);
  })
  .catch(err => console.error('Failed to change mode:', err));
}

// Sandbox Scenario Injection
function injectScenario(scenario) {
  addAuditLog('SANDBOX', `Triggering scenario injection: ${scenario}`);

  fetch(`${API_BASE}/api/v1/simulate/scenario`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario: scenario, count: 35 }),
  })
  .then(r => r.json())
  .then(res => {
    addAuditLog('ANOMALY_DETECTOR', `Injected ${res.transactions_generated} test transactions for scenario ${scenario}`);
  })
  .catch(err => console.error('Scenario injection failed:', err));
}

function addAuditLog(actor, desc) {
  const container = document.getElementById('audit-log-list');
  if (!container) return;

  const now = new Date().toTimeString().split(' ')[0];
  const item = document.createElement('div');
  item.className = 'audit-item';
  item.innerHTML = `
    <span class="audit-time">${now}</span>
    <span class="audit-actor actor-system">${actor}</span>
    <span class="audit-desc">${desc}</span>
  `;
  container.prepend(item);
  if (container.children.length > 30) {
    container.removeChild(container.lastChild);
  }
}
