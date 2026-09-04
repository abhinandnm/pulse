import random
import uuid
from typing import Optional, List, Tuple
from datetime import datetime, timezone

from pulse.domain.types import Bank, PaymentMethod, ErrorCode, PaymentState
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.domain.route import PaymentRoute
from pulse.simulator.failures import FailureProfile, FailureScenarioType


# Realistic market share distributions for Indian digital payments
BANK_WEIGHTS: List[Tuple[Bank, float]] = [
    (Bank.HDFC, 0.35),
    (Bank.ICICI, 0.25),
    (Bank.SBI, 0.20),
    (Bank.AXIS, 0.10),
    (Bank.KOTAK, 0.05),
    (Bank.OTHER, 0.05),
]

METHOD_WEIGHTS: List[Tuple[PaymentMethod, float]] = [
    (PaymentMethod.UPI, 0.65),
    (PaymentMethod.CARD, 0.20),
    (PaymentMethod.NET_BANKING, 0.10),
    (PaymentMethod.WALLET, 0.05),
]


def _weighted_choice(choices: List[Tuple], rng: random.Random):
    items, weights = zip(*choices)
    return rng.choices(items, weights=weights, k=1)[0]


def generate_amount_for_method(method: PaymentMethod, rng: random.Random) -> float:
    """Generate realistic transaction ticket size based on payment rail."""
    if method == PaymentMethod.UPI:
        return round(rng.uniform(50.0, 2500.0), 2)
    elif method == PaymentMethod.CARD:
        return round(rng.uniform(300.0, 12000.0), 2)
    elif method == PaymentMethod.NET_BANKING:
        return round(rng.uniform(1000.0, 45000.0), 2)
    else:  # WALLET
        return round(rng.uniform(20.0, 800.0), 2)


def generate_transaction(
    route_id: str = "psp_hdfc_direct",
    bank: Optional[Bank] = None,
    payment_method: Optional[PaymentMethod] = None,
    amount_inr: Optional[float] = None,
    is_synthetic: bool = False,
    rng: Optional[random.Random] = None,
) -> Transaction:
    """Generate a realistic transaction attempt. Deterministic if rng provided."""
    _rng = rng if rng is not None else random.Random()

    from pulse.simulator.routes import DEFAULT_ROUTES
    route = DEFAULT_ROUTES.get(route_id)

    if bank is not None:
        selected_bank = bank
    elif route and route.supported_banks:
        eligible_banks = [(b, w) for b, w in BANK_WEIGHTS if b in route.supported_banks]
        selected_bank = _weighted_choice(eligible_banks, _rng) if eligible_banks else _rng.choice(route.supported_banks)
    else:
        selected_bank = _weighted_choice(BANK_WEIGHTS, _rng)

    if payment_method is not None:
        selected_method = payment_method
    elif route and route.supported_methods:
        eligible_methods = [(m, w) for m, w in METHOD_WEIGHTS if m in route.supported_methods]
        selected_method = _weighted_choice(eligible_methods, _rng) if eligible_methods else _rng.choice(route.supported_methods)
    else:
        selected_method = _weighted_choice(METHOD_WEIGHTS, _rng)

    selected_amount = amount_inr or generate_amount_for_method(selected_method, _rng)

    # Deterministic or random ID
    txn_hex = f"{_rng.getrandbits(32):08x}"
    idemp_hex = f"{_rng.getrandbits(32):08x}"

    return Transaction(
        transaction_id=f"txn_{txn_hex}",
        idempotency_key=f"idemp_{idemp_hex}",
        timestamp=datetime.now(timezone.utc),
        amount_inr=selected_amount,
        bank=selected_bank,
        payment_method=selected_method,
        route_id=route_id,
        merchant_id="merchant_pulse_store",
        customer_id=f"cust_{_rng.getrandbits(16):04x}",
        payment_state=PaymentState.CREATED,
        retry_count=0,
        is_synthetic=is_synthetic,
    )


def execute_transaction(
    txn: Transaction,
    route: PaymentRoute,
    failure_profile: Optional[FailureProfile] = None,
    request_index: int = 0,
    canary_traffic_pct: int = 0,
    rng: Optional[random.Random] = None,
) -> TransactionResult:
    """
    Execute a payment transaction through a payment route with deterministic
    failure injection support.
    """
    _rng = rng if rng is not None else random.Random()

    # 1. Capability Validation: Check if route actually supports this bank and method
    if txn.bank not in route.supported_banks or txn.payment_method not in route.supported_methods:
        latency = round(_rng.uniform(40.0, 100.0), 2)
        return TransactionResult(
            transaction=txn,
            success=False,
            latency_ms=latency,
            error_code=ErrorCode.GATEWAY_ERROR,
            error_message=f"Route {route.route_id} does not support {txn.bank.value} via {txn.payment_method.value}",
            payment_state=PaymentState.FAILED,
        )

    # 2. Check if a failure profile is active and matches this transaction
    if failure_profile and failure_profile.scenario_type != FailureScenarioType.HEALTHY:
        applies = True

        # Check route match
        if failure_profile.target_route_id and failure_profile.target_route_id != route.route_id:
            applies = False

        # Check bank match
        if failure_profile.target_bank and failure_profile.target_bank != txn.bank:
            applies = False

        # Check method match
        if failure_profile.target_method and failure_profile.target_method != txn.payment_method:
            applies = False

        # Check flapping scenario condition (oscillates every flapping_cycle_size requests)
        if failure_profile.scenario_type == FailureScenarioType.ROUTE_FLAPPING:
            cycle = (request_index // failure_profile.flapping_cycle_size) % 2
            if cycle == 0:
                applies = False  # Healthy half of cycle

        # Check mid-canary scenario condition (only fails when canary reaches trigger %)
        if failure_profile.scenario_type == FailureScenarioType.MID_CANARY_FAILURE:
            if canary_traffic_pct < failure_profile.canary_trigger_percentage:
                applies = False  # Behaves healthy during initial small probe

        if applies:
            # Check failure probability
            if _rng.random() < failure_profile.failure_probability:
                latency = round(_rng.uniform(failure_profile.latency_min_ms, failure_profile.latency_max_ms), 2)
                error_code = failure_profile.error_code
                error_msg = failure_profile.error_message or "Gateway failure during processing"
                
                # Timeout maps to UNKNOWN payment state
                payment_state = PaymentState.UNKNOWN if error_code == ErrorCode.PSP_TIMEOUT else PaymentState.FAILED

                return TransactionResult(
                    transaction=txn,
                    success=False,
                    latency_ms=latency,
                    error_code=error_code,
                    error_message=error_msg,
                    payment_state=payment_state,
                )

    # 3. Healthy Baseline Execution (98% success, ~80-220ms latency)
    baseline_success = _rng.random() < 0.985
    latency = round(_rng.uniform(80.0, 220.0), 2)

    if baseline_success:
        psp_ref = f"psp_ref_{_rng.getrandbits(24):06x}"
        return TransactionResult(
            transaction=txn,
            success=True,
            latency_ms=latency,
            error_code=ErrorCode.NONE,
            psp_reference=psp_ref,
            payment_state=PaymentState.CAPTURED,
        )
    else:
        # Occasional natural 1.5% drop (e.g. auth fail or network blip)
        return TransactionResult(
            transaction=txn,
            success=False,
            latency_ms=latency,
            error_code=ErrorCode.AUTH_FAILED,
            error_message="Customer cancelled or failed 2FA",
            payment_state=PaymentState.FAILED,
        )
