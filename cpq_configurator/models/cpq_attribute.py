import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_CODE_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


class CpqAttribute(models.Model):
    _name = 'cpqc.attribute'
    _description = 'CPQ Attribute'
    _order = 'cpq_product_id, sequence, id'

    cpq_product_id = fields.Many2one('cpqc.product', required=True, ondelete='cascade')
    name = fields.Char(string='Name', required=True)
    code = fields.Char(
        string='Code',
        help="Variable name used in pricing formulas (letters, digits and "
             "underscore, must start with a letter). Generated from the name "
             "if left empty.",
    )
    sequence = fields.Integer(default=10)
    attribute_type = fields.Selection([
        ('list',    'Selection list'),
        ('numeric', 'Numeric'),
        ('boolean', 'Yes / No'),
    ], string='Type', required=True, default='list')
    is_required = fields.Boolean(string='Required', default=True)

    # Numeric
    numeric_rate = fields.Float(
        string='Rate', digits='Product Price',
        help="If set, the price gets 'value x rate' for this attribute. "
             "Leave empty to use the value only inside a formula.",
    )
    numeric_unit = fields.Char(string='Unit')
    numeric_min = fields.Float(string='Min', default=0.0)
    numeric_max = fields.Float(string='Max', default=0.0)
    numeric_default = fields.Float(string='Default', default=0.0)

    # Boolean
    bool_surcharge = fields.Float(string='Surcharge if Yes', digits='Product Price')
    bool_default = fields.Boolean(string='Default')

    value_ids = fields.One2many('cpqc.attribute.value', 'attribute_id',
                                 string='Values', copy=True)

    @api.constrains('code')
    def _check_code(self):
        for attr in self:
            if not attr.code:
                continue
            if not _CODE_RE.match(attr.code):
                raise ValidationError(_(
                    "Attribute code '%s' is not valid. Use letters, digits and "
                    "underscore only, starting with a letter (e.g. 'length', "
                    "'rate_material')."
                ) % attr.code)
            twin = self.search([
                ('cpq_product_id', '=', attr.cpq_product_id.id),
                ('code', '=', attr.code),
                ('id', '!=', attr.id),
            ], limit=1)
            if twin:
                raise ValidationError(_(
                    "Attribute code '%s' is already used on this product. "
                    "Codes must be unique so formulas stay unambiguous."
                ) % attr.code)

    @api.model
    def _slugify_code(self, name):
        base = re.sub(r'[^a-zA-Z0-9_]', '_', (name or '').strip().lower())
        base = re.sub(r'_+', '_', base).strip('_')
        if not base or not base[0].isalpha():
            base = 'f_' + base
        return base

    def _assign_code(self):
        """Give every attribute a unique code, derived from its name if empty."""
        for attr in self:
            if attr.code:
                continue
            candidate = attr._slugify_code(attr.name)
            existing = set(attr.cpq_product_id.attribute_ids.filtered(
                lambda a: a.id != attr.id).mapped('code'))
            code = candidate
            i = 2
            while code in existing:
                code = '%s_%d' % (candidate, i)
                i += 1
            attr.code = code

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._assign_code()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals or 'code' in vals:
            self.filtered(lambda a: not a.code)._assign_code()
        return res

    def _ensure_single_default(self):
        """A list attribute should open the configurator on one default value,
        otherwise the first option is used. Keep at most one ticked."""
        for attr in self:
            if attr.attribute_type != 'list':
                continue
            defaults = attr.value_ids.filtered('is_default')
            if len(defaults) > 1:
                (defaults - defaults[0]).is_default = False


class CpqAttributeValue(models.Model):
    _name = 'cpqc.attribute.value'
    _description = 'CPQ Attribute Value'
    _order = 'attribute_id, sequence, id'

    attribute_id = fields.Many2one('cpqc.attribute', required=True, ondelete='cascade')
    cpq_product_id = fields.Many2one(
        'cpqc.product', related='attribute_id.cpq_product_id',
        store=True, index=True,
    )
    name = fields.Char(string='Value', required=True)
    sequence = fields.Integer(default=10)
    surcharge = fields.Float(string='Surcharge', digits='Product Price')
    number_value = fields.Float(
        string='Formula Value',
        help="Numeric value this option exposes to pricing formulas through "
             "the attribute code (e.g. a rate per m2 carried by a material).",
    )
    is_default = fields.Boolean(string='Default')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.attribute_id._ensure_single_default()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'is_default' in vals:
            self.attribute_id._ensure_single_default()
        return res
