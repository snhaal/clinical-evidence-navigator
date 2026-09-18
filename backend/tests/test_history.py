"""Unit and integration tests for match history endpoints and tenancy."""

import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import User, get_optional_user, get_required_user
from app.main import app

TEST_USER_A = User(id="11111111-1111-1111-1111-111111111111", email="usera@example.com")
TEST_USER_B = User(id="22222222-2222-2222-2222-222222222222", email="userb@example.com")


@pytest.mark.asyncio
async def test_get_history_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/history")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_history_detail_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/history/some-run-id")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_history_authenticated_returns_user_runs():
    mock_items = [
        {
            "id": "run-1",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "condition": "Stage III Lung Cancer",
            "trial_title": "NCT01234567 - Trial A",
            "nct_id": "NCT01234567",
            "top_trials": ["NCT01234567 - Trial A"],
            "status": "match",
            "overall_verdict": "match",
        }
    ]

    async def mock_get_user_match_history(conn, user_id, limit, offset):
        assert user_id == TEST_USER_A.id
        assert limit == 10
        assert offset == 0
        return mock_items, 1

    app.dependency_overrides[get_required_user] = lambda: TEST_USER_A
    try:
        with (
            patch("app.api.routes.get_engine"),
            patch(
                "app.api.routes.get_user_match_history",
                side_effect=mock_get_user_match_history,
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/history?limit=10&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "run-1"
        assert data["items"][0]["condition"] == "Stage III Lung Cancer"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_history_detail_own_run_returns_200():
    mock_detail = {
        "id": "run-own",
        "patient_profile_id": "prof-1",
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "patient_profile": "60 yo male with melanoma",
        "structured_query": {
            "condition": "Melanoma",
            "stage": "Stage IV",
            "prior_therapy": [],
            "biomarkers": [],
            "exclusions": [],
            "status_filter": "RECRUITING",
        },
        "nct_id": "NCT09999999",
        "trial_title": "Melanoma Immunotherapy Study",
        "overall_verdict": "match",
        "satisfied_count": 2,
        "unclear_count": 0,
        "hard_exclusion_hit": False,
        "latency_ms": 120,
        "token_cost": 450,
        "criterion_verdicts": [
            {
                "nct_id": "NCT09999999",
                "criterion_type": "inclusion",
                "criterion_index": 0,
                "verdict": "match",
                "rationale": "Patient matches diagnosis.",
                "cited_text": "Must have confirmed melanoma.",
                "citation_validated": True,
            }
        ],
        "trials": [
            {
                "nct_id": "NCT09999999",
                "title": "Melanoma Immunotherapy Study",
                "overall_verdict": "match",
                "satisfied_count": 2,
                "unclear_count": 0,
                "hard_exclusion_hit": False,
                "criterion_verdicts": [],
            }
        ],
    }

    async def mock_get_match_run_detail(conn, match_run_id, user_id):
        assert match_run_id == "run-own"
        assert user_id == TEST_USER_A.id
        return mock_detail

    app.dependency_overrides[get_required_user] = lambda: TEST_USER_A
    try:
        with (
            patch("app.api.routes.get_engine"),
            patch(
                "app.api.routes.get_match_run_detail",
                side_effect=mock_get_match_run_detail,
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/history/run-own")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "run-own"
        assert data["trial_title"] == "Melanoma Immunotherapy Study"
        assert len(data["criterion_verdicts"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_history_detail_another_user_run_returns_403():
    async def mock_get_match_run_detail(conn, match_run_id, user_id):
        return {"forbidden": True}

    app.dependency_overrides[get_required_user] = lambda: TEST_USER_B
    try:
        with (
            patch("app.api.routes.get_engine"),
            patch(
                "app.api.routes.get_match_run_detail",
                side_effect=mock_get_match_run_detail,
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/history/run-user-a")

        assert response.status_code == 403
        assert "forbidden" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_history_detail_nonexistent_run_returns_404():
    async def mock_get_match_run_detail(conn, match_run_id, user_id):
        return None

    app.dependency_overrides[get_required_user] = lambda: TEST_USER_A
    try:
        with (
            patch("app.api.routes.get_engine"),
            patch(
                "app.api.routes.get_match_run_detail",
                side_effect=mock_get_match_run_detail,
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/history/nonexistent-id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_match_endpoint_persists_user_id_for_authenticated_user():
    saved_user_ids = []

    async def mock_insert_patient_profile(
        conn, raw_text, structured_query, clarifying_question, user_id=None
    ):
        saved_user_ids.append(user_id)
        return "fake-profile-uuid"

    app.dependency_overrides[get_optional_user] = lambda: TEST_USER_A
    try:
        with (
            patch("app.api.routes.get_engine"),
            patch("app.api.routes.get_rate_limiter") as mock_rl,
            patch(
                "app.api.routes.plan_patient_profile", new_callable=AsyncMock
            ) as mock_plan,
            patch(
                "app.api.routes.insert_patient_profile",
                side_effect=mock_insert_patient_profile,
            ),
        ):
            mock_rl.return_value.check_and_record.return_value = True
            mock_plan_result = AsyncMock()
            mock_plan_result.structured_query = None
            mock_plan_result.clarifying_question = "What is the primary condition?"
            mock_plan_result.needs_clarification = True
            mock_plan.return_value = mock_plan_result

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/match", json={"patient_profile": "Incomplete profile text"}
                )

        assert response.status_code == 200
        assert saved_user_ids == [TEST_USER_A.id]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_match_endpoint_persists_none_user_id_for_guest():
    saved_user_ids = []

    async def mock_insert_patient_profile(
        conn, raw_text, structured_query, clarifying_question, user_id=None
    ):
        saved_user_ids.append(user_id)
        return "fake-profile-uuid"

    app.dependency_overrides[get_optional_user] = lambda: None
    try:
        with (
            patch("app.api.routes.get_engine"),
            patch("app.api.routes.get_rate_limiter") as mock_rl,
            patch(
                "app.api.routes.plan_patient_profile", new_callable=AsyncMock
            ) as mock_plan,
            patch(
                "app.api.routes.insert_patient_profile",
                side_effect=mock_insert_patient_profile,
            ),
        ):
            mock_rl.return_value.check_and_record.return_value = True
            mock_plan_result = AsyncMock()
            mock_plan_result.structured_query = None
            mock_plan_result.clarifying_question = "What is the primary condition?"
            mock_plan_result.needs_clarification = True
            mock_plan.return_value = mock_plan_result

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/match", json={"patient_profile": "Incomplete profile text"}
                )

        assert response.status_code == 200
        assert saved_user_ids == [None]
    finally:
        app.dependency_overrides.clear()
