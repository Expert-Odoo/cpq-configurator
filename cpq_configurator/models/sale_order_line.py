from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    cpqc_product_id = fields.Many2one(
        'cpqc.product', string='Configurable Product',
        compute='_compute_cpqc_product_id', store=True,
    )
    cpqc_ok = fields.Boolean(compute='_compute_cpqc_product_id', store=True)
    cpqc_configuration_id = fields.Many2one(
        'cpqc.configuration', string='Configuration',
        ondelete='set null', copy=False,
    )
    cpqc_summary = fields.Text(
        'Configuration Summary', related='cpqc_configuration_id.summary', store=True,
    )

    @api.depends('product_id')
    def _compute_cpqc_product_id(self):
        for line in self:
            cpq = False
            if line.product_id:
                cpq = self.env['cpqc.product'].search([
                    ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                ], limit=1)
            line.cpqc_product_id = cpq
            line.cpqc_ok = bool(cpq)

    def _compute_display_name(self):
        if self.env.context.get('cpqc_selector'):
            for line in self:
                qty = '%g x ' % line.product_uom_qty if line.product_uom_qty != 1 else ''
                mark = ' [ok]' if line.cpqc_configuration_id else ' [ ]'
                line.display_name = '%s%s%s' % (qty, line.product_id.name, mark)
        else:
            super()._compute_display_name()

    def action_configure_cpqc(self):
        self.ensure_one()
        if not self.cpqc_product_id:
            return
        if not self.id:
            raise UserError(_("Please save the quotation before configuring the product."))
        wizard = self.env['cpqc.configurator.wizard'].create({
            'sale_line_id': self.id,
            'cpq_product_id': self.cpqc_product_id.id,
        })
        wizard._init_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Configure Product'),
            'res_model': 'cpqc.configurator.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'dialog_size': 'medium'},
        }


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cpqc_line_count = fields.Integer(compute='_compute_cpqc_line_count')
    cpqc_unconfigured_count = fields.Integer(compute='_compute_cpqc_line_count')

    @api.depends('order_line.cpqc_ok', 'order_line.cpqc_configuration_id')
    def _compute_cpqc_line_count(self):
        for order in self:
            cpq_lines = order.order_line.filtered('cpqc_ok')
            order.cpqc_line_count = len(cpq_lines)
            order.cpqc_unconfigured_count = len(
                cpq_lines.filtered(lambda l: not l.cpqc_configuration_id))

    def action_configure_cpqc_lines(self):
        self.ensure_one()
        cpq_lines = self.order_line.filtered('cpqc_ok')
        if not cpq_lines:
            return
        if len(cpq_lines) == 1:
            return cpq_lines[0].action_configure_cpqc()
        selector = self.env['cpqc.line.selector'].create({
            'order_id': self.id,
            'line_id': (cpq_lines.filtered(lambda l: not l.cpqc_configuration_id)[:1].id
                        or cpq_lines[0].id),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Choose a product to configure'),
            'res_model': 'cpqc.line.selector',
            'res_id': selector.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'cpqc_selector': True},
        }


class CpqLineSelector(models.TransientModel):
    _name = 'cpqc.line.selector'
    _description = 'CPQ Line Selection'

    order_id = fields.Many2one('sale.order', required=True, ondelete='cascade')
    line_id = fields.Many2one(
        'sale.order.line', string='Product to configure',
        domain="[('order_id', '=', order_id), ('cpqc_ok', '=', True)]",
        required=True,
    )
    line_summary = fields.Text(
        related='line_id.cpqc_summary', string='Current configuration', readonly=True,
    )

    def action_open_configurator(self):
        self.ensure_one()
        return self.line_id.action_configure_cpqc()
