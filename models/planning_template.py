from odoo import api, fields, models


class PlanningTemplate(models.Model):
    _name = "chc_cds_planning.planning_template"
    _description = "Modèle de planning réutilisable"
    _order = "name"

    name = fields.Char(string="Nom du modèle", required=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Actif", default=True)
    is_default = fields.Boolean(
        string="Modèle par défaut",
        help="Si coché, ce modèle sera utilisé par défaut pour les nouveaux plannings",
    )

    # Lignes du template
    template_line_ids = fields.One2many(
        "chc_cds_planning.planning_template_line", "template_id", string="Lignes du modèle"
    )

    @api.constrains("is_default")
    def _check_unique_default(self):
        if self.is_default:
            other_defaults = self.search(
                [("is_default", "=", True), ("id", "!=", self.id)]
            )
            if other_defaults:
                other_defaults.write({"is_default": False})

    def action_apply_to_planning(self):
        """Action pour appliquer ce template à un planning existant"""
        return {
            "type": "ir.actions.act_window",
            "name": "Appliquer le modèle",
            "res_model": "chc_cds_planning.planning_template_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_template_id": self.id},
        }


class PlanningTemplateLine(models.Model):
    _name = "chc_cds_planning.planning_template_line"
    _description = "Ligne de modèle de planning"
    _order = "day_order, period_order"

    template_id = fields.Many2one(
        "chc_cds_planning.planning_template",
        string="Modèle",
        required=True,
        ondelete="cascade",
    )

    employee_id = fields.Many2one("hr.employee", string="Employé", required=True)
    site_id = fields.Many2one("chc_cds_planning.site", string="Site", required=True)
    permanence_type_id = fields.Many2one(
        "chc_cds_planning.permanence_type", string="Type de permanence", required=True
    )

    day = fields.Selection(
        [
            ("monday", "Lundi"),
            ("tuesday", "Mardi"),
            ("wednesday", "Mercredi"),
            ("thursday", "Jeudi"),
            ("friday", "Vendredi"),
        ],
        string="Jour",
        required=True,
    )

    period = fields.Selection(
        [
            ("am", "Matin"),
            ("pm", "Après-midi"),
            ("full", "Journée complète"),
        ],
        string="Période",
        required=True,
    )

    # Champs pour l'ordre d'affichage
    day_order = fields.Integer(compute="_compute_orders", store=True)
    period_order = fields.Integer(compute="_compute_orders", store=True)

    notes = fields.Text(string="Notes")

    @api.depends("day", "period")
    def _compute_orders(self):
        day_mapping = {
            "monday": 1,
            "tuesday": 2,
            "wednesday": 3,
            "thursday": 4,
            "friday": 5,
        }
        period_mapping = {"am": 1, "full": 2, "pm": 3}

        for line in self:
            line.day_order = day_mapping.get(line.day, 0)
            line.period_order = period_mapping.get(line.period, 0)

    @api.onchange("site_id")
    def _onchange_site_filter_permanence_type(self):
        if self.site_id:
            return {
                "domain": {"permanence_type_id": [("site_ids", "in", self.site_id.id)]}
            }
