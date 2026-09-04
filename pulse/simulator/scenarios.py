import random
from typing import List, Optional, Iterator
from pulse.domain.types import Bank, PaymentMethod
from pulse.domain.transaction import TransactionResult
from pulse.simulator.failures import FailureScenarioType, FailureProfile, create_failure_profile
from pulse.simulator.routes import DEFAULT_ROUTES, PSP_HDFC_DIRECT, get_route
from pulse.simulator.generator import generate_transaction, execute_transaction


class PaymentScenarioRunner:
    """
    Deterministic payment scenario runner.
    Given identical seeds, it reproduces identical transaction flows,
    latencies, and failure patterns.
    """

    def __init__(
        self,
        seed: int = 42,
        default_route_id: str = "psp_hdfc_direct",
    ):
        self.seed = seed
        self.default_route_id = default_route_id

    def run_scenario(
        self,
        scenario_type: FailureScenarioType,
        count: int = 50,
        target_route_id: Optional[str] = None,
        target_bank: Optional[Bank] = None,
        canary_traffic_pct: int = 0,
    ) -> List[TransactionResult]:
        """Execute a batch of payments for a given scenario deterministically."""
        return list(
            self.stream_scenario(
                scenario_type=scenario_type,
                count=count,
                target_route_id=target_route_id,
                target_bank=target_bank,
                canary_traffic_pct=canary_traffic_pct,
            )
        )

    def stream_scenario(
        self,
        scenario_type: FailureScenarioType,
        count: int = 50,
        target_route_id: Optional[str] = None,
        target_bank: Optional[Bank] = None,
        canary_traffic_pct: int = 0,
    ) -> Iterator[TransactionResult]:
        """Stream payment transactions sequentially."""
        rng = random.Random(self.seed)
        route_id = target_route_id or self.default_route_id
        route = get_route(route_id) or PSP_HDFC_DIRECT

        failure_profile = create_failure_profile(
            scenario_type=scenario_type,
            target_route_id=route_id,
            target_bank=target_bank,
        )

        # In traffic surge, increase count
        actual_count = int(count * failure_profile.traffic_surge_multiplier)

        for i in range(actual_count):
            # For testing target_bank degradation, bias transactions towards that bank
            forced_bank = None
            if scenario_type == FailureScenarioType.BANK_DEGRADATION and target_bank:
                # 70% of traffic directed to affected bank during scenario test
                if rng.random() < 0.70:
                    forced_bank = target_bank

            txn = generate_transaction(
                route_id=route.route_id,
                bank=forced_bank,
                rng=rng,
            )

            result = execute_transaction(
                txn=txn,
                route=route,
                failure_profile=failure_profile,
                request_index=i,
                canary_traffic_pct=canary_traffic_pct,
                rng=rng,
            )

            yield result
