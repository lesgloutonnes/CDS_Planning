# -*- coding: utf-8 -*-
import logging
from datetime import date, datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SicknessReplacementWizard(models.TransientModel):
    _name = "chc_cds_planning.sickness_replacement_wizard"
    _description = "Wizard de remplacement pour congé maladie"

    leave_id = fields.Many2one(
        "hr.leave",
        string="Congé",
        required=True,
        readonly=True,
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employé malade",
        related="leave_id.employee_id",
        readonly=True,
    )

    leave_period = fields.Char(
        string="Période de congé",
        compute="_compute_leave_period",
        readonly=True,
    )

    replacement_line_ids = fields.One2many(
        "chc_cds_planning.sickness_replacement_line",
        "wizard_id",
        string="Affectations à remplacer",
    )

    annual_leave_conflict_line_ids = fields.One2many(
        "chc_cds_planning.sickness_annual_leave_conflict_line",
        "wizard_id",
        string="Congés annuels en conflit",
    )

    @api.depends("leave_id.date_from", "leave_id.date_to")
    def _compute_leave_period(self):
        for wizard in self:
            if wizard.leave_id and wizard.leave_id.date_from and wizard.leave_id.date_to:
                from datetime import datetime
                date_from = wizard.leave_id.date_from
                date_to = wizard.leave_id.date_to
                
                # Convertir en format date si nécessaire
                if isinstance(date_from, str):
                    date_from = datetime.strptime(date_from.split()[0], '%Y-%m-%d').date()
                elif hasattr(date_from, 'date'):
                    date_from = date_from.date()
                
                if isinstance(date_to, str):
                    date_to = datetime.strptime(date_to.split()[0], '%Y-%m-%d').date()
                elif hasattr(date_to, 'date'):
                    date_to = date_to.date()
                
                wizard.leave_period = f"Du {date_from.strftime('%d/%m/%Y')} au {date_to.strftime('%d/%m/%Y')}"
            else:
                wizard.leave_period = ""

    def action_apply_replacements(self):
        """Applique les remplacements planning et traite les congés annuels en conflit."""
        self.ensure_one()

        # --- 1. Remplacements planning ---
        replaced_count = 0
        for line in self.replacement_line_ids:
            if line.replacement_employee_id:
                line.assignment_id.write({"employee_id": line.replacement_employee_id.id})
                replaced_count += 1

        # --- 2. Congés annuels en conflit ---
        annual_cancelled = 0
        annual_split = 0
        annual_errors = 0

        for conf_line in self.annual_leave_conflict_line_ids:
            if conf_line.action == "keep":
                continue

            annual_leave = conf_line.leave_id
            if annual_leave.state != "validate":
                continue

            try:
                # leave_skip_date_check évite que _check_date() re-valide le congé
                # annuel contre le congé maladie qui vient d'être créé, ce qui
                # provoquerait une ValidationError circulaire.
                ctx = {"leave_skip_date_check": True}
                annual_leave.sudo().with_context(**ctx).action_refuse()

                if conf_line.action == "split" and conf_line.is_partial_overlap:
                    self._recreate_residual_leaves(conf_line)
                    annual_split += 1

                # Supprime le congé refusé : un congé refusé n'a plus de sens
                # dans l'historique une fois remplacé (partiellement ou totalement).
                annual_leave.sudo().with_context(**ctx).action_draft()
                annual_leave.sudo().unlink()
                annual_cancelled += 1
            except Exception:
                _logger.warning(
                    "Impossible de traiter le congé annuel %s de %s",
                    annual_leave.id,
                    annual_leave.employee_id.name,
                    exc_info=True,
                )
                annual_errors += 1

        # --- Message de confirmation ---
        parts = []
        if replaced_count:
            parts.append(f"{replaced_count} affectation(s) planning remplacée(s)")
        if annual_cancelled - annual_split:
            parts.append(f"{annual_cancelled - annual_split} congé(s) annuel(s) annulé(s)")
        if annual_split:
            parts.append(f"{annual_split} congé(s) fractionné(s) (jours résiduels recréés)")
        if annual_errors:
            parts.append(f"{annual_errors} congé(s) n'ont pas pu être traité(s) (voir logs)")

        message = " — ".join(parts) if parts else "Aucune action effectuée."

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Traitement effectué",
                "message": message,
                "type": "success" if not annual_errors else "warning",
                "sticky": bool(annual_errors),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _recreate_residual_leaves(self, conf_line):
        """Recrée les portions du congé annuel non couvertes par la maladie.

        Calcule les segments [avant la maladie] et [après la maladie] puis crée
        un nouvel hr.leave validé pour chacun, en sautant les week-ends.
        """
        annual = conf_line.leave_id
        sick = self.leave_id

        def to_date(val):
            if isinstance(val, datetime):
                return val.date()
            if isinstance(val, date):
                return val
            return None

        annual_from = to_date(annual.date_from)
        annual_to = to_date(annual.date_to)
        sick_from = to_date(sick.date_from)
        sick_to = to_date(sick.date_to)

        if not all([annual_from, annual_to, sick_from, sick_to]):
            return

        segments = []

        # Segment avant la maladie
        if annual_from < sick_from:
            before_end = sick_from - timedelta(days=1)
            while before_end.weekday() >= 5:  # saute samedi/dimanche
                before_end -= timedelta(days=1)
            if before_end >= annual_from:
                segments.append((annual_from, before_end))

        # Segment après la maladie
        if annual_to > sick_to:
            after_start = sick_to + timedelta(days=1)
            while after_start.weekday() >= 5:
                after_start += timedelta(days=1)
            if after_start <= annual_to:
                segments.append((after_start, annual_to))

        # Contexte Odoo utilisé en interne pour les splits de congés :
        # - leave_fast_create       : skip les calculs lourds à la création
        # - leave_skip_state_check  : skip _check_date_state (modif d'état autorisée)
        # - leave_skip_date_check   : skip _check_date (évite le conflit avec le congé maladie)
        create_ctx = {
            "tracking_disable": True,
            "mail_activity_automation_skip": True,
            "leave_fast_create": True,
            "leave_skip_state_check": True,
            "leave_skip_date_check": True,
        }

        for seg_from, seg_to in segments:
            try:
                new_leave = self.env["hr.leave"].sudo().with_context(**create_ctx).create({
                    "employee_id": annual.employee_id.id,
                    "holiday_status_id": annual.holiday_status_id.id,
                    "request_date_from": seg_from,
                    "request_date_to": seg_to,
                    "name": annual.name or "",
                    "state": "validate",
                })
                # _validate_leave_request défalque l'allocation et génère les événements
                # calendrier — c'est la méthode qu'Odoo utilise en interne pour ses splits.
                new_leave.sudo().with_context(**create_ctx)._validate_leave_request()
            except Exception:
                _logger.warning(
                    "Impossible de recréer le congé résiduel du %s au %s pour %s",
                    seg_from,
                    seg_to,
                    annual.employee_id.name,
                    exc_info=True,
                )



class SicknessReplacementLine(models.TransientModel):
    _name = "chc_cds_planning.sickness_replacement_line"
    _description = "Ligne de remplacement pour une affectation"

    wizard_id = fields.Many2one(
        "chc_cds_planning.sickness_replacement_wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )

    assignment_id = fields.Many2one(
        "chc_cds_planning.planning_assignment",
        string="Affectation",
        required=True,
        readonly=True,
    )

    planning_name = fields.Char(
        string="Planning",
        related="assignment_id.planning_week_id.name",
        readonly=True,
    )

    assignment_date = fields.Char(
        string="Date",
        compute="_compute_assignment_date",
        readonly=True,
    )

    day_label = fields.Char(
        string="Jour",
        compute="_compute_day_label",
        readonly=True,
    )

    period_label = fields.Char(
        string="Période",
        compute="_compute_period_label",
        readonly=True,
    )

    site_name = fields.Char(
        string="Site",
        related="assignment_id.site_id.name",
        readonly=True,
    )

    permanence_type_name = fields.Char(
        string="Type de permanence",
        related="assignment_id.permanence_type_id.name",
        readonly=True,
    )

    special_name = fields.Char(
        string="Permanence spéciale",
        related="assignment_id.special_name",
        readonly=True,
    )

    replacement_employee_id = fields.Many2one(
        "hr.employee",
        string="Remplaçant",
        domain="[('active', '=', True)]",
        help="Sélectionnez l'employé qui remplacera le malade pour cette affectation",
    )

    @api.onchange("assignment_id", "replacement_employee_id")
    def _onchange_assignment_id(self):
        """Met à jour le domaine du remplaçant selon les qualifications requises"""
        for line in self:
            if not line.assignment_id:
                return {}
            
            # Exclure toujours l'employé malade
            sick_employee_id = line.assignment_id.employee_id.id
            
            # Pour les permanences régulières, filtrer selon site et type de permanence
            if not line.assignment_id.special_name and line.assignment_id.site_id and line.assignment_id.permanence_type_id:
                # Récupérer les employés qualifiés pour ce site et type de permanence
                qualified_employees = self.env['hr.employee'].search([
                    ('active', '=', True),
                    ('qualification_ids.site_id', '=', line.assignment_id.site_id.id),
                    ('qualification_ids.permanence_type_id', '=', line.assignment_id.permanence_type_id.id),
                    ('id', '!=', sick_employee_id),
                ])
                
                if qualified_employees:
                    return {
                        'domain': {
                            'replacement_employee_id': [('id', 'in', qualified_employees.ids)]
                        }
                    }
            
            # Pour les permanences spéciales ou si pas de site/type, permettre tous les employés actifs sauf le malade
            return {
                'domain': {
                    'replacement_employee_id': [
                        ('active', '=', True),
                        ('id', '!=', sick_employee_id)
                    ]
                }
            }

    @api.depends("assignment_id.planning_week_id.start_date", "assignment_id.day")
    def _compute_assignment_date(self):
        for line in self:
            if line.assignment_id.planning_week_id.start_date and line.assignment_id.day:
                from ..utils.utils import get_date_from_week_start_and_day
                date = get_date_from_week_start_and_day(
                    line.assignment_id.planning_week_id.start_date,
                    line.assignment_id.day
                )
                line.assignment_date = date.strftime('%d/%m/%Y')
            else:
                line.assignment_date = ""

    @api.depends("assignment_id.day")
    def _compute_day_label(self):
        day_labels = {
            'monday': 'Lundi',
            'tuesday': 'Mardi',
            'wednesday': 'Mercredi',
            'thursday': 'Jeudi',
            'friday': 'Vendredi',
        }
        for line in self:
            line.day_label = day_labels.get(line.assignment_id.day, line.assignment_id.day or '')

    @api.depends("assignment_id.period")
    def _compute_period_label(self):
        period_labels = {
            'am': 'Matin',
            'pm': 'Après-midi',
            'full': 'Journée complète',
        }
        for line in self:
            line.period_label = period_labels.get(line.assignment_id.period, line.assignment_id.period or '')


class SicknessAnnualLeaveConflictLine(models.TransientModel):
    """Ligne représentant un congé annuel validé qui chevauche le congé maladie.

    Créée automatiquement lors de la validation d'un congé maladie si des congés
    annuels approuvés existent sur la même période. Le gestionnaire choisit pour
    chacun l'action à effectuer (conserver, annuler, ou fractionner).
    """

    _name = "chc_cds_planning.sickness_annual_leave_conflict_line"
    _description = "Conflit congé annuel / congé maladie"

    wizard_id = fields.Many2one(
        "chc_cds_planning.sickness_replacement_wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )

    leave_id = fields.Many2one(
        "hr.leave",
        string="Congé annuel",
        required=True,
        readonly=True,
    )

    leave_type_name = fields.Char(
        string="Type de congé",
        related="leave_id.holiday_status_id.name",
        readonly=True,
    )

    leave_period = fields.Char(
        string="Période du congé",
        compute="_compute_leave_info",
        readonly=True,
    )

    overlap_period = fields.Char(
        string="Jours en conflit avec la maladie",
        compute="_compute_leave_info",
        readonly=True,
    )

    is_partial_overlap = fields.Boolean(
        string="Chevauchement partiel",
        compute="_compute_leave_info",
        readonly=True,
    )

    action = fields.Selection(
        [
            ("keep", "Conserver tel quel"),
            ("cancel", "Annuler ce congé"),
            ("split", "Annuler et recréer les jours restants"),
        ],
        string="Action",
        default="split",
        required=True,
        help=(
            "Conserver : aucune modification.\n"
            "Annuler : le congé passe en état 'Refusé' (le solde est restitué).\n"
            "Annuler et recréer : annule le congé original et recrée automatiquement "
            "les jours non couverts par la maladie (validés immédiatement)."
        ),
    )

    @api.depends("leave_id.date_from", "leave_id.date_to", "wizard_id.leave_id")
    def _compute_leave_info(self):
        for line in self:
            annual = line.leave_id
            sick = line.wizard_id.leave_id if line.wizard_id else None

            if not annual or not sick:
                line.leave_period = ""
                line.overlap_period = ""
                line.is_partial_overlap = False
                continue

            def _to_date(val):
                if isinstance(val, datetime):
                    return val.date()
                if isinstance(val, date):
                    return val
                return None

            annual_from = _to_date(annual.date_from)
            annual_to = _to_date(annual.date_to)
            sick_from = _to_date(sick.date_from)
            sick_to = _to_date(sick.date_to)

            if not all([annual_from, annual_to, sick_from, sick_to]):
                line.leave_period = ""
                line.overlap_period = ""
                line.is_partial_overlap = False
                continue

            line.leave_period = (
                f"Du {annual_from.strftime('%d/%m/%Y')} "
                f"au {annual_to.strftime('%d/%m/%Y')}"
            )

            overlap_from = max(annual_from, sick_from)
            overlap_to = min(annual_to, sick_to)
            line.overlap_period = (
                f"Du {overlap_from.strftime('%d/%m/%Y')} "
                f"au {overlap_to.strftime('%d/%m/%Y')}"
            )

            line.is_partial_overlap = (annual_from < sick_from) or (annual_to > sick_to)
