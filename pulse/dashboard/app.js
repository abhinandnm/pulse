// PULSE — Real-time Autonomous Reliability Dashboard Client
// Connects to WebSocket /ws/telemetry and updates the Gateway Cards & Swapping State

let ws = null;
let reconnectTimer = null;
const API_BASE = window.location.origin;

let currentSystemState = 'HEALTHY';
let currentCanaryState = null;
let currentQuarantines = {};
let currentPromotedRoute = null;
let currentActiveScenario = null;

window.addEventListener('DOMContentLoaded', () => {
  connectWebSocket();
});

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('Connected to PULSE telemetry stream');
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
      if (!reconnectTimer) {
        reconnectTimer = setInterval(connectWebSocket, 2000);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch (err) {
    if (!reconnectTimer) {
      reconnectTimer = setInterval(connectWebSocket, 2000);
    }
  }
}

function renderDashboard(data) {
  const {
    system_state,
    snapshot,
    canary_state,
    active_incident,
    latest_incident,
    quarantined_routes,
    promoted_route_id,
  } = data;

  currentSystemState = system_state;
  currentCanaryState = canary_state;
  currentQuarantines = quarantined_routes || {};
  currentPromotedRoute = promoted_route_id;

  // Calculate live countdown for quarantine
  const quarRec = currentQuarantines['psp_hdfc_direct'];
  let remainingSec = 0;
  if (quarRec && quarRec.quarantined_until) {
    remainingSec = Math.max(0, Math.round((new Date(quarRec.quarantined_until).getTime() - Date.now()) / 1000));
  }
  const isGw1Quarantined = Boolean(quarRec) && remainingSec > 0;

  const isCascading = currentPromotedRoute === 'psp_aggregator_fallback' || currentActiveScenario === 'CASCADING_OUTAGE';
  const isGw1Failing = (active_incident && !active_incident.is_resolved) || isGw1Quarantined || isCascading;
  const isPromotedGw2 = !isCascading && (currentPromotedRoute === 'psp_icici_backup' || currentSystemState === 'PROMOTED');
  const canaryPct = canary_state ? canary_state.current_traffic_percentage : (isPromotedGw2 || isCascading ? 100 : 0);
  const effectiveIncident = active_incident || (isPromotedGw2 || isCascading ? latest_incident : null);

  // 1. Top Header Health Status
  const healthBadge = document.getElementById('overall-health-badge');
  const healthText = document.getElementById('overall-status-text');
  if (healthBadge && healthText) {
    if (isCascading) {
      healthBadge.className = 'overall-health-badge restored';
      healthText.textContent = 'OVERALL HEALTH: CASCADING FAILOVER ACTIVE (ROUTED TO GATEWAY 3 AXIS)';
    } else if (isPromotedGw2) {
      healthBadge.className = 'overall-health-badge restored';
      healthText.textContent = 'OVERALL HEALTH: RESTORED (100% TRAFFIC TO GATEWAY 2)';
    } else if (canary_state) {
      healthBadge.className = 'overall-health-badge canary';
      healthText.textContent = `OVERALL HEALTH: AUTONOMOUS CANARY SWAP IN PROGRESS (${canaryPct}%)`;
    } else if (isGw1Quarantined) {
      healthBadge.className = 'overall-health-badge degraded';
      healthText.textContent = `OVERALL HEALTH: GATEWAY 1 IN CIRCUIT BREAKER QUARANTINE (${remainingSec}s REMAINING)`;
    } else if (isGw1Failing || currentSystemState === 'DEGRADED') {
      healthBadge.className = 'overall-health-badge degraded';
      healthText.textContent = 'OVERALL HEALTH: GATEWAY 1 DEGRADED — AI DOCTOR INTERVENING';
    } else {
      healthBadge.className = 'overall-health-badge';
      healthText.textContent = 'OVERALL HEALTH: HEALTHY';
    }
  }

  // 2. Middle Row: The 3 Gateway Cards (gate1, gate2, gate3)
  renderGateways(isGw1Failing, isGw1Quarantined, remainingSec, canaryPct, isPromotedGw2, isCascading, currentActiveScenario);

  // 3. Bottom Row: AI Doctor & Root Cause Verdict
  renderAIDoctor(effectiveIncident, canary_state, isPromotedGw2, isCascading, isGw1Quarantined, remainingSec);

  // 4. Bottom Row: Platform KPIs
  renderPlatformKPIs(snapshot, effectiveIncident, isPromotedGw2, isCascading);
}

function renderGateways(isGw1Failing, isGw1Quarantined, remainingSec, canaryPct, isPromotedGw2, isCascading, scenario) {
  // Gateway 1 (Primary - HDFC)
  const cardGw1 = document.getElementById('card-gw1');
  const statusGw1 = document.getElementById('status-gw1');
  const srGw1 = document.getElementById('sr-gw1');
  const wilsonGw1 = document.getElementById('wilson-gw1');
  const latGw1 = document.getElementById('lat-gw1');
  const errGw1 = document.getElementById('err-gw1');
  const consGw1 = document.getElementById('cons-gw1');
  const consIconGw1 = document.getElementById('cons-icon-gw1');
  const consMsgGw1 = document.getElementById('cons-msg-gw1');

  // Gateway 2 (Backup - ICICI)
  const cardGw2 = document.getElementById('card-gw2');
  const statusGw2 = document.getElementById('status-gw2');
  const srGw2 = document.getElementById('sr-gw2');
  const wilsonGw2 = document.getElementById('wilson-gw2');
  const latGw2 = document.getElementById('lat-gw2');
  const errGw2 = document.getElementById('err-gw2');
  const consGw2 = document.getElementById('cons-gw2');
  const consIconGw2 = document.getElementById('cons-icon-gw2');
  const consMsgGw2 = document.getElementById('cons-msg-gw2');

  // Gateway 3 (Aggregator Reserve - Axis)
  const cardGw3 = document.getElementById('card-gw3');
  const statusGw3 = document.getElementById('status-gw3');
  const srGw3 = document.getElementById('sr-gw3');
  const wilsonGw3 = document.getElementById('wilson-gw3');
  const latGw3 = document.getElementById('lat-gw3');
  const errGw3 = document.getElementById('err-gw3');
  const consGw3 = document.getElementById('cons-gw3');
  const consIconGw3 = document.getElementById('cons-icon-gw3');
  const consMsgGw3 = document.getElementById('cons-msg-gw3');

  if (isCascading) {
    // Cascading Failure: Gateways 1 and 2 are down, Gateway 3 is 100% PROMOTED
    if (cardGw1) cardGw1.className = 'gateway-card outage';
    if (statusGw1) {
      statusGw1.className = 'gw-active-pill degraded';
      statusGw1.textContent = 'OUTAGE (0% TRAFFIC)';
    }
    if (srGw1) srGw1.textContent = '22.4%';
    if (wilsonGw1) wilsonGw1.textContent = '[15.1% – 31.8%]';
    if (latGw1) latGw1.textContent = '5200ms';
    if (errGw1) errGw1.textContent = '77.6%';
    if (consGw1) consGw1.className = 'gw-cons-note danger';
    if (consIconGw1) consIconGw1.textContent = '❌';
    if (consMsgGw1) consMsgGw1.textContent = 'CRITICAL: Gateway 1 unresponsive. Saturated socket timeout.';

    if (cardGw2) cardGw2.className = 'gateway-card outage';
    if (statusGw2) {
      statusGw2.className = 'gw-active-pill degraded';
      statusGw2.textContent = 'OUTAGE (SATURATED)';
    }
    if (srGw2) srGw2.textContent = '31.6%';
    if (wilsonGw2) wilsonGw2.textContent = '[21.8% – 43.2%]';
    if (latGw2) latGw2.textContent = '4100ms';
    if (errGw2) errGw2.textContent = '68.4%';
    if (consGw2) consGw2.className = 'gw-cons-note danger';
    if (consIconGw2) consIconGw2.textContent = '❌';
    if (consMsgGw2) consMsgGw2.textContent = 'CRITICAL: Secondary switch saturated under failover load.';

    // Gateway 3 takes 100% of platform traffic
    if (cardGw3) cardGw3.className = 'gateway-card promoted';
    if (statusGw3) {
      statusGw3.className = 'gw-active-pill active';
      statusGw3.textContent = 'ACTIVE (100% PROMOTED)';
    }
    if (srGw3) srGw3.textContent = '97.8%';
    if (wilsonGw3) wilsonGw3.textContent = '[95.4% – 98.9%]';
    if (latGw3) latGw3.textContent = '165ms';
    if (errGw3) errGw3.textContent = '2.2%';
    if (consGw3) consGw3.className = 'gw-cons-note nominal';
    if (consIconGw3) consIconGw3.textContent = '🛡️';
    if (consMsgGw3) {
      consMsgGw3.textContent = 'TERTIARY FAILSAFE ENGAGED: Absorbing 100% of checkout volume. All banks healthy.';
    }

  } else if (isGw1Quarantined) {
    // Gateway 1 Quarantined by Circuit Breaker
    if (cardGw1) cardGw1.className = 'gateway-card quarantined';
    if (statusGw1) {
      statusGw1.className = 'gw-active-pill quarantined';
      statusGw1.textContent = `QUARANTINED (${remainingSec}s)`;
    }
    if (srGw1) srGw1.textContent = '44.8%';
    if (wilsonGw1) wilsonGw1.textContent = '[32.4% – 51.6%]';
    if (latGw1) latGw1.textContent = '4520ms';
    if (errGw1) errGw1.textContent = '55.2%';

    if (consGw1) consGw1.className = 'gw-cons-note danger';
    if (consIconGw1) consIconGw1.textContent = '🚫';
    if (consMsgGw1) {
      consMsgGw1.textContent = `Circuit breaker cooldown: ${remainingSec}s remaining. Once timer reaches 0s, it releases to STANDBY.`;
    }

    // Gateway 2 absorbs 100% traffic
    if (cardGw2) cardGw2.className = 'gateway-card promoted';
    if (statusGw2) {
      statusGw2.className = 'gw-active-pill active';
      statusGw2.textContent = 'ACTIVE (100% PROMOTED)';
    }
    if (srGw2) srGw2.textContent = '99.4%';
    if (latGw2) latGw2.textContent = '92ms';
    if (consGw2) consGw2.className = 'gw-cons-note nominal';
    if (consIconGw2) consIconGw2.textContent = '✓';
    if (consMsgGw2) {
      consMsgGw2.textContent = 'Healthy reserve promoted to primary rail while Gateway 1 is under quarantine.';
    }

    // Gateway 3 stays reserve
    resetGw3Nominal(cardGw3, statusGw3, srGw3, wilsonGw3, latGw3, errGw3, consGw3, consIconGw3, consMsgGw3);

  } else if (isGw1Failing && !isPromotedGw2) {
    // Gateway 1 Degrading / Failing
    if (cardGw1) cardGw1.className = 'gateway-card outage';
    if (statusGw1) {
      statusGw1.className = 'gw-active-pill degraded';
      statusGw1.textContent = scenario === 'BANK_DEGRADATION' ? 'OUTAGE (HTTP 500 SURGE)' : 'OUTAGE (HIGH TIMEOUTS)';
    }

    if (scenario === 'BANK_DEGRADATION') {
      if (srGw1) srGw1.textContent = '38.2%';
      if (wilsonGw1) wilsonGw1.textContent = '[28.1% – 48.9%]';
      if (latGw1) latGw1.textContent = '850ms';
      if (errGw1) errGw1.textContent = '61.8%';
      if (consMsgGw1) {
        consMsgGw1.textContent = 'CRITICAL: Core Banking System (CBS) degradation at issuer bank HDFC. HTTP 500 surge!';
      }
    } else {
      if (srGw1) srGw1.textContent = '44.8%';
      if (wilsonGw1) wilsonGw1.textContent = '[32.4% – 51.6%]';
      if (latGw1) latGw1.textContent = '4520ms';
      if (errGw1) errGw1.textContent = '55.2%';
      if (consMsgGw1) {
        consMsgGw1.textContent = 'CRITICAL: Upstream PSP Timeouts (4500ms+). Success rate plunged below 85% SLO!';
      }
    }

    if (consGw1) consGw1.className = 'gw-cons-note danger';
    if (consIconGw1) consIconGw1.textContent = '❌';

    // Gateway 2 in Canary
    if (cardGw2) cardGw2.className = 'gateway-card canary-active';
    if (statusGw2) {
      statusGw2.className = 'gw-active-pill canary';
      statusGw2.textContent = `CANARY (${canaryPct}% TRAFFIC)`;
    }
    if (srGw2) srGw2.textContent = '99.4%';
    if (latGw2) latGw2.textContent = '92ms';
    if (consGw2) consGw2.className = 'gw-cons-note nominal';
    if (consIconGw2) consIconGw2.textContent = '⚡';
    if (consMsgGw2) {
      consMsgGw2.textContent = `Canary probe active. Absorbing ${canaryPct}% traffic and verifying 5 safety gates.`;
    }

    resetGw3Nominal(cardGw3, statusGw3, srGw3, wilsonGw3, latGw3, errGw3, consGw3, consIconGw3, consMsgGw3);

  } else if (isPromotedGw2) {
    // Gateway 2 is Promoted to 100%
    if (cardGw1) cardGw1.className = 'gateway-card standby';
    if (statusGw1) {
      statusGw1.className = 'gw-active-pill standby';
      statusGw1.textContent = 'STANDBY (0% TRAFFIC)';
    }
    if (srGw1) srGw1.textContent = '98.2%';
    if (wilsonGw1) wilsonGw1.textContent = '[96.8% – 99.4%]';
    if (latGw1) latGw1.textContent = '125ms';
    if (errGw1) errGw1.textContent = '1.8%';
    if (consGw1) consGw1.className = 'gw-cons-note nominal';
    if (consIconGw1) consIconGw1.textContent = '✓';
    if (consMsgGw1) {
      consMsgGw1.textContent = 'Relegated to standby after autonomous candidate canary promotion.';
    }

    // Gateway 2 Active (100% Promoted)
    if (cardGw2) cardGw2.className = 'gateway-card promoted';
    if (statusGw2) {
      statusGw2.className = 'gw-active-pill active';
      statusGw2.textContent = 'ACTIVE (100% PROMOTED)';
    }
    if (srGw2) srGw2.textContent = '99.4%';
    if (wilsonGw2) wilsonGw2.textContent = '[98.5% – 99.9%]';
    if (latGw2) latGw2.textContent = '92ms';
    if (errGw2) errGw2.textContent = '0.6%';
    if (consGw2) consGw2.className = 'gw-cons-note nominal';
    if (consIconGw2) consIconGw2.textContent = '✓';
    if (consMsgGw2) {
      consMsgGw2.textContent = 'Autonomous promotion complete. Processing 100% of checkout traffic with 99.4% SR.';
    }

    resetGw3Nominal(cardGw3, statusGw3, srGw3, wilsonGw3, latGw3, errGw3, consGw3, consIconGw3, consMsgGw3);

  } else {
    // Baseline Healthy Normal: Gateway 1 is Active 100%, Gateway 2 & 3 are Standby
    if (cardGw1) cardGw1.className = 'gateway-card active-primary';
    if (statusGw1) {
      statusGw1.className = 'gw-active-pill active';
      statusGw1.textContent = 'ACTIVE (100% TRAFFIC)';
    }
    if (srGw1) srGw1.textContent = '98.2%';
    if (wilsonGw1) wilsonGw1.textContent = '[96.8% – 99.4%]';
    if (latGw1) latGw1.textContent = '125ms';
    if (errGw1) errGw1.textContent = '1.8%';
    if (consGw1) consGw1.className = 'gw-cons-note nominal';
    if (consIconGw1) consIconGw1.textContent = '✓';
    if (consMsgGw1) {
      consMsgGw1.textContent = 'All metrics nominal. Routing 100% of primary traffic.';
    }

    // Gateway 2 Standby
    if (cardGw2) cardGw2.className = 'gateway-card';
    if (statusGw2) {
      statusGw2.className = 'gw-active-pill standby';
      statusGw2.textContent = 'STANDBY (0% TRAFFIC)';
    }
    if (srGw2) srGw2.textContent = '99.4%';
    if (wilsonGw2) wilsonGw2.textContent = '[98.5% – 99.9%]';
    if (latGw2) latGw2.textContent = '92ms';
    if (errGw2) errGw2.textContent = '0.6%';
    if (consGw2) consGw2.className = 'gw-cons-note nominal';
    if (consIconGw2) consIconGw2.textContent = '✓';
    if (consMsgGw2) {
      consMsgGw2.textContent = 'Healthy reserve. Standby to absorb redirected traffic.';
    }

    resetGw3Nominal(cardGw3, statusGw3, srGw3, wilsonGw3, latGw3, errGw3, consGw3, consIconGw3, consMsgGw3);
  }
}

function resetGw3Nominal(cardGw3, statusGw3, srGw3, wilsonGw3, latGw3, errGw3, consGw3, consIconGw3, consMsgGw3) {
  if (cardGw3) cardGw3.className = 'gateway-card';
  if (statusGw3) {
    statusGw3.className = 'gw-active-pill standby';
    statusGw3.textContent = 'STANDBY (RESERVE)';
  }
  if (srGw3) srGw3.textContent = '96.8%';
  if (wilsonGw3) wilsonGw3.textContent = '[94.2% – 98.1%]';
  if (latGw3) latGw3.textContent = '175ms';
  if (errGw3) errGw3.textContent = '3.2%';
  if (consGw3) consGw3.className = 'gw-cons-note nominal';
  if (consIconGw3) consIconGw3.textContent = '✓';
  if (consMsgGw3) consMsgGw3.textContent = 'Tertiary failover aggregator online and on warm standby.';
}

function renderAIDoctor(incident, canaryState, isPromotedGw2, isCascading, isGw1Quarantined, remainingSec) {
  const diagTitle = document.getElementById('diag-title');
  const diagConfVal = document.getElementById('diag-conf-val');
  const diagAction = document.getElementById('diag-action');
  const diagExplanation = document.getElementById('diag-explanation');
  const swappingCard = document.getElementById('swapping-card');
  const swapStepTitle = document.getElementById('swap-step-title');
  const swapStepPct = document.getElementById('swap-step-pct');
  const swapBarFill = document.getElementById('swap-bar-fill');
  const quarantineBox = document.getElementById('quarantine-box');

  if (isCascading) {
    if (diagTitle) diagTitle.textContent = 'CASCADING FAILURE: Multi-Gateway Outage on Gates 1 & 2';
    if (diagConfVal) diagConfVal.textContent = '99%';
    if (diagAction) diagAction.textContent = '100% PROMOTED ➔ Gateway 3 (Axis Resilient Fallback)';
    if (diagExplanation) {
      diagExplanation.textContent =
        'Both primary rail (HDFC) and secondary switch (ICICI) breached SLO safety limits. Counterfactual Engine engaged tertiary global aggregator to protect checkout volume.';
    }
    if (swappingCard) {
      swappingCard.style.display = 'block';
      if (swapStepPct) swapStepPct.textContent = '100%';
      if (swapBarFill) swapBarFill.style.width = '100%';
      if (swapStepTitle) swapStepTitle.textContent = 'Tertiary Failover Active (100% Promoted to Gateway 3):';
    }
    if (quarantineBox) quarantineBox.style.display = 'none';
    return;
  }

  if (isGw1Quarantined) {
    if (diagTitle) diagTitle.textContent = 'CIRCUIT BREAKER: Route Flapping Detected on Gateway 1';
    if (diagConfVal) diagConfVal.textContent = '99%';
    if (diagAction) diagAction.textContent = 'QUARANTINE_ROUTE ➔ Failover to Gateway 2';
    if (diagExplanation) {
      diagExplanation.textContent =
        `Anti-flapping controller detected oscillatory status flips. Autonomous circuit breaker locked Gateway 1 into quarantine cooldown (${remainingSec}s remaining).`;
    }
    if (swappingCard) swappingCard.style.display = 'none';
    if (quarantineBox) {
      quarantineBox.style.display = 'block';
      const quarantineMsg = document.getElementById('quarantine-msg');
      if (quarantineMsg) {
        quarantineMsg.textContent = `Gateway 1 placed in quarantine cooldown (${remainingSec}s remaining). Automatically releases to STANDBY once expired.`;
      }
    }
    return;
  }

  if (isPromotedGw2) {
    if (diagTitle) diagTitle.textContent = 'AUTONOMOUS RECOVERY COMPLETE — Candidate Promoted';
    if (diagConfVal) diagConfVal.textContent = '99%';
    if (diagAction) diagAction.textContent = '100% PROMOTED ➔ Gateway 2 (ICICI Direct)';
    if (diagExplanation) {
      diagExplanation.textContent =
        'Canary verified all 5 deterministic safety gates (Sample Size, SR Delta, Wilson Bound, Latency SLO, Error Cap). Candidate successfully promoted to 100% traffic.';
    }
    if (swappingCard) {
      swappingCard.style.display = 'block';
      if (swapStepPct) swapStepPct.textContent = '100%';
      if (swapBarFill) swapBarFill.style.width = '100%';
      if (swapStepTitle) swapStepTitle.textContent = 'Autonomous Traffic Swap Complete (100% Promoted):';
    }
    if (quarantineBox) quarantineBox.style.display = 'none';
    return;
  }

  if (!incident || incident.is_resolved) {
    if (diagTitle) diagTitle.textContent = 'SYSTEM NOMINAL — All Gateways Healthy';
    if (diagConfVal) diagConfVal.textContent = '99%';
    if (diagAction) diagAction.textContent = 'NO_ACTION';
    if (diagExplanation) {
      diagExplanation.textContent =
        'Continuous Wilson score monitoring confirms all routes are operating within established SLO baselines.';
    }
    if (swappingCard) swappingCard.style.display = 'none';
    if (quarantineBox) quarantineBox.style.display = 'none';
    return;
  }

  // Outage detected
  if (diagTitle) {
    diagTitle.textContent = `OUTAGE DETECTED: ${incident.root_cause || 'Gateway 1 Degradation'}`;
  }
  if (diagConfVal) diagConfVal.textContent = '95%';
  if (diagAction) diagAction.textContent = 'CANARY SWAP ➔ Gateway 2 (ICICI)';
  if (diagExplanation) {
    diagExplanation.textContent =
      incident.hypotheses && incident.hypotheses[0]
        ? incident.hypotheses[0].description
        : 'AI Doctor verified root-cause via Diagnostic Evidence Tools. Autonomous control loop initiated progressive canary rerouting to Gateway 2.';
  }

  // Swapping card
  if (swappingCard) {
    swappingCard.style.display = 'block';
    const stageIdx = canaryState && canaryState.current_stage_index !== undefined ? canaryState.current_stage_index + 1 : 1;
    const pct = canaryState ? canaryState.current_traffic_percentage : 20;
    if (swapStepPct) swapStepPct.textContent = `${pct}%`;
    if (swapBarFill) swapBarFill.style.width = `${pct}%`;
    if (swapStepTitle) {
      swapStepTitle.textContent = `Autonomous Canary Swapping Active (Stage ${stageIdx} of 3):`;
    }
  }

  if (quarantineBox) quarantineBox.style.display = 'none';
}

function renderPlatformKPIs(snapshot, incident, isPromotedGw2, isCascading) {
  const valSr = document.getElementById('val-sr');
  const valRisk = document.getElementById('val-risk');
  const valRecovered = document.getElementById('val-recovered');
  const tileRisk = document.getElementById('kpi-tile-risk');
  const valWilson = document.getElementById('val-wilson');

  // Platform Success Rate
  if (valSr) {
    if (isCascading) {
      valSr.textContent = '97.8%';
      if (valWilson) valWilson.textContent = 'SLO Restored via Tertiary Failover: Wilson CI [95.4% – 98.9%]';
    } else if (isPromotedGw2) {
      valSr.textContent = '99.2%';
      if (valWilson) valWilson.textContent = 'SLO Restored: Wilson 95% CI [98.5% – 99.9%]';
    } else if (incident && !incident.is_resolved) {
      valSr.textContent = '62.4%';
      if (valWilson) valWilson.textContent = 'SLO Breached: Wilson CI Lower Bound < 70%';
    } else if (snapshot && snapshot.success_rate !== undefined) {
      valSr.textContent = `${(snapshot.success_rate * 100).toFixed(1)}%`;
      if (valWilson) valWilson.textContent = 'SLO: ≥95% (Wilson 95% CI Verified)';
    } else {
      valSr.textContent = '98.5%';
    }
  }

  // Revenue At Risk & Recovered
  if (isCascading) {
    if (valRisk) valRisk.textContent = '₹0';
    if (valRecovered) valRecovered.textContent = '₹2,45,000';
    if (tileRisk) tileRisk.className = 'kpi-tile';
  } else if (isPromotedGw2) {
    if (valRisk) valRisk.textContent = '₹0';
    if (valRecovered) valRecovered.textContent = '₹1,68,000';
    if (tileRisk) tileRisk.className = 'kpi-tile';
  } else if (incident && !incident.is_resolved) {
    const risk = Math.round(incident.revenue_at_risk_inr || 37984);
    if (valRisk) valRisk.textContent = `₹${risk.toLocaleString('en-IN')}`;
    if (valRecovered) valRecovered.textContent = '₹0';
    if (tileRisk) tileRisk.className = 'kpi-tile danger';
  } else {
    if (valRisk) valRisk.textContent = '₹0';
    if (valRecovered) valRecovered.textContent = '₹0';
    if (tileRisk) tileRisk.className = 'kpi-tile';
  }
}

// Interactive Scenario Injection
function injectScenario(scenario) {
  currentActiveScenario = scenario;

  fetch(`${API_BASE}/api/v1/simulate/scenario`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario: scenario, count: 40 }),
  })
    .then((r) => {
      if (!r.ok) {
        throw new Error(`HTTP error ${r.status}`);
      }
      return r.json();
    })
    .then((res) => {
      console.log('Simulated scenario successfully:', res);
      if (scenario === 'HEALTHY') {
        currentActiveScenario = null;
        currentPromotedRoute = null;
      }
    })
    .catch((err) => {
      console.error('Simulation call failed:', err);
    });
}
