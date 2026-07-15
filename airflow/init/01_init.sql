-- Инициализация тестовых источников данных для ETL.
-- Используется сервисом source_db (Postgres).

CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS telemetry;

-- CRM: клиенты и протезы
CREATE TABLE IF NOT EXISTS crm.clients (
    id SERIAL PRIMARY KEY,
    external_user_id VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm.prosthetics (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES crm.clients(id),
    model VARCHAR(255) NOT NULL,
    serial_number VARCHAR(255) NOT NULL UNIQUE,
    issued_at DATE NOT NULL
);

-- Telemetry: сырые данные с датчиков протеза
CREATE TABLE IF NOT EXISTS telemetry.sensor_data (
    id SERIAL PRIMARY KEY,
    external_user_id VARCHAR(255) NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    movement_type VARCHAR(100) NOT NULL,
    signal_value FLOAT NOT NULL,
    response_time_ms INTEGER NOT NULL
);

-- Тестовые данные
INSERT INTO crm.clients (external_user_id, full_name, email) VALUES
('prothetic1', 'Иван Иванов', 'ivan@example.com'),
('prothetic2', 'Пётр Петров', 'peter@example.com')
ON CONFLICT (external_user_id) DO NOTHING;

INSERT INTO crm.prosthetics (client_id, model, serial_number, issued_at) VALUES
((SELECT id FROM crm.clients WHERE external_user_id = 'prothetic1'), 'BionicPRO-100', 'SN001', '2025-01-15'),
((SELECT id FROM crm.clients WHERE external_user_id = 'prothetic2'), 'BionicPRO-200', 'SN002', '2025-02-10')
ON CONFLICT (serial_number) DO NOTHING;

INSERT INTO telemetry.sensor_data (external_user_id, recorded_at, movement_type, signal_value, response_time_ms)
SELECT
    'prothetic1',
    NOW() - (INTERVAL '1 day' * (RANDOM() * 2)::int) - (RANDOM() * INTERVAL '12 hours'),
    (ARRAY['grip', 'pinch', 'open', 'close'])[(RANDOM() * 4)::int + 1],
    0.5 + RANDOM() * 0.5,
    50 + (RANDOM() * 100)::int
FROM generate_series(1, 50);

INSERT INTO telemetry.sensor_data (external_user_id, recorded_at, movement_type, signal_value, response_time_ms)
SELECT
    'prothetic2',
    NOW() - (INTERVAL '1 day' * (RANDOM() * 2)::int) - (RANDOM() * INTERVAL '12 hours'),
    (ARRAY['grip', 'pinch', 'open', 'close'])[(RANDOM() * 4)::int + 1],
    0.4 + RANDOM() * 0.6,
    60 + (RANDOM() * 120)::int
FROM generate_series(1, 40);
