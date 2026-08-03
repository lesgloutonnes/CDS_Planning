from datetime import date

from odoo import api, fields, models


class PlanningPresenceStats(models.Model):
    _name = "chc_cds_planning.planning_presence_stats"
    _description = "Statistiques de présence au planning"
    _order = "friday_pm_total desc, employee_name"
    _rec_name = "employee_id"

    employee_id = fields.Many2one(
        "hr.employee", string="Employé", required=True, ondelete="cascade"
    )
    employee_code = fields.Char(
        related="employee_id.employee_code", string="Code", store=True
    )
    employee_name = fields.Char(related="employee_id.name", string="Nom", store=True)

    stats_year = fields.Integer(string="Année", required=True, default=date.today().year)

    total_presence = fields.Integer(
        string="Total affectations",
        help="Nombre total d'affectations dans les plannings de l'année",
    )
    friday_pm_fct = fields.Integer(
        string="Vendredis PM Fonctionnel (MLE)",
        help="Nombre de vendredis après-midi en permanence fonctionnelle MLE",
    )
    friday_pm_tch = fields.Integer(
        string="Vendredis PM Technique (MLE)",
        help="Nombre de vendredis après-midi en permanence technique MLE",
    )
    friday_pm_total = fields.Integer(
        string="Total vendredis PM MLE",
        compute="_compute_friday_pm_total",
        store=True,
    )
    rotation_counter = fields.Integer(
        string="Compteur rotation",
        help="Compteur persistant utilisé par le générateur mensuel",
    )
    last_friday_pm_date = fields.Date(string="Dernier vendredi PM MLE")
    is_rotation_eligible = fields.Boolean(
        string="Éligible rotation",
        help="Qualifié MLE FCT ou TCH et non exclu de la rotation",
    )
    deviation_from_avg = fields.Float(
        string="Écart vs moyenne",
        digits=(16, 1),
        help="Écart par rapport à la moyenne des vendredis PM MLE (éligibles uniquement)",
    )

    _sql_constraints = [
        (
            "employee_year_unique",
            "UNIQUE(employee_id, stats_year)",
            "Une seule ligne de stats par employé et par année.",
        )
    ]

    @api.depends("friday_pm_fct", "friday_pm_tch")
    def _compute_friday_pm_total(self):
        for record in self:
            record.friday_pm_total = record.friday_pm_fct + record.friday_pm_tch

    @api.model
    def _get_mle_site(self):
        return self.env["chc_cds_planning.site"].search([("code", "=", "MLE")], limit=1)

    @api.model
    def _get_perm_types(self):
        return self.env["chc_cds_planning.permanence_type"].search(
            [("code", "in", ["FCT", "TCH"])]
        )

    @api.model
    def _is_rotation_eligible(self, employee, mle_site, perm_types):
        if employee.employee_code == "JUAPE":
            return False
        qualifications = employee.qualification_ids.filtered(
            lambda q: q.site_id.id == mle_site.id
            and q.permanence_type_id.id in perm_types.ids
        )
        return bool(qualifications)

    @api.model
    def _count_friday_pm_assignments(self, employee, year, mle_site, perm_type_code):
        assignments = self.env["chc_cds_planning.planning_assignment"].search(
            [
                ("employee_id", "=", employee.id),
                ("day", "=", "friday"),
                ("period", "=", "pm"),
                ("site_id", "=", mle_site.id),
                ("permanence_type_id.code", "=", perm_type_code),
                ("planning_week_id.start_date", ">=", f"{year}-01-01"),
                ("planning_week_id.start_date", "<=", f"{year}-12-31"),
            ]
        )
        return len(assignments)

    @api.model
    def _count_total_presence(self, employee, year):
        assignments = self.env["chc_cds_planning.planning_assignment"].search(
            [
                ("employee_id", "=", employee.id),
                ("planning_week_id.start_date", ">=", f"{year}-01-01"),
                ("planning_week_id.start_date", "<=", f"{year}-12-31"),
            ]
        )
        return len(assignments)

    @api.model
    def action_refresh_stats(self, year=None):
        """Recalcule les statistiques de présence pour l'année donnée."""
        year = year or date.today().year
        mle_site = self._get_mle_site()
        perm_types = self._get_perm_types()

        if not mle_site:
            return self._open_stats_action(year)

        self.search([("stats_year", "=", year)]).unlink()

        employees = self.env["hr.employee"].search([])
        stats_vals = []

        for employee in employees:
            total_presence = self._count_total_presence(employee, year)
            friday_pm_fct = self._count_friday_pm_assignments(
                employee, year, mle_site, "FCT"
            )
            friday_pm_tch = self._count_friday_pm_assignments(
                employee, year, mle_site, "TCH"
            )
            is_eligible = self._is_rotation_eligible(employee, mle_site, perm_types)

            if not total_presence and not is_eligible:
                continue

            counter_record = self.env[
                "chc_cds_planning.friday_rotation_counter"
            ].search([("employee_id", "=", employee.id)], limit=1)

            stats_vals.append(
                {
                    "employee_id": employee.id,
                    "stats_year": year,
                    "total_presence": total_presence,
                    "friday_pm_fct": friday_pm_fct,
                    "friday_pm_tch": friday_pm_tch,
                    "rotation_counter": counter_record.counter if counter_record else 0,
                    "last_friday_pm_date": (
                        counter_record.last_assignment_date if counter_record else False
                    ),
                    "is_rotation_eligible": is_eligible,
                }
            )

        records = self.create(stats_vals)

        eligible = records.filtered("is_rotation_eligible")
        if eligible:
            avg = sum(eligible.mapped("friday_pm_total")) / len(eligible)
            for record in records:
                if record.is_rotation_eligible:
                    record.deviation_from_avg = record.friday_pm_total - avg

        return self._open_stats_action(year)

    @api.model
    def _open_stats_action(self, year):
        action = self.env.ref(
            "chc_cds_planning.action_chc_cds_planning_presence_stats"
        ).read()[0]
        action["domain"] = [("stats_year", "=", year)]
        action["context"] = dict(
            self.env.context,
            default_stats_year=year,
            search_default_rotation_eligible=1,
        )
        return action

    @api.model
    def get_summary(self, year=None):
        """Retourne un résumé textuel pour l'en-tête de la vue stats."""
        year = year or date.today().year
        records = self.search(
            [("stats_year", "=", year), ("is_rotation_eligible", "=", True)]
        )
        if not records:
            return "Aucune donnée de rotation disponible."

        totals = records.mapped("friday_pm_total")
        avg = sum(totals) / len(totals)
        min_val = min(totals)
        max_val = max(totals)
        spread = max_val - min_val

        return (
            f"Année {year} — {len(records)} employés éligibles — "
            f"Moyenne : {avg:.1f} vendredis PM MLE — "
            f"Min : {min_val} / Max : {max_val} (écart : {spread})"
        )
