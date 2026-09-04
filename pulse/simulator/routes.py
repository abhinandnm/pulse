from typing import Dict, Optional, List
from pulse.domain.types import Bank, PaymentMethod
from pulse.domain.route import PaymentRoute

# Primary routes available in the simulation
PSP_HDFC_DIRECT = PaymentRoute(
    route_id="psp_hdfc_direct",
    name="PSP-A (HDFC Direct High-Speed Pipeline)",
    supported_methods=[PaymentMethod.UPI, PaymentMethod.NET_BANKING],
    supported_banks=[Bank.HDFC],
    cost_per_txn_inr=0.20,
)

PSP_ICICI_BACKUP = PaymentRoute(
    route_id="psp_icici_backup",
    name="PSP-B (ICICI / Multi-Bank Secondary Switch)",
    supported_methods=[PaymentMethod.UPI, PaymentMethod.CARD, PaymentMethod.NET_BANKING],
    supported_banks=[Bank.ICICI, Bank.HDFC, Bank.AXIS],
    cost_per_txn_inr=0.50,
)

PSP_AGGREGATOR_FALLBACK = PaymentRoute(
    route_id="psp_aggregator_fallback",
    name="PSP-C (Global Resilient Aggregator)",
    supported_methods=[
        PaymentMethod.UPI,
        PaymentMethod.CARD,
        PaymentMethod.NET_BANKING,
        PaymentMethod.WALLET,
    ],
    supported_banks=[
        Bank.HDFC,
        Bank.ICICI,
        Bank.SBI,
        Bank.AXIS,
        Bank.KOTAK,
        Bank.OTHER,
    ],
    cost_per_txn_inr=0.75,
)

DEFAULT_ROUTES: Dict[str, PaymentRoute] = {
    "psp_hdfc_direct": PSP_HDFC_DIRECT,
    "psp_icici_backup": PSP_ICICI_BACKUP,
    "psp_aggregator_fallback": PSP_AGGREGATOR_FALLBACK,
    # Aliases mentioned in BRICKS specification
    "PSP_A": PSP_HDFC_DIRECT,
    "PSP_B": PSP_ICICI_BACKUP,
    "PSP_C": PSP_AGGREGATOR_FALLBACK,
}


def get_route(route_id: str) -> Optional[PaymentRoute]:
    """Retrieve route configuration by ID or alias."""
    return DEFAULT_ROUTES.get(route_id)


def get_eligible_routes(bank: Bank, method: PaymentMethod) -> List[PaymentRoute]:
    """Return all routes that can handle this specific bank and payment method."""
    unique_routes = [PSP_HDFC_DIRECT, PSP_ICICI_BACKUP, PSP_AGGREGATOR_FALLBACK]
    return [
        r for r in unique_routes
        if bank in r.supported_banks and method in r.supported_methods
    ]
