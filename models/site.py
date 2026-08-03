from odoo import fields, models


class Site(models.Model):
    _name = "chc_cds_planning.site"
    _description = "Site de travail"
    _order = "code"

    name = fields.Char(string="Nom", required=True)
    code = fields.Char(string="Code", required=True, size=3)
    address = fields.Text(string="Adresse")
    active = fields.Boolean(string="Actif", default=True)
    color = fields.Integer(string="Couleur")
