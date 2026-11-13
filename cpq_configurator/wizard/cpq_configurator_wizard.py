from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CpqConfiguratorWizard(models.TransientModel):
    _name = 'cpqc.configurator.wizard'
    _description = 'CPQ Configurator'

    sale_line_id = fields.Many2one('sale.order.line', required=True, ondelete='cascade')
    cpq_product_id = fields.Many2one('cpqc.product', required=True)
    line_ids = fields.One2many('cpqc.configurator.wizard.line', 'wizard_id')
    price_total = fields.Float('Total Price (excl. tax)', digits='Product Price', readonly=True)
    price_breakdown = fields.Text('Price breakdown', readonly=True)

    def _init_lines(self):
        self.ensure_one()
        if self.line_ids:
            self.line_ids.unlink()
        existing = self.sale_line_id.cpqc_configuration_id
        lines = []
        if existing:
            for cval in existing.value_ids.sorted(lambda v: v.attribute_id.sequence):
                lines.append((0, 0, {
                    'attribute_id': cval.attribute_id.id,
                    'sequence': cval.attribute_id.sequence,
                    'value_list_id': cval.value_list_id.id if cval.value_list_id else False,
                    'value_numeric': cval.value_numeric,
                    'value_boolean': cval.value_boolean,
                }))
        else:
            for attr in self.cpq_product_id.attribute_ids.sorted('sequence'):
                default_list = attr.value_ids.filtered('is_default')[:1]
                if not default_list and attr.attribute_type == 'list':
                    default_list = attr.value_ids[:1]
                lines.append((0, 0, {
                    'attribute_id': attr.id,
                    'sequence': attr.sequence,
                    'value_list_id': default_list.id if attr.attribute_type == 'list' and default_list else False,
                    'value_numeric': attr.numeric_default if attr.attribute_type == 'numeric' else 0.0,
                    'value_boolean': attr.bool_default if attr.attribute_type == 'boolean' else False,
                }))
        if lines:
            self.write({'line_ids': lines})
        self._recompute_price()

    @api.onchange('line_ids')
    def _onchange_lines(self):
        self._recompute_price()

    def _values_by_attr(self):
        self.ensure_one()
        result = {}
        for wl in self.line_ids:
            result[wl.attribute_id.id] = {
                'numeric': wl.value_numeric,
                'list_value': wl.value_list_id,
                'bool': wl.value_boolean,
            }
        return result

    def _recompute_price(self):
        self.ensure_one()
        res = self.cpq_product_id._compute_cpq_price(self._values_by_attr())
        currency = res['currency']
        breakdown = ['%s: %.2f %s' % (l['label'], l['amount'], currency)
                     for l in res['lines']]
        self.price_total = res['total']
        self.price_breakdown = '\n'.join(breakdown)

    def _get_lines_to_validate(self):
        """Lines checked at confirmation. Add-ons can override to skip lines
        that their rules have hidden."""
        return self.line_ids

    def _validate_configuration(self):
        self.ensure_one()
        errors = []
        for wl in self._get_lines_to_validate():
            attr = wl.attribute_id
            if attr.attribute_type == 'numeric':
                value = wl.value_numeric
                if not value:
                    if attr.is_required:
                        errors.append(_('%s is required.') % attr.name)
                    continue
                low, high = attr.numeric_min, attr.numeric_max
                if (low and value < low) or (high and value > high):
                    unit = (' %s' % attr.numeric_unit) if attr.numeric_unit else ''
                    errors.append(_('%s must be between %g and %g%s (got %g%s).') % (
                        attr.name, low, high, unit, value, unit))
            elif attr.attribute_type == 'list':
                if attr.is_required and not wl.value_list_id:
                    errors.append(_('%s is required.') % attr.name)
        if errors:
            raise UserError('\n'.join(errors))

    def action_confirm(self):
        self.ensure_one()
        self._validate_configuration()
        self._recompute_price()
        sale_line = self.sale_line_id
        config_vals = {
            'sale_line_id': sale_line.id,
            'cpq_product_id': self.cpq_product_id.id,
            'price_unit': self.price_total,
        }
        config = sale_line.cpqc_configuration_id
        if config:
            config.value_ids.unlink()
            config.write(config_vals)
        else:
            config = self.env['cpqc.configuration'].create(config_vals)
        self.env['cpqc.configuration.value'].create([{
            'configuration_id': config.id,
            'attribute_id': wl.attribute_id.id,
            'value_list_id': wl.value_list_id.id if wl.value_list_id else False,
            'value_numeric': wl.value_numeric,
            'value_boolean': wl.value_boolean,
        } for wl in self.line_ids])
        sale_line.write({
            'cpqc_configuration_id': config.id,
            'price_unit': self.price_total,
            'name': config.summary or sale_line.name,
        })
        return {'type': 'ir.actions.act_window_close'}


class CpqConfiguratorWizardLine(models.TransientModel):
    _name = 'cpqc.configurator.wizard.line'
    _description = 'CPQ Configurator Line'
    _order = 'sequence, attribute_id'

    wizard_id = fields.Many2one('cpqc.configurator.wizard', ondelete='cascade')
    sequence = fields.Integer(default=10)
    attribute_id = fields.Many2one('cpqc.attribute', required=True)
    value_list_id = fields.Many2one(
        'cpqc.attribute.value', domain="[('attribute_id', '=', attribute_id)]")
    value_numeric = fields.Float(digits=(16, 4))
    value_boolean = fields.Boolean()

    attribute_type = fields.Selection(related='attribute_id.attribute_type', readonly=True)
    attribute_label = fields.Char(compute='_compute_attribute_label')

    @api.depends('attribute_id', 'attribute_id.name', 'attribute_id.numeric_unit')
    def _compute_attribute_label(self):
        for line in self:
            attr = line.attribute_id
            if attr.attribute_type == 'numeric' and attr.numeric_unit:
                line.attribute_label = '%s (%s)' % (attr.name, attr.numeric_unit)
            else:
                line.attribute_label = attr.name or ''
