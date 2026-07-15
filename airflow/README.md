# Airflow ETL для витрины отчётности BionicPRO

Папка содержит DAG и инфраструктуру для формирования витрины отчётности `reports.prosthesis_report_mart` в ClickHouse.

## Структура

```text
airflow/
├── Dockerfile              # Образ Airflow с нужными Python-зависимостями
├── requirements.txt        # Зависимости
├── dags/
│   └── reports_mart_dag.py # DAG prosthesis_reports_mart
└── init/
    └── 01_init.sql         # Тестовые схемы и данные CRM + Telemetry
```

## DAG `prosthesis_reports_mart`

- **Расписание:** ежедневно в 03:00 (`0 3 * * *`).
- **Задачи:**
  1. `ensure_mart_table` — создаёт БД и таблицу в ClickHouse.
  2. `extract_crm` — извлекает справочник клиентов и протезов.
  3. `extract_telemetry` — извлекает телеметрию за расчётный день `{{ ds }}`.
  4. `transform_and_load` — объединяет данные, агрегирует и загружает в ClickHouse.
- **Идемпотентность:** перед загрузкой удаляются строки за текущий `report_date`.

## Запуск локально

```bash
docker compose up -d --build
```

Точки доступа:

- Airflow UI: http://localhost:8081 (admin / admin)
- ClickHouse HTTP: http://localhost:8123
- ClickHouse native: `localhost:9000`
- Source DB (CRM + Telemetry): `localhost:5435`
