from odoo import fields, models


class EmployeeQualifications(models.Model):
    _name = "chc_cds_planning.employee_qualifications"
    _description = "Qualifications des employés"

    employee_id = fields.Many2one("hr.employee", string="Employé", required=True)
    permanence_type_id = fields.Many2one(
        "chc_cds_planning.permanence_type", string="Type de permanence", required=True
    )
    site_id = fields.Many2one("chc_cds_planning.site", string="Site", required=True)
    priority = fields.Selection(
        [
            ("1", "Critique"),
            ("2", "Prioritaire"),
            ("3", "Élevé"),
            ("4", "Moyen"),
            ("5", "Faible"),
            ("6", "En cas de fin du monde"),
        ],
        string="Priorité",
        default="4",
    )
