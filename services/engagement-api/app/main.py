from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
import uuid
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.account_controls import (
    AccountSummary,
    RoleChangeRequest,
    StatusChangeRequest,
    UnconfiguredAccountControls,
)
from app.circles import CircleCreate, CircleSettings, CircleSettingsUpdate, CircleSummary, CircleUpdate
from app.config import Settings, load_settings
from app.content_feed import (
    ContentPublicationReceipt,
    ContentPublicationRequest,
    FeedMedia,
    FeedPage,
    UnconfiguredContentFeedService,
)
from app.content_moderation import (
    ModerationDecisionReceipt,
    ModerationDecisionRequest,
    ModerationPreview,
    ModerationQueueItem,
    UnconfiguredContentModerationService,
)
from app.content_uploads import (
    ContentUploadAuthorisation,
    ContentUploadReceipt,
    ContentUploadRequest,
    UnconfiguredContentUploadService,
)
from app.logging_config import configure_logging, request_id_context, trace_id_context
from app.member_auth import (
    MemberSessionFailure,
    MemberSessionHandler,
    MemberSessionRequest,
    SessionResponse,
    UnconfiguredMemberSessionService,
)
from app.member_runtime import member_runtime
from app.notification_preferences import NotificationPreferences, NotificationPreferencesUpdate
from app.postgres_circles import UnconfiguredCircleService
from app.postgres_notification_preferences import UnconfiguredNotificationPreferencesService
from app.postgres_profiles import UnconfiguredProfileService
from app.problems import problem_response
from app.profile_photos import (
    PhotoUploadRequest,
    UnconfiguredProfilePhotoService,
    UploadAuthorisation,
)
from app.profiles import Profile, ProfileUpdate
from app.readiness import REQUIRED_DEPENDENCIES, DependencyProbe, NotConfiguredProbe
from app.request_limits import RequestBodyLimitMiddleware
from app.session_controls import SessionControls, SessionSummary, UnconfiguredSessionControls, denied
from app.session_refresh import RefreshRequest
from app.staff_auth import (
    StaffSessionHandler,
    StaffSessionRequest,
    StaffSessionResponse,
    UnconfiguredStaffSessionService,
)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TRACEPARENT_PATTERN = re.compile(
    r"^[\da-f]{2}-([\da-f]{32})-([\da-f]{16})-[\da-f]{2}$",
    flags=re.IGNORECASE,
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


def _problem(request: Request, status: int, code: str, title: str, *, retryable=False) -> JSONResponse:
    response = problem_response(request.state.trace_id, status, code, title, retryable=retryable)
    if status == 429:
        response.headers["Retry-After"] = "600"
    return response


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) and template.startswith("/") else "<unmatched>"


def _correlation_ids(request: Request) -> tuple[str, str]:
    candidate = request.headers.get("X-Request-Id", "")
    request_id = candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid.uuid4())
    traceparent = request.headers.get("traceparent", "")
    match = TRACEPARENT_PATTERN.fullmatch(traceparent)
    valid_traceparent = (
        match
        and traceparent[:2].lower() != "ff"
        and match.group(1) != "0" * 32
        and match.group(2) != "0" * 16
    )
    trace_id = match.group(1).lower() if valid_traceparent else secrets.token_hex(16)
    return request_id, trace_id


def create_app(
    settings: Settings | None = None,
    probes: Mapping[str, DependencyProbe] | None = None,
    *,
    member_session_handler: MemberSessionHandler | None = None,
    staff_session_handler: StaffSessionHandler | None = None,
    session_controls_handler: SessionControls | None = None,
    profile_service=None,
    profile_photo_service=None,
    notification_preferences_service=None,
    circle_service=None,
    content_upload_service=None,
    content_moderation_service=None,
    content_feed_service=None,
    account_controls=None,
    member_runtime_factory=member_runtime,
    probe_timeout_seconds: float = 2.0,
    max_request_body_bytes: int = 1_048_576,
) -> FastAPI:
    if not 0 < probe_timeout_seconds <= 30:
        raise ValueError("probe_timeout_seconds must be greater than zero and at most 30")
    if max_request_body_bytes < 1:
        raise ValueError("max_request_body_bytes must be positive")
    config = settings or load_settings()
    configure_logging(config.log_level)
    logger = logging.getLogger("engagement.api")
    provided_probes = dict(probes or {})
    unknown_probes = set(provided_probes) - set(REQUIRED_DEPENDENCIES)
    if unknown_probes:
        raise ValueError("unknown readiness dependency")
    readiness_probes = {
        name: provided_probes.get(name, NotConfiguredProbe()) for name in REQUIRED_DEPENDENCIES
    }

    @asynccontextmanager
    async def lifespan(application):
        if config.member_session_enabled and member_session_handler is None:
            async with member_runtime_factory(config) as handler:
                application.state.member_session_handler = handler
                if session_controls_handler is None:
                    application.state.session_controls = (
                        getattr(handler, "session_controls", None) or UnconfiguredSessionControls()
                    )
                if config.staff_session_enabled and staff_session_handler is None:
                    application.state.staff_session_handler = getattr(
                        handler,
                        "staff_session_handler",
                        UnconfiguredStaffSessionService(),
                    )
                if config.profile_enabled and profile_service is None:
                    application.state.profile_service = getattr(
                        handler, "profile_service", UnconfiguredProfileService()
                    )
                if config.profile_enabled and notification_preferences_service is None:
                    application.state.notification_preferences_service = getattr(
                        handler,
                        "notification_preferences_service",
                        UnconfiguredNotificationPreferencesService(),
                    )
                if config.profile_enabled and circle_service is None:
                    application.state.circle_service = getattr(
                        handler, "circle_service", UnconfiguredCircleService()
                    )
                if config.profile_photo_enabled and profile_photo_service is None:
                    application.state.profile_photo_service = getattr(
                        handler, "profile_photo_service", UnconfiguredProfilePhotoService()
                    )
                if config.content_upload_enabled and content_upload_service is None:
                    application.state.content_upload_service = getattr(
                        handler, "content_upload_service", UnconfiguredContentUploadService()
                    )
                if config.content_moderation_enabled and content_moderation_service is None:
                    application.state.content_moderation_service = getattr(
                        handler,
                        "content_moderation_service",
                        UnconfiguredContentModerationService(),
                    )
                if config.content_feed_enabled and content_feed_service is None:
                    application.state.content_feed_service = getattr(
                        handler, "content_feed_service", UnconfiguredContentFeedService()
                    )
                if config.account_controls_enabled and account_controls is None:
                    application.state.account_controls = getattr(
                        handler, "account_controls", UnconfiguredAccountControls()
                    )
                try:
                    yield
                finally:
                    application.state.member_session_handler = UnconfiguredMemberSessionService()
                    application.state.session_controls = UnconfiguredSessionControls()
                    if staff_session_handler is None:
                        application.state.staff_session_handler = UnconfiguredStaffSessionService()
                    if profile_service is None:
                        application.state.profile_service = UnconfiguredProfileService()
                    if notification_preferences_service is None:
                        application.state.notification_preferences_service = (
                            UnconfiguredNotificationPreferencesService()
                        )
                    if circle_service is None:
                        application.state.circle_service = UnconfiguredCircleService()
                    if profile_photo_service is None:
                        application.state.profile_photo_service = UnconfiguredProfilePhotoService()
                    if content_upload_service is None:
                        application.state.content_upload_service = UnconfiguredContentUploadService()
                    if content_moderation_service is None:
                        application.state.content_moderation_service = (
                            UnconfiguredContentModerationService()
                        )
                    if content_feed_service is None:
                        application.state.content_feed_service = UnconfiguredContentFeedService()
                    if account_controls is None:
                        application.state.account_controls = UnconfiguredAccountControls()
        else:
            yield

    app = FastAPI(
        lifespan=lifespan,
        title=config.app_name,
        version=__version__,
        docs_url=None if config.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if config.environment == "production" else "/openapi.json",
    )
    app.state.settings = config
    app.state.readiness_probes = readiness_probes
    app.state.member_session_handler = member_session_handler or UnconfiguredMemberSessionService()
    app.state.staff_session_handler = staff_session_handler or UnconfiguredStaffSessionService()
    app.state.session_controls = session_controls_handler or UnconfiguredSessionControls()
    app.state.profile_service = profile_service or UnconfiguredProfileService()
    app.state.profile_photo_service = profile_photo_service or UnconfiguredProfilePhotoService()
    app.state.content_upload_service = content_upload_service or UnconfiguredContentUploadService()
    app.state.content_moderation_service = (
        content_moderation_service or UnconfiguredContentModerationService()
    )
    app.state.content_feed_service = content_feed_service or UnconfiguredContentFeedService()
    app.state.notification_preferences_service = (
        notification_preferences_service or UnconfiguredNotificationPreferencesService()
    )
    app.state.circle_service = circle_service or UnconfiguredCircleService()
    app.state.account_controls = account_controls or UnconfiguredAccountControls()

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.trusted_host_list)
    if config.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-Id", "traceparent"],
            expose_headers=["X-Request-Id", "traceparent"],
        )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=max_request_body_bytes)

    @app.exception_handler(StarletteHTTPException)
    async def normalize_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _problem(request, 404, "NOT_FOUND", "Resource not found")
        if exc.status_code == 405:
            return _problem(request, 405, "METHOD_NOT_ALLOWED", "Method not allowed")
        return _problem(request, 400, "INVALID_REQUEST", "Invalid request")

    @app.exception_handler(RequestValidationError)
    async def normalize_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del exc
        return _problem(request, 400, "VALIDATION_FAILED", "Request validation failed")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter()
        request_id, trace_id = _correlation_ids(request)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request_token = request_id_context.set(request_id)
        trace_token = trace_id_context.set(trace_id)
        try:
            if request.url.hostname not in config.trusted_host_list:
                response = _problem(request, 400, "INVALID_REQUEST", "Invalid request")
            else:
                response = await call_next(request)
        except Exception:
            logger.exception("unhandled_request_error")
            response = _problem(
                request,
                500,
                "INTERNAL_ERROR",
                "Internal server error",
            )
        finally:
            request_id_context.reset(request_token)
            trace_id_context.reset(trace_token)

        response.headers["X-Request-Id"] = request_id
        response.headers["traceparent"] = f"00-{trace_id}-{secrets.token_hex(8)}-01"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "method": request.method,
                "route": _route_template(request),
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.get("/health", tags=["Operations"], response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post(
        "/v1/auth/member/session",
        tags=["Authentication"],
        response_model=SessionResponse,
    )
    async def create_member_session(
        request: Request, payload: MemberSessionRequest
    ) -> SessionResponse | JSONResponse:
        try:
            return await app.state.member_session_handler.create(payload)
        except MemberSessionFailure as exc:
            return _problem(
                request,
                exc.status,
                exc.code,
                exc.title,
                retryable=exc.retryable,
            )

    @app.post("/v1/auth/staff/session", tags=["Authentication"], response_model=StaffSessionResponse)
    async def create_staff_session(request: Request, payload: StaffSessionRequest):
        try:
            return await app.state.staff_session_handler.create(payload)
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/auth/refresh",
        tags=["Authentication"],
        response_model=SessionResponse | StaffSessionResponse,
    )
    async def refresh_session(request: Request, payload: RefreshRequest):
        try:
            return await app.state.session_controls.refresh(payload.refresh_token)
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    def bearer_token(request: Request) -> str:
        header = request.headers.get("Authorization", "")
        scheme, separator, token = header.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or any(char.isspace() for char in token):
            raise denied()
        return token

    async def session_operation(request: Request, action: str, target: uuid.UUID | None = None):
        try:
            token = bearer_token(request)
            controls = app.state.session_controls
            if action == "list":
                return await controls.list_sessions(token)
            if action == "logout":
                await controls.logout(token)
            else:
                await controls.revoke(token, target)
            return Response(status_code=204)
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get("/v1/me/sessions", tags=["Authentication"], response_model=list[SessionSummary])
    async def list_my_sessions(request: Request):
        return await session_operation(request, "list")

    @app.post("/v1/auth/logout", tags=["Authentication"], status_code=204, response_class=Response)
    async def logout_session(request: Request):
        return await session_operation(request, "logout")

    @app.delete(
        "/v1/me/sessions/{sessionId}",
        tags=["Authentication"],
        status_code=204,
        response_class=Response,
    )
    async def revoke_my_session(request: Request, sessionId: uuid.UUID):
        return await session_operation(request, "revoke", sessionId)

    @app.get("/v1/me/profile", tags=["Profile"], response_model=Profile, response_model_exclude_none=True)
    async def get_my_profile(request: Request):
        try:
            return await app.state.profile_service.get(bearer_token(request))
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.patch("/v1/me/profile", tags=["Profile"], response_model=Profile, response_model_exclude_none=True)
    async def update_my_profile(request: Request, payload: ProfileUpdate):
        try:
            return await app.state.profile_service.update(
                bearer_token(request), payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/me/profile/photo-upload",
        tags=["Profile"],
        response_model=UploadAuthorisation,
        status_code=201,
    )
    async def start_profile_photo_upload(request: Request, payload: PhotoUploadRequest):
        try:
            return await app.state.profile_photo_service.start(
                bearer_token(request), payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/me/profile/photo-upload/{uploadId}/complete",
        tags=["Profile"],
        response_model=Profile,
        response_model_exclude_none=True,
    )
    async def complete_profile_photo_upload(request: Request, uploadId: uuid.UUID):
        try:
            return await app.state.profile_photo_service.complete(
                bearer_token(request), uploadId, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/contributor/content-uploads",
        tags=["Content"],
        response_model=ContentUploadAuthorisation,
        status_code=201,
    )
    async def start_content_upload(request: Request, payload: ContentUploadRequest):
        try:
            return await app.state.content_upload_service.start(
                bearer_token(request), payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/contributor/content-uploads/{uploadId}/complete",
        tags=["Content"],
        response_model=ContentUploadReceipt,
    )
    async def complete_content_upload(request: Request, uploadId: uuid.UUID):
        try:
            return await app.state.content_upload_service.complete(
                bearer_token(request), uploadId, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get(
        "/v1/admin/content-moderation",
        tags=["Administration"],
        response_model=list[ModerationQueueItem],
    )
    async def list_content_moderation_queue(request: Request):
        try:
            return await app.state.content_moderation_service.queue(bearer_token(request))
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get(
        "/v1/admin/content-moderation/{contentItemId}/preview",
        tags=["Administration"],
        response_model=ModerationPreview,
    )
    async def preview_content_for_moderation(request: Request, contentItemId: uuid.UUID):
        try:
            return await app.state.content_moderation_service.preview(
                bearer_token(request), contentItemId
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/admin/content-moderation/{contentItemId}/decision",
        tags=["Administration"],
        response_model=ModerationDecisionReceipt,
    )
    async def decide_content_moderation(
        request: Request,
        contentItemId: uuid.UUID,
        payload: ModerationDecisionRequest,
    ):
        try:
            return await app.state.content_moderation_service.decide(
                bearer_token(request), contentItemId, payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/admin/content/{contentItemId}/publication",
        tags=["Administration"],
        response_model=ContentPublicationReceipt,
    )
    async def publish_content(
        request: Request,
        contentItemId: uuid.UUID,
        payload: ContentPublicationRequest,
    ):
        try:
            return await app.state.content_feed_service.publish(
                bearer_token(request), contentItemId, payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get("/v1/feed", tags=["Content"], response_model=FeedPage)
    async def get_content_feed(request: Request, limit: int = 20, cursor: str | None = None):
        if not 1 <= limit <= 50:
            return _problem(request, 400, "VALIDATION_FAILED", "Request validation failed")
        try:
            return await app.state.content_feed_service.feed(
                bearer_token(request), limit, cursor
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get("/v1/feed/{contentItemId}/media", tags=["Content"], response_model=FeedMedia)
    async def get_content_media(request: Request, contentItemId: uuid.UUID):
        try:
            return await app.state.content_feed_service.media(
                bearer_token(request), contentItemId
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get(
        "/v1/me/notification-preferences",
        tags=["Notifications"],
        response_model=NotificationPreferences,
    )
    async def get_my_notification_preferences(request: Request):
        try:
            return await app.state.notification_preferences_service.get(bearer_token(request))
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.put(
        "/v1/me/notification-preferences",
        tags=["Notifications"],
        response_model=NotificationPreferences,
    )
    async def replace_my_notification_preferences(request: Request, payload: NotificationPreferencesUpdate):
        try:
            return await app.state.notification_preferences_service.replace(
                bearer_token(request), payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get("/v1/me/circles", tags=["Circles"], response_model=list[CircleSummary])
    async def list_my_circles(request: Request):
        try:
            return await app.state.circle_service.list_mine(bearer_token(request))
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post("/v1/me/circles/{circleId}/membership", tags=["Circles"], status_code=204)
    async def join_circle(request: Request, circleId: uuid.UUID):
        try:
            await app.state.circle_service.join(bearer_token(request), circleId, request.state.trace_id)
            return Response(status_code=204)
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.delete("/v1/me/circles/{circleId}/membership", tags=["Circles"], status_code=204)
    async def leave_circle(request: Request, circleId: uuid.UUID):
        try:
            await app.state.circle_service.leave(bearer_token(request), circleId, request.state.trace_id)
            return Response(status_code=204)
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get("/v1/admin/circles", tags=["Administration"], response_model=list[CircleSummary])
    async def list_admin_circles(request: Request):
        try:
            return await app.state.circle_service.list_all(bearer_token(request))
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post("/v1/admin/circles", tags=["Administration"], response_model=CircleSummary, status_code=201)
    async def create_circle(request: Request, payload: CircleCreate):
        try:
            return await app.state.circle_service.create(
                bearer_token(request), payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.patch("/v1/admin/circles/{circleId}", tags=["Administration"], response_model=CircleSummary)
    async def update_circle(request: Request, circleId: uuid.UUID, payload: CircleUpdate):
        try:
            return await app.state.circle_service.update(
                bearer_token(request), circleId, payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.post(
        "/v1/admin/users/{userId}/circles/{circleId}/membership",
        tags=["Administration"],
        status_code=204,
    )
    async def assign_circle(request: Request, userId: uuid.UUID, circleId: uuid.UUID):
        try:
            await app.state.circle_service.assign(
                bearer_token(request), userId, circleId, request.state.trace_id
            )
            return Response(status_code=204)
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.delete(
        "/v1/admin/users/{userId}/circles/{circleId}/membership",
        tags=["Administration"],
        status_code=204,
    )
    async def remove_circle(request: Request, userId: uuid.UUID, circleId: uuid.UUID):
        try:
            await app.state.circle_service.remove(
                bearer_token(request), userId, circleId, request.state.trace_id
            )
            return Response(status_code=204)
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get("/v1/admin/circle-settings", tags=["Administration"], response_model=CircleSettings)
    async def get_circle_settings(request: Request):
        try:
            return await app.state.circle_service.settings(bearer_token(request))
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.put("/v1/admin/circle-settings", tags=["Administration"], response_model=CircleSettings)
    async def replace_circle_settings(request: Request, payload: CircleSettingsUpdate):
        try:
            return await app.state.circle_service.replace_settings(
                bearer_token(request), payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.patch("/v1/admin/users/{userId}/status", tags=["Administration"], response_model=AccountSummary)
    async def change_account_status(request: Request, userId: uuid.UUID, payload: StatusChangeRequest):
        try:
            return await app.state.account_controls.status(
                bearer_token(request), userId, payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.patch("/v1/admin/users/{userId}/role", tags=["Administration"], response_model=AccountSummary)
    async def change_account_role(request: Request, userId: uuid.UUID, payload: RoleChangeRequest):
        try:
            return await app.state.account_controls.role(
                bearer_token(request), userId, payload, request.state.trace_id
            )
        except MemberSessionFailure as exc:
            return _problem(request, exc.status, exc.code, exc.title, retryable=exc.retryable)

    @app.get("/ready", tags=["Operations"], response_model=HealthResponse)
    async def ready(request: Request) -> JSONResponse:
        async def check_dependency(name: str, probe: DependencyProbe) -> tuple[str, bool, str]:
            try:
                result = await asyncio.wait_for(probe.check(), timeout=probe_timeout_seconds)
                return name, result.ready is True, "ready" if result.ready is True else "unavailable"
            except TimeoutError:
                return name, False, "timeout"
            except Exception:
                logger.exception("readiness_probe_failed", extra={"dependency": name})
                return name, False, "error"

        checks = await asyncio.gather(
            *(check_dependency(name, probe) for name, probe in readiness_probes.items())
        )
        is_ready = len(checks) == len(REQUIRED_DEPENDENCIES) and all(ready for _, ready, _ in checks)
        if is_ready:
            return JSONResponse({"status": "ok"})
        for name, dependency_ready, outcome in checks:
            if not dependency_ready:
                logger.warning(
                    "readiness_failed", extra={"dependency": name, "context": {"outcome": outcome}}
                )
        response = _problem(
            request,
            503,
            "DEPENDENCY_UNAVAILABLE",
            "A required dependency is unavailable",
            retryable=True,
        )
        response.headers["Retry-After"] = "30"
        return response

    return app
