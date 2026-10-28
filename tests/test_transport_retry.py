"""Тести спільного HTTP-транспорту: повторні спроби й журнал доставки.

Що саме доводимо (і чому саме так):

1. Тимчасовий збій (503) повторюється, і успішна спроба повертає `resp`
   з `ok=True`. Без цього один блимок провайдера = втрачене повідомлення.
2. Постійна помилка (400) НЕ повторюється: невалідний токен не має
   коштувати чотирьох спроб і п'ятнадцяти секунд очікування.
3. Мережевий виняток після вичерпання спроб піднімається назовні —
   виклик сам вирішує, як це подати оператору.
4. Кожна завершена спроба лишає рядок у `channel.delivery.log`, і в
   `error_snippet` не потрапляє токен (маскування).

`time.sleep` підміняємо, щоб тест не спав реальні секунди: перевіряємо
ПОЛІТИКУ (скільки спроб, які коди), а не фізичну тривалість.
"""

from unittest.mock import MagicMock, patch

import requests
from odoo.tests.common import TransactionCase


class TestTransportRetry(TransactionCase):
    """Повторні спроби та журнал доставки на `channel.backend`."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env['channel.backend'].create(
            {
                'name': 'Retry Test Backend',
                'service': 'telegram',
                'bot_token': '123456:TEST-TOKEN-SECRET',
                'active': True,
            }
        )
        cls.DeliveryLog = cls.env['channel.delivery.log']

    def _response(self, status_code, text=''):
        """Мінімальна заглушка `requests.Response`."""
        resp = MagicMock()
        resp.status_code = status_code
        resp.ok = 200 <= status_code < 400
        resp.text = text
        return resp

    def _logs(self):
        return self.DeliveryLog.search([('backend_id', '=', self.backend.id)])

    def test_retries_on_temporary_status_then_succeeds(self):
        """503 → 503 → 200: три спроби, успіх, ОДИН рядок журналу.

        Контракт журналу: один рядок на завершений виклик, а не на кожну
        спробу. Оператору потрібна відповідь «дійшло чи ні і з якої спроби»,
        а не три рядки шуму на кожне повідомлення. Кількість спроб видно
        в полі `attempts`.
        """
        responses = [
            self._response(503, 'Service Unavailable'),
            self._response(503, 'Service Unavailable'),
            self._response(200, 'ok'),
        ]
        with (
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.requests.post') as post,
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.time.sleep'),
        ):
            post.side_effect = responses
            resp = self.backend._http_post_with_retries(
                'https://api.example.test/send',
                json={'text': 'hi'},
                external_thread_id='chat-42',
            )

        self.assertEqual(post.call_count, 3, 'мало бути рівно три спроби')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.ok)

        logs = self._logs()
        self.assertEqual(len(logs), 1, 'один рядок на завершений виклик')
        self.assertEqual(logs.status_code, 200, 'фіксуємо результат останньої спроби')
        self.assertTrue(logs.ok)
        self.assertEqual(logs.attempts, 3, 'кількість спроб видно в журналі')
        self.assertEqual(logs.external_thread_id, 'chat-42')
        self.assertEqual(logs.event_type, 'message')

    def test_does_not_retry_on_permanent_client_error(self):
        """400 — це помилка запиту, а не збою: одна спроба, без сну."""
        with (
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.requests.post') as post,
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.time.sleep') as sleep,
        ):
            post.return_value = self._response(400, 'Bad Request: invalid token')
            resp = self.backend._http_post_with_retries('https://api.example.test/send')

        self.assertEqual(post.call_count, 1, '400 не повторюємо')
        sleep.assert_not_called()
        self.assertEqual(resp.status_code, 400)

        logs = self._logs()
        self.assertEqual(len(logs), 1)
        self.assertFalse(logs.ok)
        self.assertEqual(logs.status_code, 400)
        self.assertIn('invalid token', logs.error_snippet)

    def test_raises_after_network_failures_exhausted(self):
        """Мережевий виняток на всіх спробах — піднімається назовні.

        Журнал пишеться ДО `raise`, але в `TransactionCase` виняток
        відкочує транзакцію разом із цим записом. Тому перевіряємо не
        рядок у БД, а сам факт виклику `_log_delivery` з правильними
        аргументами — це і є контракт «фінальний збій зафіксовано».
        """
        with (
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.requests.post') as post,
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.time.sleep'),
            patch.object(
                type(self.backend),
                '_log_delivery',
                autospec=True,
            ) as log_delivery,
        ):
            post.side_effect = requests.ConnectionError('connection reset')
            with self.assertRaises(requests.ConnectionError):
                self.backend._http_post_with_retries(
                    'https://api.example.test/send',
                    max_attempts=2,
                )

        self.assertEqual(post.call_count, 2, 'max_attempts=2 → рівно дві спроби')
        self.assertEqual(
            log_delivery.call_count,
            1,
            'фіксуємо лише фінальний збій, не кожну спробу',
        )
        kwargs = log_delivery.call_args.kwargs
        self.assertFalse(kwargs['ok'])
        self.assertEqual(kwargs['status_code'], 0)
        self.assertEqual(kwargs['attempts'], 2)
        self.assertIn('connection reset', kwargs['error'])

    def test_error_snippet_masks_secrets(self):
        """Токен у тілі помилки не має потрапляти в журнал відкритим."""
        with (
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.requests.post') as post,
            patch('odoo.addons.fayna_channel_bridge.models.channel_backend.time.sleep'),
        ):
            post.return_value = self._response(
                401,
                'Unauthorized: token 123456:TEST-TOKEN-SECRET rejected',
            )
            self.backend._http_post_with_retries('https://api.example.test/send')

        log = self._logs()
        self.assertEqual(len(log), 1)
        self.assertNotIn(
            'TEST-TOKEN-SECRET',
            log.error_snippet,
            'секрет не має лишатися в журналі відкритим',
        )

    def test_log_delivery_never_breaks_sending(self):
        """Якщо журнал недоступний — відправка не має падати."""
        with patch.object(
            type(self.env['channel.delivery.log']),
            'create',
            side_effect=Exception('db is read-only'),
        ):
            # Не має підняти виняток назовні.
            self.backend._log_delivery(
                url='https://api.example.test/send',
                ok=True,
                status_code=200,
            )
