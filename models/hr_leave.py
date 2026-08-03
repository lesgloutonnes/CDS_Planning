from pytz import timezone
from odoo import api, models
from odoo.tools.misc import format_date
from odoo.tools.translate import _


class HrLeave(models.Model):
    _inherit = "hr.leave"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_sick_leave(self):
        """Retourne True si ce congé est de type maladie."""
        return bool(
            self.holiday_status_id
            and "maladie" in (self.holiday_status_id.name or "").lower()
        )

    # ------------------------------------------------------------------
    # Surcharges de contraintes
    # ------------------------------------------------------------------

    @api.constrains("date_from", "date_to", "state", "employee_id", "holiday_type")
    def _check_date(self):
        """Autorise la création d'un congé maladie même si un congé annuel validé
        existe déjà sur la même période.

        Les congés annuels en conflit sont traités lors de la validation via le wizard.
        Respecte le contexte leave_skip_date_check (utilisé par notre wizard lors du
        refus des congés annuels en conflit, pour éviter une ValidationError circulaire).
        """
        if self.env.context.get("leave_skip_date_check"):
            return
        non_sick = self.filtered(lambda l: not l._is_sick_leave())
        if non_sick:
            super(HrLeave, non_sick)._check_date()

    @api.constrains("date_from", "date_to", "employee_id", "holiday_type")
    def _check_validity(self):
        """Autorise un congé maladie même si les jours sont déjà couverts par un congé
        annuel approuvé (ce qui ferait afficher 0 jour et déclencherait cette erreur).

        La durée réelle est calculée correctement via _get_number_of_days ci-dessous.
        """
        non_sick = self.filtered(lambda l: not l._is_sick_leave())
        if non_sick:
            super(HrLeave, non_sick)._check_validity()

    # ------------------------------------------------------------------
    # Calcul de la durée
    # ------------------------------------------------------------------

    def _get_duration(self, resource_calendar=None, check_leave_type=True):
        """Pour les congés maladie, calcule la durée sans soustraire les intervalles
        d'absence liés aux autres hr.leave approuvés.

        Dans Odoo 17, _get_duration passe à list_work_time_per_day un domaine qui
        inclut tous les resource.calendar.leaves liés à des hr.leave validés.
        Quand un congé annuel couvre la même période, le congé maladie obtient
        0 jours ouvrés, ce qui déclenche l'erreur "pas censé travailler" dans
        action_validate → _get_leaves_on_public_holiday().

        Correction : on passe un domaine qui n'exclut que les jours fériés publics
        (holiday_id=False), ignorant les absences hr.leave existantes.
        """
        if self._is_sick_leave() and self.employee_id and self.date_from and self.date_to:
            resource_calendar = resource_calendar or self.resource_calendar_id
            if resource_calendar:
                # N'exclut que les jours fériés globaux, pas les congés individuels approuvés
                domain = [("time_type", "=", "leave"), ("holiday_id", "=", False)]
                if self.leave_type_request_unit == "day" and check_leave_type:
                    work_time_list = self.employee_id.list_work_time_per_day(
                        self.date_from, self.date_to,
                        calendar=resource_calendar,
                        domain=domain,
                    )
                    return (len(work_time_list), sum(t[1] for t in work_time_list))
                else:
                    data = self.employee_id._get_work_days_data_batch(
                        self.date_from, self.date_to,
                        domain=domain,
                        calendar=resource_calendar,
                    )[self.employee_id.id]
                    return (data["days"], data["hours"])
        return super()._get_duration(
            resource_calendar=resource_calendar, check_leave_type=check_leave_type
        )

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------

    @api.depends(
        'tz', 'date_from', 'date_to', 'name',
        'employee_id', 'employee_ids', 'holiday_status_id', 'holiday_status_id.name',
        'number_of_hours_display', 'leave_type_request_unit', 'number_of_days',
        'mode_company_id', 'category_id', 'department_id', 'holiday_type',
    )
    @api.depends_context('short_name', 'hide_employee_name', 'groupby')
    def _compute_display_name(self):
        # Récupère tous les congés avec sudo pour contourner les règles d'accès sur hr.leave.type
        leave_types = self.mapped('holiday_status_id').sudo()
        names_by_type_id = {t.id: t.name or '' for t in leave_types}

        # Associe à chaque congé le nom de son type via le dict ; .get() avec '' par défaut couvre les congés sans holiday_status_id renseigné
        type_names = {
            leave.id: names_by_type_id.get(leave.holiday_status_id.id, '')
            for leave in self
        }

        for leave in self:
            leave_type = type_names.get(leave.id, '')

            # Cible : employé, société, département ou catégorie
            if leave.holiday_type == 'company':
                target = leave.mode_company_id.name or ''
            elif leave.holiday_type == 'department':
                target = leave.department_id.name or ''
            elif leave.holiday_type == 'category':
                target = leave.category_id.name or ''
            elif leave.employee_id:
                target = leave.employee_id.name or ''
            else:
                target = ', '.join(leave.employee_ids.mapped('name'))

            # Durée formatée
            if leave.leave_type_request_unit == 'hour':
                h = leave.number_of_hours_display
                duration_str = f"{h:.2f}h"
            else:
                d = int(leave.number_of_days) if leave.number_of_days == int(leave.number_of_days) else leave.number_of_days
                duration_str = f"{d} jours"

            # Plage de dates (contextes non-court)
            if not self.env.context.get('short_name') and leave.date_from and leave.date_to:
                user_tz = timezone(leave.tz)
                d_from = format_date(self.env, leave.date_from.astimezone(user_tz).date()) or ''
                d_to = format_date(self.env, leave.date_to.astimezone(user_tz).date()) or ''
                date_range = f" ({d_from} – {d_to})" if d_from != d_to else (f" ({d_from})" if d_from else '')
            else:
                date_range = ''

            # Assemblage : type toujours présent si disponible
            hide_target = (
                self.env.context.get('hide_employee_name')
                and 'employee_id' in self.env.context.get('group_by', [])
            )
            if not target or hide_target:
                # Vue groupée sans nom : type seul
                leave.display_name = f"{leave_type}: {duration_str}{date_range}" if leave_type else f"{duration_str}{date_range}"
            elif leave_type:
                leave.display_name = f"{leave_type} – {target}: {duration_str}{date_range}"
            else:
                leave.display_name = f"{target}: {duration_str}{date_range}"

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)

        group = self.env.ref(
            "chc_cds_planning.group_hr_leave_notify", raise_if_not_found=False
        )
        if group:
            users = group.users
            activity_type = self.env.ref("mail.mail_activity_data_todo")
            model_id = self.env["ir.model"]._get_id("hr.leave")

            for leave in leaves:
                for user in users:
                    self.env["mail.activity"].create(
                        {
                            "res_model_id": model_id,
                            "res_id": leave.id,
                            "activity_type_id": activity_type.id,
                            "user_id": user.id,
                            "summary": "Demande de congé",
                            "note": f"Nouvelle demande de {leave.employee_id.name}",
                        }
                    )

        return leaves

    def action_approve(self):
        """Surcharge pour vérifier les affectations en cas de congé maladie"""
        result = super().action_approve()

        for leave in self.filtered(lambda rec: rec.state == "validate"):
            if leave.holiday_status_id and "maladie" in (
                leave.holiday_status_id.name or ""
            ).lower():
                assignments = self._get_overlapping_assignments(leave)
                annual_leaves = self._get_overlapping_annual_leaves(leave)
                if assignments or annual_leaves:
                    return self._open_replacement_wizard(leave, assignments, annual_leaves)

        return result

    def _open_replacement_wizard(self, leave, assignments, annual_leaves=None):
        """Ouvre le wizard de remplacement pour les affectations et congés annuels en conflit.

        Les créations de modèles transients se font en sudo() : le contrôle d'accès
        est géré au niveau de l'action qui ouvre le wizard, pas au niveau du modèle.
        """
        env = self.sudo().env

        wizard = env["chc_cds_planning.sickness_replacement_wizard"].create(
            {"leave_id": leave.id}
        )

        for assignment in assignments:
            env["chc_cds_planning.sickness_replacement_line"].create(
                {"wizard_id": wizard.id, "assignment_id": assignment.id}
            )

        for annual_leave in (annual_leaves or self.env["hr.leave"]):
            env["chc_cds_planning.sickness_annual_leave_conflict_line"].create(
                {"wizard_id": wizard.id, "leave_id": annual_leave.id}
            )

        return {
            "type": "ir.actions.act_window",
            "res_model": "chc_cds_planning.sickness_replacement_wizard",
            "view_mode": "form",
            "res_id": wizard.id,
            "target": "new",
            "context": self.env.context,
        }

    def _get_overlapping_annual_leaves(self, sick_leave):
        """Récupère les congés validés (non-maladie) qui chevauchent le congé maladie.

        Utilisé lors de la validation d'un congé maladie pour détecter les congés
        annuels déjà approuvés sur la même période, afin de proposer leur annulation
        ou leur fractionnement dans le wizard de remplacement.
        """
        return self.env["hr.leave"].search([
            ("employee_id", "=", sick_leave.employee_id.id),
            ("state", "=", "validate"),
            ("date_from", "<=", sick_leave.date_to),
            ("date_to", ">=", sick_leave.date_from),
            ("id", "!=", sick_leave.id),
            ("holiday_status_id.name", "not ilike", "maladie"),
        ])

    def _get_overlapping_assignments(self, leave):
        """Récupère les affectations qui chevauchent avec la période de congé"""
        if not leave.date_from or not leave.date_to:
            return self.env["chc_cds_planning.planning_assignment"]

        from datetime import date, datetime

        if isinstance(leave.date_from, str):
            leave_date_from = datetime.strptime(
                leave.date_from.split()[0], "%Y-%m-%d"
            ).date()
        elif isinstance(leave.date_from, datetime):
            leave_date_from = leave.date_from.date()
        elif isinstance(leave.date_from, date):
            leave_date_from = leave.date_from
        else:
            leave_date_from = leave.date_from

        if isinstance(leave.date_to, str):
            leave_date_to = datetime.strptime(
                leave.date_to.split()[0], "%Y-%m-%d"
            ).date()
        elif isinstance(leave.date_to, datetime):
            leave_date_to = leave.date_to.date()
        elif isinstance(leave.date_to, date):
            leave_date_to = leave.date_to
        else:
            leave_date_to = leave.date_to

        plannings = self.env["chc_cds_planning.planning_weekly"].search(
            [
                ("start_date", "<=", leave_date_to),
                ("end_date", ">=", leave_date_from),
            ]
        )

        if not plannings:
            return self.env["chc_cds_planning.planning_assignment"]

        all_assignments = self.env["chc_cds_planning.planning_assignment"].search(
            [
                ("planning_week_id", "in", plannings.ids),
                ("employee_id", "=", leave.employee_id.id),
            ]
        )

        from ..utils.utils import get_date_from_week_start_and_day

        overlapping_assignments = self.env["chc_cds_planning.planning_assignment"]

        for assignment in all_assignments:
            planning = assignment.planning_week_id
            if planning.start_date:
                assignment_date = get_date_from_week_start_and_day(
                    planning.start_date, assignment.day
                )
                if leave_date_from <= assignment_date <= leave_date_to:
                    overlapping_assignments |= assignment

        return overlapping_assignments
