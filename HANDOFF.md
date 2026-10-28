# МІСТ — стан роботи на 2026-10-28 10:08 UTC

> Це **знімок**, а не істина. Перед дією звір факти командою
> (закон АНТИБРЕХНЯ — запис ≠ стан).

## Де ми

Етапи 1–2 консолідації закриті, зелені, запушені.
**Етап 3 (транспортні хелпери) — закомічений і запушений: `fa5e423`.**
Але його 5 нових тестів **ще жодного разу не виконувались** — див. факт 3.

## Стан репозиторію

HEAD `fa5e423`, гілка `main`, remote `VladSh77/fayna-channel-bridge`,
робоче дерево чисте, локально = віддалено.

Що увійшло в `fa5e423` (8 файлів, +495/−8):

| файл | що це |
|---|---|
| `models/channel_backend.py` | `_http_post_with_retries`, `_log_delivery`, 7 місць виклику |
| `models/channel_delivery_log.py` | модель `channel.delivery.log` — технічний журнал доставки |
| `models/__init__.py` | імпорт нової моделі |
| `security/ir.model.access.csv` | ACL officer/admin на нову модель |
| `__manifest__.py` | версія `17.0.1.6.0` → `17.0.1.7.0` |
| `ci/docker-compose.test.yml` | `-u fayna_channel_bridge` у сервісі `tests` |
| `tests/test_transport_retry.py` | 5 тестів на retry/лог — **НЕ ЗАПУСКАЮТЬСЯ** |
| `HANDOFF.md` | цей файл |

## Доведені факти (команда → результат)

1. **Схема БД стенда відставала від коду.**
   `psql` → модуль `17.0.1.6.0`, таблиці `channel_delivery_log` немає.
   Симптом: `ERROR: relation "channel_delivery_log" does not exist` (3 errors).
   Причина: сервіс `tests` ганяв `--test-enable` без `-u`, а БД стенда переживає прогони.
   Фікс: додано `-u fayna_channel_bridge` у `ci/docker-compose.test.yml`.
   Результат: 3 errors зникли → `7 failed, 0 error(s)`.

2. **7 фейлів — `'Resp' object has no attribute 'ok'`.**
   Лог модуля: `Channel Bridge: LiveChat send exception — 'Resp' object has no attribute 'ok'`.
   Причина: хелпер читав `resp.ok`, а тестова заглушка — `type('Resp', (), {})()` з лише `status_code`.
   Фікс: `ok = 200 <= resp.status_code < 400` замість `resp.ok`.
   Результат: `0 failed, 0 error(s) of 121 tests`, `EXIT=0`.

3. **Зелений прогін — ЗВУЖЕНИЙ доказ.**
   `grep -cE "Starting TestTransportRetry"` → `0` (exit 1).
   Стартував 21 клас, `TestTransportRetry` серед них немає.
   Файл у контейнері Є: `docker run --rm -v "$PWD":/mnt/extra-addons/fayna_channel_bridge odoo:17.0 ls -la .../tests/`
   → `test_transport_retry.py` 7180 B.
   Причина знайдена читанням `tests/__init__.py`: у списку імпортів **немає** `test_transport_retry`.

## Перший крок наступної сесії

1. У `tests/__init__.py` додати `test_transport_retry,` (між `test_telegram_webhook,` і `test_ui_operator,`).
2. `docker compose -f ci/docker-compose.test.yml run --rm tests`
3. Перевірити: `Starting TestTransportRetry` — **5 разів**, кількість методів 121 → **126**,
   `0 failed, 0 error(s)`.
4. Лише після цього коміт етапу 3.

4. **Етап 3 закомічений і запушений.**
   `git commit` → `fa5e423`, `git push origin main` → `e8b2196..fa5e423`,
   `git ls-remote origin refs/heads/main` → `fa5e423…` (локально = віддалено).
   AI-підписів у повідомленні: `grep -ciE "co-authored|generated with|claude|anthropic"` → `0`.

## Що НЕ закрито

- 5 нових тестів не виконувались → поведінка retry/логу **не доведена** тестом.
  Коміт `fa5e423` містить код і тести, але тести — «сплячі».
- `HANDOFF.md` увійшов у коміт `fa5e423` (робочий файл у репо — прибрати або
  перенести в `docs/` наступною сесією).

## Рішення власника, які діють

- Повний злив: усе з `omnichannel-bridge` → `fayna-channel-bridge`, `omnichannel-bridge` архівуємо.
- Один репо, одна гілка, без дублів.
- Модуль рівня продакшн, логіка нативна Odoo, не дублювати те, що вже є з коробки.
- Вимоги Odoo до модулів — закон.
- Прод — джерело правди.
- Жодних AI-підписів у комітах; без force-push; `fayna-sendpulse-odoo` не чіпати.
- `fayna-odoo-migration` — НАШ проєкт (інший), не «чужий».
- Помилки називати своїми: «я», не «ми».

## Команда «міст» у новому чаті — що робити

1. Прочитати цей файл повністю.
2. Звірити стан фактами, не переказом:
   `git status --short`, `git log --oneline -1`, `git remote -v`.
3. Якщо робоче дерево збігається з таблицею вище — виконувати
   «Перший крок наступної сесії» з п.1.
4. Якщо не збігається — довіряти команді, а не цьому файлу,
   і спершу доповісти розбіжність.
