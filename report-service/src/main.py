"""
Reports API для BionicPRO.

Предоставляет эндпоинт /reports, который возвращает агрегированный отчёт
о работе протеза из витрины ClickHouse. Доступ возможен только после
аутентификации через Keycloak, и пользователь может запросить только
собственный отчёт.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import requests
from clickhouse_driver import Client
from fastapi import Depends, FastAPI, HTTPException, Query, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Конфигурация сервиса через переменные окружения."""

    app_name: str = "BionicPRO Reports API"
    debug: bool = Field(default=False, alias="DEBUG")

    # ClickHouse
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 9000
    clickhouse_db: str = "reports"
    clickhouse_user: str = "reports"
    clickhouse_password: str = "reports_password"
    clickhouse_mart_table: str = "prosthesis_report_mart"

    # Keycloak
    keycloak_url: str = "http://keycloak:8080"
    keycloak_realm: str = "reports-realm"
    keycloak_client_id: str = "reports-api"
    keycloak_client_secret: str = "oNwoLQdvJAvRcL89SydqCWCe5ry1jMgq"

    class Config:
        env_prefix = ""
        extra = "ignore"


settings = Settings()
app = FastAPI(title=settings.app_name)

# Разрешаем CORS для локальной разработки фронтенда / BFF
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = HTTPBearer(auto_error=True)


def _clickhouse_client() -> Client:
    return Client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_db,
        user=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )


def _introspect_token(token: str) -> dict[str, Any]:
    """Проверяет токен через Keycloak Token Introspection Endpoint."""
    url = (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/token/introspect"
    )
    data = {
        "token": token,
        "client_id": settings.keycloak_client_id,
        "client_secret": settings.keycloak_client_secret,
    }
    try:
        response = requests.post(url, data=data, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Auth service unavailable: {exc}",
        )

    payload = response.json()
    if not payload.get("active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(oauth2_scheme),
) -> dict[str, Any]:
    """Извлекает идентификатор текущего пользователя из Bearer-токена."""
    payload = _introspect_token(credentials.credentials)
    # Внешний идентификатор пользователя в CRM/ClickHouse совпадает с preferred_username
    user_id = payload.get("preferred_username") or payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain user identifier",
        )
    return {
        "user_id": user_id,
        "email": payload.get("email"),
        "roles": payload.get("realm_access", {}).get("roles", []),
    }


@app.get("/reports", summary="Получить отчёт о работе протеза")
def get_reports(
    period_from: date | None = Query(
        default=None,
        description="Начало периода (YYYY-MM-DD). По умолчанию 30 дней назад.",
    ),
    period_to: date | None = Query(
        default=None,
        description="Конец периода (YYYY-MM-DD). По умолчанию вчера.",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Возвращает подготовленный отчёт по пользователю из витрины ClickHouse.

    Пользователь может получить отчёт только за себя. Все вычисления
    выполнены заранее в Airflow, API делает только SELECT из готовой витрины.
    """
    user_id = current_user["user_id"]

    today = date.today()
    if period_to is None:
        period_to = today - timedelta(days=1)
    if period_from is None:
        period_from = period_to - timedelta(days=29)

    if period_from > period_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_from cannot be greater than period_to",
        )

    client = _clickhouse_client()
    query = f"""
        SELECT
            external_user_id,
            full_name,
            prosthetic_model,
            prosthetic_serial,
            report_date,
            movements_count,
            avg_signal_value,
            max_signal_value,
            min_signal_value,
            avg_response_time_ms,
            usage_minutes
        FROM {settings.clickhouse_mart_table}
        WHERE external_user_id = %(user_id)s
          AND report_date >= %(period_from)s
          AND report_date <= %(period_to)s
        ORDER BY report_date ASC
    """
    rows = client.execute(
        query,
        {
            "user_id": user_id,
            "period_from": period_from.isoformat(),
            "period_to": period_to.isoformat(),
        },
    )

    columns = [
        "external_user_id",
        "full_name",
        "prosthetic_model",
        "prosthetic_serial",
        "report_date",
        "movements_count",
        "avg_signal_value",
        "max_signal_value",
        "min_signal_value",
        "avg_response_time_ms",
        "usage_minutes",
    ]
    reports = [dict(zip(columns, row)) for row in rows]

    return {
        "user_id": user_id,
        "period_from": period_from.isoformat(),
        "period_to": period_to.isoformat(),
        "count": len(reports),
        "reports": reports,
    }


@app.get("/health", summary="Health-check")
def health() -> dict[str, str]:
    return {"status": "ok"}
