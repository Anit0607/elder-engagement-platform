from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.circles import CircleCreate, CircleSuggestionRules, CircleUpdate, is_suggested
from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.postgres_circles import PostgresCircleService


def test_circle_suggestions_use_general_interest_or_language_rules():
    assert is_suggested(CircleSuggestionRules(), [], None)
    interest_rule = CircleSuggestionRules(interests=["Music"])
    assert is_suggested(interest_rule, ["music", "walking"], "en")
    assert not is_suggested(interest_rule, ["gardening"], "en")
    language_rule = CircleSuggestionRules(preferredLanguages=["bn"])
    assert is_suggested(language_rule, [], "bn")
    assert not is_suggested(language_rule, [], "hi")


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " "},
        {"name": "Health", "suggestionRules": None},
        {"name": "Health", "suggestionRules": {"interests": ["Music", "music"]}},
        {"name": "Health", "suggestionRules": {"preferredLanguages": ["fr"]}},
        {"name": "Health", "unknown": True},
    ],
)
def test_circle_create_rejects_ambiguous_or_unsupported_values(payload):
    with pytest.raises(ValidationError):
        CircleCreate.model_validate(payload)


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"active": None}, {"suggestionRules": None}])
def test_circle_update_requires_a_real_change(payload):
    with pytest.raises(ValidationError):
        CircleUpdate.model_validate(payload)


class CircleListConnection:
    def __init__(self, interests='["Music"]'):
        self.interests = interests

    async def fetchrow(self, query, *args):
        return {"preferred_language": "en", "interests": self.interests}

    async def fetch(self, query, *args):
        return [
            {
                "id": uuid4(),
                "name": "Fictional music circle",
                "description": None,
                "active": True,
                "suggestion_rules": '{"interests":["Music"],"preferredLanguages":[]}',
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "selected_by_user": None,
                "joined": False,
            }
        ]


@pytest.mark.anyio
async def test_database_encoded_profile_interests_drive_suggestions():
    result = await PostgresCircleService(None)._list(CircleListConnection(), uuid4())
    assert len(result) == 1 and result[0].suggested
    with pytest.raises(MemberSessionFailure) as error:
        await PostgresCircleService(None)._list(CircleListConnection("not-json"), uuid4())
    assert error.value.status == 503


class CircleService:
    def __init__(self):
        self.circle_id = uuid4()
        self.user_id = uuid4()
        self.calls = []

    def summary(self):
        return {
            "id": self.circle_id,
            "name": "Fictional music circle",
            "description": "Synthetic test circle",
            "active": True,
            "suggestionRules": {"interests": ["Music"], "preferredLanguages": ["bn"]},
            "joined": False,
            "selectedByUser": None,
            "suggested": True,
            "createdAt": datetime.now(UTC),
            "updatedAt": datetime.now(UTC),
        }

    async def list_mine(self, token):
        self.calls.append(("list", token))
        return [self.summary()]

    async def list_all(self, token):
        self.calls.append(("list-all", token))
        return [self.summary()]

    async def create(self, token, request, trace):
        self.calls.append(("create", token, request.name, trace))
        return self.summary()

    async def update(self, token, circle_id, request, trace):
        self.calls.append(("update", token, circle_id, request.active, trace))
        return self.summary()

    async def join(self, token, circle_id, trace):
        self.calls.append(("join", token, circle_id, trace))

    async def leave(self, token, circle_id, trace):
        self.calls.append(("leave", token, circle_id, trace))

    async def assign(self, token, user_id, circle_id, trace):
        self.calls.append(("assign", token, user_id, circle_id, trace))

    async def remove(self, token, user_id, circle_id, trace):
        self.calls.append(("remove", token, user_id, circle_id, trace))

    async def settings(self, token):
        self.calls.append(("settings", token))
        return {"maxMemberships": 5, "updatedAt": datetime.now(UTC)}

    async def replace_settings(self, token, request, trace):
        self.calls.append(("replace-settings", token, request.max_memberships, trace))
        return {"maxMemberships": request.max_memberships, "updatedAt": datetime.now(UTC)}


def test_circle_http_contract_and_unconfigured_guard(settings):
    service = CircleService()
    headers = {"Authorization": "Bearer synthetic-proof"}
    create = {
        "name": "Fictional music circle",
        "description": "Synthetic test circle",
        "suggestionRules": {"interests": ["Music"], "preferredLanguages": ["bn"]},
    }
    with TestClient(create_app(settings, circle_service=service)) as client:
        assert client.get("/v1/me/circles", headers=headers).status_code == 200
        assert client.post("/v1/admin/circles", headers=headers, json=create).status_code == 201
        assert client.get("/v1/admin/circles", headers=headers).status_code == 200
        assert (
            client.patch(
                f"/v1/admin/circles/{service.circle_id}", headers=headers, json={"active": False}
            ).status_code
            == 200
        )
        assert (
            client.post(f"/v1/me/circles/{service.circle_id}/membership", headers=headers).status_code == 204
        )
        assert (
            client.delete(f"/v1/me/circles/{service.circle_id}/membership", headers=headers).status_code
            == 204
        )
        path = f"/v1/admin/users/{service.user_id}/circles/{service.circle_id}/membership"
        assert client.post(path, headers=headers).status_code == 204
        assert client.delete(path, headers=headers).status_code == 204
        assert client.get("/v1/admin/circle-settings", headers=headers).json()["maxMemberships"] == 5
        assert (
            client.put("/v1/admin/circle-settings", headers=headers, json={"maxMemberships": 7}).json()[
                "maxMemberships"
            ]
            == 7
        )
        assert client.get("/v1/me/circles").status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/me/circles", headers=headers).status_code == 503

    assert {call[0] for call in service.calls} == {
        "list",
        "list-all",
        "create",
        "update",
        "join",
        "leave",
        "assign",
        "remove",
        "settings",
        "replace-settings",
    }
