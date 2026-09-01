# Fayna Channel Bridge

Власний прямий транспортний шар для DM-каналів Odoo (без зовнішнього посередника).

## Статус

**M0** — каркас модуля + модель channel.backend + Telegram пілот.
**M1** — real auto-failover (healthcheck + перемикання transport_priority).
**M2** — Meta (IG, Messenger) send через наявні page токени + Messenger webhook (verify + POST).
**M3** — Viber, WhatsApp Cloud, TikTok, LiveChat send + webhook.

## Структура

Корінь репо **і є самим модулем** — `__manifest__.py` лежить у корені,
тому на сервері репо клонується прямо в `custom-addons/fayna_channel_bridge`,
і `addons_path` міняти не треба.

```
fayna-channel-bridge/            # = модуль fayna_channel_bridge
├── __manifest__.py
├── hooks.py                     # post_init_hook(env) — групи адмінам
├── controllers/
│   └── main.py                  # 7 вебхуків: telegram, messenger, viber,
│                                #   whatsapp, tiktok, livechat (+ verify)
├── models/
│   ├── channel_backend.py       # підключений канал, відправка, healthcheck
│   ├── channel_conversation.py  # розмови + receive handler
│   ├── channel_message.py       # журнал + ідемпотентність
│   ├── channel_provider.py      # декларативний каталог провайдерів
│   └── mail_channel.py          # _inherit discuss.channel: вихідні
├── wizard/
│   └── channel_connect_wizard.py
├── security/
│   ├── security.xml             # групи + ir.rule
│   └── ir.model.access.csv
├── data/
│   ├── channel_backend_cron.xml
│   └── channel_provider_data.xml
├── views/                       # 4 XML
├── static/
│   ├── src/channel_dashboard/   # OWL-SPA «Підключити канали»
│   └── description/             # index.html, icon.png 128×128, banner.png
├── i18n/                        # .pot + uk.po + pl.po
├── migrations/                  # 17.0.1.1.0 … 17.0.1.6.0
├── tests/                       # 12 файлів
├── ci/
│   ├── Dockerfile.test
│   └── docker-compose.test.yml
├── .github/workflows/ci.yml     # lint + test-job на Odoo 17
├── docs/                        # ТЗ, аудит, план тестів, плани робіт
├── pyproject.toml               # конфіг ruff, pytest, coverage
├── .pre-commit-config.yaml
└── README.md
```

## Docker-тестування

Модуль тестується в ізольованому Odoo 17 середовищу через Docker.

```bash
# 1. Запустити тестове середовище (підниме Odoo + PostgreSQL, інсталює модули)
docker compose -f ci/docker-compose.test.yml up

# 2. Запустити тести
docker compose -f ci/docker-compose.test.yml exec web pytest

# 3. Зупинити і прибрати
docker compose -f ci/docker-compose.test.yml down
```

> **Важливо:** `fayna_channel_bridge` — повністю автономний модуль (без
> зовнішнього базового модуля). `ci/docker-compose.test.yml` монтує лише цей
> каталог як `extra-addons`; залежності — штатні `mail` та `web`.

## Локальний lint (ruff)

```bash
ruff check .
ruff format .
```

## Конфигурація

Канали керуються через меню **Channel Bridge → Канали** (модель `channel.backend`):

- `service` — канал (telegram/instagram/facebook/messenger/viber/whatsapp/tiktok/livechat)
- `provider` — `direct` (власний транспорт)
- `transport_priority` — `own` / `auto`
- `bot_token` — Telegram Bot Token (encrypted)
- `heal_url` — webhook URL (авто-заповнюється при `register_telegram_webhook`)

## Telegram webhook

Реєстрація: `POST https://api.telegram.org/bot<TOKEN>/setWebhook` →
`https://<odoo>/bridge/telegram/webhook/<TOKEN>`.

Прийом: `POST /bridge/telegram/webhook/<token>` — токен у URL є аутентифікацією.
Payload нормалізується до загальної структури і передається в
`channel.conversation._process_incoming_event` (власний обробник вхідних).

## Ідемпотентність

`channel.message` має partial unique index на
`(provider_message_id, service, direction='incoming')` — повторний webhook
не дублює повідомлення.

## Транспорт

`channel.conversation.transport`:
- `own` — власний транспорт через `channel.backend`
- `auto` — спершу власний, при помилці fallback

## Архів розмов

`channel.conversation` підтримує архівацію старих розмов через нативний
механізм Odoo (`active`). Cron `cron_archive_old_conversations` стискає
розмови старші за налаштований період (за замовчуванням 30 днів),
зберігаючи історію переписок без видалення даних.
