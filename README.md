# Marketplace CI/CD, Testing and Observability

Система расширена до двух сервисов:

- `api` - основной Marketplace API: auth, products, orders, promo codes.
- `notification` - сервис уведомлений: принимает события заказов и пишет уведомления в БД.
- `db` - PostgreSQL, миграции применяются через Flyway.

## Запуск

```bash
docker compose up -d --build
```

После запуска:

- API: http://localhost:8000
- Notification: http://localhost:8001
- Swagger UI: http://localhost:8080
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (`admin` / `admin`)
- Alertmanager: http://localhost:9093

## Тесты

```bash
make unit
make integration
make e2e
make load
make sli
```

Integration и E2E тесты ожидают поднятый `docker compose` и проверяют реальное взаимодействие `api -> notification -> PostgreSQL`.

## CI pipeline

Workflow: `.github/workflows/ci.yml`.

Пайплайн запускается на `push` и `pull_request`:

1. устанавливает Python-зависимости;
2. запускает unit-тесты;
3. собирает Docker services;
4. поднимает полное compose-окружение;
5. запускает integration и E2E тесты;
6. запускает k6 нагрузку: 10 VU, 30 секунд;
7. проверяет SLI через Prometheus API;
8. сохраняет k6 output, SLI JSON и docker logs как artifacts.

## Метрики

Оба сервиса экспортируют `/metrics` в Prometheus-формате:

- `http_requests_total{service,method,endpoint,status}`
- `http_request_errors_total{service,method,endpoint,error_type}`
- `http_request_duration_seconds_bucket{service,method,endpoint,le}`

Prometheus scrape config лежит в `monitoring/prometheus/prometheus.yml`.

## Dashboards

Grafana provisioning:

- `monitoring/grafana/dashboards/services.json` - latency p50/p95/p99, errors, throughput и latency distribution для `api` и `notification`.
- `monitoring/grafana/dashboards/infrastructure.json` - PostgreSQL active connections, transaction rate, cache hit ratio, DB size.

## Alerts

Alert rules: `monitoring/prometheus/alerts.yml`.

- `MarketplaceHighErrorRate`: error rate API выше 5% за 5 минут.
- `MarketplaceHighLatencyP95`: p95 latency API выше 1 секунды за 5 минут.
- `MarketplaceTargetDown`: Prometheus не может scrape-ить `api` или `notification`.

Alertmanager поднимается в compose и доступен на http://localhost:9093.

Для демонстрации firing-состояния можно запустить:

```bash
python3 scripts/trigger_error_alert.py
```

Через 1-2 минуты `MarketplaceHighErrorRate` появится в Prometheus Alerts и Alertmanager.

## SLI/SLO

SLI считаются из реальных Prometheus-метрик и проверяются скриптом `scripts/check_prometheus_sli.py`.

| SLI | PromQL | SLO | Порог отказа |
| --- | --- | --- | --- |
| API availability | `1 - ((sum(rate(http_request_errors_total{service="marketplace-api"}[1m])) or vector(0)) / clamp_min(sum(rate(http_requests_total{service="marketplace-api"}[1m])), 0.001))` | `> 99.5%` | `< 99%` |
| API p95 latency | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="marketplace-api"}[1m])) by (le))` | `< 500ms` | `> 1000ms` |
| API error rate | `(sum(rate(http_request_errors_total{service="marketplace-api"}[1m])) or vector(0)) / clamp_min(sum(rate(http_requests_total{service="marketplace-api"}[1m])), 0.001)` | `< 1%` | `> 5%` |

В CI после k6 нагрузки скрипт проверяет availability, p95 latency и error rate. Если условия не выполнены, pipeline падает.
