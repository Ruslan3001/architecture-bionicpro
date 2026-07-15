"""
ETL DAG для формирования витрины отчётности BionicPRO.

Источники:
- CRM (Postgres): клиенты и протезы.
- Telemetry DB (Postgres): сырые данные с датчиков протеза.

Приёмник:
- ClickHouse: витрина reports.prosthesis_report_mart.

Расписание: ежедневно в 03:00 (обработка данных за предыдущий день ds).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import psycopg2
from airflow.decorators import dag, task
from clickhouse_driver import Client
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Настройки подключений (передаются через переменные окружения в docker-compose)
# ---------------------------------------------------------------------------
def _crm_conn_kwargs() -> dict[str, Any]:
    return {
        "host": os.getenv("CRM_DB_HOST", "source_db"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_NAME", "source_db"),
        "user": os.getenv("CRM_DB_USER", "source_admin"),
        "password": os.getenv("CRM_DB_PASSWORD", "source_password"),
        "options": f"-c search_path={os.getenv('CRM_DB_SCHEMA', 'crm')}",
    }


def _telemetry_conn_kwargs() -> dict[str, Any]:
    return {
        "host": os.getenv("TELEMETRY_DB_HOST", "source_db"),
        "port": int(os.getenv("TELEMETRY_DB_PORT", "5432")),
        "dbname": os.getenv("TELEMETRY_DB_NAME", "source_db"),
        "user": os.getenv("TELEMETRY_DB_USER", "source_admin"),
        "password": os.getenv("TELEMETRY_DB_PASSWORD", "source_password"),
        "options": f"-c search_path={os.getenv('TELEMETRY_DB_SCHEMA', 'telemetry')}",
    }


def _clickhouse_client() -> Client:
    return Client(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
        database=os.getenv("CLICKHOUSE_DB", "reports"),
        user=os.getenv("CLICKHOUSE_USER", "reports"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "reports_password"),
    )


# ---------------------------------------------------------------------------
# Схема витрины
# ---------------------------------------------------------------------------
MART_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS reports.prosthesis_report_mart (
    external_user_id String,
    full_name String,
    prosthetic_model String,
    prosthetic_serial String,
    report_date Date,
    movements_count UInt32,
    avg_signal_value Float64,
    max_signal_value Float64,
    min_signal_value Float64,
    avg_response_time_ms Float64,
    usage_minutes UInt32
) ENGINE = MergeTree()
ORDER BY (external_user_id, report_date)
PARTITION BY toYYYYMM(report_date)
"""


def _df_to_json(df: pd.DataFrame) -> str:
    return df.to_json(date_format="iso", orient="split")


def _df_from_json(json_str: str) -> pd.DataFrame:
    return pd.read_json(json_str, orient="split")


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------
default_args = {
    "owner": "bionicpro",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="prosthesis_reports_mart",
    default_args=default_args,
    description="ETL: формирование витрины отчётности по протезам в ClickHouse",
    schedule="0 3 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["bionicpro", "reports", "clickhouse"],
)
def prosthesis_reports_mart():
    @task
    def ensure_mart_table() -> None:
        """Создаёт БД и таблицу-витрину в ClickHouse, если их ещё нет."""
        client = _clickhouse_client()
        client.execute("CREATE DATABASE IF NOT EXISTS reports")
        client.execute(MART_TABLE_DDL)

    @task
    def extract_crm() -> str:
        """Загружает справочник клиентов и протезов из CRM."""
        conn = psycopg2.connect(**_crm_conn_kwargs())
        try:
            query = """
                SELECT
                    c.id AS client_id,
                    c.external_user_id,
                    c.full_name,
                    p.id AS prosthetic_id,
                    p.model AS prosthetic_model,
                    p.serial_number AS prosthetic_serial
                FROM clients c
                LEFT JOIN prosthetics p ON p.client_id = c.id
            """
            df = pd.read_sql_query(query, conn)
            return _df_to_json(df)
        finally:
            conn.close()

    @task
    def extract_telemetry(report_date: str) -> str:
        """Загружает телеметрию за расчётный день."""
        conn = psycopg2.connect(**_telemetry_conn_kwargs())
        try:
            query = """
                SELECT
                    external_user_id,
                    recorded_at,
                    movement_type,
                    signal_value,
                    response_time_ms
                FROM sensor_data
                WHERE recorded_at >= %(date)s::date
                  AND recorded_at < %(date)s::date + INTERVAL '1 day'
            """
            df = pd.read_sql_query(query, conn, params={"date": report_date})
            return _df_to_json(df)
        finally:
            conn.close()

    @task
    def transform_and_load(crm_json: str, telemetry_json: str, report_date: str) -> int:
        """Объединяет CRM и телеметрию, агрегирует и загружает в витрину ClickHouse."""
        crm_df = _df_from_json(crm_json)
        telemetry_df = _df_from_json(telemetry_json)

        if crm_df.empty or telemetry_df.empty:
            print("Нет данных для обработки: пропускаем загрузку витрины.")
            return 0

        # Приводим даты
        telemetry_df["recorded_at"] = pd.to_datetime(telemetry_df["recorded_at"])
        telemetry_df["report_date"] = telemetry_df["recorded_at"].dt.date

        # Агрегируем телеметрию по пользователю и дню
        agg = (
            telemetry_df.groupby(["external_user_id", "report_date"])
            .agg(
                movements_count=("movement_type", "size"),
                avg_signal_value=("signal_value", "mean"),
                max_signal_value=("signal_value", "max"),
                min_signal_value=("signal_value", "min"),
                avg_response_time_ms=("response_time_ms", "mean"),
                first_record=("recorded_at", "min"),
                last_record=("recorded_at", "max"),
            )
            .reset_index()
        )

        # usage_minutes — разница между первой и последней записью за день + 1 минута
        agg["usage_minutes"] = (
            pd.to_datetime(agg["last_record"]) - pd.to_datetime(agg["first_record"])
        ).dt.total_seconds() // 60 + 1
        agg["usage_minutes"] = agg["usage_minutes"].astype(int)

        # Объединяем с CRM
        merged = crm_df.merge(agg, on="external_user_id", how="inner")

        # Оставляем только текущий расчётный день
        target_date = pd.to_datetime(report_date).date()
        merged = merged[merged["report_date"] == target_date]

        if merged.empty:
            print(f"Нет телеметрии за {report_date}: пропускаем загрузку.")
            return 0

        # Подготовка строк для ClickHouse
        rows = merged[
            [
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
        ].values.tolist()

        client = _clickhouse_client()
        # Идемпотентность: удаляем старые строки за этот день перед вставкой
        client.execute(
            "ALTER TABLE reports.prosthesis_report_mart DELETE WHERE report_date = %(date)s",
            {"date": report_date},
            settings={"mutations_sync": 1},
        )
        client.execute("INSERT INTO reports.prosthesis_report_mart VALUES", rows)

        print(f"Загружено строк в витрину: {len(rows)}")
        return len(rows)

    # -----------------------------------------------------------------------
    # Поток задач
    # -----------------------------------------------------------------------
    report_date = "{{ ds }}"

    ensure_table = ensure_mart_table()
    crm_data = extract_crm()
    telemetry_data = extract_telemetry(report_date)
    load_mart = transform_and_load(crm_data, telemetry_data, report_date)

    # Справочник CRM и телеметрия могут собираться параллельно,
    # но витрина создаётся/обновляется только после подготовки таблицы.
    ensure_table >> [crm_data, telemetry_data] >> load_mart


dag = prosthesis_reports_mart()
