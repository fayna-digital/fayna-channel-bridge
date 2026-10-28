import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ChannelDeliveryLog(models.Model):
    """Журнал вихідних HTTP-доставок у провайдера.

    Навіщо окрема модель, а не лише `channel.message`:
    `channel.message` — це бізнес-журнал переписки (те, що бачить оператор).
    Тут — технічний слід виклику API провайдера: результат, код відповіді,
    фрагмент помилки. Саме цей журнал відповідає на питання «чому
    повідомлення не дійшло» без здогадів.

    Контракт запису — ОДИН рядок на завершений виклик, а не на кожну спробу.
    Retry всередині виклику не плодить рядки: їх кількість видно в полі
    `attempts`, а `status_code`/`ok` описують фінальний результат. Оператору
    потрібна відповідь «дійшло чи ні і з якої спроби», а не три рядки шуму
    на кожне повідомлення. Кілька рядків на один `channel.message` буває лише
    при кількох окремих викликах (fallback на інший канал), не через retry.

    Записи створюються через `sudo()` з транспорту: відправка йде від імені
    системи, а читати журнал має право лише менеджер каналів (див.
    `security/ir.model.access.csv`).

    PII: `error_snippet` обрізаний до 240 символів і проходить через
    `_mask_secrets()` транспорту — токени й телефони в журнал не потрапляють.
    """

    _name = 'channel.delivery.log'
    _description = 'Channel outbound delivery log'
    _order = 'id desc'
    _rec_name = 'endpoint'

    created_at = fields.Datetime(
        string='Created at',
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    backend_id = fields.Many2one(
        comodel_name='channel.backend',
        string='Channel',
        ondelete='set null',
        index=True,
        help='Канал, через який виконувалася доставка. Порожньо для '
        'викликів, що не належать жодному каналу (напр. перевірка токена).',
    )
    service = fields.Char(
        string='Service',
        index=True,
        help='Технічний код каналу на момент доставки (telegram, viber…). '
        'Дублює backend.service навмисно: журнал має лишатися читабельним '
        'навіть після видалення каналу.',
    )
    external_thread_id = fields.Char(
        string='Recipient',
        index=True,
        help='Ідентифікатор отримувача в провайдера (chat_id, PSID, wa_id…).',
    )
    endpoint = fields.Char(
        string='Endpoint',
        help='URL, на який виконувався виклик (без query-параметрів із токеном).',
    )
    event_type = fields.Char(
        string='Event type',
        default='message',
        help='Що саме надсилали: message, typing, mark_seen, set_webhook…',
    )
    ok = fields.Boolean(string='Success', default=False, index=True)
    status_code = fields.Integer(string='HTTP status')
    attempts = fields.Integer(
        string='Attempts',
        default=1,
        help='Скільки HTTP-спроб знадобилося (1 = з першого разу).',
    )
    error_snippet = fields.Char(
        string='Error',
        help='Перші 240 символів відповіді провайдера або тексту винятку.',
    )

    def name_get(self):
        """Читабельна назва рядка в списках і в полі many2one."""
        result = []
        for record in self:
            label = '{} → {}'.format(
                record.service or record.endpoint or 'delivery',
                record.external_thread_id or '—',
            )
            result.append((record.id, label))
        return result
