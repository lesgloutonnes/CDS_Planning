from datetime import date

from odoo import api, fields, models


class FridayRotationCounter(models.Model):
    """Compteur persistant pour la rotation des vendredis PM MLE"""

    _name = "chc_cds_planning.friday_rotation_counter"
    _description = "Compteur rotation vendredi PM MLE"

    employee_id = fields.Many2one(
        "hr.employee", string="Employé", required=True, ondelete="cascade"
    )
    counter = fields.Integer(string="Nombre de vendredis PM MLE", default=0)
    last_assignment_date = fields.Date(string="Dernier vendredi PM MLE")
    last_reset_year = fields.Integer(
        string="Année du dernier reset", default=lambda self: date.today().year
    )

    _sql_constraints = [
        ("employee_unique", "UNIQUE(employee_id)", "Un seul compteur par employé!")
    ]

    @api.model
    def check_and_reset_if_new_year(self):
        """Vérifie si on est dans une nouvelle année et réinitialise les compteurs si nécessaire"""
        current_year = date.today().year
        counters = self.search([])

        counters_to_reset = counters.filtered(
            lambda c: c.last_reset_year < current_year
        )

        if counters_to_reset:
            counters_to_reset.write(
                {
                    "counter": 0,
                    "last_assignment_date": False,
                    "last_reset_year": current_year,
                }
            )
            return len(counters_to_reset)
        return 0

    @classmethod
    def get_or_create_counter(cls, env, employee_id):
        """Récupère ou crée le compteur pour un employé"""
        counter = env["chc_cds_planning.friday_rotation_counter"].search(
            [("employee_id", "=", employee_id)], limit=1
        )

        if not counter:
            counter = env["chc_cds_planning.friday_rotation_counter"].create(
                {"employee_id": employee_id, "counter": 0}
            )

        return counter

    @classmethod
    def reset_all_counters(cls, env):
        """Réinitialise tous les compteurs manuellement"""
        current_year = date.today().year
        counters = env["chc_cds_planning.friday_rotation_counter"].search([])
        counters.write(
            {
                "counter": 0,
                "last_assignment_date": False,
                "last_reset_year": current_year,
            }
        )
