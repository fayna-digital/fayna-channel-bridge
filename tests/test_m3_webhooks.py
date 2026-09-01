# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License LGPL-3 (GNU Lesser General Public License v3.0).
"""Тести на вебхуки WhatsApp, TikTok і LiveChat.

Покриває:
  - WhatsApp GET: 404, 401, 200
  - WhatsApp POST: 404, 400 (empty), 400 (invalid JSON), 401 (bad format),
    401 (wrong secret), 200 (valid text)
  - TikTok POST: 404, 400 (empty), 400 (invalid JSON), 401 (wrong secret),
    200 (non‑receive event, no record), 200 (receive event, record)
  - LiveChat POST: 404, 400 (empty), 400 (invalid JSON), 401 (wrong secret),
    200 (non‑incoming_event, no record)
"""

import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


def _sign(body: bytes, secret: str, prefix: bool = False) -> str:
    """Повертає HMAC‑SHA256 підпис у hex‑форматі; при prefix додає ``sha256=``."""
    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return f'sha256={digest}' if prefix else digest


@tagged('post_install', '-at_install')
class TestWhatsAppWebhook(HttpCase):
    """Тести для маршруту /bridge/whatsapp/webhook."""

    VERIFY_TOKEN = 'wh_verify_token'
    SECRET = 'wh_secret'
    SERVICE = 'whatsapp'

    def setUp(self):
        super().setUp()
        self.authenticate('', '')

    def _incoming_count(self):
        return self.env['channel.message'].search_count(
            [('service', '=', self.SERVICE), ('direction', '=', 'incoming')]
        )

    def _payload(self, text='Привіт'):
        return {
            'entry': [
                {
                    'changes': [
                        {
                            'value': {
                                'messages': [
                                    {
                                        'from': 'user_1',
                                        'id': 'msg_1',
                                        'type': 'text',
                                        'text': {'body': text},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

    def test_get_no_backend(self):
        """GET без налаштованого бекенда → 404."""
        r = self.url_open(
            '/bridge/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=any&hub.challenge=123'
        )
        self.assertEqual(r.status_code, 404)

    def test_get_invalid_token(self):
        """GET з невірним токеном → 401."""
        self.env['channel.backend'].create(
            {
                'name': 'WH',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.VERIFY_TOKEN,
            }
        )
        r = self.url_open(
            '/bridge/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123'
        )
        self.assertEqual(r.status_code, 401)

    def test_get_success(self):
        """GET з правильним токеном → 200 і тіло challenge."""
        self.env['channel.backend'].create(
            {
                'name': 'WH',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.VERIFY_TOKEN,
            }
        )
        r = self.url_open(
            '/bridge/whatsapp/webhook?hub.mode=subscribe&hub.verify_token='
            + self.VERIFY_TOKEN
            + '&hub.challenge=challenge_text'
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, 'challenge_text')
        self.assertIn('text/plain', r.headers.get('Content-Type', ''))

    def test_post_no_backend(self):
        """POST без налаштованого бекенда → 404."""
        body = json.dumps(self._payload()).encode('utf-8')
        r = self.url_open(
            '/bridge/whatsapp/webhook',
            data=body,
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r.status_code, 404)

    def test_post_empty_body(self):
        """POST з порожнім тілом → 200 (error) і без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'WH',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        r = self.opener.post(
            self.base_url() + '/bridge/whatsapp/webhook',
            data=b'',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r.status_code, 200)
        resp = json.loads(r.text or '{}')
        self.assertEqual(resp.get('status'), 'error')
        self.assertEqual(self._incoming_count(), 0)

    def test_post_invalid_json(self):
        """POST з невалідним JSON → 400 і без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'WH',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        r = self.url_open(
            '/bridge/whatsapp/webhook',
            data=b'{invalid json',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_bad_signature_format(self):
        """POST з підписом без префікса або обрізаним → 401."""
        self.env['channel.backend'].create(
            {
                'name': 'WH',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload()).encode('utf-8')
        # без префікса
        bad_sig = hmac.new(self.SECRET.encode('utf-8'), body, hashlib.sha256).hexdigest()
        r1 = self.url_open(
            '/bridge/whatsapp/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': bad_sig},
        )
        self.assertEqual(r1.status_code, 401)
        # обрізаний з префіксом
        full_sig = _sign(body, self.SECRET, prefix=True)
        r2 = self.url_open(
            '/bridge/whatsapp/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': full_sig[:20]},
        )
        self.assertEqual(r2.status_code, 401)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_wrong_secret(self):
        """POST з валідним форматом, але чужим секретом → 401."""
        self.env['channel.backend'].create(
            {
                'name': 'WH',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload()).encode('utf-8')
        sig = _sign(body, 'other_secret', prefix=True)
        r = self.url_open(
            '/bridge/whatsapp/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': sig},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_valid_text_message(self):
        """POST з валідним підписом і текстовим повідомленням → 200 і запис."""
        self.env['channel.backend'].create(
            {
                'name': 'WH',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload('Тестове повідомлення')).encode('utf-8')
        sig = _sign(body, self.SECRET, prefix=True)
        r = self.url_open(
            '/bridge/whatsapp/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': sig},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._incoming_count(), 1)


@tagged('post_install', '-at_install')
class TestTikTokWebhook(HttpCase):
    """Тести для маршруту /bridge/tiktok/webhook."""

    SECRET = 'tt_secret'
    SERVICE = 'tiktok'

    def setUp(self):
        super().setUp()
        self.authenticate('', '')

    def _incoming_count(self):
        return self.env['channel.message'].search_count(
            [('service', '=', self.SERVICE), ('direction', '=', 'incoming')]
        )

    def _payload(self, event='im.message.receive', text='Привіт'):
        return {
            'event': event,
            'msg_id': 'msg_123',
            'sender': {'open_id': 'user_1'},
            'content': {'text': text},
        }

    def test_post_no_backend(self):
        """POST без налаштованого бекенда → 404."""
        body = json.dumps(self._payload()).encode('utf-8')
        r = self.url_open(
            '/bridge/tiktok/webhook',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Bridge-Secret': _sign(body, self.SECRET),
            },
        )
        self.assertEqual(r.status_code, 404)

    def test_post_empty_body(self):
        """POST з порожнім тілом → 200 (error) і без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'TT',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        r = self.opener.post(
            self.base_url() + '/bridge/tiktok/webhook',
            data=b'',
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': ''},
        )
        self.assertEqual(r.status_code, 200)
        resp = json.loads(r.text or '{}')
        self.assertEqual(resp.get('status'), 'error')
        self.assertEqual(self._incoming_count(), 0)

    def test_post_invalid_json(self):
        """POST з невалідним JSON → 400 і без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'TT',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        r = self.url_open(
            '/bridge/tiktok/webhook',
            data=b'{bad json',
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': ''},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_wrong_header_secret(self):
        """POST з неправильним X-Bridge-Secret → 401."""
        self.env['channel.backend'].create(
            {
                'name': 'TT',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload()).encode('utf-8')
        r = self.url_open(
            '/bridge/tiktok/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': 'wrong'},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_non_receive_event(self):
        """POST з валідним підписом, event != im.message.receive → 200 без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'TT',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload(event='other.event')).encode('utf-8')
        sig = _sign(body, self.SECRET)
        r = self.url_open(
            '/bridge/tiktok/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': sig},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_receive_event_creates_message(self):
        """POST з валідним підписом і event = im.message.receive → 200 і запис."""
        self.env['channel.backend'].create(
            {
                'name': 'TT',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload()).encode('utf-8')
        sig = _sign(body, self.SECRET)
        r = self.url_open(
            '/bridge/tiktok/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': sig},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._incoming_count(), 1)


@tagged('post_install', '-at_install')
class TestLiveChatWebhook(HttpCase):
    """Тести для маршруту /bridge/livechat/webhook."""

    SECRET = 'lc_secret'
    SERVICE = 'livechat'

    def setUp(self):
        super().setUp()
        self.authenticate('', '')

    def _incoming_count(self):
        return self.env['channel.message'].search_count(
            [('service', '=', self.SERVICE), ('direction', '=', 'incoming')]
        )

    def _payload(self, event='incoming_event', text='Привіт'):
        return {
            'event': event,
            'data': {'id': 'msg_1', 'text': text},
        }

    def test_post_no_backend(self):
        """POST без налаштованого бекенда → 404."""
        body = json.dumps(self._payload()).encode('utf-8')
        r = self.url_open(
            '/bridge/livechat/webhook',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Bridge-Secret': _sign(body, self.SECRET),
            },
        )
        self.assertEqual(r.status_code, 404)

    def test_post_empty_body(self):
        """POST з порожнім тілом → 200 (error) і без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'LC',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        r = self.opener.post(
            self.base_url() + '/bridge/livechat/webhook',
            data=b'',
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': ''},
        )
        self.assertEqual(r.status_code, 200)
        resp = json.loads(r.text or '{}')
        self.assertEqual(resp.get('status'), 'error')
        self.assertEqual(self._incoming_count(), 0)

    def test_post_invalid_json(self):
        """POST з невалідним JSON → 400 і без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'LC',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        r = self.url_open(
            '/bridge/livechat/webhook',
            data=b'{bad',
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': ''},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_wrong_header_secret(self):
        """POST з неправильним X-Bridge-Secret → 401."""
        self.env['channel.backend'].create(
            {
                'name': 'LC',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload()).encode('utf-8')
        r = self.url_open(
            '/bridge/livechat/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': 'wrong'},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self._incoming_count(), 0)

    def test_post_non_incoming_event(self):
        """POST з валідним підписом, event != incoming_event → 200 без запису."""
        self.env['channel.backend'].create(
            {
                'name': 'LC',
                'service': self.SERVICE,
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': self.SECRET,
            }
        )
        body = json.dumps(self._payload(event='other_event')).encode('utf-8')
        sig = _sign(body, self.SECRET)
        r = self.url_open(
            '/bridge/livechat/webhook',
            data=body,
            headers={'Content-Type': 'application/json', 'X-Bridge-Secret': sig},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._incoming_count(), 0)
