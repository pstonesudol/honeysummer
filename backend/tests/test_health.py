import pytest

from app.server import app


@pytest.mark.asyncio
async def test_health_endpoint_reports_service_status():
    request, response = await app.asgi_client.get("/api/health/")

    assert response.status == 200
    assert response.json == {"status": "ok", "service": "honey-summer-api"}
