from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class CpqFormula(models.Model):
    _name = 'cpqc.formula'
    _description = 'CPQ Pricing Formula'
    _order = 'cpq_product_id, sequence, id'

    cpq_product_id = fields.Many2one('cpqc.product', required=True, ondelete='cascade')
    name = fields.Char(string='Formula Name', required=True)
    sequence = fields.Integer(default=10)
    expression = fields.Char(
        string='Expression', required=True,
        help="Arithmetic expression over attribute codes. "
             "Allowed operators: + - * / ** ( ). "
             "Allowed functions: round, min, max, abs. "
             "Example: length * width * rate_material",
    )
    active = fields.Boolean(default=True)

    # Functions exposed to the expression. No builtins, no imports, no attribute
    # access: a restricted arithmetic evaluator, not arbitrary Python.
    _ALLOWED_FUNCS = {
        'round': round,
        'min': min,
        'max': max,
        'abs': abs,
    }

    def _eval_context(self, var):
        ctx = dict(self._ALLOWED_FUNCS)
        ctx.update(var)
        return ctx

    def _evaluate(self, var):
        """Evaluate the formula against a {code: value} dict. Returns a float,
        0.0 on any error so a bad formula never breaks a quotation."""
        self.ensure_one()
        if not self.active or not self.expression:
            return 0.0
        try:
            res = safe_eval(self.expression, self._eval_context(var))
            return float(res or 0.0)
        except Exception:
            return 0.0

    @api.constrains('expression')
    def _check_expression(self):
        """Reject a formula that cannot evaluate, with the attribute codes set
        to 1, so the user is warned at save time rather than on the quotation."""
        for formula in self:
            if not formula.expression:
                continue
            codes = formula.cpq_product_id.attribute_ids.filtered('code').mapped('code')
            probe = {c: 1.0 for c in codes}
            try:
                safe_eval(formula.expression, formula._eval_context(probe))
            except Exception as err:
                raise ValidationError(_(
                    "Formula '%s' cannot be evaluated: %s\n"
                    "Use attribute codes and arithmetic only "
                    "(+ - * / ** , round, min, max, abs)."
                ) % (formula.name or formula.expression, err))
