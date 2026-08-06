from datetime import date

from odoo import api, fields, models

from ..utils.friday_rotation import get_planning_week_ids_for_year
from ..utils.utils import ISOLATED_ON_SITE_CODES


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
        string="Perm FCT",
        help="Nombre de permanences fonctionnelles (hors on site)",
    )
    friday_pm_tch = fields.Integer(
        string="Perm TCH",
        help="Nombre de permanences techniques (hors on site et on site MLE)",
    )
    friday_pm_total = fields.Integer(
        string="Compteur Vendredi PM",
        compute="_compute_friday_pm_total",
        store=True,
        help="Somme Perm FCT + Perm TCH (hors on site et on site MLE)",
    )
    rotation_counter_fct = fields.Integer(
        string="Compteur rotation FCT",
        help="Compteur persistant permanences fonctionnelles (hors on site)",
    )
    rotation_counter_tch = fields.Integer(
        string="Compteur rotation TCH",
        help="Compteur persistant permanences techniques (hors on site)",
    )
    rotation_counter = fields.Integer(
        string="Compteur rotation total",
        help="Total des compteurs de rotation FCT + TCH",
    )
    last_friday_pm_date = fields.Date(string="Dernier vendredi PM MLE")
    is_rotation_eligible = fields.Boolean(
        string="Éligible rotation",
        help="Qualifié MLE FCT ou TCH et non exclu de la rotation",
    )
    deviation_from_avg = fields.Float(
        string="Écart vs moyenne",
        digits=(16, 1),
        help="Écart par rapport à la moyenne du compteur vendredi PM (éligibles uniquement)",
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
    def _count_perm_assignments(self, employee, year, perm_type_code):
        """Compte les permanences FCT ou TCH de l'année, hors on site / on site MLE.

        - FCT : permanences fonctionnelles uniquement
        - TCH : permanences techniques uniquement (pas ATL / on site MLE)
        - Les sites on site (HEU, HRM, WAR) sont toujours exclus
        - Les permanences spéciales sont exclues
        """
        week_ids = get_planning_week_ids_for_year(self.env, year)
        if not week_ids:
            return 0
        return self.env["chc_cds_planning.planning_assignment"].search_count(
            [
                ("employee_id", "=", employee.id),
                ("permanence_type_id.code", "=", perm_type_code),
                ("site_id.code", "not in", list(ISOLATED_ON_SITE_CODES)),
                ("special_name", "=", False),
                ("planning_week_id", "in", week_ids),
            ]
        )

    @api.model
    def _count_total_presence(self, employee, year):
        week_ids = get_planning_week_ids_for_year(self.env, year)
        if not week_ids:
            return 0
        return self.env["chc_cds_planning.planning_assignment"].search_count(
            [
                ("employee_id", "=", employee.id),
                ("planning_week_id", "in", week_ids),
            ]
        )

    @api.model
    def action_refresh_stats(self, year=None):
        """Recalcule les statistiques de présence pour l'année donnée."""
        year = year or date.today().year
        mle_site = self._get_mle_site()
        perm_types = self._get_perm_types()

        if not mle_site:
            return self._open_stats_action(year)

        self.env[
            "chc_cds_planning.friday_rotation_counter"
        ].rebuild_from_assignments(year)

        self.search([("stats_year", "=", year)]).unlink()

        employees = self.env["hr.employee"].search([])
        stats_vals = []

        for employee in employees:
            total_presence = self._count_total_presence(employee, year)
            perm_fct = self._count_perm_assignments(employee, year, "FCT")
            perm_tch = self._count_perm_assignments(employee, year, "TCH")
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
                    "friday_pm_fct": perm_fct,
                    "friday_pm_tch": perm_tch,
                    "rotation_counter_fct": (
                        counter_record.counter_fct if counter_record else 0
                    ),
                    "rotation_counter_tch": (
                        counter_record.counter_tch if counter_record else 0
                    ),
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
        action["name"] = f"Stats présence & vendredis PM ({year})"
        action["domain"] = [("stats_year", "=", year)]
        action["context"] = dict(
            self.env.context,
            default_stats_year=year,
            search_default_rotation_eligible=1,
        )
        summary = self.get_summary(year)
        # Odoo 17 : notification puis ouverture de la vue stats
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Stats actualisées",
                "message": summary,
                "type": "success" if "éligibles" in summary else "warning",
                "sticky": False,
                "next": action,
            },
        }

    @api.model
    def get_summary(self, year=None):
        """Retourne un résumé textuel pour l'en-tête de la vue stats."""
        year = year or date.today().year
        records = self.search(
            [("stats_year", "=", year), ("is_rotation_eligible", "=", True)]
        )
        if not records:
            return (
                f"Année {year} — aucune donnée de rotation. "
                "Générez des plannings puis actualisez."
            )

        totals = records.mapped("friday_pm_total")
        avg = sum(totals) / len(totals)
        min_val = min(totals)
        max_val = max(totals)
        spread = max_val - min_val

        fct_totals = records.mapped("friday_pm_fct")
        tch_totals = records.mapped("friday_pm_tch")
        fct_spread = max(fct_totals) - min(fct_totals) if fct_totals else 0
        tch_spread = max(tch_totals) - min(tch_totals) if tch_totals else 0

        return (
            f"Année {year} — {len(records)} employés éligibles — "
            f"Moyenne : {avg:.1f} (Perm FCT + Perm TCH) — "
            f"Min : {min_val} / Max : {max_val} (écart : {spread}) — "
            f"Écart Perm FCT : {fct_spread} / Écart Perm TCH : {tch_spread}"
        )
