from odoo import api, fields, models
from markupsafe import Markup

from ..utils.friday_rotation import is_friday_pm_mle_assignment

# Sites « On Site » distants (TCH : horaires et libellé calendrier dédiés)
ISOLATED_ON_SITE_CODES = frozenset({"HEU", "HRM", "WAR"})


class PlanningAssignment(models.Model):
    _name = "chc_cds_planning.planning_assignment"
    _description = "Planning Assignment"
    _order = "id"

    planning_week_id = fields.Many2one(
        "chc_cds_planning.planning_weekly",
        string="Planning Week",
        required=True,
        ondelete="cascade",
    )

    employee_id = fields.Many2one("hr.employee", string="Employee", required=True)

    site_id = fields.Many2one("chc_cds_planning.site", string="Site")

    permanence_type_id = fields.Many2one(
        "chc_cds_planning.permanence_type", string="Type de permanence"
    )

    # Champs pour les permanences spéciales
    special_name = fields.Char(
        string="Nom",
        help="Si rempli, cette affectation est une permanence spéciale (ex: Accréditation, Formation, Audit, etc.)",
    )

    special_color = fields.Char(
        string="Couleur",
        default="#6f42c1",
        help="Couleur pour l'affichage visuel des permanences spéciales (format hexadécimal)",
    )

    is_special = fields.Boolean(
        string="Permanence spéciale",
        compute="_compute_is_special",
        store=True,
        help="Indique si cette affectation est une permanence spéciale",
    )

    day = fields.Selection(
        [
            ("monday", "Monday"),
            ("tuesday", "Tuesday"),
            ("wednesday", "Wednesday"),
            ("thursday", "Thursday"),
            ("friday", "Friday"),
        ],
        string="Day",
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

    start_time = fields.Float(
        string="Start Time",
        required=True,
        compute="_onchange_period_times",
        store=True,
        help="Heure de début (format décimal : 7.5 = 7h30, 12.5 = 12h30)",
    )
    end_time = fields.Float(
        string="End Time",
        required=True,
        compute="_onchange_period_times",
        store=True,
        help="Heure de fin (format décimal : 12.0 = 12h00, 17.5 = 17h30)",
    )

    notes = fields.Text(string="Notes")

    @api.depends("special_name")
    def _compute_is_special(self):
        for record in self:
            record.is_special = bool(record.special_name)

    @staticmethod
    def _calculate_times(period, permanence_type_code=None, site_code=None):
        """Calcule les heures de début et fin selon la période, le type et le site.

        TCH sur sites isolés (HEU, HRM, WAR) : 8h30–12h30 (AM), 12h30–16h30 (PM).
        """
        site_code = (site_code or "").strip().upper()
        on_site_isolated_tch = (
            permanence_type_code == "TCH" and site_code in ISOLATED_ON_SITE_CODES
        )

        if period == "am":
            if on_site_isolated_tch:
                return (8.5, 12.5)  # 8h30 - 12h30
            if permanence_type_code in ("FCT", "TCH"):
                return (7.5, 12.75)  # 7h30 - 12h45
            return (7.5, 12.0)  # 7h30 - 12h00
        if period == "pm":
            if on_site_isolated_tch:
                return (12.5, 16.5)  # 12h30 - 16h30
            if permanence_type_code in ("FCT", "TCH"):
                return (12.75, 18.0)  # 12h45 - 18h00
            return (12.5, 17.5)  # 12h30 - 17h30
        if period == "full":
            return (8.5, 16.5)  # 8h30 - 16h30
        return (8.5, 16.5)

    @api.model_create_multi
    def create(self, vals_list):
        """Surcharge compatible batch pour valeurs par défaut."""
        for vals in vals_list:
            # Pour les perms spéciales, définir site et type par défaut si non fournis
            if vals.get("special_name") and not vals.get("site_id"):
                # Utiliser MLE par défaut pour les perms spéciales
                mle_site = self.env["chc_cds_planning.site"].search(
                    [("code", "=", "MLE")], limit=1
                )
                if mle_site:
                    vals["site_id"] = mle_site.id

            if vals.get("special_name") and not vals.get("permanence_type_id"):
                # Utiliser TCH (technique) par défaut pour les perms spéciales
                tch_type = self.env["chc_cds_planning.permanence_type"].search(
                    [("code", "=", "TCH")], limit=1
                )
                if tch_type:
                    vals["permanence_type_id"] = tch_type.id

            # Calculer start_time et end_time si non fournis et si period est disponible
            if "start_time" not in vals or "end_time" not in vals:
                period = vals.get("period")
                if period:
                    permanence_type_code = None
                    if vals.get("permanence_type_id"):
                        permanence_type = self.env["chc_cds_planning.permanence_type"].browse(
                            vals["permanence_type_id"]
                        )
                        if permanence_type.exists():
                            permanence_type_code = permanence_type.code

                    site_code = None
                    if vals.get("site_id"):
                        site = self.env["chc_cds_planning.site"].browse(vals["site_id"])
                        if site.exists():
                            site_code = site.code

                    start_time, end_time = self._calculate_times(
                        period, permanence_type_code, site_code
                    )
                    vals["start_time"] = start_time
                    vals["end_time"] = end_time

        records = super().create(vals_list)

        if not self.env.context.get('skip_tracking'):
            for record in records:
                if record.planning_week_id:
                    record.planning_week_id.message_post(
                        body=Markup(
                            f"Affectation ajoutée ({record.day}) :<br/>"
                            f"  Employé : {record.employee_id.name}<br/>"
                            f"  Site : {record.site_id.name}<br/>"
                            f"  Type : {record.permanence_type_id.name}<br/>"
                            f"  Période : {record.period}"
                        )
                    )

        self._sync_friday_counters_if_needed(records)
        return records

    def write(self, vals):
        old_values = {}
        tracked_fields = {
            'employee_id': 'Employé',
            'site_id': 'Site',
            'permanence_type_id': 'Type',
            'period': 'Période',
            'day': 'Jour',
            'notes': 'Notes',
        }
        friday_pm_before = self.filtered(is_friday_pm_mle_assignment)
        for record in self:
            old_values[record.id] = {
                field: getattr(record, field) for field in tracked_fields
            }

        result = super().write(vals)

        for record in self:
            if not record.planning_week_id or self.env.context.get('skip_tracking'): #lors de la création pas de log
                continue
            changes = []
            
            for field, label in tracked_fields.items():
                if field not in vals:
                    continue
                old = old_values[record.id][field]
                new = getattr(record, field)
                old_display = old.name if hasattr(old, 'name') else (old or '-')
                new_display = new.name if hasattr(new, 'name') else (new or '-')
                if old != new:
                    changes.append(f"{label} : {old_display} -> {new_display}")
            
            if changes:
                body = Markup(
                    f"Affectation modifiée : {record.employee_id.name} ({record.day})<br/>"
                    + "<br/>".join(f"   {change}" for change in changes)
                )
                record.planning_week_id.message_post(body=body)
        friday_pm_after = self.filtered(is_friday_pm_mle_assignment)
        self._sync_friday_counters_if_needed(friday_pm_before | friday_pm_after)
        return result
    
    def unlink(self):
        friday_pm_records = self.filtered(is_friday_pm_mle_assignment)
        needs_sync = bool(friday_pm_records)
        if self.env.context.get('skip_tracking'):
            result = super().unlink()
            if needs_sync:
                self._sync_friday_counters_if_needed(friday_pm_records)
            return result

        messages = []
        for record in self:
            if record.planning_week_id:
                messages.append((
                    record.planning_week_id,
                    Markup(
                        f"Affectation supprimée ({record.day}) :<br/>"
                        f"  Employé : {record.employee_id.name}<br/>"
                        f"  Site : {record.site_id.name}<br/>"
                        f"  Type : {record.permanence_type_id.name}<br/>"
                        f"  Période : {record.period}"
                    )
                ))
        result = super().unlink()
        for planning, msg in messages:
            planning.message_post(body=msg)
        self._sync_friday_counters_if_needed(friday_pm_records)
        return result

    @api.model
    def _sync_friday_counters_if_needed(self, records):
        if self.env.context.get("skip_friday_counter_sync"):
            return
        if records:
            self.env[
                "chc_cds_planning.friday_rotation_counter"
            ].sync_after_assignment_change()

    @api.depends("period", "permanence_type_id", "site_id")
    def _onchange_period_times(self):
        """Calcule les heures de début et fin selon la période, le type et le site."""
        for assignment in self:
            perm_code = (
                assignment.permanence_type_id.code
                if assignment.permanence_type_id
                else None
            )
            site_code = assignment.site_id.code if assignment.site_id else None
            period = assignment.period

            if not period:
                continue

            start, end = self._calculate_times(period, perm_code, site_code)
            assignment.start_time = start
            assignment.end_time = end

    @api.onchange("site_id")
    def _onchange_site_filter_permanence_type(self):
        if self.site_id:
            return {
                "domain": {"permanence_type_id": [("site_ids", "in", self.site_id.id)]}
            }

    @api.onchange("permanence_type_id", "period")
    def _onchange_period_rules(self):
        for assignment in self:
            # Ne pas appliquer les règles si c'est une perm spéciale
            if assignment.special_name:
                continue

            if not assignment.permanence_type_id or not assignment.period:
                continue

            code = assignment.permanence_type_id.code

            if code == "ATL" and assignment.period != "full":
                assignment.period = "full"

            elif code in ("FCT", "TCH") and assignment.period == "full":
                assignment.period = False

    @api.onchange("special_name")
    def _onchange_special_name(self):
        """Auto-remplissage pour les perms spéciales"""
        for assignment in self:
            if assignment.special_name:
                # Pour les perms spéciales, définir site et type par défaut
                if not assignment.site_id:
                    mle_site = self.env["chc_cds_planning.site"].search(
                        [("code", "=", "MLE")], limit=1
                    )
                    if mle_site:
                        assignment.site_id = mle_site

                if not assignment.permanence_type_id:
                    tch_type = self.env["chc_cds_planning.permanence_type"].search(
                        [("code", "=", "TCH")], limit=1
                    )
                    if tch_type:
                        assignment.permanence_type_id = tch_type
            else:
                # Si on retire le nom spécial, réinitialiser la couleur
                if assignment.special_color == "#6f42c1":
                    assignment.special_color = False

    @api.onchange("employee_id")
    def _onchange_employee_autofill(self):
        """Auto-remplissage intelligent basé sur les qualifications de l'employé"""
        for assignment in self:
            # Ne pas auto-remplir si c'est une perm spéciale
            if assignment.special_name:
                continue

            if not assignment.employee_id:
                # Si pas d'employé sélectionné, réinitialiser les champs
                assignment.site_id = False
                assignment.permanence_type_id = False
                continue

            # Récupérer toutes les qualifications de l'employé
            qualifications = assignment.employee_id.qualification_ids

            # Vérifier s'il y a des qualifications
            if not qualifications:
                # Pas de qualifications définies pour cet employé
                # On peut soit laisser vide, soit proposer des valeurs par défaut
                assignment.site_id = False
                assignment.permanence_type_id = False
                continue

            # Stratégie de sélection intelligente :
            # 1. Priorité aux qualifications de niveau expert (3)
            # 2. Puis intermédiaire (2)
            # 3. Enfin débutant (1)

            best_qualification = None

            # Chercher d'abord les qualifications expertes
            expert_qualifications = qualifications.filtered(lambda q: q.priority == "3")
            if expert_qualifications:
                best_qualification = expert_qualifications[0]
            else:
                # Sinon chercher les qualifications intermédiaires
                intermediate_qualifications = qualifications.filtered(
                    lambda q: q.priority == "2"
                )
                if intermediate_qualifications:
                    best_qualification = intermediate_qualifications[0]
                else:
                    # Enfin prendre la première qualification disponible
                    best_qualification = qualifications[0]

            # Appliquer la meilleure qualification trouvée
            if best_qualification:
                assignment.site_id = best_qualification.site_id.id
                assignment.permanence_type_id = best_qualification.permanence_type_id.id

    # Pour alimenter le champ "day" automatiquement
    @api.model
    def default_get(self, fields):
        assignment = super().default_get(fields)
        if self.env.context.get("default_day"):
            assignment["day"] = self.env.context["default_day"]
        return assignment

    @api.constrains("site_id", "permanence_type_id", "special_name")
    def _check_site_and_type_required(self):
        """Vérifie que site et type sont requis sauf pour les perms spéciales"""
        for record in self:
            if not record.special_name:
                # Pour les perms régulières, site et type sont obligatoires
                if not record.site_id:
                    from odoo.exceptions import ValidationError

                    raise ValidationError(
                        "Le site est obligatoire pour les permanences régulières."
                    )
                if not record.permanence_type_id:
                    from odoo.exceptions import ValidationError

                    raise ValidationError(
                        "Le type de permanence est obligatoire pour les permanences régulières."
                    )

    @api.constrains("special_name", "day", "employee_id", "planning_week_id")
    def _check_special_assignment_unique(self):
        """Vérifie l'unicité des perms spéciales (même nom, jour, employé, planning)"""
        for record in self:
            if record.special_name:
                duplicates = self.search(
                    [
                        ("planning_week_id", "=", record.planning_week_id.id),
                        ("special_name", "=", record.special_name),
                        ("day", "=", record.day),
                        ("employee_id", "=", record.employee_id.id),
                        ("id", "!=", record.id),
                    ]
                )
                if duplicates:
                    from odoo.exceptions import ValidationError

                    raise ValidationError(
                        f"Un employé ne peut pas être assigné deux fois à la même permanence spéciale "
                        f"({record.special_name}) le même jour !"
                    )
