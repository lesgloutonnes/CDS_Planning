from odoo import fields, models


class EmployeeUnavailability(models.Model):
    _name = "chc_cds_planning.employee_unavailability"
    _description = "Indisponibilité des employés"

    employee_id = fields.Many2one("hr.employee", string="Employé", required=True)
    day_of_week = fields.Selection(
        [
            ("0", "Lundi"),
            ("1", "Mardi"),
            ("2", "Mercredi"),
            ("3", "Jeudi"),
            ("4", "Vendredi"),
            ("5", "Toute la semaine"),
        ],
        string="Jour",
        required=True,
    )
    am = fields.Boolean(string="AM", default=False)
    pm = fields.Boolean(string="PM", default=False)

    reason = fields.Text(string="Raison")
