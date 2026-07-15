# Report Service (API отчётности BionicPRO)

Бэкенд-сервис на Python + FastAPI, который предоставляет API `/reports` для получения агрегированных отчётов о работе протеза из витрины ClickHouse.

## Эндпоинты

- `GET /health` — health-check.
- `GET /reports?period_from=YYYY-MM-DD&period_to=YYYY-MM-DD` — отчёт пользователя.
  - Требует Bearer JWT от Keycloak.
  - Пользователь получает только собственный отчёт (`preferred_username` из токена).
  - Данные читаются из готовой витрины `reports.prosthesis_report_mart`, сложных вычислений в реальном времени не выполняется.

## Запуск локально

Через docker compose:

```bash
docker compose up -d --build report-service
```

Swagger UI: http://localhost:8000/docs

## Переменные окружения

| Переменная | Значение по умолчанию | Описание |
|------------|----------------------|----------|
| `CLICKHOUSE_HOST` | `clickhouse` | Хост ClickHouse |
| `CLICKHOUSE_PORT` | `9000` | Порт ClickHouse (native) |
| `CLICKHOUSE_DB` | `reports` | База данных |
| `CLICKHOUSE_USER` | `reports` | Пользователь ClickHouse |
| `CLICKHOUSE_PASSWORD` | `reports_password` | Пароль ClickHouse |
| `KEYCLOAK_URL` | `http://keycloak:8080` | URL Keycloak |
| `KEYCLOAK_REALM` | `reports-realm` | Realm |
| `KEYCLOAK_CLIENT_ID` | `reports-api` | Client ID для introspection |
| `KEYCLOAK_CLIENT_SECRET` | `oNwoLQdvJAvRcL89SydqCWCe5ry1jMgq` | Client secret |
