from __future__ import annotations


def test_health_endpoint_returns_research_safe_payload(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["environment"] == "development"
    assert payload["research_use_only"] is True
    assert isinstance(payload["agent_llm_configured"], bool)
    assert response.headers["x-research-use-only"] == "true"
    assert response.headers["x-clinical-use"] == "not-intended"
