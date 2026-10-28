# Архітектурне рішення: консолідація в один модуль `fayna_channel_bridge`

**Дата:** 2026-10-28
**Статус:** PROPOSED (потребує рішення власника по 3 відкритих питаннях)
**Автор рішення:** сесія Roo, на основі фактів з диска й прода
**Цільовий репо:** `VladSh77/fayna-channel-bridge` (branch `main`, HEAD `ec77d64`)
**Джерело зливу:** `VladSh77/omnichannel-bridge` (branch `main`, HEAD `c08c4a1`)
**Архів:** `fayna-sendpulse-odoo` (старий SendPulse, не чіпаємо), `omnichannel-bridge` (після зливу → архів)

---

## 1. Доведені факти (перевірено на диску й на проді)

| # | Факт | Доказ |
|---|---|---|
| F1 | На проді стоїть **лише** `fayna_channel_bridge` 17.0.1.6.0, стан `installed` | `odoo shell` на `campscout_web` |
| F2 | `omnichannel_bridge` на проді **`uninstalled`**, моделей у БД немає | `MOD: omnichannel_bridge \| state: uninstalled \| version: False` |
| F3 | `channel.backend` на проді — **5 записів** (реальні підключення) | `channel.backend count: 5` |
| F4 | `fayna-channel-bridge`: 42 py/xml/js файли, 6 529 рядків, 12 тест-файлів, CI зелений, coverage 80% | `wc -l`, `.github/workflows/ci.yml` |
| F5 | `omnichannel-bridge`: 44 моделі, **12 511 рядків** лише в `models/`, 16 219 всього | `wc -l models/*.py` |
| F6 | Обидва модулі override-ять **рівно один** спільний файл — `discuss.channel` | `grep _inherit` в обох |
| F7 | `fayna-channel-bridge` **не має жодного** згадування `crm` | `grep -rn crm` → 0 |
| F8 | `omnichannel-bridge` має CRM-прив'язку: `_omni_maybe_create_crm_lead()` (`omni_bridge.py:323`) | читання коду |
| F9 | Обидва мають **власний транспорт**, паралельний | див. §2 |
| F10 | `fayna-channel-bridge` має **7 HTTP-роутів**, `omnichannel-bridge` — **1** | `grep @http.route` |
| F11 | `omnichannel-bridge` має `omni.integration` (8 провайдерів, 1 рядок на компанію) — це **окремий** реєстр від `channel.backend` | `models/omni_integration.py` |
| F12 | `fayna-channel-bridge` має `channel.provider` (12 провайдерів, декларативний) | `models/channel_provider.py` |

---

## 2. Головна небезпека зливу: два паралельні транспорти

Це те, що **не можна** злити механічно — інакше отримаємо два способи відправити одне й те саме повідомлення.

### Транспорт A — `fayna_channel_bridge` (канонічний, залишаємо)

`models/channel_backend.py:249 send_message(text, attachment_url, provider_user_id)`

Маршрутизація за `service`:
- `messenger` / `instagram` / `facebook` → `_meta_send_single()` → Graph API **v25.0**
- `viber` → `_viber_send_single()`
- `whatsapp` → `_whatsapp_send_single()`
- `tiktok` → `_tiktok_send_single()`
- `livechat` → `_livechat_send_single()` → LiveChat REST **v3.3**
- `telegram` (default) → `_telegram_send_single()` + автоспліт за лімітом 4096

Повертає `(success: bool, provider_message_id: str|None, error: str|None)` — **структурований результат**, придатний для retry-логіки.

Має: `_classify_error()`, `_compute_next_retry_at()`, `PERMANENT_ERROR_MAP`, `cron_bridge_retry()`, `cron_bridge_healthcheck()`.

### Транспорт B — `omnichannel_bridge` (дублює, викидаємо)

`models/omni_bridge.py:879 omni_send_outbound(provider, external_thread_id, customer_partner, body_html)`

Маршрутизація за `provider`:
- `telegram` → `_omni_telegram_send_message()`
- `meta` → `_omni_meta_send_psid()`
- `whatsapp` / `twilio_whatsapp` → `_omni_whatsapp_send_to_wa_id()`
- `viber` → `_omni_viber_send_to_user()`
- **`else:` → лише `_logger.info('Outbound not implemented')`** — тихо ковтає

Повертає `None` — **немає результату**, retry неможливий.

Має `_omni_http_post_with_retries()` (4 спроби, експоненційна затримка до 16 с) — **єдина частина, яку варто перенести**.

### Рішення

| що | доля |
|---|---|
| `channel_backend.send_message()` + 7 `_*_send_single()` | **ЗАЛИШИТИ** як єдиний транспорт |
| `omni_bridge.omni_send_outbound()` + 4 `_omni_*_send_*()` | **ВИКИНУТИ** |
| `omni_bridge._omni_http_post_with_retries()` | **ПЕРЕНЕСТИ** в `channel_backend` як спільний хелпер retry |
| `omni_bridge._omni_log_outbound_delivery()` | **ПЕРЕНЕСТИ** — журнал вихідних (аудит) |
| `omni.outbound.log` (модель) | **ПЕРЕНЕСТИ** — 16 рядків, корисний аудит |

**Правило:** один модуль = один транспорт. `channel.backend.send_message()` — єдина точка виходу назовні.

---

## 3. Другий конфлікт: два реєстри провайдерів

| | `channel.provider` (канон) | `omni.integration` (старий) |
|---|---|---|
| рядків | 411 | 107 |
| провайдерів | 12 | 8 |
| ключ | `code` | `provider` |
| унікальність | `code` | `(company_id, provider)` |
| декларативність | `connect_method`, `precondition_ids`, `region_blocklist`, `consent_required`, `cost_warning`, `side_effect_warning`, `help_url`, `fallback_method_ids`, `token_placeholder` | лише `api_token`, `webhook_secret` |
| облікові дані | `channel.backend` (5 записів на проді) | `omni.integration` (0 записів — модуль не встановлено) |

### Рішення

`omni.integration` **не переносити**. `channel.provider` + `channel.backend` вже покривають його повністю й ширше.

**Виняток:** `omni.integration._selection_providers()` містить `twilio_whatsapp` і `line`, яких немає в `channel.provider`. Перевірити, чи вони реально потрібні:
- `twilio_whatsapp` — дублює `whatsapp` (той самий Cloud API, інший шлюз). **Не переносити**, доки немає клієнта на Twilio.
- `line` — у `omnichannel_bridge` це `DELIVERY_STUB`. **Не переносити.**

---

## 4. Третій конфлікт: `discuss.channel` — два різні підходи

| | `fayna_channel_bridge/models/mail_channel.py` (119 рядків) | `omnichannel_bridge/models/mail_channel.py` (1883 рядки) |
|---|---|---|
| `message_post()` | рядок 40 | рядок 1438 |
| логіка | `_get_bridge_conversation()` → skip якщо `bridge_incoming` → skip `notification`/`auto_comment` → skip `_is_note_subtype()` → `super()` → `conversation._send_single_message()` | `super()` → оновлює 4 таймстемпи → пауза бота при відповіді менеджера → `_omni_handle_website_livechat_inbound()` → `_omni_route_operator_reply_to_messenger()` → `_omni_sync_inbox_rows()` |
| напрям | Odoo → месенджер (вихідний) | месенджер → Odoo (вхідний) + вихідний |
| поля | 0 (усі в `channel.conversation`) | **24 поля** прямо на `discuss.channel` |
| `_to_store()` | немає | є (рядок 88) — віддає поля в Owl-стор |

### Ключове архітектурне розходження

`fayna_channel_bridge` тримає стан розмови в **окремій моделі** `channel.conversation` (609 рядків) і лише посилається на `discuss.channel`.

`omnichannel_bridge` тримає стан **прямо на `discuss.channel`** — 24 поля, `_sql_constraints` на `(omni_provider, omni_external_thread_id)`.

### Рішення

**Залишити модель `channel.conversation`** — це чистіше (не засмічує нативну таблицю, легше міграція, легше тести).

**Перенести на `channel.conversation`** ті поля з `discuss.channel`, які описують бізнес-стан, а не технічний:

| поле `discuss.channel` (omni) | куди | чому |
|---|---|---|
| `omni_provider` | вже є як `channel.conversation.service` | дубль |
| `omni_external_thread_id` | вже є як `channel.conversation.provider_thread_id` | дубль |
| `omni_customer_partner_id` | вже є як `channel.conversation.partner_id` | дубль |
| `omni_bot_paused` | **перенести** | бізнес-стан (менеджер перехопив) |
| `omni_bot_pause_reason` | **перенести** | бізнес-стан |
| `omni_last_human_reply_at` | **перенести** | бізнес-стан |
| `omni_last_bot_reply_at` | **перенести** | бізнес-стан |
| `omni_last_manager_activity_at` | **перенести** | бізнес-стан |
| `omni_last_outbound_at` | **перенести** | бізнес-стан |
| `omni_last_outbound_hash` | **перенести** | антидубль вихідних |
| `omni_last_outbound_author_kind` | **перенести** | бізнес-стан |
| `omni_legal_notice_sent_at` | **перенести** | RODO |
| `omni_reserve_lead_id` | **перенести** | зв'язок з CRM |
| `omni_reserve_entry_id` | **перенести** | зв'язок з CRM |
| `omni_reserve_requested_at` | **перенести** | бізнес-стан |
| `omni_last_customer_inbound_at` | **перенести** | 24-годинне вікно Meta |
| `omni_window_reminder_sent_at` | **перенести** | бізнес-стан |
| `omni_window_last_call_sent_at` | **перенести** | бізнес-стан |
| `omni_window_reminder_count` | **перенести** | бізнес-стан |
| `omni_last_fomo_notify_at` | **перенести** | маркетинг |
| `omni_last_marketing_touch_at` | **перенести** | маркетинг |
| `omni_last_marketing_touch_type` | **перенести** | маркетинг |
| `omni_livechat_entry_state` | **перенести** | стан входу в livechat |
| `omni_livechat_entry_topic` | **перенести** | стан входу в livechat |
| `omni_livechat_contact_attempts` | **перенести** | стан входу в livechat |
| `omni_detected_lang` | **перенести** | мовний хінт для AI |

**`_to_store()`** — перенести логіку в `channel.conversation` не можна (це метод `discuss.channel`). Рішення: залишити **тонкий** override `_to_store()` у `mail_channel.py` канону, який додає лише `bridge_conversation_id` — решта полів читається через `channel.conversation`.

**`_sql_constraints`** — перенести на `channel.conversation`: `unique(service, provider_thread_id)`.

---

## 5. Що саме переносимо з `omnichannel_bridge` (по файлах)

### 5.1 Перенести повністю (нова цінність, якої немає в каноні)

| файл | рядків | що дає | куди в каноні |
|---|---|---|---|
| `omni_bridge.py` (частково) | 1116 | `omni_process_webhook()`, `_omni_register_webhook_event()` (дедуп через savepoint + IntegrityError), `_omni_maybe_create_crm_lead()` | `models/channel_webhook.py` (новий) + `models/channel_conversation.py` |
| `omni_crm_analytics.py` | 397 | аналітика по CRM-лідах з месенджерів | `models/channel_crm_analytics.py` (новий) |
| `omni_sales_intel.py` | 602 | тригери продажів на вхідних повідомленнях | `models/channel_sales_intel.py` (новий) |
| `omni_memory.py` | 323 | пам'ять діалогу (контекст для AI) | `models/channel_memory.py` (новий) |
| `omni_ai.py` | 2387 | AI-автовідповіді, LLM-класифікація, fallback | `models/channel_ai.py` (новий) |
| `omni_ai_job.py` | 183 | черга AI-задач | `models/channel_ai_job.py` (новий) |
| `omni_knowledge.py` | 1426 | база знань для AI | `models/channel_knowledge.py` (новий) |
| `omni_knowledge_article.py` | 68 | статті бази знань | разом з `channel_knowledge.py` |
| `omni_notify.py` | 629 | сповіщення менеджерам (Telegram) | `models/channel_notify.py` (новий) |
| `omni_inbox_thread.py` | 627 | черга вхідних для операторів | `models/channel_inbox.py` (новий) |
| `omni_conversation_audit.py` | 333 | аудит розмов | `models/channel_audit.py` (новий) |
| `omni_conversation_identity_wizard.py` | 145 | майстер прив'язки клієнта | `wizard/channel_identity_wizard.py` |
| `omni_partner_identity.py` | 40 | ідентичність партнера | `models/channel_partner_identity.py` |
| `omni_partner_bind_wizard.py` | 25 | майстер прив'язки | разом з identity wizard |
| `omni_webhook_event.py` | 73 | реєстр webhook-подій (дедуп) | `models/channel_webhook_event.py` |
| `omni_chat_archive.py` | 69 | архів розмов (30 днів) | `models/channel_archive.py` |
| `omni_moderation_rule.py` | 30 | правила модерації | `models/channel_moderation.py` |
| `omni_objection_policy.py` | 38 | політика заперечень | `models/channel_objection.py` |
| `omni_stage_transition.py` | 32 | переходи стадій | `models/channel_stage.py` |
| `omni_stage_event.py` | 15 | події стадій | разом з `channel_stage.py` |
| `omni_reserve_entry.py` | 31 | резервування місць | `models/channel_reserve.py` |
| `omni_insurance_package.py` | 26 | страхові пакети | `models/channel_insurance.py` |
| `omni_coupon_redemption.py` | 26 | купони | `models/channel_coupon.py` |
| `omni_promo.py` | 55 | промо | разом з `channel_coupon.py` |
| `omni_payment_event.py` | 17 | платіжні події | `models/channel_payment.py` |
| `omni_outbound_log.py` | 16 | журнал вихідних | `models/channel_outbound_log.py` |
| `omni_legal_document.py` | 44 | юридичні документи (RODO) | `models/channel_legal.py` |
| `omni_manager_reply_assist.py` | 42 | підказки менеджеру | `models/channel_reply_assist.py` |
| `omni_manager_reply_template.py` | 23 | шаблони відповідей | разом з reply_assist |
| `omni_prompt_audit.py` | 31 | аудит промптів | `models/channel_prompt_audit.py` |
| `omni_llm_fallback_session.py` | 24 | fallback-сесії LLM | `models/channel_llm_fallback.py` |
| `omni_tg_broadcast.py` | 59 | розсилка в Telegram | `models/channel_broadcast.py` |
| `omni_action_utils.py` | 35 | хелпери act_window | `models/channel_action_utils.py` |
| `res_partner.py` | 502 | розширення партнера (стадії, мова, теги) | `models/res_partner.py` (новий) |
| `sale_order.py` | 48 | зв'язок з продажами | `models/sale_order.py` (новий) |
| `account_move.py` | 36 | зв'язок з рахунками | `models/account_move.py` (новий) |
| `payment_transaction.py` | 40 | зв'язок з платежами | `models/payment_transaction.py` (новий) |
| `product_template.py` | 14 | зв'язок з продуктами | `models/product_template.py` (новий) |
| `res_company.py` | 25 | налаштування компанії | `models/res_company.py` (новий) |
| `mail_message.py` | 28 | розширення повідомлень | `models/mail_message.py` (новий) |
| `mail_guest.py` | 16 | гостьові сесії livechat | `models/mail_guest.py` (новий) |
### 5.2 НЕ переносити (дублює канон або застаріле)

| файл | рядків | причина |
|---|---|---|
| `omni_integration.py` | 107 | дублює `channel.provider` + `channel.backend` |
| `omni_bridge.py` → `omni_send_outbound()` + 4 `_omni_*_send_*()` | ~200 | дублює `channel_backend.send_message()` |
| `res_config_settings.py` | 780 | канон має власні налаштування; переносити лише окремі поля |
| `utils/omni_provider_contracts.py` | 45 | замінюється на `channel.provider.connect_method` |
| `utils/webhook_parsers.py` | — | канон має власні парсери в `controllers/main.py` |

### 5.3 Перенести частково

| файл | що взяти | що викинути |
|---|---|---|
| `omni_bridge.py` | `_omni_http_post_with_retries()`, `_omni_log_outbound_delivery()`, `_omni_register_webhook_event()`, `_omni_maybe_create_crm_lead()`, `omni_get_or_create_thread()` | `omni_send_outbound()`, `_omni_*_send_*()`, `_omni_meta_credentials()` |
| `mail_channel.py` | `_to_store()` (тонкий), `omni_manager_session_active_now()` | 24 поля (→ `channel.conversation`), `message_post()` |

---

## 6. Цільова структура модуля після зливу

```
fayna_channel_bridge/
├── __manifest__.py          # depends: mail, web, crm, sale_management, account, stock
├── models/
│   ├── channel_backend.py        # 1046 → ~1100 (транспорт + retry-хелпер)
│   ├── channel_provider.py       # 411 (реєстр провайдерів, декларативний)
│   ├── channel_conversation.py   # 609 → ~900 (+24 поля стану)
│   ├── channel_message.py        # як є
│   ├── channel_webhook.py        # НОВИЙ (з omni_bridge: ingest + дедуп)
│   ├── channel_webhook_event.py  # НОВИЙ (з omni_webhook_event)
│   ├── channel_crm_analytics.py  # НОВИЙ (з omni_crm_analytics)
│   ├── channel_sales_intel.py    # НОВИЙ (з omni_sales_intel)
│   ├── channel_ai.py             # НОВИЙ (з omni_ai)
│   ├── channel_ai_job.py         # НОВИЙ (з omni_ai_job)
│   ├── channel_knowledge.py      # НОВИЙ (з omni_knowledge + article)
│   ├── channel_memory.py         # НОВИЙ (з omni_memory)
│   ├── channel_notify.py         # НОВИЙ (з omni_notify)
│   ├── channel_inbox.py          # НОВИЙ (з omni_inbox_thread)
│   ├── channel_audit.py          # НОВИЙ (з omni_conversation_audit)
│   ├── channel_archive.py        # НОВИЙ (з omni_chat_archive)
│   ├── channel_legal.py          # НОВИЙ (з omni_legal_document — RODO)
│   ├── channel_outbound_log.py   # НОВИЙ (з omni_outbound_log)
│   ├── channel_moderation.py     # НОВИЙ
│   ├── channel_objection.py      # НОВИЙ
│   ├── channel_stage.py          # НОВИЙ (з omni_stage_transition + event)
│   ├── channel_reserve.py        # НОВИЙ
│   ├── channel_insurance.py      # НОВИЙ
│   ├── channel_coupon.py         # НОВИЙ (з omni_coupon_redemption + promo)
│   ├── channel_payment.py        # НОВИЙ (з omni_payment_event)
│   ├── channel_reply_assist.py   # НОВИЙ
│   ├── channel_prompt_audit.py   # НОВИЙ
│   ├── channel_llm_fallback.py   # НОВИЙ
│   ├── channel_broadcast.py      # НОВИЙ
│   ├── channel_action_utils.py   # НОВИЙ
│   ├── channel_partner_identity.py # НОВИЙ
│   ├── mail_channel.py           # 119 → ~150 (тонкий _to_store)
│   ├── res_partner.py            # НОВИЙ (502 з omni)
│   ├── res_company.py            # НОВИЙ
│   ├── mail_message.py           # НОВИЙ
│   ├── mail_guest.py             # НОВИЙ
│   ├── sale_order.py             # НОВИЙ
│   ├── account_move.py           # НОВИЙ
│   ├── payment_transaction.py    # НОВИЙ
│   └── product_template.py       # НОВИЙ
├── wizard/
│   ├── channel_identity_wizard.py  # НОВИЙ
│   └── (наявні)
├── controllers/main.py      # 661 (7 роутів — залишається)
├── views/                   # +29 view-файлів з omni
├── data/                    # +37 data-файлів з omni
├── security/                # + omni_security.xml
├── i18n/                    # + pl.po, uk_UA.po з omni
├── static/src/              # + omni_client_info_panel, omni_thread_actions, thread_patch
├── migrations/              # + 17.0.1.7.0 (перенесення полів)
└── tests/                   # 12 наявних + нові на кожен перенесений блок
```

**Оцінка обсягу:** ~12 500 рядків переноситься, ~1 000 викидається, ~2 000 переписується під канон. Разом модуль ~19 000–20 000 рядків.

---

## 7. Порядок роботи (етапи з verify-критеріями)

| # | етап | → verify |
|---|---|---|
| 1 | Виправити 3 підтверджені баги в каноні (`t-if="not"`, `@api.model`, `groupedProviders`) | `grep` → 0 входжень `t-if="not"`; `call_kw` повертає 12 провайдерів; Owl рендерить панель |
| 2 | Локальний Docker-стенд + прогін 175 наявних тестів | `pytest` → 0 failed, coverage ≥ 80% |
| 3 | Перенести транспортні хелпери (`_omni_http_post_with_retries`, `_omni_log_outbound_delivery`, `omni.outbound.log`) | нові тести на retry + журнал → зелені |
| 4 | Перенести 24 поля стану на `channel.conversation` + міграція `17.0.1.7.0` | `-u` на чистій БД → 0 помилок; поля існують |
| 5 | Перенести CRM-шар (`_omni_maybe_create_crm_lead`, `omni_crm_analytics`, `res_partner`) | тест: вхідне від нового партнера → створено `crm.lead` |
| 6 | Перенести webhook-ingest (`omni_process_webhook`, `_omni_register_webhook_event`, `omni_webhook_event`) | тест: дубль webhook → 1 подія, 1 повідомлення |
| 7 | Перенести AI-шар (`omni_ai`, `omni_ai_job`, `omni_knowledge`, `omni_memory`) | тест: вхідне → AI-відповідь у межах таймауту |
| 8 | Перенести операторський шар (`omni_inbox_thread`, `omni_notify`, `omni_manager_reply_*`) | тест: ескалація → сповіщення менеджеру |
| 9 | Перенести бізнес-моделі (reserve, insurance, coupon, payment, sale, stage) | тести на кожну модель |
| 10 | Перенести views + static + i18n + security | `-u` → 0 помилок; панель рендериться; переклади 100% |
| 11 | Повний прогін тестів + coverage | `pytest` → 0 failed, coverage ≥ 80% |
| 12 | Деплой на прод + доказ | модуль `installed`, версія нова, лог без ERROR, панель працює |
| 13 | Архівувати `omnichannel-bridge` | репо → `archived` на GitHub, README з посиланням на канон |

---

## 8. Відкриті питання (потребують рішення власника)

1. **`sale_management`, `account`, `stock`** — канон зараз залежить лише від `mail` + `web`. `omnichannel_bridge` тягне 4 додаткові модулі. Ставимо ці залежності в канон (важчий модуль, але повний продукт), чи робимо їх **опційними** через перевірку `'crm.lead' in self.env`?

2. **`omni_ai.py` (2387 рядків)** — найбільший файл: і промпти, і виклики LLM, і логіка відповідей. Переносити як є (швидко, але тягне борг), чи розбити на `channel_ai.py` + `channel_prompt.py` + `channel_llm_client.py` (чистіше, але +2 дні)?

3. **`res_config_settings.py` (780 рядків)** — канон має власні налаштування. Переносити всі 780 рядків полів, чи лише ті, що стосуються перенесених моделей (орієнтовно 300)?

---

## 9. Що НЕ робимо

- Не чіпаємо `fayna-sendpulse-odoo` — це інший (старий) модуль, лишається як є.
- Не встановлюємо `omnichannel_bridge` на прод — він там `uninstalled`, після зливу не буде потрібен.
- Не робимо force-push і не переписуємо історію канону.
- Не додаємо AI-підписів у коміти.
