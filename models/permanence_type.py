from odoo import fields, models


class PermanenceType(models.Model):
    _name = "chc_cds_planning.permanence_type"
    _description = "Type de permanence"
    _order = "name"

    name = fields.Char(string="Nom", required=True)
    code = fields.Char(string="Code", required=True)
    description = fields.Text(string="Description")
    color = fields.Integer(string="Couleur")

    site_ids = fields.Many2many(
        "chc_cds_planning.site",
        string="Sites associés",
        help="Sites où ce type de permanence est applicable.",
    )
