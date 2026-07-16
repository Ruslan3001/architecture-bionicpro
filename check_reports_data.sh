#!/usr/bin/env bash
# Скрипт проверки наличия данных для отчётов BionicPRO.
# Работает через docker compose exec — не требует Python-драйверов на хосте.
#
# Запуск:
#   ./check_reports_data.sh

set -euo pipefail

COMPOSE_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="bionicpro"

cd "$COMPOSE_PROJECT_DIR"

# ---------------------------------------------------------------------------
# Проверка наличия docker compose
# ---------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    echo "Ошибка: docker не найден. Установите Docker/Docker Desktop."
    exit 1
fi

if ! docker compose version &>/dev/null; then
    echo "Ошибка: 'docker compose' не доступен."
    exit 1
fi

# ---------------------------------------------------------------------------
# Проверка запущенных контейнеров
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "Проверка контейнеров"
echo "======================================================================"

PS_OUTPUT=$(docker compose ps 2>/dev/null || true)

for service in source_db clickhouse; do
    if echo "$PS_OUTPUT" | grep -qE "\b${service}(-[0-9]+)?\b.*\bUp\b"; then
        echo "  [OK] $service запущен"
    else
        echo "  [FAIL] $service не запущен или не найден"
        echo "Запустите стек: docker compose up -d"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# 1. PostgreSQL — сырые данные телеметрии
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "1. Источник: PostgreSQL (telemetry.sensor_data)"
echo "======================================================================"

PG_TELEMETRY=$(docker compose exec -T source_db psql -U source_admin -d source_db -t -A -F "|" <<'SQL'
SELECT
    recorded_at::date AS telemetry_date,
    external_user_id,
    COUNT(*) AS records_count
FROM telemetry.sensor_data
GROUP BY recorded_at::date, external_user_id
ORDER BY telemetry_date DESC, external_user_id ASC;
SQL
)

if [[ -z "$PG_TELEMETRY" ]]; then
    echo "В telemetry.sensor_data НЕТ данных."
    echo "Отчёт получить невозможно ни за какой период."
    exit 0
fi

printf "%-12s %-14s %-10s\n" "Дата" "Пользователь" "Записей"
printf -- "-----------------------------------------\n"
echo "$PG_TELEMETRY" | while IFS='|' read -r t_date user cnt; do
    printf "%-12s %-14s %-10s\n" "$t_date" "$user" "$cnt"
done

PG_MIN_DATE=$(echo "$PG_TELEMETRY" | awk -F'|' '{print $1}' | sort | head -n1)
PG_MAX_DATE=$(echo "$PG_TELEMETRY" | awk -F'|' '{print $1}' | sort -r | head -n1)
PG_USERS=$(echo "$PG_TELEMETRY" | awk -F'|' '{print $2}' | sort -u | tr '\n' ',' | sed 's/,$//')

echo ""
echo "Диапазон дат в источнике: $PG_MIN_DATE .. $PG_MAX_DATE"
echo "Пользователи в источнике: $PG_USERS"

# ---------------------------------------------------------------------------
# 2. ClickHouse — витрина отчётности
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "2. Витрина: ClickHouse (reports.prosthesis_report_mart)"
echo "======================================================================"

CH_TABLE_EXISTS=$(docker compose exec -T clickhouse clickhouse-client \
    --user reports --password reports_password --database reports \
    --query="EXISTS TABLE reports.prosthesis_report_mart" 2>/dev/null || echo "0")

if [[ "$CH_TABLE_EXISTS" != "1" ]]; then
    CH_MART=""
else
    CH_MART=$(docker compose exec -T clickhouse clickhouse-client \
        --user reports --password reports_password --database reports --format=TSV <<'SQL'
SELECT
    report_date,
    external_user_id,
    count() AS records_count
FROM reports.prosthesis_report_mart
GROUP BY report_date, external_user_id
ORDER BY report_date DESC, external_user_id ASC;
SQL
    )
fi

if [[ -z "$CH_MART" ]]; then
    echo "Витрина ClickHouse ПУСТА."
    echo "В PostgreSQL есть данные, но они ещё не загружены в ClickHouse."
    echo ""
    echo "Возможные действия:"
    echo "  a) Дождитесь запуска DAG prosthesis_reports_mart (03:00 ночи)"
    echo "  b) Запустите DAG вручную через Airflow UI: http://localhost:8081"
    echo "  c) Выполните backfill за нужные даты, например:"
    echo "     docker compose exec airflow-scheduler airflow dags trigger"
    echo "       prosthesis_reports_mart --exec-date $PG_MAX_DATE"
    echo ""
    echo "После загрузки данные в отчёте появятся за период:"
    echo "  $PG_MIN_DATE .. $PG_MAX_DATE"
    exit 0
fi

printf "%-14s %-14s %-10s\n" "Дата отчёта" "Пользователь" "Строк"
printf -- "--------------------------------------------\n"
echo "$CH_MART" | while IFS=$'\t' read -r r_date user cnt; do
    printf "%-14s %-14s %-10s\n" "$r_date" "$user" "$cnt"
done

CH_MIN_DATE=$(echo "$CH_MART" | awk -F'\t' '{print $1}' | sort | head -n1)
CH_MAX_DATE=$(echo "$CH_MART" | awk -F'\t' '{print $1}' | sort -r | head -n1)
CH_USERS=$(echo "$CH_MART" | awk -F'\t' '{print $2}' | sort -u | tr '\n' ',' | sed 's/,$//')

echo ""
echo "Диапазон дат в витрине:   $CH_MIN_DATE .. $CH_MAX_DATE"
echo "Пользователи в витрине:   $CH_USERS"

# ---------------------------------------------------------------------------
# 3. Рекомендация по периоду
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "3. Рекомендация по выбору периода отчёта"
echo "======================================================================"

YESTERDAY=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)

if [[ "$CH_MIN_DATE" == "$CH_MAX_DATE" ]]; then
    REC_FROM="$CH_MIN_DATE"
    REC_TO="$CH_MAX_DATE"
else
    REC_FROM="$CH_MIN_DATE"
    REC_TO="$CH_MAX_DATE"
    if [[ "$REC_TO" > "$YESTERDAY" ]]; then
        REC_TO="$YESTERDAY"
    fi
fi

echo "Ближайший период с результатом: $REC_FROM — $REC_TO"
echo ""
echo "URL для report-service:"
echo "  http://localhost:8000/reports?period_from=$REC_FROM&period_to=$REC_TO"
echo ""
echo "Параметры для фронтенда / ReportPage:"
echo "  period_from: $REC_FROM"
echo "  period_to:   $REC_TO"

# ---------------------------------------------------------------------------
# 4. Проверка пропущенных дат
# ---------------------------------------------------------------------------
MISSING=()
while IFS='|' read -r t_date user cnt; do
    found=$(echo "$CH_MART" | awk -F'\t' -v d="$t_date" -v u="$user" '$1==d && $2==u {print}' || true)
    if [[ -z "$found" ]]; then
        MISSING+=("$t_date / $user ($cnt записей)")
    fi
done <<< "$PG_TELEMETRY"

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo ""
    echo "Внимание: есть даты в источнике, которых ещё нет в витрине:"
    for item in "${MISSING[@]}"; do
        echo "  - $item"
    done
    echo "Запустите DAG prosthesis_reports_mart за эти даты, чтобы получить отчёт."
fi
