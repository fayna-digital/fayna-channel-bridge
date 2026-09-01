# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License LGPL-3 (GNU Lesser General Public License v3.0).
"""Тести для `channel_backend`:
- `_split_text_by_limit` (8 тестів)
- `_looks_like_image` (5 тестів)
- `action_switch_all_to_own` (3 тести)
- `action_retry_check` (3 тести)
"""

from unittest.mock import patch

from odoo.addons.fayna_channel_bridge.models.channel_backend import ChannelBackend
from odoo.tests import TransactionCase


class TestSplitTextHelper(TransactionCase):
    """Тести для статичного методу `_split_text_by_limit`."""

    MAX_CHARS = 50
    EFFECTIVE_MAX = MAX_CHARS - 20

    def _backend(self):
        return self.env['channel.backend'].create(
            {
                'name': 'Split Test',
                'service': 'telegram',
                'provider': 'direct',
                'active': True,
            }
        )

    def test_empty_string_returns_empty_list(self):
        """Порожній рядок → порожній список."""
        backend = self._backend()
        result = backend._split_text_by_limit('', self.MAX_CHARS)
        self.assertEqual(result, [])

    def test_short_text_returns_single_element(self):
        """Короткий текст → один елемент, рівний вхідному."""
        backend = self._backend()
        text = 'Короткий текст'
        result = backend._split_text_by_limit(text, self.MAX_CHARS)
        self.assertEqual(result, [text])

    def test_exact_max_length_returns_single_element(self):
        """Текст рівно `max_chars` → один елемент."""
        backend = self._backend()
        text = 'a' * self.MAX_CHARS
        result = backend._split_text_by_limit(text, self.MAX_CHARS)
        self.assertEqual(result, [text])

    def test_two_paragraphs_exceed_limit_split_by_paragraph(self):
        """Два абзаци, що разом не влазять → два елементи, кожен абзац."""
        backend = self._backend()
        para1 = 'a' * self.EFFECTIVE_MAX
        para2 = 'b' * self.EFFECTIVE_MAX
        text = f'{para1}\n\n{para2}'
        result = backend._split_text_by_limit(text, self.MAX_CHARS)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], para1.strip())
        self.assertEqual(result[1], para2.strip())

    def test_sentence_split_when_paragraph_too_long(self):
        """Один абзац, кілька речень → розбито по реченнях."""
        backend = self._backend()
        s1 = 'a' * 24 + '.'
        s2 = 'b' * 24 + '.'
        text = f'{s1} {s2}'
        result = backend._split_text_by_limit(text, self.MAX_CHARS)
        self.assertEqual(len(result), 2)
        for part in result:
            self.assertLessEqual(len(part), self.EFFECTIVE_MAX)

    def test_word_split_when_sentence_too_long(self):
        """Один довгий речення без розділових → розбито по словах."""
        backend = self._backend()
        words = ['слово'] * 10  # 5*10=50 > effective_max
        sentence = ' '.join(words) + '.'
        result = backend._split_text_by_limit(sentence, self.MAX_CHARS)
        self.assertGreater(len(result), 1)
        for part in result:
            self.assertLessEqual(len(part), self.EFFECTIVE_MAX)

    def test_hard_split_long_word(self):
        """Один слово довше `effective_max` → жорстке розбиття."""
        backend = self._backend()
        long_word = 'x' * (self.EFFECTIVE_MAX * 3 + 5)
        result = backend._split_text_by_limit(long_word, self.MAX_CHARS)
        self.assertGreater(len(result), 1)
        for part in result:
            self.assertLessEqual(len(part), self.EFFECTIVE_MAX)

    def test_invariant_no_part_exceeds_effective_max_and_all_words_present(self):
        """Жодна частина не перевищує `effective_max`, усі слова присутні."""
        backend = self._backend()
        text = (
            'Перше речення. Друге речення, яке трохи довше.\n\n'
            'Третій абзац містить кілька слів і ще одне речення.'
        )
        result = backend._split_text_by_limit(text, self.MAX_CHARS)
        for part in result:
            self.assertLessEqual(len(part), self.EFFECTIVE_MAX)
        original_words = [w for w in text.replace('\n', ' ').split(' ') if w]
        rebuilt_words = []
        for part in result:
            rebuilt_words.extend([w for w in part.split(' ') if w])
        self.assertCountEqual(original_words, rebuilt_words)


class TestLooksLikeImageHelper(TransactionCase):
    """Тести для статичного методу `_looks_like_image`."""

    def _backend(self):
        return self.env['channel.backend'].create(
            {
                'name': 'Image Test',
                'service': 'telegram',
                'provider': 'direct',
                'active': True,
            }
        )

    def test_empty_value_returns_false(self):
        """Порожнє значення → False."""
        backend = self._backend()
        self.assertFalse(backend._looks_like_image(''))

    def test_no_extension_returns_false(self):
        """URL без розширення → False."""
        backend = self._backend()
        self.assertFalse(backend._looks_like_image('http://example.com/image'))

    def test_valid_image_extensions_case_insensitive(self):
        """Різні розширення зображень (різний регістр) → True."""
        backend = self._backend()
        for ext in ('jpg', 'JPG', 'png', 'Gif', 'JPEG', 'webp'):
            url = f'http://example.com/pic.{ext}'
            self.assertTrue(backend._looks_like_image(url), f'{ext} should be recognized')

    def test_url_with_query_ignores_query(self):
        """URL з параметрами після `?` → розширення враховується."""
        backend = self._backend()
        url = 'http://example.com/photo.jpg?size=large'
        self.assertTrue(backend._looks_like_image(url))

    def test_invalid_extension_returns_false(self):
        """Нерелевантне розширення → False."""
        backend = self._backend()
        url = 'http://example.com/document.txt'
        self.assertFalse(backend._looks_like_image(url))


class TestActionSwitchAllToOwnHelper(TransactionCase):
    """Тести для методу `action_switch_all_to_own`."""

    OWN_TRANSPORT = 'own'
    OTHER_TRANSPORT = 'auto'

    def _make_backend(self, active=True, transport=OTHER_TRANSPORT):
        return self.env['channel.backend'].create(
            {
                'name': f'Backend {transport}',
                'service': 'telegram',
                'provider': 'direct',
                'active': active,
                'transport_priority': transport,
            }
        )

    def test_switch_multiple_backends(self):
        """Кілька активних бекендів з іншим транспортом → перемикаються."""
        b1 = self._make_backend(active=True, transport=self.OTHER_TRANSPORT)
        b2 = self._make_backend(active=True, transport=self.OTHER_TRANSPORT)
        b3 = self._make_backend(active=False, transport=self.OTHER_TRANSPORT)
        count = self.env['channel.backend'].action_switch_all_to_own()
        self.assertEqual(count, 2)
        b1.invalidate_recordset()
        b2.invalidate_recordset()
        b3.invalidate_recordset()
        self.assertEqual(b1.transport_priority, self.OWN_TRANSPORT)
        self.assertEqual(b2.transport_priority, self.OWN_TRANSPORT)
        self.assertEqual(b3.transport_priority, self.OTHER_TRANSPORT)

    def test_no_switch_when_all_own(self):
        """Всі активні вже на `own` → повертає 0, нічого не змінює."""
        b = self._make_backend(active=True, transport=self.OWN_TRANSPORT)
        count = self.env['channel.backend'].action_switch_all_to_own()
        self.assertEqual(count, 0)
        b.invalidate_recordset()
        self.assertEqual(b.transport_priority, self.OWN_TRANSPORT)

    def test_inactive_backends_not_switched(self):
        """Неактивний бекенд з іншим транспортом не враховується."""
        b = self._make_backend(active=False, transport=self.OTHER_TRANSPORT)
        count = self.env['channel.backend'].action_switch_all_to_own()
        self.assertEqual(count, 0)
        b.invalidate_recordset()
        self.assertEqual(b.transport_priority, self.OTHER_TRANSPORT)


class TestActionRetryCheckHelper(TransactionCase):
    """Тести для методу `action_retry_check`."""

    def _make_backend(self, service='viber'):
        return self.env['channel.backend'].create(
            {
                'name': f'{service.capitalize()} Backend',
                'service': service,
                'provider': 'direct',
                'active': True,
            }
        )

    def test_non_telegram_channel_records_failure(self):
        """Не‑Telegram канал → записує помилку «not implemented»."""
        backend = self._make_backend(service='viber')
        result = backend.action_retry_check()
        self.assertFalse(backend.last_healthcheck_ok)
        self.assertTrue(backend.last_error)
        self.assertIn('not implemented', backend.last_error.lower())
        self.assertEqual(result.get('tag'), 'display_notification')

    def test_telegram_success(self):
        """Telegram‑канал, успішна реєстрація вебхука."""
        backend = self._make_backend(service='telegram')
        backend.write({'bot_token': '123:ABC'})
        with patch.object(
            ChannelBackend,
            'register_telegram_webhook',
            return_value=('https://example.com/webhook', ''),
        ):
            result = backend.action_retry_check()
        self.assertTrue(backend.last_healthcheck_ok)
        self.assertFalse(backend.last_error)
        self.assertEqual(result.get('tag'), 'display_notification')
        self.assertEqual(result.get('params', {}).get('type'), 'success')

    def test_telegram_failure(self):
        """Telegram‑канал, помилка реєстрації вебхука."""
        backend = self._make_backend(service='telegram')
        backend.write({'bot_token': '123:ABC'})
        error_msg = 'Invalid token'
        with patch.object(
            ChannelBackend,
            'register_telegram_webhook',
            return_value=('', error_msg),
        ):
            result = backend.action_retry_check()
        self.assertFalse(backend.last_healthcheck_ok)
        self.assertIn(error_msg, backend.last_error)
        self.assertEqual(result.get('tag'), 'display_notification')
        self.assertEqual(result.get('params', {}).get('type'), 'danger')
