# Архитектура безопасности BionicPRO

## Обзор решения

Данная архитектура обеспечивает безопасное управление учётными данными в системе BionicPRO с соблюдением требований [[Clean Architecture]] и международных стандартов безопасности:

1. **Унификация доступа** — централизованная аутентификация через [[Keycloak Identity Brokering]] с поддержкой внешних удостоверяющих служб разных стран.
2. **Безопасность токенов (Zero-Token Leakage)** — клиентские приложения (Web и Mobile) НЕ получают токены от IdP напрямую, а работают исключительно через зашифрованные session cookies по паттерну [[BFF Pattern]].
3. **Локальное хранение данных** — соблюдение национальных законодательств (ФЗ-152, GDPR): персональные и медицинские данные хранятся в стране присутствия, а в системе циркулирует только обезличенный маппинг идентификаторов (`sub` -> `user_id`).

## Компоненты архитектуры

### 1. Identity Federation Layer
**IdP Broker (Keycloak)** — единая точка доверия и федерации идентичности:
- Подключается к внешним IdP по протоколам OIDC / SAML 2.0.
- Осуществляет маппинг внешних идентификаторов на внутренние учётные записи BionicPRO.
- Выпускает короткоживущие JWT (Access Tokens) и Refresh Tokens для внутренних сервисов.

**Внешние IdP:**
- **Россия:** Госуслуги / корпоративные IdP (OIDC / SAML 2.0).
- **ЕС:** eID / NPA (SAML 2.0).
- **Другие страны:** локальные сертифицированные удостоверяющие службы.

### 2. BFF / API Gateway (Backend-for-Frontend)
**Node.js / Express Gateway** — проксирующий слой между клиентскими приложениями и внутренним API:
- Инициирует [[OAuth 2.0 PKCE]] Flow для веб- и мобильных клиентов.
- Управляет пользовательскими сессиями через HttpOnly, Secure, SameSite cookies.
- Прячет Access и Refresh токены в [[Token Vault]] (клиентский код не имеет к ним доступа).
- Проксирует запросы к бизнес-API, оборачивая их в Bearer JWT.
- Автоматически выполняет бесшовный refresh токенов по истечении срока жизни Access Token.

### 3. Token Vault
**Redis (Encrypted Storage)** — изолированное серверное хранилище токенов:
- Токены шифруются по стандарту [[AES-256-GCM]] перед записью в память.
- Жесткая привязка к `session_id` пользователя.
- Автоматическая инвалидация (TTL) при завершении сессии или выходе из системы.

### 4. Клиентские приложения (Web & Mobile)
- **Веб-приложение (React / TypeScript)** и **Мобильное приложение (iOS / Android на React Native)** не содержат логики работы с JWT.
- Взаимодействуют с BFF исключительно по HTTPS, передавая сессионную куку. Это полностью исключает риск кражи токенов через XSS-уязвимости.

## Потоки аутентификации (Authentication Flows)

### 1. Пользовательский поток: PKCE Flow via BFF (Web & Mobile)
Безопасная аутентификация для клиентов с интерактивным UI (Proof Key for Code Exchange, RFC 7636):

```text
[Web / Mobile Client] ──(1. Login)──> [BFF Gateway] ──(2. PKCE Auth URL)──> [Keycloak / External IdP]
         ^                                 │                                          │
         │                         (6. Save Tokens)                               (3. User Auth)
         │                                 ↓                                          │
 [Session Cookie] <──(7. Set Cookie)── [Token Vault] <──(5. Exchange Code)─── (4. Auth Code + State)

```

1. Клиент (React/Mobile) запрашивает авторизацию у BFF.
2. BFF генерирует криптографическую пару `code_verifier` и `code_challenge` (SHA-256) и редиректит пользователя на Keycloak.
3. Keycloak проводит аутентификацию через выбранный внешний IdP.
4. Keycloak возвращает `authorization code` на callback-эндпоинт BFF.
5. BFF обменивает `code` + `code_verifier` на пару токенов (Access + Refresh).
6. BFF шифрует и сохраняет токены в Redis Token Vault.
7. Клиенту устанавливается защищенная сессионная кука (`HttpOnly`, `Secure`, `SameSite=Strict`).

### 2. M2M-поток: ESP32 Чип протеза (Client Credentials Grant)

Поскольку микроконтроллер в протезе не имеет графического интерфейса для ввода логина/пароля, используется межсервисная аутентификация:

* **Программа в чипе** напрямую обращается к Keycloak по протоколу `OAuth 2.0 Client Credentials Grant`, предъявляя вшитые защищенные сертификаты/ключи устройства.
* Полученный короткоживущий Access Token используется для отправки телеметрии напрямую в бизнес-API (без участия BFF).

### 3. Инженерный поток: ML-инженер (Device / Client Credentials Flow)

* **CLI-утилита** ML-инженера для выгрузки аналитических витрин из ClickHouse/CRM использует `OAuth 2.0 Device Authorization Grant` или индивидуальные сервисные аккаунты (`Client Credentials`) для получения JWT и безопасных запросов к API.

## Матрица угроз и меры защиты

| Атака / Уязвимость | Реализованная мера защиты |
| --- | --- |
| **XSS (Cross-Site Scripting)** | Токены отсутствуют в браузере. Используются `HttpOnly` cookies, недоступные для JavaScript. |
| **CSRF (Cross-Site Request Forgery)** | Строгие флаги `SameSite=Strict` для cookies + валидача `state` параметра при OIDC-федерации. |
| **Утечка токенов с устройства** | [[Zero-Token Leakage]]: Access/Refresh токены хранятся только в зашифрованном Redis на бэкенде. |
| **Перехват Authorization Code** | Использование расширения [[OAuth 2.0 PKCE]] с методом шифрования `S256`. |
| **Replay & MitM Attacks** | Проверка `nonce`, обязательное использование TLS 1.3 (HTTPS), короткий TTL Access-токенов (5-15 мин). |
| **Несанкционированный доступ к данным** | Строгая реализация [[RBAC]] (Role-Based Access Control) на уровне API; проверка `user_id` из JWT при генерации отчётов. |

## Структура проекта

```text
architecture-bionicpro/
├── airflow/                        # ETL на Apache Airflow
│   ├── dags/
│   │   └── reports_mart_dag.py    # DAG формирования витрины отчётности в ClickHouse
│   ├── init/
│   │   └── 01_init.sql            # Тестовые схемы CRM и Telemetry
│   ├── Dockerfile
│   └── requirements.txt
├── bff-service/                    # BFF / API Gateway сервис
│   ├── src/
│   │   ├── index.ts               # Точка входа Express
│   │   ├── middleware/
│   │   │   └── auth.ts            # Валидация сессий и инжект JWT в прокси-запросы
│   │   ├── services/
│   │   │   └── token-vault.ts     # Клиент Redis и шифрование AES-256-GCM
│   │   └── utils/
│   │       └── pkce.ts            # Генерация Code Verifier / Challenge
│   ├── Dockerfile
│   ├── package.json
│   └── tsconfig.json
├── report-service/                 # API отчётности (FastAPI + ClickHouse)
│   ├── src/
│   │   └── main.py                # Эндпоинт /reports с проверкой JWT (Keycloak)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                       # Веб-приложение (React + TypeScript)
│   └── src/
│       ├── App.tsx                # Главный компонент (работа через session cookie)
│       └── services/
│           └── auth.ts            # API-клиент для вызовов к BFF (/api/auth/login, /logout)
├── keycloak/
│   └── realm-export.json          # Экспорт реалма BionicPRO (клиенты, RBAC, IdP mappers)
├── docker-compose.yaml             # Оркестрация инфраструктуры и сервисов
└── BionicPRO_C4_model_security.drawio  # Архитектурная диаграмма C4 (To-Be)

```

## Алгоритм работы решения

### 1. Подготовка данных (ETL)

1. **PostgreSQL (`source_db`)** содержит операционные данные:
   - `crm.clients` и `crm.prosthetics` — справочник пользователей и протезов;
   - `telemetry.sensor_data` — сырые телеметрические записи с датчиков протеза.
2. **Apache Airflow DAG `prosthesis_reports_mart`** запускается ежедневно в 03:00 и обрабатывает данные за предыдущий день (`{{ ds }}`):
   - извлекает справочник клиентов/протезов из CRM;
   - извлекает телеметрию за расчётный день;
   - агрегирует показатели: количество движений, средний/максимальный/минимальный сигнал, среднее время отклика, минуты использования;
   - создаёт таблицу-витрину `reports.prosthesis_report_mart` в **ClickHouse**, если она отсутствует;
   - идемпотентно перезаписывает данные за расчётный день (удаляет старые строки и вставляет новые).

### 2. Получение отчёта пользователем

1. Пользователь открывает веб-приложение по адресу `http://localhost:3000`.
2. Frontend инициализирует Keycloak JS adapter в режиме `check-sso` с PKCE `S256`.
3. Если пользователь не аутентифицирован, отображается кнопка **«Войти»**. При нажатии выполняется PKCE-поток: браузер перенаправляется на Keycloak, пользователь вводит логин/пароль, Keycloak возвращает authorization code на callback frontend, adapter обменивает code на access token.
4. После входа frontend автоматически запрашивает `GET /reports/availability` у `report-service`, передавая access token в заголовке `Authorization: Bearer <token>`.
5. `report-service` проверяет JWT локально по публичному ключу Keycloak (JWKS), извлекает `preferred_username` как `user_id` и проверяет роль `prothetic_user`.
6. `report-service` запрашивает из ClickHouse минимальную и максимальную дату отчёта для текущего пользователя и возвращает их frontend.
7. Frontend показывает доступный диапазон дат и подставляет его в поля **«С»** и **«По»**.

### 3. Что происходит при нажатии кнопки «Получить отчёт»

1. Frontend проверяет, аутентифицирован ли пользователь. Если нет — показывает ошибку.
2. Frontend формирует URL: `GET /reports?period_from=<date>&period_to=<date>`.
3. Если access token скоро истекает, frontend пытается обновить его через `keycloak.updateToken(30)`. При неудаче предлагает войти заново.
4. Frontend отправляет запрос в `report-service` с заголовком `Authorization: Bearer <access_token>`.
5. `report-service` валидирует JWT:
   - проверяет подпись по JWKS Keycloak;
   - проверяет issuer (принимаются `http://localhost:8080` и `http://127.0.0.1:8080`);
   - проверяет срок действия.
6. `report-service` извлекает `user_id` из токена и проверяет роль `prothetic_user`. Без роли возвращает `403 Forbidden`.
7. `report-service` выполняет SQL-запрос к ClickHouse:
   ```sql
   SELECT *
   FROM prosthesis_report_mart
   WHERE external_user_id = %(user_id)s
     AND report_date >= %(period_from)s
     AND report_date <= %(period_to)s
   ORDER BY report_date ASC
   ```
8. ClickHouse возвращает только строки текущего пользователя. `report-service` формирует JSON-ответ:
   ```json
   {
     "user_id": "prothetic1",
     "period_from": "2026-07-13",
     "period_to": "2026-07-15",
     "count": 3,
     "reports": [...]
   }
   ```
9. Frontend обрабатывает ответ:
   - если `count > 0` — отображает таблицу и предлагает скачать JSON;
   - если `count == 0` — показывает сообщение «Нет данных за выбранный период» с пояснением, что период ещё не обработан Airflow;
   - если `401` — пытается обновить токен и повторить запрос; при повторной неудаче показывает «Ошибка аутентификации. Пожалуйста, войдите снова.»;
   - если `403` — «Доступ запрещён. Вы можете запрашивать только собственный отчёт.»

### 4. Границы безопасности и ограничения

- Пользователь видит **только свои данные**: фильтрация выполняется на уровне SQL по `external_user_id = user_id`.
- `report-service` **не имеет прямого доступа** к сырым источникам PostgreSQL; он читает только агрегированную витрину ClickHouse.
- Генерация отчётов возможна **только за периоды, уже обработанные Airflow**. Запрос за будущие или ещё не загруженные даты вернёт пустой результат (`count: 0`).
- Обновление витрины происходит автоматически ночью; ручной запуск возможен через Airflow UI или CLI.

## Запуск и проверка локально

### Предварительные требования

- Установлены Docker и Docker Compose.
- Свободны порты: `3000`, `5433`, `5435`, `8000`, `8080`, `8081`, `8123`, `9000`.

### Запуск инфраструктуры

```bash
cd architecture-bionicpro
docker compose up -d
```

Подождите 1–2 минуты, пока Keycloak и Airflow завершат инициализацию.

### Точки доступа

| Сервис | URL | Учётные данные |
| --- | --- | --- |
| Frontend (React) | http://localhost:3000 | — |
| Keycloak Admin Panel | http://localhost:8080 | `admin` / `admin` |
| Airflow UI | http://localhost:8081 | `admin` / `admin` |
| Report Service API | http://localhost:8000 | Bearer token |

### Подготовка данных перед первым отчётом

После первого запуска витрина ClickHouse пуста, потому что DAG `prosthesis_reports_mart` срабатывает ежедневно в 03:00. Чтобы получить отчёт сразу, запустите DAG вручную через Airflow UI (`http://localhost:8081`) или CLI:

```bash
docker compose exec airflow-scheduler airflow dags backfill \
  prosthesis_reports_mart \
  -s 2026-07-13 -e 2026-07-16 \
  --reset-dagruns -y
```

Также можно проверить наличие данных скриптом:

```bash
./check_reports_data.sh
```

Скрипт покажет диапазон дат в источнике PostgreSQL, уже загруженные даты в ClickHouse и рекомендуемый период для отчёта.

### Тестовые учётные записи (Keycloak Realm)

| Логин | Пароль | Роль (RBAC) | Описание |
| --- | --- | --- | --- |
| `prothetic1` | `prothetic123` | `prothetic_user` | Пилот протеза (доступ только к своим отчётам) |
| `prothetic2` | `prothetic123` | `prothetic_user` | Пилот протеза (доступ только к своим отчётам) |
| `user1` | `password123` | `user` | Стандартный пользователь |
| `admin1` | `admin123` | `administrator` | Администратор безопасности |


## Изменения в диаграмме C4 (To-Be)

Финальная архитектура отражена в файле `BionicPRO_C4_model_security.drawio`.
[Финальная архитектура отражена в файле `BionicPRO_C4_model_security.drawio`](SECURITY_ARCHITECTURE.md)

**Ключевые архитектурные обновления:**

1. **Добавлен IdP Broker (Keycloak):** изолирует внутреннюю систему от разнородных внешних систем аутентификации.
2. **Внедрен BFF / API Gateway + Redis Token Vault:** ликвидирована уязвимость с утечкой токенов на клиентские устройства, реализован PKCE Flow на стороне бэкенда.
3. **Унифицированы клиенты:** Веб-профиль и Мобильное приложение подключены через единый контур безопасности (Session Cookies).
4. **Легализованы M2M-потоки:** явно выделена безопасная аутентификация ESP32-чипов и CLI-инструментов ML-инженеров напрямую через Keycloak без передачи паролей.