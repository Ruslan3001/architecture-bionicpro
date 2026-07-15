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

## Запуск и проверка локально

```bash
# Запуск инфраструктуры
docker compose up -d

# Точки доступа:
# - Frontend (React):     http://localhost:3000
# - Keycloak Admin Panel: http://localhost:8080 (admin / admin)

```

### Тестовые учётные записи (Keycloak Realm)

| Логин | Пароль | Роль (RBAC) | Описание |
| --- | --- | --- | --- |
| `prothetic1` | `prothetic123` | `prothetic_user` | Пилот протеза (доступ только к своим отчётам) |
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