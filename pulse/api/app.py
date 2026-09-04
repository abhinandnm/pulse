import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from pulse.domain.types import OperatingMode, Bank, PaymentMethod, ErrorCode, PaymentState
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.observer.collector import TelemetryObserver
from pulse.memory.repository import IncidentRepository
from pulse.simulator.scenarios import PaymentScenarioRunner
from pulse.simulator.failures import FailureScenarioType
from pulse.simulator.routes import DEFAULT_ROUTES
from pulse.engine.loop import AutonomousControlLoop
from pulse.api.razorpay_adapter import RazorpayAdapter


# Application Request/Response schemas
class SetModeRequest(BaseModel):
    mode: OperatingMode


class SimulateScenarioRequest(BaseModel):
    scenario: FailureScenarioType
    count: int = Field(default=30, ge=1, le=500)
    target_route: Optional[str] = None
    target_bank: Optional[Bank] = None


class CreateOrderRequest(BaseModel):
    amount_inr: float = Field(gt=0)
    currency: str = "INR"
    receipt: Optional[str] = None


# Shared system instances
observer = TelemetryObserver(window_seconds=60)
repository = IncidentRepository()
control_loop = AutonomousControlLoop(
    observer=observer,
    operating_mode=OperatingMode.AUTONOMOUS,
    repository=repository,
)
razorpay = RazorpayAdapter()

app = FastAPI(
    title="PULSE — Autonomous AI Payment Reliability & Revenue Recovery",
    version="1.0.0",
    description="Razorpay Buildathon Track 03: AI Revenue Recovery Platform REST & WebSocket API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

dashboard_path = Path(__file__).resolve().parent.parent / "dashboard"
if dashboard_path.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect root path to interactive dashboard."""
    return RedirectResponse(url="/dashboard/")



@app.get("/health")
def health_check():
    """Liveness probe."""
    return {
        "status": "HEALTHY",
        "system_state": control_loop.fsm.current_state.value,
        "operating_mode": control_loop.operating_mode.value,
    }


@app.get("/api/v1/telemetry")
def get_telemetry():
    """Get the current live TelemetrySnapshot."""
    return observer.get_snapshot().model_dump()


@app.get("/api/v1/routes")
def get_routes():
    """Get all routes and their live RouteHealth."""
    snapshot = observer.get_snapshot()
    routes_data = []
    for r_id in ["psp_hdfc_direct", "psp_icici_backup", "psp_aggregator_fallback"]:
        route = DEFAULT_ROUTES[r_id]
        health = snapshot.route_health.get(r_id)
        routes_data.append({
            "route_id": route.route_id,
            "name": route.name,
            "supported_methods": [m.value for m in route.supported_methods],
            "supported_banks": [b.value for b in route.supported_banks],
            "cost_per_txn_inr": route.cost_per_txn_inr,
            "health": health.model_dump() if health else None,
        })
    return routes_data


@app.post("/api/v1/control/mode")
def set_operating_mode(req: SetModeRequest):
    """Set Pulse operating mode: OBSERVE, ASSISTED, or AUTONOMOUS."""
    control_loop.set_operating_mode(req.mode)
    return {
        "status": "SUCCESS",
        "mode": control_loop.operating_mode.value,
    }


@app.post("/api/v1/control/step")
def execute_control_step():
    """Trigger a step of the autonomous control loop."""
    result = control_loop.step()
    return result.model_dump()


@app.get("/api/v1/incidents")
def list_incidents(unresolved_only: bool = False):
    """List operational incidents from memory."""
    incidents = repository.list_incidents(limit=50, unresolved_only=unresolved_only)
    return [inc.model_dump() for inc in incidents]


@app.post("/api/v1/simulate/scenario")
def trigger_simulation(req: SimulateScenarioRequest):
    """Inject a deterministic failure scenario into the payment stream."""
    runner = PaymentScenarioRunner()
    results = runner.run_scenario(
        scenario_type=req.scenario,
        count=req.count,
        target_route_id=req.target_route,
        target_bank=req.target_bank,
    )
    observer.record_batch(results)
    # Automatically execute one loop step after injection
    loop_result = control_loop.step()
    return {
        "status": "INJECTED",
        "scenario": req.scenario.value,
        "transactions_generated": len(results),
        "loop_result": loop_result.model_dump(),
    }


@app.post("/api/v1/razorpay/order")
def create_razorpay_order(req: CreateOrderRequest):
    """Create a Razorpay Test Mode Order."""
    order = razorpay.create_order(
        amount_inr=req.amount_inr,
        currency=req.currency,
        receipt=req.receipt,
    )
    return order


@app.post("/api/v1/razorpay/webhook")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None),
):
    """
    Ingest Razorpay webhook with strict HMAC SHA256 signature verification.
    """
    body = await request.body()
    if not x_razorpay_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Razorpay-Signature header",
        )

    is_valid = razorpay.verify_webhook_signature(body, x_razorpay_signature)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )

    payload = json.loads(body.decode("utf-8"))
    event_type = payload.get("event", "unknown")

    # Ingest event into observer if payment event
    if "payment" in event_type:
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        amount = entity.get("amount", 10000) / 100.0  # Convert paise to INR
        status_str = entity.get("status", "captured")
        is_success = status_str in ("captured", "authorized")

        txn = Transaction(
            transaction_id=entity.get("id", f"pay_wh_{uuid.uuid4().hex[:6]}"),
            amount_inr=max(1.0, float(amount)),
            bank=Bank.HDFC,
            payment_method=PaymentMethod.UPI,
            route_id="psp_hdfc_direct",
        )
        res = TransactionResult(
            transaction=txn,
            success=is_success,
            latency_ms=120.0,
            error_code=ErrorCode.NONE if is_success else ErrorCode.GATEWAY_ERROR,
            psp_reference=entity.get("id"),
        )
        observer.record_transaction(res)

    return {"status": "PROCESSED", "event": event_type}


@app.websocket("/ws/telemetry")
async def telemetry_websocket(websocket: WebSocket):
    """
    High-frequency real-time telemetry WebSocket stream (~100ms updates).
    Streams live snapshot, route health, FSM state, and active canary progress.
    """
    await websocket.accept()
    try:
        while True:
            snap = observer.get_snapshot()
            data = {
                "system_state": control_loop.fsm.current_state.value,
                "operating_mode": control_loop.operating_mode.value,
                "snapshot": snap.model_dump(),
                "canary_state": control_loop.active_canary_state.model_dump() if control_loop.active_canary_state else None,
                "active_incident": control_loop.active_incident.model_dump() if control_loop.active_incident else None,
            }
            await websocket.send_text(json.dumps(data, default=str))
            await asyncio.sleep(0.1)  # 100ms stream rate
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
