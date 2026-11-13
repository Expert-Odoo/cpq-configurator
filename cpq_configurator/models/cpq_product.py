from odoo import models, fields, api, _


class CpqProduct(models.Model):
    _name = 'cpqc.product'
    _description = 'Configurable Product (CPQ)'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    product_tmpl_id = fields.Many2one(
        'product.template', string='Odoo Product',
        required=True, ondelete='cascade',
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Internal Notes')

    base_price = fields.Float(
        string='Base Price', digits='Product Price', default=0.0,
        help="Starting amount of the unit price. Surcharges, numeric rates "
             "and formulas are added on top of it.",
    )

    attribute_ids = fields.One2many(
        'cpqc.attribute', 'cpq_product_id',
        string='Attributes', copy=True,
    )
    formula_ids = fields.One2many(
        'cpqc.formula', 'cpq_product_id',
        string='Pricing Formulas', copy=True,
    )

    # Convenience sub-views of the values, filtered by attribute kind.
    list_value_ids = fields.One2many(
        'cpqc.attribute.value', 'cpq_product_id',
        string='Selection Values',
        domain=[('attribute_id.attribute_type', '=', 'list')],
    )

    price_preview = fields.Char(
        string='Price Formula', compute='_compute_price_preview', store=False,
    )

    @api.depends('base_price', 'attribute_ids.name', 'attribute_ids.attribute_type',
                 'attribute_ids.numeric_rate', 'formula_ids.name', 'formula_ids.expression')
    def _compute_price_preview(self):
        for p in self:
            parts = []
            if p.base_price:
                parts.append('Base')
            if any(a.attribute_type == 'list' or a.attribute_type == 'boolean'
                   for a in p.attribute_ids):
                parts.append('surcharges')
            if any(a.attribute_type == 'numeric' and a.numeric_rate
                   for a in p.attribute_ids):
                parts.append('attribute rates')
            for f in p.formula_ids:
                parts.append(f.name or 'formula')
            p.price_preview = 'Price = ' + ' + '.join(parts) if parts else 'Price = 0'

    # ------------------------------------------------------------------
    # Pricing engine
    # ------------------------------------------------------------------
    def _variable_dict(self, values_by_attr):
        """Build the {code: value} dict exposed to the pricing formulas.

        values_by_attr maps an attribute id to a dict:
            {'numeric': float, 'list_value': cpqc.attribute.value, 'bool': bool}
        A list attribute exposes the number_value of the selected option, so a
        formula can write things like ``length * width * rate_material``.
        """
        self.ensure_one()
        d = {}
        for attr in self.attribute_ids:
            if not attr.code:
                continue
            v = values_by_attr.get(attr.id, {})
            if attr.attribute_type == 'numeric':
                d[attr.code] = v.get('numeric') or 0.0
            elif attr.attribute_type == 'boolean':
                d[attr.code] = 1.0 if v.get('bool') else 0.0
            elif attr.attribute_type == 'list':
                lv = v.get('list_value')
                d[attr.code] = lv.number_value if lv else 0.0
        return d

    def _compute_cpq_price(self, values_by_attr):
        """Return {'total', 'lines', 'currency'} for a given configuration.

        This is the single entry point for price computation. Paid add-ons
        extend pricing by overriding this method (super() then add their part).
        """
        self.ensure_one()
        currency = self.env.company.currency_id.name or 'EUR'
        total = self.base_price
        lines = []
        if self.base_price:
            lines.append({'label': _('Base price'), 'amount': self.base_price})

        # Surcharges and numeric rates.
        for attr in self.attribute_ids.sorted('sequence'):
            v = values_by_attr.get(attr.id, {})
            if attr.attribute_type == 'list':
                lv = v.get('list_value')
                if lv and lv.surcharge:
                    total += lv.surcharge
                    lines.append({'label': '%s: %s' % (attr.name, lv.name),
                                  'amount': lv.surcharge})
            elif attr.attribute_type == 'boolean':
                if v.get('bool') and attr.bool_surcharge:
                    total += attr.bool_surcharge
                    lines.append({'label': attr.name, 'amount': attr.bool_surcharge})
            elif attr.attribute_type == 'numeric' and attr.numeric_rate:
                value = v.get('numeric') or 0.0
                amount = value * attr.numeric_rate
                total += amount
                unit = (' %s' % attr.numeric_unit) if attr.numeric_unit else ''
                lines.append({
                    'label': '%s: %g%s x %g' % (attr.name, value, unit, attr.numeric_rate),
                    'amount': amount,
                })

        # Named formulas.
        var = self._variable_dict(values_by_attr)
        for formula in self.formula_ids.sorted('sequence'):
            if not formula.active:
                continue
            amount = formula._evaluate(var)
            if amount:
                total += amount
                lines.append({'label': formula.name or _('Formula'), 'amount': amount})

        return {'total': total, 'lines': lines, 'currency': currency}
