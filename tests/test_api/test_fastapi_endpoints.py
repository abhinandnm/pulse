import json
import pytest
from fastapi.testclient import TestClient

from pulse.api.app import app, razorpay
from pulse.domain.types import OperatingMode, ErrorCode


class TestFastAPIEndpoints:
    def setup_method(self):
        self.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "HEALTHY"
        assert "system_state" in data
        assert "operating_mode" in data

    def test_root_and_dashboard_static(self):
        # Root redirects to /dashboard/
        res_root = self.client.get("/", follow_redirects=False)
        assert res_root.status_code in (302, 307)
        assert res_root.headers["location"] == "/dashboard/"

        # Dashboard serves HTML
        res_dash = self.client.get("/dashboard/")
        assert res_dash.status_code == 200
        assert "PULSE" in res_dash.text


    def test_get_telemetry(self):
        res = self.client.get("/api/v1/telemetry")
        assert res.status_code == 200
        data = res.json()
        assert "total_transactions" in data
        assert "success_rate" in data
        assert "latency" in data

    def test_get_routes(self):
        res = self.client.get("/api/v1/routes")
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 3
        route_ids = [r["route_id"] for r in data]
        assert "psp_hdfc_direct" in route_ids

    def test_set_operating_mode(self):
        res = self.client.post("/api/v1/control/mode", json={"mode": "ASSISTED"})
        assert res.status_code == 200
        assert res.json()["mode"] == "ASSISTED"

        # Set back to AUTONOMOUS
        res2 = self.client.post("/api/v1/control/mode", json={"mode": "AUTONOMOUS"})
        assert res2.status_code == 200
        assert res2.json()["mode"] == "AUTONOMOUS"

    def test_create_razorpay_order(self):
        res = self.client.post(
            "/api/v1/razorpay/order",
            json={"amount_inr": 2500.0, "currency": "INR", "receipt": "test_rcpt_01"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["id"].startswith("order_")
        assert data["amount"] == 250000  # 2500 INR * 100 paise
        assert data["currency"] == "INR"

    def test_razorpay_webhook_signature_verification(self):
        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_wh_123",
                        "amount": 50000,
                        "status": "captured",
                    }
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        # 1. Invalid / missing signature returns 400
        res_no_sig = self.client.post(
            "/api/v1/razorpay/webhook",
            content=body_bytes,
        )
        assert res_no_sig.status_code == 400

        res_bad_sig = self.client.post(
            "/api/v1/razorpay/webhook",
            content=body_bytes,
            headers={"X-Razorpay-Signature": "invalid_sig"},
        )
        assert res_bad_sig.status_code == 400

        # 2. Valid signature returns 200
        valid_sig = razorpay.generate_webhook_signature(body_bytes)
        res_valid = self.client.post(
            "/api/v1/razorpay/webhook",
            content=body_bytes,
            headers={"X-Razorpay-Signature": valid_sig},
        )
        assert res_valid.status_code == 200
        assert res_valid.json()["status"] == "PROCESSED"

    def test_simulate_scenario_endpoint(self):
        res = self.client.post(
            "/api/v1/simulate/scenario",
            json={"scenario": "PSP_TIMEOUT", "count": 20},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "INJECTED"
        assert data["scenario"] == "PSP_TIMEOUT"
        assert "loop_result" in data

    def test_telemetry_websocket(self):
        with self.client.websocket_connect("/ws/telemetry") as websocket:
            data = websocket.receive_text()
            payload = json.loads(data)
            assert "system_state" in payload
            assert "snapshot" in payload
