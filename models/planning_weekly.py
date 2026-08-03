# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError, AccessError
from markupsafe import Markup


class PlanningWeekly(models.Model):
    _name = "chc_cds_planning.planning_weekly"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Planning hebdomadaire"
    _order = "start_date desc"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Nom", compute="_compute_name", tracking=True)
    start_date = fields.Date(string="Date de début", required=True)
    end_date = fields.Date(
        string="Date de fin", compute="_compute_end_date", store=True
    )
    state = fields.Selection(
        [("draft", "Brouillon"), ("confirmed", "Confirmé"), ("published", "Publié")],
        string="État",
        default="draft",
        tracking=True
    )
    note = fields.Html(string="Notes")
    publish_calendar_snapshot = fields.Text(
        string="Snapshot invitations calendrier",
        copy=False,
        help="Snapshot technique des invitations envoyées lors de la dernière publication.",
    )
    publish_calendar_sequence = fields.Integer(
        string="Séquence invitations calendrier",
        default=0,
        copy=False,
        help="Compteur technique utilisé pour versionner les mises à jour ICS.",
    )

    is_readonly = fields.Boolean(string="Read Only", compute="_compute_is_readonly")

    load_default_planning = fields.Boolean(
        string="Charger le planning par défaut",
        default=True,
        help="Cocher pour pré-remplir automatiquement avec le planning type",
    )

    assignment_ids = fields.One2many(
        "chc_cds_planning.planning_assignment", "planning_week_id", string="Affectations"
    )

    assignment_ids_monday = fields.One2many(
        "chc_cds_planning.planning_assignment",
        "planning_week_id",
        string="Lundi",
        domain=[("day", "=", "monday")],
    )

    assignment_ids_tuesday = fields.One2many(
        "chc_cds_planning.planning_assignment",
        "planning_week_id",
        string="Mardi",
        domain=[("day", "=", "tuesday")],
    )

    assignment_ids_wednesday = fields.One2many(
        "chc_cds_planning.planning_assignment",
        "planning_week_id",
        string="Mercredi",
        domain=[("day", "=", "wednesday")],
    )

    assignment_ids_thursday = fields.One2many(
        "chc_cds_planning.planning_assignment",
        "planning_week_id",
        string="Jeudi",
        domain=[("day", "=", "thursday")],
    )

    assignment_ids_friday = fields.One2many(
        "chc_cds_planning.planning_assignment",
        "planning_week_id",
        string="Vendredi",
        domain=[("day", "=", "friday")],
    )

    # Permanences spéciales (événements ponctuels)
    # Maintenant unifiées dans assignment_ids avec special_name rempli
    special_assignment_ids = fields.One2many(
        "chc_cds_planning.planning_assignment",
        "planning_week_id",
        string="Permanences spéciales",
        domain=[("special_name", "!=", False)],
        help="Permanences ponctuelles (ex: accréditation, projet spécial, audit, etc.)",
    )

    @api.depends("state")
    def _compute_is_readonly(self):
        for record in self:
            record.is_readonly = record.state != "draft"

    @api.model_create_multi
    def create(self, vals_list):
        """Surcharge de create (compatible batch) pour ajouter les affectations par défaut."""
        # Créer d'abord les plannings
        plannings = super().create(vals_list)

        # Pour chaque planning créé, appliquer éventuellement le planning par défaut
        for planning, vals in zip(plannings, vals_list):
            if vals.get("load_default_planning", True):
                planning._generate_default_assignments()

        return plannings

    def _generate_default_assignments(self):
        """Génère les affectations par défaut basées sur un modèle prédéfini

        Note: Cette méthode ne vérifie pas la contrainte max_days_per_week des employés
        lors de la génération, car la génération se base désormais sur un planning par défaut
        (template) qui est déjà défini. La validation de la contrainte max_days_per_week
        est effectuée lors de la confirmation du planning (méthode action_confirm), ce qui
        permet de détecter et signaler les dépassements avant la finalisation du planning.
        """
        self.ensure_one()

        # Supprimer les affectations existantes si elles existent
        self.assignment_ids.with_context(skip_tracking=True).unlink()

        # Récupérer le modèle de planning par défaut
        default_template = self._get_default_template()

        if not default_template:
            # Si pas de template par défaut, essayer de copier le dernier planning
            self._copy_from_last_planning()
            return

        # Créer les affectations selon le template
        assignments_to_create = []
        assignment_model = self.env["chc_cds_planning.planning_assignment"]
        
        # Récupérer le calendrier par défaut pour vérifier les jours fériés
        from ..utils.utils import is_public_holiday, get_date_from_week_start_and_day
        default_calendar = self.env["resource.calendar"].search([
            ("active", "=", True)
        ], limit=1, order="id asc")
        calendar_id = default_calendar.id if default_calendar else None

        for line in default_template.template_line_ids:
            # Calculer la date exacte pour ce jour
            if self.start_date:
                current_date = get_date_from_week_start_and_day(self.start_date, line.day)
                
                # Vérifier si c'est un jour férié public (si oui, ne pas créer d'affectation)
                if is_public_holiday(self.env, current_date, calendar_id):
                    # C'est un jour férié, ne pas créer d'affectation
                    continue
            
            # Vérifier la disponibilité de l'employé si demandé
            if not self._is_employee_available(line.employee_id, line.day):
                continue

            # Calculer start_time et end_time avant la création
            permanence_type_code = (
                line.permanence_type_id.code if line.permanence_type_id else None
            )
            site_code = line.site_id.code if line.site_id else None
            start_time, end_time = assignment_model._calculate_times(
                line.period, permanence_type_code, site_code
            )

            assignments_to_create.append(
                {
                    "planning_week_id": self.id,
                    "employee_id": line.employee_id.id,
                    "site_id": line.site_id.id,
                    "permanence_type_id": line.permanence_type_id.id,
                    "day": line.day,
                    "period": line.period,
                    "start_time": start_time,
                    "end_time": end_time,
                    "notes": "",
                }
            )

        # Créer toutes les affectations en une fois
        if assignments_to_create:
            assignment_model.with_context(skip_tracking=True).create(assignments_to_create)

    def _get_default_template(self):
        """
        Retourne le template de planning par défaut
        """
        try:
            # Rechercher le template par défaut actif
            default_template = self.env["chc_cds_planning.planning_template"].search(
                [("is_default", "=", True), ("active", "=", True)], limit=1
            )

            if default_template and default_template.template_line_ids:
                return default_template

            # Si pas de template par défaut, prendre le premier template disponible
            fallback_template = self.env["chc_cds_planning.planning_template"].search(
                [("active", "=", True)], limit=1
            )

            if fallback_template and fallback_template.template_line_ids:
                return fallback_template

            return None

        except Exception as e:
            # En cas d'erreur, logger et retourner None
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(f"Erreur lors de la récupération du template par défaut: {e}")
            return None

    def _copy_from_last_planning(self):
        """Copie les affectations du dernier planning disponible"""
        try:
            last_planning = self.search(
                [("id", "!=", self.id), ("start_date", "<", self.start_date)],
                order="start_date desc",
                limit=1,
            )

            if not last_planning or not last_planning.assignment_ids:
                return

            # Copier les affectations en adaptant les dates
            assignments_to_create = []
            assignment_model = self.env["chc_cds_planning.planning_assignment"]
            
            # Récupérer le calendrier par défaut pour vérifier les jours fériés
            from ..utils.utils import is_public_holiday, get_date_from_week_start_and_day
            default_calendar = self.env["resource.calendar"].search([
                ("active", "=", True)
            ], limit=1, order="id asc")
            calendar_id = default_calendar.id if default_calendar else None

            for assignment in last_planning.assignment_ids:
                # Calculer la date exacte pour ce jour
                if self.start_date:
                    current_date = get_date_from_week_start_and_day(self.start_date, assignment.day)
                    
                    # Vérifier si c'est un jour férié public (si oui, ne pas créer d'affectation)
                    if is_public_holiday(self.env, current_date, calendar_id):
                        # C'est un jour férié, ne pas créer d'affectation
                        continue
                
                # Vérifier que l'employé est toujours disponible
                if self._is_employee_available(assignment.employee_id, assignment.day):
                    permanence_type_code = (
                        assignment.permanence_type_id.code
                        if assignment.permanence_type_id
                        else None
                    )
                    site_code = (
                        assignment.site_id.code if assignment.site_id else None
                    )
                    start_time, end_time = assignment_model._calculate_times(
                        assignment.period, permanence_type_code, site_code
                    )

                    assignments_to_create.append(
                        {
                            "planning_week_id": self.id,
                            "employee_id": assignment.employee_id.id,
                            "site_id": assignment.site_id.id,
                            "permanence_type_id": assignment.permanence_type_id.id,
                            "day": assignment.day,
                            "period": assignment.period,
                            "start_time": start_time,
                            "end_time": end_time,
                        }
                    )

            if assignments_to_create:
                self.env["chc_cds_planning.planning_assignment"].with_context(skip_tracking=True).create(
                    assignments_to_create
                )

        except Exception as e:
            # En cas d'erreur, continuer sans affectations
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(f"Erreur lors de la copie du planning précédent: {e}")

    def _is_employee_available(self, employee, day):
        """Vérifie si un employé est disponible un jour donné"""
        from ..utils.utils import is_employee_available_for_day

        return is_employee_available_for_day(self.env, employee, self.start_date, day)

    def action_load_default_planning(self): # Action pour charger manuellement le planning par défaut
        if not self.env.user.has_group(
            'chc_cds_planning.group_planning_admin'
        ):
            raise AccessError("Droits administrateur planning requis.")
        
        self.ensure_one()

        # Vérifier qu'il existe un template par défaut
        default_template = self._get_default_template()

        if not default_template:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "⚠️ Aucun template disponible",
                    "message": "Aucun template de planning par défaut n'a été trouvé. Veuillez créer un template dans le menu Configuration > Templates de planning.",
                    "type": "warning",
                    "sticky": True,
                },
            }

        # Supprimer les affectations existantes
        if self.assignment_ids:
            self.assignment_ids.with_context(skip_tracking=True).unlink()

        # Générer les nouvelles affectations
        self._generate_default_assignments()

        # Compter les affectations créées
        nb_assignments = len(self.assignment_ids)

        self.message_post(
            body=Markup(
                f"Planning type chargé : {nb_assignments} affectations créées "
                f"depuis le template <b>{default_template.name}</b>."
            )
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Planning par défaut chargé",
                "message": f"Le template '{default_template.name}' a été appliqué avec succès ! {nb_assignments} affectations créées.",
                "type": "success",
                "sticky": False,
            },
        }

    def action_copy_from_previous(self):
        if not self.env.user.has_group(
            'chc_cds_planning.group_planning_admin'
        ):
            raise AccessError("Droits administrateur planning requis.")

        self.ensure_one()

        previous_planning = self.search(
            [("start_date", "<", self.start_date)], order="start_date desc", limit=1
        )

        if not previous_planning:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "⚠️ Aucun planning précédent",
                    "message": "Aucun planning antérieur trouvé pour la copie.",
                    "type": "warning",
                    "sticky": False,
                },
            }

        if not previous_planning.assignment_ids:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "⚠️ Planning précédent vide",
                    "message": "Le planning précédent ne contient aucune affectation à copier.",
                    "type": "warning",
                    "sticky": False,
                },
            }

        # Supprimer les affectations actuelles
        if self.assignment_ids:
            self.assignment_ids.with_context(skip_tracking=True).unlink()

        # Copier depuis le planning précédent
        self._copy_from_last_planning()

        # Compter les affectations copiées
        nb_assignments = len(self.assignment_ids)

        self.message_post(
            body=Markup(
                f"Planning copié depuis la semaine du : {previous_planning.start_date.strftime('%d/%m/%Y')} - {nb_assignments} affectations copiées."
            )
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Planning copié",
                "message": f'Planning copié depuis la semaine du {previous_planning.start_date.strftime("%d/%m/%Y")}. {nb_assignments} affectations copiées.',
                "type": "success",
                "sticky": False,
            },
        }

    def action_choose_template(self):
        if not self.env.user.has_group(
            'chc_cds_planning.group_planning_admin'
        ):
            raise AccessError("Droits administrateur planning requis.")
        
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "chc_cds_planning.planning_template_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_planning_id": self.id,
                "default_replace_existing": True,
                "default_check_availability": True,
                "default_action": "apply",
            },
        }

    def action_save_as_template(self):
        if not self.env.user.has_group(
            'chc_cds_planning.group_planning_admin'
        ):
            raise AccessError("Droits administrateur planning requis.")
        
        self.ensure_one()

        if not self.assignment_ids:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "⚠️ Planning vide",
                    "message": "Impossible de créer un modèle à partir d'un planning vide.",
                    "type": "warning",
                    "sticky": False,
                },
            }

        return {
            "type": "ir.actions.act_window",
            "res_model": "chc_cds_planning.planning_template_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_planning_id": self.id,
                "default_action": "save",
            },
        }

    @api.depends("start_date")
    def _compute_name(self):
        for planning in self:
            if planning.start_date and planning.end_date:
                planning.name = f"Semaine du {planning.start_date.strftime('%d/%m/%Y')} au {planning.end_date.strftime('%d/%m/%Y')}"
            else:
                planning.name = "Nouvelle semaine"

    @api.depends("start_date")
    def _compute_end_date(self):
        for planning in self:
            if planning.start_date:
                # Le planning est pour une semaine (5 jours ouvrés), donc on ajoute 4 jours
                planning.end_date = planning.start_date + timedelta(days=4)
            else:
                planning.end_date = False

    @api.constrains("start_date")
    def _check_start_date_monday(self):
        for planning in self:
            if planning.start_date and planning.start_date.weekday() != 0:
                raise ValidationError("La date de début doit être un lundi")

    def _get_default_resource_calendar_id(self):
        """Même calendrier que pour la génération (jours fériés)."""
        cal = self.env["resource.calendar"].search(
            [("active", "=", True)], limit=1, order="id asc"
        )
        return cal.id if cal else None

    def _is_public_holiday_weekday(self, day_name):
        """True si ce jour de la semaine du planning est férié (pas d'exigence de couverture)."""
        self.ensure_one()
        if not self.start_date:
            return False
        from ..utils.utils import get_date_from_week_start_and_day, is_public_holiday

        d = get_date_from_week_start_and_day(self.start_date, day_name)
        return is_public_holiday(self.env, d, self._get_default_resource_calendar_id())

    def _count_non_holiday_weekdays(self):
        """Nombre de jours lundi–vendredi non fériés dans la semaine du planning."""
        self.ensure_one()
        if not self.start_date:
            return 5
        from ..utils.utils import get_date_from_week_start_and_day, is_public_holiday

        cal_id = self._get_default_resource_calendar_id()
        n = 0
        for day_name in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
        ):
            d = get_date_from_week_start_and_day(self.start_date, day_name)
            if not is_public_holiday(self.env, d, cal_id):
                n += 1
        return n

    def action_confirm(self):
        # Ajouter action remettre au brouille
        # Confirme le planning après validation de tous les critères obligatoires.

        # Si le contexte contient ``force_confirm=True``, les validations bloquantes
        # sont transformées en alertes et la confirmation est tout de même effectuée.
        # 

        if not self.env.user.has_group(
            'chc_cds_planning.group_planning_admin'
        ):
            raise AccessError("Droits administrateur planning requis.")
        
        force_confirm = bool(self.env.context.get("force_confirm"))
        forced_messages = []

        for planning in self:
            errors = []  # Liste pour collecter toutes les erreurs

            # Configuration des jours et champs
            days_config = [
                ("monday", "Lundi", "assignment_ids_monday"),
                ("tuesday", "Mardi", "assignment_ids_tuesday"),
                ("wednesday", "Mercredi", "assignment_ids_wednesday"),
                ("thursday", "Jeudi", "assignment_ids_thursday"),
                ("friday", "Vendredi", "assignment_ids_friday"),
            ]

            # ================================
            # VALIDATION 1: Minimum d'employés à MLE On Site
            # ================================
            for day, label, field_name in days_config:
                if planning._is_public_holiday_weekday(day):
                    continue
                assignments = getattr(planning, field_name).filtered(
                    lambda a: a.day == day and a.permanence_type_id.code == "ATL"
                )
                employee_ids = {a.employee_id.id for a in assignments}

                if len(employee_ids) < 2:
                    errors.append(
                        f"❌ {label}: Vous devez affecter au moins 2 employés à MLE On Site."
                    )

            # ================================
            # VALIDATION 2: Permanences techniques site obligatoires
            # ================================
            site_constraints = {
                "HEU": 2,  # min 2 jours/semaine
                "HRM": 2,
                "WAR": 1,
            }

            # Initialisation d'un ensemble de jours TEC par site
            site_tech_days = {site: set() for site in site_constraints}

            for day, label, field_name in days_config:
                assignments = getattr(planning, field_name)

                for site_code in site_constraints:
                    tech_assignments = assignments.filtered(
                        lambda a: a.day == day
                        and a.site_id.code == site_code
                        and a.permanence_type_id.code == "TCH"
                    )
                    if tech_assignments:
                        site_tech_days[site_code].add(day)

            # Vérification finale des contraintes hebdomadaires (plafonnée aux jours ouvrés non fériés)
            working_days = planning._count_non_holiday_weekdays()
            for site_code, min_days in site_constraints.items():
                actual_days = len(site_tech_days[site_code])
                required_days = min(min_days, working_days) if working_days else 0
                if actual_days < required_days:
                    errors.append(
                        f"❌ Le site {site_code} doit avoir une permanence technique (TCH) au moins {required_days} jour(s) sur les jours ouvrés de la semaine, actuellement : {actual_days}."
                    )

            # ================================
            # VALIDATION 3: Permanences fonctionnelles obligatoires (FCT)
            # ================================
            for day, label, field_name in days_config:
                if planning._is_public_holiday_weekday(day):
                    continue
                assignments = getattr(planning, field_name)

                fonct_assignments_am = assignments.filtered(
                    lambda a: a.day == day
                    and a.site_id.code == "MLE"
                    and a.permanence_type_id.code == "FCT"
                    and a.period == "am"
                )

                fonct_assignments_pm = assignments.filtered(
                    lambda a: a.day == day
                    and a.site_id.code == "MLE"
                    and a.permanence_type_id.code == "FCT"
                    and a.period == "pm"
                )

                if not fonct_assignments_am:
                    errors.append(
                        f"❌ {label}: Aucune permanence fonctionnelle am affectée au site MLE."
                    )

                if not fonct_assignments_pm:
                    errors.append(
                        f"❌ {label}: Aucune permanence fonctionnelle pm affectée au site MLE."
                    )

            # ================================
            # VALIDATION 4: Permanences techniques obligatoires (TCH)
            # ================================
            for day, label, field_name in days_config:
                if planning._is_public_holiday_weekday(day):
                    continue
                assignments = getattr(planning, field_name)

                tech_assignments_am = assignments.filtered(
                    lambda a: a.day == day
                    and a.site_id.code == "MLE"
                    and a.permanence_type_id.code == "TCH"
                    and a.period == "am"
                )

                tech_assignments_pm = assignments.filtered(
                    lambda a: a.day == day
                    and a.site_id.code == "MLE"
                    and a.permanence_type_id.code == "TCH"
                    and a.period == "pm"
                )

                if not tech_assignments_am:
                    errors.append(
                        f"❌ {label}: Aucune permanence technique am affectée au site MLE."
                    )

                if not tech_assignments_pm:
                    errors.append(
                        f"❌ {label}: Aucune permanence technique pm affectée au site MLE."
                    )

            # ================================
            # VALIDATION 5: Pas de conflits d'horaires
            # ================================
            for day, label, field_name in days_config:
                assignments = getattr(planning, field_name).filtered(
                    lambda a: a.day == day
                )

                # Grouper par employé
                employee_assignments = {}
                for assignment in assignments:
                    emp_id = assignment.employee_id.id
                    if emp_id not in employee_assignments:
                        employee_assignments[emp_id] = []
                    employee_assignments[emp_id].append(assignment)

                # Vérifier les conflits pour chaque employé
                for emp_id, emp_assignments in employee_assignments.items():
                    if len(emp_assignments) > 1:
                        # RÈGLE : Un employé ne peut faire qu'UNE seule permanence par jour
                        for i, assign1 in enumerate(emp_assignments):
                            for assign2 in emp_assignments[i + 1 :]:
                                if self._check_time_overlap(assign1, assign2):
                                    errors.append(
                                        f"❌ {label}: {assign1.employee_id.name} est assigné à 2 permanences le même jour : "
                                        f"{assign1.site_id.name} {assign1.period.upper()} ({assign1.permanence_type_id.name}) "
                                        f"ET {assign2.site_id.name} {assign2.period.upper()} ({assign2.permanence_type_id.name}). "
                                        f"Un employé ne peut faire qu'UNE permanence par jour."
                                    )

            # ================================
            # VALIDATION 6: Respect du maximum de jours par employé
            # ================================
            employee_day_count = {}
            for day, label, field_name in days_config:
                assignments = getattr(planning, field_name).filtered(
                    lambda a: a.day == day
                )

                for assignment in assignments:
                    emp_id = assignment.employee_id.id
                    if emp_id not in employee_day_count:
                        employee_day_count[emp_id] = set()
                    employee_day_count[emp_id].add(day)

            for emp_id, worked_days in employee_day_count.items():
                employee = self.env["hr.employee"].browse(emp_id)
                max_days = employee.max_days_per_week or 5

                if len(worked_days) > max_days:
                    errors.append(
                        f"❌ {employee.name} travaille {len(worked_days)} jours "
                        f"(maximum autorisé: {max_days})."
                    )

            # ================================
            # VALIDATION 7: Vérifier les qualifications
            # ================================
            for day, label, field_name in days_config:
                assignments = getattr(planning, field_name).filtered(
                    lambda a: a.day == day
                )

                for assignment in assignments:
                    # Vérifier si l'employé a la qualification pour ce type de permanence sur ce site
                    qualification = self.env[
                        "chc_cds_planning.employee_qualifications"
                    ].search(
                        [
                            ("employee_id", "=", assignment.employee_id.id),
                            (
                                "permanence_type_id",
                                "=",
                                assignment.permanence_type_id.id,
                            ),
                            ("site_id", "=", assignment.site_id.id),
                        ],
                        limit=1,
                    )

                    # Pour MLE On Site, on peut être plus souple (niveau débutant acceptable)
                    if assignment.permanence_type_id.code == "ATL":
                        continue  # Pas de vérification stricte pour MLE On Site

                    # Pour les permanences techniques/fonctionnelles, qualification obligatoire
                    if not qualification and assignment.permanence_type_id.code in [
                        "TEC",
                        "FCT",
                        "TCH",
                    ]:
                        errors.append(
                            f"❌ {label}: {assignment.employee_id.name} n'a pas la qualification "
                            f"pour {assignment.permanence_type_id.name} au site {assignment.site_id.name}."
                        )

            # ================================
            # VALIDATION 8: Vérifier les contraintes de disponibilité
            # ================================
            for day, label, field_name in days_config:
                assignments = getattr(planning, field_name).filtered(
                    lambda a: a.day == day
                )

                # Convertir le nom du jour en index (monday=0, tuesday=1, etc.)
                from ..utils.utils import get_day_index

                day_index = get_day_index(day)

                for assignment in assignments:
                    # Vérifier les contraintes explicites
                    constraints = self.env[
                        "chc_cds_planning.employee_unavailability"
                    ].search(
                        [
                            ("employee_id", "=", assignment.employee_id.id),
                            ("day_of_week", "=", str(day_index)),
                        ]
                    )

                    if constraints:
                        constraint = constraints[0]
                        reason = f" ({constraint.reason})" if constraint.reason else ""
                        errors.append(
                            f"❌ {label}: {assignment.employee_id.name} est indisponible{reason}."
                        )

            # ================================
            # VALIDATION 9: Vérifier les congés
            # ================================
            start_date = planning.start_date
            if start_date:
                from ..utils.utils import get_date_from_week_start_and_day

                for day_index, (day, label, field_name) in enumerate(days_config):
                    current_date = get_date_from_week_start_and_day(start_date, day)
                    assignments = getattr(planning, field_name).filtered(
                        lambda a: a.day == day
                    )

                    for assignment in assignments:
                        # Vérifier si l'employé est en congé ce jour-là
                        leaves = self.env["hr.leave"].search(
                            [
                                ("employee_id", "=", assignment.employee_id.id),
                                ("date_from", "<=", current_date),
                                ("date_to", ">=", current_date),
                                ("state", "=", "validate"),
                            ]
                        )

                        if leaves:
                            leave = leaves[0]
                            errors.append(
                                f"❌ {label}: {assignment.employee_id.name} est en congé "
                                f"({leave.holiday_status_id.name})."
                            )

            # en cas d'erreur on affiche un message et on raise une exception
            if errors:
                error_message = (
                    f"Le planning {planning.name} ne peut pas être confirmé :\n\n"
                    + "\n".join(errors)
                )

                if not force_confirm:
                    if len(self) > 1:
                        raise ValidationError(error_message)
                    return self._open_force_confirm_wizard(planning, error_message)

                forced_messages.append(
                    f"{planning.name} confirmé malgré les alertes suivantes :\n"
                    + "\n".join(errors)
                )

        # on set l'état du planning si tout est ok (ou forcé)
        self.write({"state": "confirmed"})

        # message success du nombre de planning confirmés
        try:
            action_ref = self.env.ref(
                "chc_cds_planning.action_chc_cds_planning_planning_weekly"
            )
            action = action_ref.read()[0]
        except Exception:
            action = None

        message = f"{len(self)} planning(s) confirmé(s) avec succès."
        notification_type = "success"
        if forced_messages:
            message = "Confirmation forcée réalisée :\n\n" + "\n\n".join(
                forced_messages
            )
            notification_type = "warning"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Confirmation réalisée",
                "message": message,
                "type": notification_type,
                "sticky": False,
                "next": action,
            },
        }

    def _open_force_confirm_wizard(
        self,
        planning,
        error_message,
        remaining_planning_ids=None,
        total_confirmed_count=0,
    ):
        """Ouvre un wizard affichant les erreurs et proposant la confirmation forcée."""
        import json

        wizard_view = self.env.ref(
            "chc_cds_planning.view_planning_confirm_override_wizard_form"
        )

        # Convertir la liste d'IDs en JSON pour le stocker dans le wizard
        remaining_ids_json = json.dumps(remaining_planning_ids or [])

        return {
            "type": "ir.actions.act_window",
            "res_model": "chc_cds_planning.confirm_override_wizard",
            "view_mode": "form",
            "view_id": wizard_view.id,
            "target": "new",
            "context": {
                "default_planning_id": planning.id,
                "default_error_message": error_message,
                "default_remaining_planning_ids": remaining_ids_json,
                "default_total_confirmed_count": total_confirmed_count,
            },
        }

    def _check_time_overlap(self, assignment1, assignment2):
        """Vérifie si deux affectations ont des horaires qui se chevauchent

        RÈGLE SIMPLE : Un employé ne peut faire qu'UNE SEULE permanence par jour.
        Peu importe les périodes (AM, PM, Full), si c'est le même jour = CONFLIT.
        """
        from ..utils.utils import check_time_overlap

        return check_time_overlap(assignment1, assignment2)

    def action_reset_to_draft(self):
        if not self.env.user.has_group(
            'chc_cds_planning.group_planning_admin'
        ):
            raise AccessError("Droits administrateur planning requis.")


        to_reset = self.filtered(lambda p: p.state != "draft")
        if not to_reset:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Aucun changement",
                    "message": "Tous les plannings sélectionnés sont déjà en brouillon.",
                    "type": "info",
                    "sticky": False,
                },
            }

        to_reset.write({"state": "draft"})

        try:
            action_ref = self.env.ref(
                "chc_cds_planning.action_chc_cds_planning_planning_weekly"
            )
            action = action_ref.read()[0]
        except Exception:
            action = None

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Plannings remis en brouillon",
                "message": f"{len(to_reset)} planning(s) ont été remis en brouillon.",
                "type": "success",
                "sticky": False,
                "next": action,
            },
        }

    def action_publish(self):
        """Publie le(s) planning(s) et envoie des invitations calendrier par email"""
        if not self.env.user.has_group(
            "chc_cds_planning.group_planning_admin"
        ):
            raise AccessError("Droits administrateur planning requis.")

        to_publish = self.filtered(lambda p: p.state != "published")
        if not to_publish:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Aucun changement",
                    "message": "Tous les plannings sélectionnés sont déjà publiés",
                    "type": "info",
                    "sticky": False,
                },
            }

        # Publier les plannings
        to_publish.write({"state": "published"})

        total_emails_sent = 0
        total_employees_targeted = 0
        missing_email_employees = set()
        invite_errors = []

        for planning in to_publish:
            try:
                from ..utils.utils import send_calendar_invites_for_planning

                invite_result = send_calendar_invites_for_planning(planning)
                total_emails_sent += invite_result.get("emails_sent", 0)
                total_employees_targeted += invite_result.get("employees_targeted", 0)
                missing_email_employees.update(
                    invite_result.get("missing_email_employees", [])
                )

                for error in invite_result.get("errors", []):
                    invite_errors.append(f"{planning.name}: {error}")
            except Exception as e:
                import logging

                _logger = logging.getLogger(__name__)
                _logger.error(
                    f"Erreur invitations calendrier pour planning {planning.id}: {e}",
                    exc_info=True,
                )
                invite_errors.append(f"{planning.name}: {e}")

        # Préparer l'action de rechargement
        try:
            action_ref = self.env.ref(
                "chc_cds_planning.action_chc_cds_planning_planning_weekly"
            )
            action = action_ref.read()[0]
        except Exception:
            action = None

        message = f"✅ {len(to_publish)} planning(s) ont été publiés"
        if total_employees_targeted:
            message += (
                f". {total_emails_sent} invitation(s) calendrier envoyée(s) "
                f"pour {total_employees_targeted} employé(s)."
            )
        else:
            message += ". Aucune affectation à notifier."

        if missing_email_employees:
            names = ", ".join(sorted(missing_email_employees))
            message += f" Email professionnel manquant pour : {names}."

        notification_type = "success"
        if invite_errors:
            notification_type = "warning"
            message += " Certaines invitations n'ont pas pu être envoyées."

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Plannings publiés",
                "message": message,
                "type": notification_type,
                "sticky": False,
                "next": action,
            },
        }

    def action_export_pdf_from_menu(self):
        """Exporte le(s) planning(s) en PDF depuis le menu Actions (accessible aux utilisateurs standards)
        
        Cette méthode utilise sudo() dès le début pour contourner la vérification des droits d'écriture.
        L'export PDF est une opération en lecture seule, pas besoin de droits d'écriture.
        Pour plusieurs plannings, utilise directement la route HTTP pour éviter les problèmes de permissions.
        """
        # Utiliser sudo() dès le début pour éviter toute vérification de droits
        records_sudo = self.sudo()
        
        # Pour plusieurs plannings, utiliser directement la route HTTP qui gère l'export en groupe
        # Cette route utilise auth="user" et ne nécessite pas de droits d'écriture
        if len(records_sudo) > 1:
            from ..utils.utils import get_batch_pdf_download_action
            batch_action = get_batch_pdf_download_action(records_sudo.ids)
            if batch_action:
                return batch_action
        
        # Pour un seul planning, utiliser la méthode normale
        return records_sudo.action_export_pdf()

    def action_export_pdf(self):
        """Exporte le(s) planning(s) en PDF sans changer le statut"""
        to_export = self.sudo()
        if not to_export:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Aucun planning",
                    "message": "Aucun planning sélectionné",
                    "type": "warning",
                    "sticky": False,
                },
            }

        # Optimisation: en export multi, on évite de générer des attachments individuels
        # puis un PDF groupé (double travail coûteux).
        if len(to_export) > 1:
            from ..utils.utils import get_batch_pdf_download_action

            batch_action = get_batch_pdf_download_action(to_export.ids)
            if batch_action:
                return batch_action

        # Export unitaire: générer un seul attachment et le télécharger.
        attachments = []
        for planning in to_export:
            try:
                from ..utils.utils import generate_pdf_export_via_report

                attachment = generate_pdf_export_via_report(planning)
                if attachment:
                    attachments.append(attachment)
                else:
                    # Logger si la génération a échoué
                    import logging

                    _logger = logging.getLogger(__name__)
                    _logger.warning(
                        f"Génération PDF échouée pour planning {planning.id} - aucun attachment créé"
                    )
            except Exception as e:
                import logging

                _logger = logging.getLogger(__name__)
                _logger.error(
                    f"Erreur export PDF pour planning {planning.id}: {e}", exc_info=True
                )

        # Préparer l'action de rechargement
        try:
            action_ref = self.env.ref(
                "chc_cds_planning.action_chc_cds_planning_planning_weekly"
            )
            action = action_ref.read()[0]
        except Exception:
            action = None

        # Si un seul planning exporté, télécharger directement le PDF
        if len(to_export) == 1 and len(attachments) == 1:
            attachment = attachments[0]
            # Retourner une action qui déclenche le téléchargement automatique
            return {
                "type": "ir.actions.act_url",
                "url": f"/planning/download_pdf/{attachment.id}",
                "target": "self",
            }

        # Fallback notification
        message = f"✅ {len(attachments)} export(s) PDF généré(s) pour {len(to_export)} planning(s). Consultez les pièces jointes."

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Export PDF",
                "message": message,
                "type": "success",
                "sticky": False,
                "next": action,
            },
        }

    def action_confirm_from_menu(self):
        """Confirme les plannings depuis le menu actions, avec gestion des erreurs"""
        # Pour un seul planning, action_confirm gère déjà le wizard
        if len(self) == 1:
            # Un seul planning : action_confirm gère le wizard automatiquement
            return self.action_confirm()

        # Plusieurs plannings : vérifier chaque planning et traiter ceux avec erreurs
        plannings_with_errors = []
        plannings_ok = []

        for planning in self:
            errors = planning._check_confirmation_errors()
            if errors:
                plannings_with_errors.append((planning, errors))
            else:
                plannings_ok.append(planning)

        # Confirmer directement ceux qui n'ont pas d'erreurs
        if plannings_ok:
            # Convertir la liste en recordset pour utiliser write()
            # Gérer les erreurs de transaction pour éviter InFailedSqlTransaction
            try:
                self.browse([p.id for p in plannings_ok]).write({"state": "confirmed"})
            except Exception as e:
                # En cas d'erreur lors du write(), ajouter les plannings à la liste d'erreurs
                # et propager l'erreur pour que Odoo puisse faire le rollback
                import logging
                _logger = logging.getLogger(__name__)
                _logger.error(f"Erreur lors de la confirmation des plannings: {e}", exc_info=True)
                # Ajouter les plannings qui n'ont pas pu être confirmés à la liste d'erreurs
                for planning in plannings_ok:
                    plannings_with_errors.append((planning, [f"Erreur lors de la confirmation: {str(e)}"]))
                plannings_ok = []
                # Si tous les plannings ont échoué, lever l'erreur pour que la transaction soit rollback
                if not plannings_ok and not plannings_with_errors:
                    raise

        # S'il y a des plannings avec erreurs, ouvrir le wizard pour le premier
        if plannings_with_errors:
            first_planning, first_errors = plannings_with_errors[0]
            error_message = (
                f"Le planning {first_planning.name} ne peut pas être confirmé :\n\n"
                + "\n".join(first_errors)
            )

            # Préparer la liste des IDs des plannings restants (avec erreurs)
            remaining_ids = [p.id for p, _ in plannings_with_errors[1:]]

            # Nombre de plannings déjà confirmés directement (sans erreurs)
            total_confirmed_count = len(plannings_ok)

            return first_planning._open_force_confirm_wizard(
                first_planning, error_message, remaining_ids, total_confirmed_count
            )

        # Tous les plannings sont OK, afficher un message de succès
        try:
            action_ref = self.env.ref(
                "chc_cds_planning.action_chc_cds_planning_planning_weekly"
            )
            action = action_ref.read()[0]
        except Exception:
            action = None

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Confirmation réussie",
                "message": f"{len(self)} planning(s) confirmé(s) avec succès.",
                "type": "success",
                "sticky": False,
                "next": action,
            },
        }

    def _check_confirmation_errors(self):
        """Vérifie les erreurs de confirmation sans lever d'exception"""
        self.ensure_one()
        errors = []

        # Configuration des jours et champs
        days_config = [
            ("monday", "Lundi", "assignment_ids_monday"),
            ("tuesday", "Mardi", "assignment_ids_tuesday"),
            ("wednesday", "Mercredi", "assignment_ids_wednesday"),
            ("thursday", "Jeudi", "assignment_ids_thursday"),
            ("friday", "Vendredi", "assignment_ids_friday"),
        ]

        planning = self

        # ================================
        # VALIDATION 1: Minimum d'employés à l'atelier
        # ================================
        for day, label, field_name in days_config:
            if planning._is_public_holiday_weekday(day):
                continue
            assignments = getattr(planning, field_name).filtered(
                lambda a: a.day == day and a.permanence_type_id.code == "ATL"
            )
            employee_ids = {a.employee_id.id for a in assignments}

            if len(employee_ids) < 2:
                errors.append(
                    f"❌ {label}: Vous devez affecter au moins 2 employés à l'atelier."
                )

        # ================================
        # VALIDATION 2: Permanences techniques site obligatoires
        # ================================
        site_constraints = {
            "HEU": 2,
            "HRM": 2,
            "WAR": 1,
        }

        site_tech_days = {site: set() for site in site_constraints}

        for day, label, field_name in days_config:
            assignments = getattr(planning, field_name)

            for site_code in site_constraints:
                tech_assignments = assignments.filtered(
                    lambda a: a.day == day
                    and a.site_id.code == site_code
                    and a.permanence_type_id.code == "TCH"
                )
                if tech_assignments:
                    site_tech_days[site_code].add(day)

        working_days = planning._count_non_holiday_weekdays()
        for site_code, min_days in site_constraints.items():
            actual_days = len(site_tech_days[site_code])
            required_days = min(min_days, working_days) if working_days else 0
            if actual_days < required_days:
                errors.append(
                    f"❌ Le site {site_code} doit avoir une permanence technique (TCH) au moins {required_days} jour(s) sur les jours ouvrés de la semaine, actuellement : {actual_days}."
                )

        # ================================
        # VALIDATION 3: Permanences fonctionnelles obligatoires (FCT)
        # ================================
        for day, label, field_name in days_config:
            if planning._is_public_holiday_weekday(day):
                continue
            assignments = getattr(planning, field_name)

            fonct_assignments_am = assignments.filtered(
                lambda a: a.day == day
                and a.site_id.code == "MLE"
                and a.permanence_type_id.code == "FCT"
                and a.period == "am"
            )

            fonct_assignments_pm = assignments.filtered(
                lambda a: a.day == day
                and a.site_id.code == "MLE"
                and a.permanence_type_id.code == "FCT"
                and a.period == "pm"
            )

            if not fonct_assignments_am:
                errors.append(
                    f"❌ {label}: Aucune permanence fonctionnelle am affectée au site MLE."
                )

            if not fonct_assignments_pm:
                errors.append(
                    f"❌ {label}: Aucune permanence fonctionnelle pm affectée au site MLE."
                )

        # ================================
        # VALIDATION 4: Permanences techniques obligatoires (TCH)
        # ================================
        for day, label, field_name in days_config:
            if planning._is_public_holiday_weekday(day):
                continue
            assignments = getattr(planning, field_name)

            tech_assignments_am = assignments.filtered(
                lambda a: a.day == day
                and a.site_id.code == "MLE"
                and a.permanence_type_id.code == "TCH"
                and a.period == "am"
            )

            tech_assignments_pm = assignments.filtered(
                lambda a: a.day == day
                and a.site_id.code == "MLE"
                and a.permanence_type_id.code == "TCH"
                and a.period == "pm"
            )

            if not tech_assignments_am:
                errors.append(
                    f"❌ {label}: Aucune permanence technique am affectée au site MLE."
                )

            if not tech_assignments_pm:
                errors.append(
                    f"❌ {label}: Aucune permanence technique pm affectée au site MLE."
                )

        # ================================
        # VALIDATION 5: Pas de conflits d'horaires
        # ================================
        for day, label, field_name in days_config:
            assignments = getattr(planning, field_name).filtered(lambda a: a.day == day)

            employee_assignments = {}
            for assignment in assignments:
                emp_id = assignment.employee_id.id
                if emp_id not in employee_assignments:
                    employee_assignments[emp_id] = []
                employee_assignments[emp_id].append(assignment)

            for emp_id, emp_assignments in employee_assignments.items():
                if len(emp_assignments) > 1:
                    for i, assign1 in enumerate(emp_assignments):
                        for assign2 in emp_assignments[i + 1 :]:
                            if self._check_time_overlap(assign1, assign2):
                                errors.append(
                                    f"❌ {label}: {assign1.employee_id.name} est assigné à 2 permanences le même jour : "
                                    f"{assign1.site_id.name} {assign1.period.upper()} ({assign1.permanence_type_id.name}) "
                                    f"ET {assign2.site_id.name} {assign2.period.upper()} ({assign2.permanence_type_id.name}). "
                                    f"Un employé ne peut faire qu'UNE permanence par jour."
                                )

        # ================================
        # VALIDATION 6: Respect du maximum de jours par employé
        # ================================
        employee_day_count = {}
        for day, label, field_name in days_config:
            assignments = getattr(planning, field_name).filtered(lambda a: a.day == day)

            for assignment in assignments:
                emp_id = assignment.employee_id.id
                if emp_id not in employee_day_count:
                    employee_day_count[emp_id] = set()
                employee_day_count[emp_id].add(day)

        for emp_id, worked_days in employee_day_count.items():
            employee = self.env["hr.employee"].browse(emp_id)
            max_days = employee.max_days_per_week or 5

            if len(worked_days) > max_days:
                errors.append(
                    f"❌ {employee.name} travaille {len(worked_days)} jours "
                    f"(maximum autorisé: {max_days})."
                )

        # ================================
        # VALIDATION 7: Vérifier les qualifications
        # ================================
        for day, label, field_name in days_config:
            assignments = getattr(planning, field_name).filtered(lambda a: a.day == day)

            for assignment in assignments:
                qualification = self.env["chc_cds_planning.employee_qualifications"].search(
                    [
                        ("employee_id", "=", assignment.employee_id.id),
                        (
                            "permanence_type_id",
                            "=",
                            assignment.permanence_type_id.id,
                        ),
                        ("site_id", "=", assignment.site_id.id),
                    ],
                    limit=1,
                )

                if assignment.permanence_type_id.code == "ATL":
                    continue

                if not qualification and assignment.permanence_type_id.code in [
                    "TEC",
                    "FCT",
                    "TCH",
                ]:
                    errors.append(
                        f"❌ {label}: {assignment.employee_id.name} n'a pas la qualification "
                        f"pour {assignment.permanence_type_id.name} au site {assignment.site_id.name}."
                    )

        # ================================
        # VALIDATION 8: Vérifier les contraintes de disponibilité
        # ================================
        for day, label, field_name in days_config:
            assignments = getattr(planning, field_name).filtered(lambda a: a.day == day)

            from ..utils.utils import get_day_index

            day_index = get_day_index(day)

            for assignment in assignments:
                constraints = self.env["chc_cds_planning.employee_unavailability"].search(
                    [
                        ("employee_id", "=", assignment.employee_id.id),
                        ("day_of_week", "=", str(day_index)),
                    ]
                )

                if constraints:
                    constraint = constraints[0]
                    reason = f" ({constraint.reason})" if constraint.reason else ""
                    errors.append(
                        f"❌ {label}: {assignment.employee_id.name} est indisponible{reason}."
                    )

        # ================================
        # VALIDATION 9: Vérifier les congés
        # ================================
        start_date = planning.start_date
        if start_date:
            from ..utils.utils import get_date_from_week_start_and_day

            for day_index, (day, label, field_name) in enumerate(days_config):
                current_date = get_date_from_week_start_and_day(start_date, day)
                assignments = getattr(planning, field_name).filtered(
                    lambda a: a.day == day
                )

                for assignment in assignments:
                    leaves = self.env["hr.leave"].search(
                        [
                            ("employee_id", "=", assignment.employee_id.id),
                            ("date_from", "<=", current_date),
                            ("date_to", ">=", current_date),
                            ("state", "=", "validate"),
                        ]
                    )

                    if leaves:
                        leave = leaves[0]
                        errors.append(
                            f"❌ {label}: {assignment.employee_id.name} est en congé "
                            f"({leave.holiday_status_id.name})."
                        )

        return errors

    def action_publish_with_check(self):
        """Publie le(s) planning(s) uniquement s'ils sont confirmés"""
        if not self.env.user.has_group(
            "chc_cds_planning.group_planning_admin"
        ):
            raise AccessError("Droits administrateur planning requis.")

        # Filtrer les plannings qui ne sont pas confirmés
        not_confirmed = self.filtered(lambda p: p.state != "confirmed")

        if not_confirmed:
            planning_names = ", ".join(not_confirmed.mapped("name"))
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "❌ Publication impossible",
                    "message": f"Les plannings suivants doivent être confirmés avant publication : {planning_names}",
                    "type": "danger",
                    "sticky": True,
                },
            }

        # Tous les plannings sont confirmés, on peut publier
        return self.action_publish()

    def _get_batch_pdf_download_action(self, planning_ids):
        """Prépare une action permettant de déclencher un téléchargement PDF multi-plannings"""
        from ..utils.utils import get_batch_pdf_download_action

        return get_batch_pdf_download_action(planning_ids)

    def _prepare_planning_data_for_export(self):
        """Prépare les données pour l'export PDF (similaire à _prepare_planning_data du contrôleur)"""
        from ..utils.utils import prepare_planning_data_for_export

        # Utiliser sudo() pour éviter les problèmes d'accès lors de la préparation des données
        # Cela permet aux utilisateurs standards d'exporter même s'ils n'ont pas tous les droits
        return prepare_planning_data_for_export(self.sudo())

    def _prepare_employee_data_for_export(self, assignment):
        """Prépare les données d'un employé pour l'export (similaire au contrôleur)"""
        from ..utils.utils import prepare_employee_data_for_export

        return prepare_employee_data_for_export(assignment)

    def _generate_pdf_export_via_report(self):
        """Génère un export PDF du planning via le système de rapport Odoo (comme Print)"""
        from ..utils.utils import generate_pdf_export_via_report

        return generate_pdf_export_via_report(self)

    def action_view_visual_planning(self):
        """Redirection vers la vue visuelle du planning"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/web/planning/%s" % self.id,
            "target": "self",
        }
