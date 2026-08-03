# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields, models


class MonthlyPlanningGenerator(models.TransientModel):
    _name = "chc_cds_planning.monthly_planning_generator"
    _description = "Générateur de planning mensuel"

    month = fields.Selection(
        [
            ("1", "Janvier"),
            ("2", "Février"),
            ("3", "Mars"),
            ("4", "Avril"),
            ("5", "Mai"),
            ("6", "Juin"),
            ("7", "Juillet"),
            ("8", "Août"),
            ("9", "Septembre"),
            ("10", "Octobre"),
            ("11", "Novembre"),
            ("12", "Décembre"),
        ],
        string="Mois",
        required=True,
        default=lambda self: str(fields.Date.today().month),
    )

    year = fields.Integer(
        string="Année", required=True, default=lambda self: date.today().year
    )

    replace_existing = fields.Boolean(
        string="Remplacer les plannings existants",
        default=False,
    )


    def action_generate_monthly_planning(self):
        """Génère tous les plannings du mois en copiant le template et en gérant les indisponibilités"""
        self.ensure_one()

        try:
            # 0. Vérifier et réinitialiser les compteurs si nouvelle année
            reset_count = self.env[
                "chc_cds_planning.friday_rotation_counter"
            ].check_and_reset_if_new_year()

            # 1. Récupérer le template par défaut
            default_template = self._get_default_template()
            if not default_template or not default_template.template_line_ids:
                return self._show_notification(
                    "Aucun template",
                    "Aucun template de planning par défaut trouvé. Veuillez en créer un.",
                    "error",
                )

            # 2. Calculer les semaines du mois
            weeks = self._get_weeks_in_month()
            if not weeks:
                return self._show_notification(
                    "Aucune semaine",
                    "Aucune semaine trouvée dans ce mois.",
                    "warning",
                )

            # 3. Vérifier les plannings existants
            existing_plannings = self._check_existing_plannings(weeks)
            if existing_plannings and not self.replace_existing:
                return self._show_notification(
                    "Plannings existants",
                    f"Des plannings existent déjà pour {len(existing_plannings)} semaines. Cochez 'Remplacer' pour continuer.",
                    "warning",
                )

            # 4. Supprimer les plannings existants si demandé
            if self.replace_existing and existing_plannings:
                existing_plannings.with_context(skip_tracking=True).unlink()

            # 5. Initialiser l'état de rotation pour le vendredi PM MLE
            rotation_state = self._initialize_rotation_state()

            # 6. Générer chaque planning hebdomadaire
            created_plannings = []
            replacements_log = []

            for week_idx, week_start in enumerate(weeks):
                try:
                    # Réinitialiser le set des employés ayant fait vendredi PM MLE cette semaine
                    rotation_state["friday_pm_mle_assigned"] = set()

                    planning, week_replacements = self._generate_weekly_from_template(
                        week_start, default_template, rotation_state
                    )
                    if planning:
                        created_plannings.append(planning)
                        replacements_log.extend(week_replacements)

                except Exception as e:
                    return self._show_notification(
                        "Erreur", f"Erreur semaine {week_start}: {str(e)}", "error"
                    )

            # 7. Rapport de génération
            report = self._generate_report(rotation_state, replacements_log)

            # Ajouter une info si des compteurs de rotation ont été réinitialisés
            if reset_count:
                report_suffix = (
                    f" • {reset_count} compteur"
                    f"{'s' if reset_count > 1 else ''} de rotation vendredi remis"
                    f"{' au' if reset_count == 1 else ' aux'} valeurs initiales pour la nouvelle année"
                )
                report = (report or "") + report_suffix

            # Calculer les dates pour filtrer les plannings du mois
            month_start = date(self.year, int(self.month), 1)
            if int(self.month) == 12:
                month_end = date(self.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(self.year, int(self.month) + 1, 1) - timedelta(days=1)

            # Rediriger vers la vue hebdomadaire avec notification
            try:
                action_ref = self.env.ref(
                    "chc_cds_planning.action_chc_cds_planning_planning_weekly"
                )
                action = action_ref.read()[0]

                # Ajouter le domaine pour filtrer les plannings du mois
                action["domain"] = [
                    ("start_date", ">=", month_start.strftime("%Y-%m-%d")),
                    ("start_date", "<=", month_end.strftime("%Y-%m-%d")),
                ]

                # Afficher la notification puis rediriger
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Plannings générés",
                        "message": f"{len(created_plannings)} plannings créés pour {self._get_month_name()} {self.year}.{report}",
                        "type": "success",
                        "sticky": False,
                        "next": action,
                    },
                }
            except Exception:
                # Si l'action n'est pas trouvée, afficher la notification et fermer
                return self._show_notification(
                    "Plannings générés",
                    f"{len(created_plannings)} plannings créés pour {self._get_month_name()} {self.year}.{report}",
                    "success",
                )

        except Exception as e:
            return self._show_notification("Erreur critique", str(e), "error")

    def _initialize_rotation_state(self):
        """Initialise l'état de rotation pour le vendredi PM MLE en chargeant les compteurs persistants"""
        employees = self._get_available_employees()

        # Exclure JUAPE de la rotation (il ne fait pas partie de la rotation du vendredi)
        employees_for_rotation = employees.filtered(
            lambda e: e.employee_code != "JUAPE"
        )

        # Charger les compteurs persistants depuis la base de données
        employee_friday_pm_mle = {}
        for emp in employees_for_rotation:
            counter_record = self.env["chc_cds_planning.friday_rotation_counter"].search(
                [("employee_id", "=", emp.id)], limit=1
            )

            if counter_record:
                employee_friday_pm_mle[emp.id] = counter_record.counter
            else:
                employee_friday_pm_mle[emp.id] = 0

        return {
            "employee_friday_pm_mle": employee_friday_pm_mle,
            "friday_pm_mle_assigned": set(),  # Réinitialisé chaque semaine
            "employees": employees_for_rotation,
        }

    def _get_default_template(self):
        """Retourne le template de planning par défaut"""
        default_template = self.env["chc_cds_planning.planning_template"].search(
            [("is_default", "=", True), ("active", "=", True)], limit=1
        )

        if default_template and default_template.template_line_ids:
            return default_template

        # Fallback sur le premier template actif
        fallback_template = self.env["chc_cds_planning.planning_template"].search(
            [("active", "=", True)], limit=1
        )

        return fallback_template if fallback_template else None

    def _generate_weekly_from_template(self, week_start, template, rotation_state):
        """Génère un planning hebdomadaire depuis le template, gère les indispos et la rotation vendredi PM"""

        # Créer le planning hebdomadaire
        planning = self.env["chc_cds_planning.planning_weekly"].create(
            {
                "start_date": week_start,
                "load_default_planning": False,
            }
        )

        assignments_to_create = []
        replacements_log = []

        # Copier chaque ligne du template
        for template_line in template.template_line_ids:
            # Calculer la date exacte
            day_index = ["monday", "tuesday", "wednesday", "thursday", "friday"].index(
                template_line.day
            )
            current_date = week_start + timedelta(days=day_index)

            # Vérifier si c'est un jour férié public (si oui, ne pas créer d'affectation)
            from ..utils.utils import is_public_holiday
            
            # Récupérer le calendrier par défaut pour vérifier les jours fériés
            default_calendar = self.env["resource.calendar"].search([
                ("active", "=", True)
            ], limit=1, order="id asc")
            calendar_id = default_calendar.id if default_calendar else None
            
            if is_public_holiday(self.env, current_date, calendar_id):
                # C'est un jour férié, ne pas créer d'affectation
                replacements_log.append(
                    f"🏛️ {template_line.day} {template_line.period}: Jour férié, aucune affectation créée"
                )
                continue

            # Vérifier disponibilité de l'employé du template
            original_employee = template_line.employee_id
            selected_employee = original_employee

            if not self._is_employee_available(original_employee, current_date):
                # Employé indisponible → trouver un remplaçant
                replacement = self._find_replacement_employee(
                    template_line.site_id,
                    template_line.permanence_type_id,
                    current_date,
                    rotation_state,
                )
                if replacement:
                    selected_employee = replacement
                    replacements_log.append(
                        f"{template_line.day} {template_line.period}: {original_employee.name} → {replacement.name}"
                    )
                else:
                    # Aucun remplaçant trouvé, logger mais créer quand même avec l'employé original
                    # (l'utilisateur devra corriger manuellement)
                    replacements_log.append(
                        f"⚠️ {template_line.day} {template_line.period}: {original_employee.name} indisponible, aucun remplaçant trouvé"
                    )

            # Calculer start_time et end_time avant la création
            permanence_type_code = (
                template_line.permanence_type_id.code
                if template_line.permanence_type_id
                else None
            )
            assignment_model = self.env["chc_cds_planning.planning_assignment"]
            site_code = (
                template_line.site_id.code if template_line.site_id else None
            )
            start_time, end_time = assignment_model._calculate_times(
                template_line.period, permanence_type_code, site_code
            )

            # Créer l'affectation
            assignments_to_create.append(
                {
                    "planning_week_id": planning.id,
                    "employee_id": selected_employee.id,
                    "site_id": template_line.site_id.id,
                    "permanence_type_id": template_line.permanence_type_id.id,
                    "day": template_line.day,
                    "period": template_line.period,
                    "start_time": start_time,
                    "end_time": end_time,
                    "notes": template_line.notes or "",
                }
            )

        # Créer toutes les affectations
        if assignments_to_create:
            created_assignments = self.env["chc_cds_planning.planning_assignment"].with_context(skip_tracking=True).create(
                assignments_to_create
            )

            # Appliquer la rotation vendredi PM MLE (équilibrage par employé)
            self._apply_friday_rotation(
                created_assignments, week_start, rotation_state, replacements_log
            )

            # Vérifier et corriger les conflits vendredi AM/PM (si une personne est en PM et aussi en AM)
            self._check_friday_am_pm_conflicts(
                created_assignments, week_start, rotation_state, replacements_log
            )

            # Vérifier et corriger les doublons (un employé assigné plusieurs fois le même jour)
            self._check_and_fix_duplicate_assignments(
                created_assignments, week_start, rotation_state, replacements_log
            )

        return planning, replacements_log

    def _find_replacement_employee(
        self, site, permanence_type, current_date, rotation_state
    ):
        """Trouve un employé de remplacement disponible et qualifié"""
        employees = rotation_state["employees"]

        candidates = []
        for emp in employees:
            # Vérifier disponibilité
            if not self._is_employee_available(emp, current_date):
                continue

            # Vérifier qualification
            qualification = emp.qualification_ids.filtered(
                lambda q: q.permanence_type_id.id == permanence_type.id
                and q.site_id.id == site.id
            )
            if not qualification:
                continue

            # Calculer score : priorité de qualification (plus bas = meilleur)
            priority_score = int(qualification[0].priority)
            friday_pm_score = rotation_state.get("employee_friday_pm_mle", {}).get(
                emp.id, 0
            )

            # Score composite
            composite_score = priority_score + (friday_pm_score * 2.0)
            candidates.append((emp, composite_score))

        if not candidates:
            return None

        # Trier et prendre le meilleur
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def _apply_friday_rotation(
        self, assignments, week_start, rotation_state, replacements_log
    ):
        """Applique la rotation équilibrée pour vendredi PM MLE (tech et fonct)"""

        # Filtrer les affectations vendredi PM MLE
        friday_pm_assignments = assignments.filtered(
            lambda a: a.day == "friday"
            and (a.period or "").replace(" ", "").lower() == "pm"
            and a.site_id.code == "MLE"
            and a.permanence_type_id.code in ["TCH", "FCT"]
        )

        if not friday_pm_assignments:
            return

        # Pour chaque affectation vendredi PM MLE
        for assignment in friday_pm_assignments:
            current_employee = assignment.employee_id

            # Exclure JUAPE de la rotation : s'il est assigné, on ne fait rien
            if current_employee.employee_code == "JUAPE":
                continue

            # Vérifier si cet employé a déjà fait beaucoup de vendredis PM MLE ce mois
            # et s'il y a quelqu'un de moins sollicité disponible
            current_count = rotation_state["employee_friday_pm_mle"].get(
                current_employee.id, 0
            )

            # Chercher un remplaçant potentiellement moins sollicité
            replacement = self._find_friday_replacement(
                assignment.site_id,
                assignment.permanence_type_id,
                week_start,
                rotation_state,
                current_employee.id,
                current_count,
            )

            if replacement:
                original_name = current_employee.name
                assignment.with_context(skip_tracking=True).write({"employee_id": replacement.id})
                rotation_state["friday_pm_mle_assigned"].add(replacement.id)
                rotation_state["employee_friday_pm_mle"][replacement.id] = (
                    rotation_state["employee_friday_pm_mle"].get(replacement.id, 0) + 1
                )

                # Mettre à jour le compteur persistant
                self._update_persistent_counter(
                    replacement.id,
                    rotation_state["employee_friday_pm_mle"][replacement.id],
                    week_start,
                )

                replacements_log.append(
                    f"🔄 Rotation vendredi: {original_name} ({current_count}x) → {replacement.name} ({rotation_state['employee_friday_pm_mle'][replacement.id]-1}x) - {assignment.permanence_type_id.name} {assignment.period}"
                )
            else:
                # Garder l'employé actuel
                rotation_state["friday_pm_mle_assigned"].add(current_employee.id)
                rotation_state["employee_friday_pm_mle"][current_employee.id] = (
                    rotation_state["employee_friday_pm_mle"].get(current_employee.id, 0)
                    + 1
                )

                # Mettre à jour le compteur persistant
                self._update_persistent_counter(
                    current_employee.id,
                    rotation_state["employee_friday_pm_mle"][current_employee.id],
                    week_start,
                )

    def _find_friday_replacement(
        self,
        site,
        permanence_type,
        week_start,
        rotation_state,
        current_emp_id,
        current_count,
    ):
        """Trouve un remplaçant pour vendredi PM moins sollicité que l'employé actuel"""
        employees = rotation_state["employees"]
        friday_date = week_start + timedelta(days=4)  # Vendredi

        candidates = []
        for emp in employees:
            # Ne pas re-prendre l'employé actuel
            if emp.id == current_emp_id:
                continue

            # Exclure JUAPE de la rotation (il ne fait pas partie de la rotation du vendredi)
            if emp.employee_code == "JUAPE":
                continue

            # Ne pas prendre ceux qui ont déjà fait vendredi PM MLE cette semaine
            if emp.id in rotation_state["friday_pm_mle_assigned"]:
                continue

            # Vérifier disponibilité
            if not self._is_employee_available(emp, friday_date):
                continue

            # Vérifier qualification
            qualification = emp.qualification_ids.filtered(
                lambda q: q.permanence_type_id.id == permanence_type.id
                and q.site_id.id == site.id
            )
            if not qualification:
                continue

            # Calculer score : priorité + pénalité si déjà fait vendredi PM MLE ce mois
            priority_score = int(qualification[0].priority)
            friday_pm_count = rotation_state.get("employee_friday_pm_mle", {}).get(
                emp.id, 0
            )

            # Ne remplacer que si l'employé de remplacement a fait MOINS de vendredis PM MLE
            if friday_pm_count >= current_count:
                continue

            # Forte pénalité pour ceux qui en ont déjà fait
            composite_score = priority_score + (friday_pm_count * 10.0)
            candidates.append((emp, composite_score, friday_pm_count))

        if not candidates:
            return None

        # Trier par score (plus bas = meilleur)
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def _update_persistent_counter(self, employee_id, new_count, assignment_date):
        """Met à jour le compteur persistant d'un employé"""
        counter_record = self.env["chc_cds_planning.friday_rotation_counter"].search(
            [("employee_id", "=", employee_id)], limit=1
        )

        if counter_record:
            counter_record.write(
                {
                    "counter": new_count,
                    "last_assignment_date": assignment_date
                    + timedelta(days=4),  # Vendredi
                }
            )
        else:
            self.env["chc_cds_planning.friday_rotation_counter"].create(
                {
                    "employee_id": employee_id,
                    "counter": new_count,
                    "last_assignment_date": assignment_date + timedelta(days=4),
                }
            )

    def _generate_report(self, rotation_state, replacements_log):
        """Génère un rapport de génération concis"""
        friday_pm_mle = rotation_state.get("employee_friday_pm_mle", {})

        report_parts = []

        # Statistiques vendredi PM MLE (résumé uniquement)
        total_friday_pm = sum(friday_pm_mle.values())
        if total_friday_pm > 0:
            non_zero = [item for item in friday_pm_mle.items() if item[1] > 0]
            report_parts.append(
                f"Rotation vendredi: {total_friday_pm} affectations sur {len(non_zero)} employés"
            )

        # Résumé des remplacements
        if replacements_log:
            indispo_replacements = [
                r for r in replacements_log if "→" in r and "🔄" not in r
            ]
            friday_rotations = [r for r in replacements_log if "🔄" in r]
            warnings = [r for r in replacements_log if "⚠️" in r]

            summary_parts = []
            if indispo_replacements:
                summary_parts.append(
                    f"{len(indispo_replacements)} remplacement{'s' if len(indispo_replacements) > 1 else ''} indisponibilités"
                )
            if friday_rotations:
                summary_parts.append(
                    f"{len(friday_rotations)} rotation{'s' if len(friday_rotations) > 1 else ''} vendredi"
                )
            if warnings:
                summary_parts.append(
                    f"{len(warnings)} avertissement{'s' if len(warnings) > 1 else ''}"
                )

            if summary_parts:
                report_parts.append(", ".join(summary_parts))

        # Retourner un rapport concis (une seule ligne si possible)
        if report_parts:
            return " • " + " • ".join(report_parts)

        return ""


    # ============================================================================
    # Vérification des conflits vendredi AM/PM
    # ============================================================================

    def _check_friday_am_pm_conflicts(
        self, assignments, week_start, rotation_state, replacements_log
    ):
        """Vérifie et corrige les conflits vendredi où une personne est à la fois en AM et PM"""
        try:
            friday_date = week_start + timedelta(days=4)  # Vendredi

            # Récupérer toutes les affectations du vendredi
            friday_assignments = assignments.filtered(lambda a: a.day == "friday")

            if not friday_assignments:
                return

            # Trouver les personnes en PM le vendredi
            friday_pm_assignments = friday_assignments.filtered(
                lambda a: (a.period or "").replace(" ", "").lower() == "pm"
            )

            for pm_assignment in friday_pm_assignments:
                pm_employee = pm_assignment.employee_id

                # Vérifier si cette personne a aussi une affectation AM le vendredi
                am_assignment = friday_assignments.filtered(
                    lambda a: a.employee_id.id == pm_employee.id
                    and (a.period or "").replace(" ", "").lower() in ["am", "full"]
                )

                if am_assignment:
                    # Conflit détecté : cette personne est en AM et PM le même jour
                    # Trouver un remplaçant pour l'AM
                    replacement = self._find_replacement_for_am_assignment(
                        am_assignment[0], friday_date, rotation_state
                    )

                    if replacement:
                        old_employee_name = am_assignment[0].employee_id.name
                        am_assignment[0].with_context(skip_tracking=True).write({"employee_id": replacement.id})
                        replacements_log.append(
                            f"🔄 Vendredi AM: {old_employee_name} (déjà en PM) → {replacement.name}"
                        )
                    else:
                        replacements_log.append(
                            f"⚠️ Vendredi AM: {pm_employee.name} est en AM et PM, aucun remplaçant trouvé pour l'AM"
                        )
        except Exception as e:
            # Logger l'erreur mais ne pas bloquer la génération
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(
                f"Erreur dans _check_friday_am_pm_conflicts: {e}", exc_info=True
            )

    def _find_replacement_for_am_assignment(
        self, am_assignment, target_date, rotation_state
    ):
        """Trouve un remplaçant pour une affectation AM en évitant le conflit avec PM"""
        employees = rotation_state["employees"]
        site = am_assignment.site_id
        permanence_type = am_assignment.permanence_type_id

        # Exclure l'employé actuel
        current_employee = am_assignment.employee_id

        candidates = []
        for emp in employees:
            # Ne pas prendre l'employé actuel
            if emp.id == current_employee.id:
                continue

            # Vérifier disponibilité
            if not self._is_employee_available(emp, target_date):
                continue

            # Vérifier qualification
            qualification = emp.qualification_ids.filtered(
                lambda q: q.permanence_type_id.id == permanence_type.id
                and q.site_id.id == site.id
            )
            if not qualification:
                continue

            # Vérifier que l'employé n'est pas déjà en PM ce vendredi
            # (récupérer depuis la base pour être sûr)
            existing_pm = self.env["chc_cds_planning.planning_assignment"].search(
                [
                    ("planning_week_id", "=", am_assignment.planning_week_id.id),
                    ("day", "=", "friday"),
                    ("employee_id", "=", emp.id),
                    ("period", "=", "pm"),
                ],
                limit=1,
            )

            if existing_pm:
                continue  # Cet employé est déjà en PM ce vendredi

            # Calculer score : priorité de qualification (plus bas = meilleur)
            priority_score = int(qualification[0].priority)
            candidates.append((emp, priority_score))

        if not candidates:
            return None

        # Trier et prendre le meilleur
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    # ============================================================================
    # Vérification et correction des doublons
    # ============================================================================

    def _check_and_fix_duplicate_assignments(
        self, assignments, week_start, rotation_state, replacements_log
    ):
        """Vérifie et corrige les doublons où un employé est assigné plusieurs fois le même jour

        Règle : Un employé ne peut faire qu'UNE seule permanence par jour.
        Si un doublon est détecté, on trouve un remplaçant pour les affectations en doublon.
        """
        try:
            # Grouper les affectations par jour et par employé
            assignments_by_day_employee = {}
            for assignment in assignments:
                day = assignment.day
                emp_id = assignment.employee_id.id
                key = (day, emp_id)
                if key not in assignments_by_day_employee:
                    assignments_by_day_employee[key] = []
                assignments_by_day_employee[key].append(assignment)

            # Trouver les doublons (un employé assigné plusieurs fois le même jour)
            for (day, emp_id), day_assignments in assignments_by_day_employee.items():
                if len(day_assignments) > 1:
                    # Doublon détecté : cet employé est assigné plusieurs fois ce jour-là
                    # Garder la première affectation, trouver un remplaçant pour les autres
                    kept_assignment = day_assignments[0]
                    duplicate_assignments = day_assignments[1:]

                    for duplicate in duplicate_assignments:
                        # Calculer la date
                        day_index = [
                            "monday",
                            "tuesday",
                            "wednesday",
                            "thursday",
                            "friday",
                        ].index(day)
                        target_date = week_start + timedelta(days=day_index)

                        # Trouver un remplaçant
                        replacement = self._find_replacement_for_duplicate(
                            duplicate, target_date, rotation_state, kept_assignment
                        )

                        if replacement:
                            old_employee_name = duplicate.employee_id.name
                            duplicate.with_context(skip_tracking=True).write({"employee_id": replacement.id})
                            replacements_log.append(
                                f"🔄 Doublon corrigé {day}: {old_employee_name} (déjà assigné) → {replacement.name} "
                                f"({duplicate.site_id.code} {duplicate.permanence_type_id.name} {duplicate.period})"
                            )
                        else:
                            # Aucun remplaçant trouvé, on supprime l'affectation en doublon
                            old_employee_name = duplicate.employee_id.name
                            duplicate.with_context(skip_tracking=True).unlink()
                            replacements_log.append(
                                f"⚠️ Doublon supprimé {day}: {old_employee_name} déjà assigné ce jour-là, "
                                f"aucun remplaçant trouvé pour {duplicate.site_id.code} {duplicate.permanence_type_id.name} {duplicate.period}"
                            )
        except Exception as e:
            # Logger l'erreur mais ne pas bloquer la génération
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(
                f"Erreur dans _check_and_fix_duplicate_assignments: {e}", exc_info=True
            )

    def _find_replacement_for_duplicate(
        self, duplicate_assignment, target_date, rotation_state, kept_assignment
    ):
        """Trouve un remplaçant pour une affectation en doublon

        Exclut l'employé déjà assigné (kept_assignment) et l'employé en doublon.
        """
        site = duplicate_assignment.site_id
        permanence_type = duplicate_assignment.permanence_type_id
        employees = rotation_state.get("employees", self._get_available_employees())

        # Exclure l'employé déjà assigné ce jour-là (kept_assignment)
        kept_employee_id = kept_assignment.employee_id.id

        candidates = []
        for emp in employees:
            # Ne pas prendre l'employé déjà assigné ce jour-là
            if emp.id == kept_employee_id:
                continue

            # Vérifier disponibilité
            if not self._is_employee_available(emp, target_date):
                continue

            # Vérifier qualification
            qualification = emp.qualification_ids.filtered(
                lambda q: q.permanence_type_id.id == permanence_type.id
                and q.site_id.id == site.id
            )
            if not qualification:
                continue

            # Vérifier que l'employé n'est pas déjà assigné ce jour-là
            existing = self.env["chc_cds_planning.planning_assignment"].search(
                [
                    ("planning_week_id", "=", duplicate_assignment.planning_week_id.id),
                    ("day", "=", duplicate_assignment.day),
                    ("employee_id", "=", emp.id),
                ],
                limit=1,
            )

            if existing:
                continue  # Cet employé est déjà assigné ce jour-là

            # Calculer score : priorité de qualification (plus bas = meilleur)
            priority_score = int(qualification[0].priority)
            candidates.append((emp, priority_score))

        if not candidates:
            return None

        # Trier et prendre le meilleur
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    # ============================================================================
    # Méthodes utilitaires
    # ============================================================================

    def _get_weeks_in_month(self):
        month_start = date(self.year, int(self.month), 1)

        # Calculer le dernier jour du mois
        if int(self.month) == 12:
            month_end = date(self.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(self.year, int(self.month) + 1, 1) - timedelta(days=1)

        # Pour éviter les chevauchements entre mois, on ne génère que les semaines
        # dont le lundi (start_date) est DANS le mois sélectionné.
        #
        # Exemple : avril 2026 commence un mercredi (01/04). La semaine qui contient
        # les 01-03/04 démarre le lundi 30/03 : elle appartient donc au mois de mars
        # (car start_date=30/03). Avril commencera au lundi 06/04.
        days_until_monday = (7 - month_start.weekday()) % 7
        first_monday = month_start + timedelta(days=days_until_monday)

        weeks = []
        current_monday = first_monday

        # Parcourir toutes les semaines dont le lundi est dans le mois
        while current_monday <= month_end:
            weeks.append(current_monday)
            current_monday += timedelta(days=7)

            # Sécurité : éviter les boucles infinies
            if len(weeks) > 10:
                break

        return weeks

    def _check_existing_plannings(self, weeks):
        return self.env["chc_cds_planning.planning_weekly"].search(
            [("start_date", "in", weeks)]
        )

    def _get_available_employees(self):
        return self.env["hr.employee"].search(
            [("active", "=", True), ("qualification_ids", "!=", False)]
        )

    def _is_employee_available(self, employee, target_date):
        # Vérifier les jours fériés publics
        from ..utils.utils import is_public_holiday
        
        calendar_id = None
        if hasattr(employee, 'resource_calendar_id') and employee.resource_calendar_id:
            calendar_id = employee.resource_calendar_id.id
        
        if is_public_holiday(self.env, target_date, calendar_id):
            return False

        # Vérifier les congés approuvés
        leaves = self.env["hr.leave"].search(
            [
                ("employee_id", "=", employee.id),
                ("date_from", "<=", target_date),
                ("date_to", ">=", target_date),
                ("state", "=", "validate"),
            ]
        )

        if leaves:
            return False

        # Vérifier les contraintes d'indisponibilité
        day_index = target_date.weekday()
        unavailabilities = self.env["chc_cds_planning.employee_unavailability"].search(
            [
                ("employee_id", "=", employee.id),
                ("day_of_week", "=", str(day_index)),
            ]
        )

        return not unavailabilities

    def _get_month_name(self):
        months = {
            "1": "Janvier",
            "2": "Février",
            "3": "Mars",
            "4": "Avril",
            "5": "Mai",
            "6": "Juin",
            "7": "Juillet",
            "8": "Août",
            "9": "Septembre",
            "10": "Octobre",
            "11": "Novembre",
            "12": "Décembre",
        }
        return months.get(self.month, "Mois inconnu")

    def _show_notification(self, title, message, type_):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": type_,
                "sticky": type_ == "error",
            },
        }
