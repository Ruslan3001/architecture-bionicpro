#!/usr/bin/env python3
"""
Скрипт проверки наличия данных для отчётов BionicPRO.

Проверяет:
1. Сырые данные телеметрии в PostgreSQL (source_db).
2. Агрегированные данные в витрине ClickHouse (reports.prosthesis_report_mart).
3. Выводит рекомендуемый период для запроса отчёта через report-service.

Подключения берутся из docker-compose.yaml проекта (порты проброшены наружу).

Запуск:
    python check_reports_data.py

Требования:
    pip install psycopg2-binary clickhouse-driver
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Параметры подключения (соответствуют docker-compose.yaml)
# ---------------------------------------------------------------------------
POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5435,
    "dbname": "source_db",
    "user": "source_admin",
    "password": "source_password",
}

CLICKHOUSE_CONFIG = {
    "host": "localhost",
    "port": 9000,
    "database": "reports",
    "user": "reports",
    "password": "reports_password",
}


def _check_dependencies() -> None:
    try:
        import psycopg2  # noqa: F401
        from clickhouse_driver import Client  # noqa: F401
    except ImportError as exc:
        module = exc.name
        print("Ошибка: не установлен необходимый Python-пакет.")
        if module and "clickhouse" in module:
            print("  Установите: pip install clickhouse-driver")
        elif module and "psycopg2" in module:
            print("  Установите: pip install psycopg2-binary")
        else:
            print("  Установите: pip install psycopg2-binary clickhouse-driver")
        print("\nЛибо используйте bash-скрипт: ./check_reports_data.sh")
        sys.exit(1)


def _fetch_postgres_telemetry_dates() -> list[dict[str, Any]]:
    import psycopg2

    query = """
        SELECT
            recorded_at::date AS telemetry_date,
            external_user_id,
            COUNT(*)::int AS records_count
        FROM telemetry.sensor_data
        GROUP BY recorded_at::date, external_user_id
        ORDER BY telemetry_date DESC, external_user_id ASC;
    """
    with psycopg2.connect(**POSTGRES_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in rows]


def _fetch_clickhouse_mart_dates() -> list[dict[str, Any]]:
    from clickhouse_driver import Client

    client = Client(**CLICKHOUSE_CONFIG)
    query = """
        SELECT
            report_date,
            external_user_id,
            count() AS records_count
        FROM reports.prosthesis_report_mart
        GROUP BY report_date, external_user_id
        ORDER BY report_date DESC, external_user_id ASC;
    """
    rows = client.execute(query)
    return [
        {
            "report_date": row[0],
            "external_user_id": row[1],
            "records_count": row[2],
        }
        for row in rows
    ]


def _print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def _format_period(period_from: date, period_to: date) -> str:
    return f"period_from={period_from.isoformat()}&period_to={period_to.isoformat()}"


def main() -> int:
    _check_dependencies()

    today = date.today()
    yesterday = today - timedelta(days=1)

    # -----------------------------------------------------------------------
    # 1. PostgreSQL — сырые данные телеметрии
    # -----------------------------------------------------------------------
    _print_section("1. Источник: PostgreSQL (telemetry.sensor_data)")
    try:
        telemetry_rows = _fetch_postgres_telemetry_dates()
    except Exception as exc:
        print(f"Не удалось подключиться к PostgreSQL: {exc}")
        print("Убедитесь, что контейнер source_db запущен:")
        print("  docker compose ps source_db")
        return 1

    if not telemetry_rows:
        print("В telemetry.sensor_data НЕТ данных.")
        print("Отчёт получить невозможно ни за какой период.")
        return 0

    print(f"{'Дата':<12} {'Пользователь':<14} {'Записей':<10}")
    print("-" * 40)
    for row in telemetry_rows:
        print(
            f"{row['telemetry_date']:<12} "
            f"{row['external_user_id']:<14} "
            f"{row['records_count']:<10}"
        )

    pg_min_date = min(r["telemetry_date"] for r in telemetry_rows)
    pg_max_date = max(r["telemetry_date"] for r in telemetry_rows)
    pg_users = sorted({r["external_user_id"] for r in telemetry_rows})
    print(f"\nДиапазон дат в источнике: {pg_min_date} .. {pg_max_date}")
    print(f"Пользователи в источнике: {', '.join(pg_users)}")

    # -----------------------------------------------------------------------
    # 2. ClickHouse — витрина отчётности
    # -----------------------------------------------------------------------
    _print_section("2. Витрина: ClickHouse (reports.prosthesis_report_mart)")
    try:
        mart_rows = _fetch_clickhouse_mart_dates()
    except Exception as exc:
        print(f"Не удалось подключиться к ClickHouse: {exc}")
        print("Убедитесь, что контейнер clickhouse запущен:")
        print("  docker compose ps clickhouse")
        return 1

    if not mart_rows:
        print("Витрина ClickHouse ПУСТА.")
        print("В PostgreSQL есть данные, но они ещё не загружены в ClickHouse.")
        print("\nВозможные действия:")
        print("  a) Дождитесь запуска DAG prosthesis_reports_mart (03:00 ночи)")
        print("  b) Запустите DAG вручную через Airflow UI: http://localhost:8081")
        print("  c) Выполните backfill за нужные даты, например:")
        print("     docker compose exec airflow-scheduler airflow dags trigger")
        print("       prosthesis_reports_mart --exec-date 2026-07-15")
        print("\nПосле загрузки данные в отчёте появятся за период:")
        print(f"  {pg_min_date} .. {pg_max_date}")
        return 0

    print(f"{'Дата отчёта':<14} {'Пользователь':<14} {'Строк':<10}")
    print("-" * 42)
    for row in mart_rows:
        print(
            f"{row['report_date']:<14} "
            f"{row['external_user_id']:<14} "
            f"{row['records_count']:<10}"
        )

    ch_min_date = min(r["report_date"] for r in mart_rows)
    ch_max_date = max(r["report_date"] for r in mart_rows)
    ch_users = sorted({r["external_user_id"] for r in mart_rows})
    print(f"\nДиапазон дат в витрине:   {ch_min_date} .. {ch_max_date}")
    print(f"Пользователи в витрине:   {', '.join(ch_users)}")

    # -----------------------------------------------------------------------
    # 3. Рекомендация по периоду
    # -----------------------------------------------------------------------
    _print_section("3. Рекомендация по выбору периода отчёта")

    if ch_min_date == ch_max_date:
        recommended_from = ch_min_date
        recommended_to = ch_max_date
    else:
        # report-service по умолчанию берёт последние 30 дней до вчера,
        # но для тестовых данных достаточно диапазона витрины.
        recommended_from = ch_min_date
        recommended_to = ch_max_date
        if recommended_to > yesterday:
            recommended_to = yesterday

    print(f"Ближайший период с результатом: {recommended_from} — {recommended_to}")
    print(f"\nURL для report-service:")
    print(
        f"  http://localhost:8000/reports?{_format_period(recommended_from, recommended_to)}"
    )
    print(f"\nПараметры для фронтенда / ReportPage:")
    print(f"  period_from: {recommended_from}")
    print(f"  period_to:   {recommended_to}")

    missing_in_mart = [
        row
        for row in telemetry_rows
        if not any(
            mr["report_date"] == row["telemetry_date"]
            and mr["external_user_id"] == row["external_user_id"]
            for mr in mart_rows
        )
    ]
    if missing_in_mart:
        print("\nВнимание: есть даты в источнике, которых ещё нет в витрине:")
        for row in missing_in_mart:
            print(
                f"  - {row['telemetry_date']} / {row['external_user_id']} "
                f"({row['records_count']} записей)"
            )
        print("Запустите DAG prosthesis_reports_mart за эти даты, чтобы получить отчёт.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
