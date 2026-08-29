from pulse.domain.types import ErrorCode
import uuid
import random
from pulse.domain.transaction import Transaction
from pulse.domain.types import PaymentMethod,Bank
from pulse.domain.route import PaymentRoute
from pulse.domain.transaction import TransactionResult

def generate_transaction(route_id:str= "psp_hdfc_direct")-> Transaction:
    transaction_id=f"txn_{uuid.uuid4().hex[:8]}"
    amount_inr=random.randint(100,5000)
    bank=random.choice(list(Bank))
    payment_method= random.choice(list(PaymentMethod))
    return Transaction(
        transaction_id=transaction_id,
        amount_inr=amount_inr,
        bank=bank,
        payment_method=payment_method,
        route_id=route_id,
    )
    
def execute_transaction(txn: Transaction, route: PaymentRoute) -> TransactionResult:
    if txn.bank not in route.supported_banks or txn.payment_method not in route.supported_methods:
        return TransactionResult(
            transaction=txn,
            success=False,
            latency_ms=round(random.uniform(80.0,250.0),2),
            error_code=ErrorCode.GATEWAY_ERROR,
            error_message="Route does not support this bank or payment method "
        )

    latency_ms = round(random.uniform(80.0, 250.0), 2)

    if random.random() < 0.98:
        return TransactionResult(
            transaction=txn,
            success=True,
            latency_ms=latency_ms,
            error_code=ErrorCode.NONE,
            psp_reference=f"psp_ref_{uuid.uuid4().hex[:6]}",
        )
    else:
        return TransactionResult(
            transaction=txn,
            success=False,
            latency_ms=latency_ms,
            error_code=ErrorCode.PSP_TIMEOUT,
            error_message="Payment gateway timed out",
        )


if __name__ == "__main__":
    from pulse.simulator.routes import DEFAULT_ROUTES

    print("=== SIMULATING 5 PAYMENTS THROUGH HDFC DIRECT ROUTE ===")
    hdfc_route = DEFAULT_ROUTES["psp_hdfc_direct"]

    for i in range(5):
        txn = generate_transaction(route_id=hdfc_route.route_id)
        result = execute_transaction(txn, hdfc_route)

        status_text = "SUCCESS" if result.success else f"FAILED ({result.error_code.value})"
        print(f"[{i+1}] {txn.transaction_id} | {txn.bank.value} - {txn.payment_method.value} (INR {txn.amount_inr}) -> {status_text} in {result.latency_ms}ms")
