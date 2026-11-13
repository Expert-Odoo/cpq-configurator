from odoo import models, fields, api


class CpqConfiguration(models.Model):
    _name = 'cpqc.configuration'
    _description = 'Saved CPQ Configuration'

    sale_line_id = fields.Many2one(
        'sale.order.line', string='Quotation Line',
        required=True, ondelete='cascade',
    )
    cpq_product_id = fields.Many2one(
        'cpqc.product', string='Configurable Product', required=True,
    )
    value_ids = fields.One2many(
        'cpqc.configuration.value', 'configuration_id',
        string='Values', copy=True,
    )
    price_unit = fields.Float('Unit Price (excl. tax)', digits='Product Price')
    summary = fields.Text('Summary', compute='_compute_summary', store=True)

    @api.depends('value_ids', 'value_ids.value_list_id',
                 'value_ids.value_numeric', 'value_ids.value_boolean')
    def _compute_summary(self):
        for config in self:
            parts = []
            for val in config.value_ids.sorted(lambda v: v.attribute_id.sequence):
                attr = val.attribute_id
                if attr.attribute_type == 'list' and val.value_list_id:
                    parts.append(val.value_list_id.name)
                elif attr.attribute_type == 'boolean':
                    if val.value_boolean:
                        parts.append(attr.name)
                elif attr.attribute_type == 'numeric':
                    unit = (' %s' % attr.numeric_unit) if attr.numeric_unit else ''
                    parts.append('%s: %g%s' % (attr.name, val.value_numeric, unit))
            config.summary = ' - '.join(parts)


class CpqConfigurationValue(models.Model):
    _name = 'cpqc.configuration.value'
    _description = 'CPQ Configuration Value'

    configuration_id = fields.Many2one(
        'cpqc.configuration', required=True, ondelete='cascade',
    )
    attribute_id = fields.Many2one('cpqc.attribute', ondelete='cascade')
    value_list_id = fields.Many2one('cpqc.attribute.value')
    value_numeric = fields.Float(digits=(16, 4))
    value_boolean = fields.Boolean()
