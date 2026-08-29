from pulse.domain.types import Bank
from pulse.domain.types import PaymentMethod
from pulse.domain.route import PaymentRoute

DEFAULT_ROUTES = {
    "psp_hdfc_direct": PaymentRoute(
        route_id="psp_hdfc_direct",
        name="HDFC Direct UPI Switch",
        supported_methods=[PaymentMethod.UPI, PaymentMethod.NET_BANKING],
        supported_banks=[Bank.HDFC],
        cost_per_txn_inr=0.20,
    ),

    "psp_icici_backup": PaymentRoute(
        route_id="psp_icici_backup",
        name="ICICI Fallback Switch",
        supported_methods=[PaymentMethod.UPI, PaymentMethod.CARD],
        supported_banks=[Bank.ICICI, Bank.HDFC],
        cost_per_txn_inr=0.75,
    ),

    "psp_aggregator_fallback": PaymentRoute(
        route_id="psp_aggregator_fallback",
        name="Global Multi-Bank Aggregator",
        supported_methods=[PaymentMethod.UPI, PaymentMethod.CARD, PaymentMethod.NET_BANKING, PaymentMethod.WALLET],
        supported_banks=[Bank.HDFC, Bank.ICICI, Bank.SBI, Bank.AXIS, Bank.KOTAK, Bank.OTHER],
        cost_per_txn_inr=0.75,
    ),
}



