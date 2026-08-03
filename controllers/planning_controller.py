import logging
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class PlanningController(http.Controller):
    MAX_BATCH_DOWNLOAD_IDS = 50
    AUTO_REFRESH_ALLOWED_LOGIN_PARAM = (
        "chc_cds_planning.idle_autorefresh_allowed_login"
    )

    def _json_internal_error(self):
        """Retour JSON générique pour éviter l'exposition d'erreurs techniques."""
        return {"success": False, "error": "Erreur interne du serveur."}

    def _get_idle_autorefresh_allowed_login(self):
        """Retourne le login autorisé à l'auto-refresh TV (config système)."""
        return (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param(self.AUTO_REFRESH_ALLOWED_LOGIN_PARAM, default="")
            .strip()
            .lower()
        )

    def _can_use_idle_autorefresh(self):
        """Vérifie si l'utilisateur courant est autorisé au mode auto-refresh."""
        allowed_login = self._get_idle_autorefresh_allowed_login()
        current_login = (request.env.user.login or "").strip().lower()
        return bool(allowed_login and current_login == allowed_login)

    def _can_read_planning(self, planning):
        """Vérifie qu'un planning est accessible en lecture par l'utilisateur courant."""
        try:
            planning.check_access_rights("read")
            planning.check_access_rule("read")
            return True
        except AccessError:
            return False

    def _get_readable_plannings(self, planning_ids):
        """Retourne les plannings lisibles correspondant exactement aux IDs demandés."""
        if not planning_ids:
            return request.env["chc_cds_planning.planning_weekly"]
        plannings = request.env["chc_cds_planning.planning_weekly"].search(
            [("id", "in", planning_ids)]
        )
        if len(plannings) != len(planning_ids):
            return request.env["chc_cds_planning.planning_weekly"]
        return plannings

    def _is_valid_export_attachment(self, attachment):
        """Valide qu'une pièce jointe est un PDF de planning exportable."""
        if not attachment or not attachment.exists():
            return False
        return (
            attachment.res_model == "chc_cds_planning.planning_weekly"
            and bool(attachment.res_id)
            and attachment.mimetype == "application/pdf"
        )

    def _parse_batch_ids(self, ids_raw):
        """Parse et valide la liste d'IDs transmise en querystring."""
        if not ids_raw:
            return []

        parsed = []
        seen = set()
        for raw in str(ids_raw).split(","):
            value = (raw or "").strip()
            if not value:
                continue
            if not value.isdigit():
                return []
            int_value = int(value)
            if int_value <= 0:
                return []
            if int_value in seen:
                continue
            seen.add(int_value)
            parsed.append(int_value)

        if len(parsed) > self.MAX_BATCH_DOWNLOAD_IDS:
            return []
        return parsed

    @http.route("/web/planning/<int:planning_id>", type="http", auth="user")
    def visual_planning(self, planning_id, **kwargs):
        """Affichage de la vue visuelle du planning"""
        try:
            # En mode normal, on redirige vers une action webclient (navbar Odoo).
            # En mode embarqué (iframe), on rend le template standalone.
            if not kwargs.get("embedded"):
                try:
                    action = request.env.ref(
                        "chc_cds_planning.action_chc_cds_planning_visual_planning"
                    )
                    if action:
                        return request.redirect(
                            f"/web#action={action.id}&planning_id={planning_id}"
                        )
                except Exception:
                    # Si l'action n'est pas trouvée / pas encore chargée, on continue en rendu direct.
                    pass

            planning = request.env["chc_cds_planning.planning_weekly"].browse(
                planning_id
            )
            if not planning.exists():
                return request.not_found()

            # Navigation
            prev_planning = request.env["chc_cds_planning.planning_weekly"].search(
                [("id", "<", planning_id)], order="id desc", limit=1
            )
            next_planning = request.env["chc_cds_planning.planning_weekly"].search(
                [("id", ">", planning_id)], order="id asc", limit=1
            )

            # Action de retour
            try:
                action_ref = request.env.ref(
                    "chc_cds_planning.action_chc_cds_planning_planning_weekly"
                )
                back_action_id = action_ref.id if action_ref else None
            except ValueError:
                # La référence d'action n'existe pas dans la base de données
                _logger.warning(
                    "Action 'chc_cds_planning.action_chc_cds_planning_planning_weekly' not found"
                )
                back_action_id = None

            data = self._prepare_planning_data(planning)
            is_export = kwargs.get("export") == "pdf"
            is_embedded = bool(kwargs.get("embedded"))
            data.update(
                {
                    "current_planning_id": planning_id,
                    "prev_planning_id": prev_planning.id if prev_planning else None,
                    "next_planning_id": next_planning.id if next_planning else None,
                    "has_prev": bool(prev_planning) and not is_export,
                    "has_next": bool(next_planning) and not is_export,
                    "back_action_id": back_action_id,
                    "planning_state": planning.state,
                    "is_export": is_export,  # Flag pour indiquer que c'est un export
                    "is_embedded": is_embedded,
                    "user_login": request.env.user.login,  # Email de l'utilisateur connecté
                    "can_idle_auto_refresh": self._can_use_idle_autorefresh(),
                }
            )

            return request.render("chc_cds_planning.visual_planning_template", data)

        except Exception as e:
            _logger.error(f"Erreur dans visual_planning: {e}")
            return request.render(
                "web.http_error",
                {
                    "status_code": 500,
                    "status_message": "Erreur interne du serveur",
                    "error_message": str(e),
                },
            )

    @http.route(
        "/planning/get_current_week_planning",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def get_current_week_planning(self, **kwargs):
        """Retourne l'ID du planning de la semaine actuelle (lundi de la semaine en cours)"""
        try:
            # Calculer le lundi de la semaine actuelle
            today = datetime.now().date()
            days_since_monday = today.weekday()  # 0 = lundi, 6 = dimanche
            current_week_monday = today - timedelta(days=days_since_monday)

            # Chercher le planning pour cette semaine
            planning = request.env["chc_cds_planning.planning_weekly"].search(
                [("start_date", "=", current_week_monday)], limit=1
            )

            if planning:
                return {
                    "success": True,
                    "planning_id": planning.id,
                    "current_week_monday": current_week_monday.strftime("%Y-%m-%d"),
                }
            else:
                return {
                    "success": False,
                    "error": "Aucun planning trouvé pour la semaine actuelle",
                    "current_week_monday": current_week_monday.strftime("%Y-%m-%d"),
                }
        except Exception as e:
            _logger.error(f"Erreur dans get_current_week_planning: {e}", exc_info=True)
            return self._json_internal_error()

    @http.route(
        "/planning/update_assignment", type="json", auth="user", methods=["POST"]
    )
    def update_assignment(self, **kwargs):
        """Mettre à jour les affectations suite au drag & drop"""
        try:
            operation = kwargs.get("operation")
            planning_id = kwargs.get("planning_id")
            source = kwargs.get("source", {})
            target = kwargs.get("target", {})

            if not operation or not planning_id or not source or not target:
                return {"success": False, "error": "Données manquantes"}

            planning = request.env["chc_cds_planning.planning_weekly"].browse(
                planning_id
            )
            if not planning.exists():
                return {"success": False, "error": "Planning non trouvé"}

            # Vérifier que le planning est en mode brouillon
            if planning.state != "draft":
                return {
                    "success": False,
                    "error": "Les modifications ne sont autorisées qu'en mode brouillon. Le planning est publié ou confirmé.",
                }

            if operation == "swap":
                return self._handle_swap_simple(planning, source, target)
            elif operation == "move":
                return self._handle_move_simple(planning, source, target)
            else:
                return {
                    "success": False,
                    "error": f"Opération '{operation}' non supportée",
                }

        except Exception as e:
            _logger.error(f"Erreur dans update_assignment: {e}", exc_info=True)
            return self._json_internal_error()

    # ===============================
    # NOUVELLES ROUTES POUR LE MENU CONTEXTUEL
    # ===============================

    @http.route(
        "/planning/get_employee_suggestions", type="json", auth="user", methods=["POST"]
    )
    def get_employee_suggestions(self, **kwargs):
        """Obtenir les suggestions d'employés pour le menu contextuel"""
        try:
            action = kwargs.get("action")
            planning_id = kwargs.get("planning_id")
            position = kwargs.get("position", {})

            if not action or not planning_id:
                return {"success": False, "error": "Paramètres manquants"}

            planning = request.env["chc_cds_planning.planning_weekly"].browse(
                planning_id
            )
            if not planning.exists():
                return {"success": False, "error": "Planning non trouvé"}

            if action == "get_available_employees":
                return self._get_available_employees_for_position(planning, position)
            elif action == "get_replacement_suggestions":
                assignment_id = kwargs.get("assignment_id")
                return self._get_replacement_suggestions(
                    planning, assignment_id, position
                )
            else:
                return {"success": False, "error": f"Action '{action}' non supportée"}

        except Exception as e:
            _logger.error(f"Erreur dans get_employee_suggestions: {e}", exc_info=True)
            return self._json_internal_error()

    @http.route(
        "/planning/context_menu_action", type="json", auth="user", methods=["POST"]
    )
    def context_menu_action(self, **kwargs):
        """Exécuter une action depuis le menu contextuel"""
        try:
            action = kwargs.get("action")
            planning_id = kwargs.get("planning_id")

            if not action or not planning_id:
                return {"success": False, "error": "Paramètres manquants"}

            planning = request.env["chc_cds_planning.planning_weekly"].browse(
                planning_id
            )
            if not planning.exists():
                return {"success": False, "error": "Planning non trouvé"}

            # Vérifier que le planning est en mode brouillon
            if planning.state != "draft":
                return {
                    "success": False,
                    "error": "Les modifications ne sont autorisées qu'en mode brouillon. Le planning est publié ou confirmé.",
                }

            if action == "assign_employee":
                return self._assign_employee_to_position(planning, kwargs)
            elif action == "replace_employee":
                return self._replace_employee_in_assignment(planning, kwargs)
            elif action == "remove_assignment":
                return self._remove_assignment(planning, kwargs)
            else:
                return {"success": False, "error": f"Action '{action}' non supportée"}

        except Exception as e:
            _logger.error(f"Erreur dans context_menu_action: {e}", exc_info=True)
            return self._json_internal_error()

    # ===============================
    # MÉTHODES EXISTANTES (DRAG & DROP)
    # ===============================

    def _handle_swap_simple(self, planning, source, target):
        """Échange simple et direct entre deux affectations avec validation renforcée"""
        try:
            # Validation des données d'entrée
            if not source or not target:
                return {
                    "success": False,
                    "error": "Données source ou target manquantes",
                }

            # Récupérer les IDs des affectations depuis les données visuelles
            source_assignment_id = source.get("assignment_id")
            target_assignment_id = target.get("assignment_id")

            if not source_assignment_id or not target_assignment_id:
                return {"success": False, "error": "IDs d'affectation manquants"}

            # Validation des IDs (doivent être des nombres)
            try:
                source_assignment_id = int(source_assignment_id)
                target_assignment_id = int(target_assignment_id)
            except (ValueError, TypeError):
                return {"success": False, "error": "IDs d'affectation invalides"}

            # Vérifier que ce ne sont pas les mêmes affectations
            if source_assignment_id == target_assignment_id:
                return {
                    "success": False,
                    "error": "Impossible d'échanger une affectation avec elle-même",
                }

            # Tous les assignments sont maintenant dans planning_assignment
            source_model = "chc_cds_planning.planning_assignment"
            target_model = "chc_cds_planning.planning_assignment"

            # Récupérer les affectations directement par ID avec vérification d'existence
            source_assignment = request.env[source_model].browse(source_assignment_id)
            target_assignment = request.env[target_model].browse(target_assignment_id)

            if not source_assignment.exists():
                return {
                    "success": False,
                    "error": f"Affectation source {source_assignment_id} non trouvée",
                }

            if not target_assignment.exists():
                return {
                    "success": False,
                    "error": f"Affectation cible {target_assignment_id} non trouvée",
                }

            # Vérifier qu'elles appartiennent au bon planning
            if source_assignment.planning_week_id.id != planning.id:
                return {
                    "success": False,
                    "error": f"L'affectation source n'appartient pas au planning {planning.id}",
                }

            if target_assignment.planning_week_id.id != planning.id:
                return {
                    "success": False,
                    "error": f"L'affectation cible n'appartient pas au planning {planning.id}",
                }

            # Vérifier que les employés existent
            if not source_assignment.employee_id:
                return {
                    "success": False,
                    "error": "L'affectation source n'a pas d'employé assigné",
                }

            if not target_assignment.employee_id:
                return {
                    "success": False,
                    "error": "L'affectation cible n'a pas d'employé assigné",
                }

            # Échange simple : swap des employés avec gestion transactionnelle
            source_employee = source_assignment.employee_id
            target_employee = target_assignment.employee_id

            # Utiliser write avec un seul appel pour garantir l'atomicité
            source_assignment.write({"employee_id": target_employee.id})
            target_assignment.write({"employee_id": source_employee.id})

            # Vérifier que l'échange a bien été effectué
            source_assignment.invalidate_recordset()
            target_assignment.invalidate_recordset()

            if source_assignment.employee_id.id != target_employee.id:
                return {
                    "success": False,
                    "error": "Échec de l'échange - vérification échouée",
                }

            return {
                "success": True,
                "message": f"Échangé {source_employee.name} ↔ {target_employee.name}",
            }

        except ValueError as e:
            _logger.error(f"Erreur de validation dans swap: {e}", exc_info=True)
            return {"success": False, "error": "Erreur de validation."}
        except Exception as e:
            _logger.error(f"Erreur swap simple: {e}", exc_info=True)
            return {"success": False, "error": "Erreur lors de l'échange."}

    def _handle_move_simple(self, planning, source, target):
        """Déplacement simple vers une cellule vide avec validation renforcée"""
        try:
            # Validation des données d'entrée
            if not source:
                return {"success": False, "error": "Données source manquantes"}

            if not target:
                return {"success": False, "error": "Données cible manquantes"}

            source_assignment_id = source.get("assignment_id")
            source_is_special = source.get("is_special", False)
            target_is_special = target.get("is_special", False)

            if not source_assignment_id:
                return {"success": False, "error": "ID d'affectation source manquant"}

            # Validation de l'ID
            try:
                source_assignment_id = int(source_assignment_id)
            except (ValueError, TypeError):
                return {"success": False, "error": "ID d'affectation source invalide"}

            # Tous les assignments sont maintenant dans planning_assignment
            source_model = "chc_cds_planning.planning_assignment"

            source_assignment = request.env[source_model].browse(source_assignment_id)
            if not source_assignment.exists():
                return {
                    "success": False,
                    "error": f"Affectation source {source_assignment_id} non trouvée",
                }

            # Vérifier que l'affectation appartient au bon planning
            if source_assignment.planning_week_id.id != planning.id:
                return {
                    "success": False,
                    "error": f"L'affectation source n'appartient pas au planning {planning.id}",
                }

            # Vérifier que l'employé existe
            if not source_assignment.employee_id:
                return {
                    "success": False,
                    "error": "L'affectation source n'a pas d'employé assigné",
                }

            # Si on déplace vers une perm spéciale, on doit créer une nouvelle perm spéciale
            if target_is_special:
                # Sauvegarder le nom de l'employé avant de supprimer l'enregistrement
                employee_name = source_assignment.employee_id.name
                employee_id = source_assignment.employee_id.id

                # Récupérer le nom de la perm spéciale depuis la position
                # (on peut le déterminer depuis le site_name qui contient le nom de la perm spéciale)
                perm_name = target.get("site_name", "Permanence spéciale")
                target_day = self._get_day_name(target.get("day_index", 0))
                target_period = target.get("period", "am")

                # Si c'est une perm spéciale source et qu'on déplace dans la même perm spéciale (même nom, même jour)
                # juste changer la période
                if (
                    source_is_special
                    and source_assignment.special_name == perm_name
                    and source_assignment.day == target_day
                ):
                    source_assignment.period = target_period
                    return {
                        "success": True,
                        "message": f"Période modifiée pour {employee_name}",
                    }

                # Si on déplace depuis une perm régulière, supprimer d'abord la perm régulière
                # pour éviter le conflit avec la contrainte _check_no_conflict_with_regular_planning
                if not source_is_special:
                    source_assignment.unlink()

                # Récupérer le site MLE et le type TCH par défaut
                mle_site = self._find_site_by_code("MLE")
                tch_type = request.env["chc_cds_planning.permanence_type"].search(
                    [("code", "=", "TCH")], limit=1
                )

                # Vérifier si une perm spéciale existe déjà à cette position pour cet employé
                existing_special = request.env[
                    "chc_cds_planning.planning_assignment"
                ].search(
                    [
                        ("planning_week_id", "=", planning.id),
                        ("special_name", "=", perm_name),
                        ("day", "=", target_day),
                        ("employee_id", "=", employee_id),
                    ],
                    limit=1,
                )

                if existing_special:
                    # Mettre à jour la période si nécessaire
                    if existing_special.period != target_period:
                        existing_special.period = target_period
                else:
                    # Vérifier si une perm spéciale existe déjà à cette position (même nom, jour, période)
                    # mais avec un autre employé - dans ce cas, on la met à jour
                    existing_special_same_pos = request.env[
                        "chc_cds_planning.planning_assignment"
                    ].search(
                        [
                            ("planning_week_id", "=", planning.id),
                            ("special_name", "=", perm_name),
                            ("day", "=", target_day),
                            ("period", "=", target_period),
                        ],
                        limit=1,
                    )

                    if existing_special_same_pos:
                        # Mettre à jour l'employé existant
                        existing_special_same_pos.employee_id = employee_id
                    else:
                        # Calculer start_time et end_time pour la perm spéciale
                        assignment_model = request.env["chc_cds_planning.planning_assignment"]
                        permanence_type_code = "TCH" if tch_type else None
                        start_time, end_time = assignment_model._calculate_times(
                            target_period, permanence_type_code
                        )
                        # Créer une nouvelle perm spéciale
                        request.env["chc_cds_planning.planning_assignment"].create(
                            {
                                "planning_week_id": planning.id,
                                "special_name": perm_name,
                                "day": target_day,
                                "period": target_period,
                                "employee_id": employee_id,
                                "site_id": mle_site.id if mle_site else False,
                                "permanence_type_id": (
                                    tch_type.id if tch_type else False
                                ),
                                "start_time": start_time,
                                "end_time": end_time,
                            }
                        )

                # Si c'était une perm spéciale source (et qu'on n'a pas juste changé la période), la supprimer maintenant
                if source_is_special and (
                    source_assignment.special_name != perm_name
                    or source_assignment.day != target_day
                ):
                    source_assignment.unlink()

                return {
                    "success": True,
                    "message": f"Déplacé {employee_name} vers permanence spéciale",
                }
            else:
                # Déplacement vers une perm régulière
                # Déterminer la nouvelle position
                new_day = self._get_day_name(target.get("day_index", 0))
                new_period = target.get("period", "am")

                # Sauvegarder le nom de l'employé avant de modifier/supprimer
                employee_name = source_assignment.employee_id.name

                # Vérifier si c'est le même jour et le même site (juste changement de période)
                same_day = source_assignment.day == new_day
                same_site = (
                    source_assignment.site_id
                    and source_assignment.site_id.code == target.get("site_code", "")
                )

                # Si c'est le même jour et le même site, juste changer la période
                if same_day and same_site and not source_is_special:
                    source_assignment.period = new_period
                    return {
                        "success": True,
                        "message": f"Période modifiée pour {employee_name}",
                    }

                # Sinon, déterminer le site et le type depuis la cellule cible
                target_site_code = target.get("site_code", "").upper()
                new_site = self._find_site_by_code(target_site_code)
                new_permanence_type = self._determine_permanence_type(target)

                # Si le site n'est pas trouvé, essayer de le trouver depuis le nom
                if not new_site and target.get("site_name"):
                    site_name = target.get("site_name", "").upper()
                    # Chercher directement par code dans le nom
                    if "HRM" in site_name:
                        new_site = self._find_site_by_code("HRM")
                    elif "HEU" in site_name:
                        new_site = self._find_site_by_code("HEU")
                    elif "WAR" in site_name:
                        new_site = self._find_site_by_code("WAR")
                    elif (
                        "MLE" in site_name
                        or "MONT LÉGIA" in site_name
                        or "MONT LEGIA" in site_name
                    ):
                        new_site = self._find_site_by_code("MLE")

                # Si le site ou le type ne sont toujours pas trouvés, utiliser ceux de l'affectation source
                # MAIS seulement si c'est le même site (pour éviter de changer le site par erreur)
                if not new_site:
                    # Si le site source correspond au code cible, utiliser le site source
                    if (
                        source_assignment.site_id
                        and source_assignment.site_id.code.upper() == target_site_code
                    ):
                        new_site = source_assignment.site_id
                    else:
                        # Sinon, essayer de trouver le site depuis le code cible une dernière fois
                        new_site = self._find_site_by_code(target_site_code)
                        if not new_site:
                            new_site = source_assignment.site_id

                # Pour le type de permanence, si on n'a pas trouvé mais qu'on a un site HRM/HEU/WAR, forcer TCH
                if not new_permanence_type:
                    if new_site and new_site.code in ["HRM", "HEU", "WAR"]:
                        new_permanence_type = request.env[
                            "chc_cds_planning.permanence_type"
                        ].search([("code", "=", "TCH")], limit=1)
                    else:
                        new_permanence_type = source_assignment.permanence_type_id

                if not new_site or not new_permanence_type:
                    return {
                        "success": False,
                        "error": f"Site ou type de permanence non trouvé (site_code: {target_site_code}, site_name: {target.get('site_name', 'N/A')})",
                    }

                # Si c'est une perm spéciale, on doit créer une perm régulière
                if source_is_special:
                    # Calculer start_time et end_time pour la nouvelle affectation
                    assignment_model = request.env["chc_cds_planning.planning_assignment"]
                    permanence_type_code = (
                        new_permanence_type.code if new_permanence_type else None
                    )
                    start_time, end_time = assignment_model._calculate_times(
                        new_period, permanence_type_code
                    )
                    # Créer une nouvelle affectation régulière
                    request.env["chc_cds_planning.planning_assignment"].create(
                        {
                            "planning_week_id": planning.id,
                            "employee_id": source_assignment.employee_id.id,
                            "day": new_day,
                            "period": new_period,
                            "site_id": new_site.id,
                            "permanence_type_id": new_permanence_type.id,
                            "start_time": start_time,
                            "end_time": end_time,
                        }
                    )
                    # Supprimer l'ancienne perm spéciale
                    source_assignment.unlink()
                else:
                    # Modifier l'affectation existante
                    source_assignment.write(
                        {
                            "day": new_day,
                            "period": new_period,
                            "site_id": new_site.id,
                            "permanence_type_id": new_permanence_type.id,
                        }
                    )

                return {
                    "success": True,
                    "message": f"Déplacé {employee_name}",
                }

        except Exception as e:
            _logger.error(f"Erreur move simple: {e}", exc_info=True)
            return {"success": False, "error": "Erreur lors du déplacement."}

    # ===============================
    # NOUVELLES MÉTHODES POUR LE MENU CONTEXTUEL
    # ===============================

    def _get_available_employees_for_position(self, planning, position):
        """Trouve les employés disponibles pour une position donnée"""
        try:
            # Déterminer le site et le type de permanence
            site, permanence_type = self._resolve_position_requirements(position)

            if not site or not permanence_type:
                return {
                    "success": False,
                    "error": "Site ou type de permanence non trouvé",
                }

            # Calculer la date cible
            target_date = self._get_target_date(planning, position.get("day_index", 0))

            # Récupérer tous les employés qualifiés
            qualified_employees = self._get_qualified_employees(site, permanence_type)

            # Filtrer par disponibilité et conflits
            # Optimisation : récupérer toutes les affectations du planning une seule fois
            # Les perms spéciales sont maintenant dans planning_assignment avec special_name
            all_assignments = request.env[
                "chc_cds_planning.planning_assignment"
            ].search([("planning_week_id", "=", planning.id)])

            # Créer un dictionnaire pour accéder rapidement aux affectations par employé
            assignments_by_employee = {}
            for assignment in all_assignments:
                emp_id = assignment.employee_id.id
                if emp_id not in assignments_by_employee:
                    assignments_by_employee[emp_id] = []
                assignments_by_employee[emp_id].append(assignment)

            suggestions = []
            for emp in qualified_employees:
                if not self._is_employee_available(emp, target_date):
                    continue

                if self._has_conflict_on_day(emp, planning, position):
                    continue

                # Récupérer les informations de qualification
                qualification = emp.qualification_ids.filtered(
                    lambda q: q.permanence_type_id.id == permanence_type.id
                    and q.site_id.id == site.id
                )

                if qualification:
                    # Utiliser les affectations déjà chargées
                    emp_assignments = assignments_by_employee.get(emp.id, [])
                    assignment_count = len(emp_assignments)

                    # Calculer workload_info directement depuis les affectations déjà chargées
                    workload_parts = []
                    if assignment_count > 0:
                        workload_parts.append(
                            f"{assignment_count} affectation{'s' if assignment_count > 1 else ''}"
                        )
                    workload_info = (
                        ", ".join(workload_parts) if workload_parts else "Disponible"
                    )

                    suggestions.append(
                        {
                            "id": emp.id,
                            "name": emp.name,
                            "code": emp.employee_code or emp.name[:5].upper(),
                            "color": (
                                int(emp.color)
                                if emp.color and emp.color.isdigit()
                                else 0
                            ),
                            "qualification_priority": qualification[0].priority,
                            "assignment_count": assignment_count,  # Pour le tri
                            "workload_info": {"text": workload_info},
                        }
                    )

            # Trier par priorité de qualification puis par charge de travail (moins d'affectations = meilleur)
            suggestions.sort(
                key=lambda x: (int(x["qualification_priority"]), x["assignment_count"])
            )

            return {
                "success": True,
                "employees": suggestions[:8],  # Limiter à 8 suggestions
            }

        except Exception as e:
            _logger.error(f"Erreur dans _get_available_employees_for_position: {e}")
            return {"success": False, "error": "Erreur interne du serveur."}

    def _get_replacement_suggestions(self, planning, assignment_id, position):
        """Trouve les employés de remplacement pour une affectation existante"""
        try:
            # Tous les assignments sont maintenant dans planning_assignment
            current_assignment = request.env[
                "chc_cds_planning.planning_assignment"
            ].browse(assignment_id)
            if not current_assignment.exists():
                return {"success": False, "error": "Affectation non trouvée"}

            # Détecter si c'est une perm spéciale
            is_special = current_assignment.special_name or position.get(
                "is_special", False
            )

            if is_special:
                # Pour les perms spéciales, utiliser TCH comme qualification
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "TCH")], limit=1)
                # Pour les perms spéciales, utiliser le site de l'assignment ou MLE par défaut
                site = current_assignment.site_id or request.env[
                    "chc_cds_planning.site"
                ].search([("code", "=", "MLE")], limit=1)
            else:
                site = current_assignment.site_id
                permanence_type = current_assignment.permanence_type_id

            # Utiliser les informations de l'affectation actuelle (DAANT) pour détecter les conflits
            # plutôt que de se fier au position qui pourrait être incorrect
            assignment_day = current_assignment.day
            assignment_period = current_assignment.period

            # Calculer le day_index à partir du jour de l'affectation
            days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
            day_index = days.index(assignment_day) if assignment_day in days else 0
            target_date = self._get_target_date(planning, day_index)

            # Récupérer tous les employés qualifiés sauf l'employé actuel
            qualified_employees = self._get_qualified_employees(site, permanence_type)
            qualified_employees = qualified_employees.filtered(
                lambda e: e.id != current_assignment.employee_id.id
            )

            # Optimisation : récupérer toutes les affectations du planning une seule fois
            all_assignments = request.env[
                "chc_cds_planning.planning_assignment"
            ].search([("planning_week_id", "=", planning.id)])

            # Créer un dictionnaire pour accéder rapidement aux affectations par employé
            assignments_by_employee = {}
            for assignment in all_assignments:
                emp_id = assignment.employee_id.id
                if emp_id not in assignments_by_employee:
                    assignments_by_employee[emp_id] = []
                assignments_by_employee[emp_id].append(assignment)

            # Récupérer tous les compteurs de rotation vendredi en une seule requête
            friday_counters = {}
            day_name = assignment_day  # Utiliser le jour de l'affectation actuelle
            period = assignment_period  # Utiliser la période de l'affectation actuelle
            is_friday_pm_mle = (
                day_name == "friday"
                and site.code == "MLE"
                and permanence_type.code in ["TCH", "FCT"]
                and (period or "").replace(" ", "").lower() == "pm"
            )

            if is_friday_pm_mle:
                counters = request.env[
                    "chc_cds_planning.friday_rotation_counter"
                ].search([])
                friday_counters = {c.employee_id.id: c.counter for c in counters}

            suggestions = []
            for emp in qualified_employees:
                if not self._is_employee_available(emp, target_date):
                    continue

                # Vérifier les conflits en utilisant les informations de l'affectation actuelle
                # plutôt que le position qui pourrait être incorrect
                emp_assignments = assignments_by_employee.get(emp.id, [])

                # Vérifier si l'employé a déjà une affectation le même jour que l'affectation à remplacer
                conflicts = [a for a in emp_assignments if a.day == assignment_day]
                if conflicts:
                    # L'employé est déjà assigné ce jour-là, on l'exclut
                    continue

                qualification = emp.qualification_ids.filtered(
                    lambda q: q.permanence_type_id.id == permanence_type.id
                    and q.site_id.id == site.id
                )

                if qualification:
                    # Utiliser les affectations déjà chargées
                    assignment_count = len(emp_assignments)

                    # Vérifier les limites min/max jours par semaine
                    current_days = len(set(a.day for a in emp_assignments))

                    # Exclure si l'employé a déjà atteint son maximum
                    max_days = emp.max_days_per_week or 5
                    if current_days >= max_days:
                        continue

                    # Calculer le score de rotation vendredi PM MLE si applicable
                    friday_rotation_score = 0
                    if is_friday_pm_mle:
                        # Exclure JUAPE de la rotation vendredi PM MLE
                        if emp.employee_code == "JUAPE":
                            continue
                        friday_rotation_score = friday_counters.get(emp.id, 0)

                    # Calculer workload_info directement depuis les affectations déjà chargées
                    workload_parts = []
                    if assignment_count > 0:
                        workload_parts.append(
                            f"{assignment_count} affectation{'s' if assignment_count > 1 else ''}"
                        )
                    workload_info = (
                        ", ".join(workload_parts) if workload_parts else "Disponible"
                    )

                    suggestions.append(
                        {
                            "id": emp.id,
                            "name": emp.name,
                            "code": emp.employee_code or emp.name[:5].upper(),
                            "color": (
                                int(emp.color)
                                if emp.color and emp.color.isdigit()
                                else 0
                            ),
                            "qualification_priority": qualification[0].priority,
                            "assignment_count": assignment_count,  # Pour le tri
                            "friday_rotation_score": friday_rotation_score,  # Pour le tri vendredi PM
                            "workload_info": {"text": workload_info},
                        }
                    )

            # Trier par priorité, puis rotation vendredi (si applicable), puis charge de travail
            suggestions.sort(
                key=lambda x: (
                    int(x["qualification_priority"]),
                    x.get(
                        "friday_rotation_score", 0
                    ),  # Moins de vendredis PM = meilleur
                    x["assignment_count"],  # Moins d'affectations = meilleur
                )
            )

            return {
                "success": True,
                "employees": suggestions[:6],  # Limiter à 6 suggestions
            }

        except Exception as e:
            _logger.error(f"Erreur dans _get_replacement_suggestions: {e}")
            return {"success": False, "error": "Erreur interne du serveur."}

    def _assign_employee_to_position(self, planning, params):
        """Assigne un employé à une position vide"""
        try:
            employee_id = params.get("employee_id")
            position = params.get("position", {})

            if not employee_id:
                return {"success": False, "error": "ID employé manquant"}

            employee = request.env["hr.employee"].browse(employee_id)
            if not employee.exists():
                return {"success": False, "error": "Employé non trouvé"}

            # Détecter si c'est une perm spéciale
            is_special = position.get("is_special", False)

            # Créer l'affectation
            day_name = self._get_day_name(position.get("day_index", 0))
            period = position.get("period", "am")

            if is_special:
                # Créer une perm spéciale
                perm_name = position.get("site_name", "Permanence spéciale")

                # Récupérer le site MLE et le type TCH par défaut
                mle_site = self._find_site_by_code("MLE")
                tch_type = request.env["chc_cds_planning.permanence_type"].search(
                    [("code", "=", "TCH")], limit=1
                )

                # Calculer start_time et end_time pour la perm spéciale
                assignment_model = request.env["chc_cds_planning.planning_assignment"]
                permanence_type_code = "TCH" if tch_type else None
                start_time, end_time = assignment_model._calculate_times(
                    period, permanence_type_code
                )

                assignment_data = {
                    "planning_week_id": planning.id,
                    "employee_id": employee.id,
                    "special_name": perm_name,
                    "day": day_name,
                    "period": period,
                    "site_id": mle_site.id if mle_site else False,
                    "permanence_type_id": tch_type.id if tch_type else False,
                    "start_time": start_time,
                    "end_time": end_time,
                }
                request.env["chc_cds_planning.planning_assignment"].create(
                    assignment_data
                )
            else:
                # Résoudre les exigences de la position
                site, permanence_type = self._resolve_position_requirements(position)
                if not site or not permanence_type:
                    return {"success": False, "error": "Position invalide"}

                # Calculer start_time et end_time pour l'affectation régulière
                assignment_model = request.env["chc_cds_planning.planning_assignment"]
                permanence_type_code = permanence_type.code if permanence_type else None
                start_time, end_time = assignment_model._calculate_times(
                    period, permanence_type_code
                )
                assignment_data = {
                    "planning_week_id": planning.id,
                    "employee_id": employee.id,
                    "site_id": site.id,
                    "permanence_type_id": permanence_type.id,
                    "day": day_name,
                    "period": period,
                    "start_time": start_time,
                    "end_time": end_time,
                    "notes": "",
                }
                request.env["chc_cds_planning.planning_assignment"].create(
                    assignment_data
                )

            return {"success": True, "message": f"{employee.name} affecté avec succès"}

        except Exception as e:
            _logger.error(f"Erreur dans _assign_employee_to_position: {e}")
            return {"success": False, "error": "Erreur lors de l'assignation."}

    def _replace_employee_in_assignment(self, planning, params):
        """Remplace un employé dans une affectation existante"""
        try:
            assignment_id = params.get("assignment_id")
            new_employee_id = params.get("new_employee_id")
            position = params.get("position", {})

            if not assignment_id or not new_employee_id:
                return {"success": False, "error": "Paramètres manquants"}

            # Tous les assignments sont maintenant dans planning_assignment
            assignment = request.env["chc_cds_planning.planning_assignment"].browse(
                assignment_id
            )

            if not assignment.exists():
                return {"success": False, "error": "Affectation non trouvée"}

            new_employee = request.env["hr.employee"].browse(new_employee_id)
            if not new_employee.exists():
                return {"success": False, "error": "Nouvel employé non trouvé"}

            old_employee_name = assignment.employee_id.name
            assignment.employee_id = new_employee.id

            return {
                "success": True,
                "message": f"{old_employee_name} remplacé par {new_employee.name}",
            }

        except Exception as e:
            _logger.error(f"Erreur dans _replace_employee_in_assignment: {e}")
            return {"success": False, "error": "Erreur lors du remplacement."}

    def _remove_assignment(self, planning, params):
        """Supprime une affectation"""
        try:
            assignment_id = params.get("assignment_id")

            if not assignment_id:
                return {"success": False, "error": "ID d'affectation manquant"}

            # Tous les assignments sont maintenant dans planning_assignment
            assignment = request.env["chc_cds_planning.planning_assignment"].browse(
                assignment_id
            )

            if not assignment.exists():
                return {"success": False, "error": "Affectation non trouvée"}

            # Vérifier que l'affectation appartient au bon planning
            if assignment.planning_week_id.id != planning.id:
                return {
                    "success": False,
                    "error": "L'affectation n'appartient pas à ce planning",
                }

            employee_name = assignment.employee_id.name
            assignment.unlink()

            return {
                "success": True,
                "message": f"Assignation de {employee_name} retirée avec succès",
            }

        except Exception as e:
            _logger.error(f"Erreur dans _remove_assignment: {e}")
            return {"success": False, "error": "Erreur lors de la suppression."}

    # ===============================
    # MÉTHODES UTILITAIRES
    # ===============================

    def _resolve_position_requirements(self, position):
        """Résout les exigences d'un poste (site et type de permanence)"""
        # Détecter si c'est une perm spéciale
        is_special = position.get("is_special", False)

        if is_special:
            # Pour les perms spéciales, utiliser TCH comme qualification
            permanence_type = request.env["chc_cds_planning.permanence_type"].search(
                [("code", "=", "TCH")], limit=1
            )
            # Pour les perms spéciales, on n'a pas de site spécifique, utiliser MLE par défaut
            site = request.env["chc_cds_planning.site"].search(
                [("code", "=", "MLE")], limit=1
            )
            return site, permanence_type

        site_code = position.get("site_code", "MLE")
        permanence_type_code = position.get("permanence_type")
        site_name = position.get("site_name", "").lower()

        # Trouver le site
        site = request.env["chc_cds_planning.site"].search(
            [("code", "=", site_code)], limit=1
        )

        # Déterminer le type de permanence
        if permanence_type_code:
            permanence_type = request.env["chc_cds_planning.permanence_type"].search(
                [("code", "=", permanence_type_code)], limit=1
            )
        else:
            # Déduction basée sur le site et le nom
            if site_code in ["HRM", "HEU", "WAR"]:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "TCH")], limit=1)
            elif site_code == "MLE":
                if "on site mle" in site_name.lower() or "atelier" in site_name.lower():
                    permanence_type = request.env[
                        "chc_cds_planning.permanence_type"
                    ].search([("code", "=", "ATL")], limit=1)
                elif "fonctionnelle" in site_name:
                    permanence_type = request.env[
                        "chc_cds_planning.permanence_type"
                    ].search([("code", "=", "FCT")], limit=1)
                elif "technique" in site_name:
                    permanence_type = request.env[
                        "chc_cds_planning.permanence_type"
                    ].search([("code", "=", "TCH")], limit=1)
                else:
                    permanence_type = request.env[
                        "chc_cds_planning.permanence_type"
                    ].search([("code", "=", "ATL")], limit=1)
            else:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([], limit=1)

        return site, permanence_type

    def _get_qualified_employees(self, site, permanence_type):
        """Récupère les employés qualifiés pour un site et type de permanence"""
        return request.env["hr.employee"].search(
            [
                ("active", "=", True),
                ("qualification_ids.site_id", "=", site.id),
                ("qualification_ids.permanence_type_id", "=", permanence_type.id),
            ]
        )

    def _get_target_date(self, planning, day_index):
        """Calcule la date cible basée sur le planning et l'index du jour"""
        if not planning.start_date:
            return None
        return planning.start_date + timedelta(days=day_index)

    def _is_employee_available(self, employee, target_date):
        """Vérifie si un employé est disponible à une date donnée"""
        if not target_date:
            return True

        # Vérifier les jours fériés publics
        from ..utils.utils import is_public_holiday
        
        calendar_id = None
        if hasattr(employee, 'resource_calendar_id') and employee.resource_calendar_id:
            calendar_id = employee.resource_calendar_id.id
        
        if is_public_holiday(request.env, target_date, calendar_id):
            return False

        # Vérifier les congés
        leaves = request.env["hr.leave"].search(
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
        unavailabilities = request.env[
            "chc_cds_planning.employee_unavailability"
        ].search(
            [("employee_id", "=", employee.id), ("day_of_week", "=", str(day_index))]
        )

        return not unavailabilities

    def _has_conflict_on_day(self, employee, planning, position):
        """Vérifie si l'employé a déjà une affectation conflictuelle ce jour-là

        Exclut les employés déjà assignés ce jour-là pour éviter de suggérer
        des remplacements inutiles (ex: un employé déjà assigné le mardi
        ne devrait pas être suggéré pour remplacer quelqu'un d'autre le mardi)
        """
        day_name = self._get_day_name(position.get("day_index", 0))
        period = position.get("period", "am")

        existing_assignments = request.env[
            "chc_cds_planning.planning_assignment"
        ].search(
            [
                ("planning_week_id", "=", planning.id),
                ("employee_id", "=", employee.id),
                ("day", "=", day_name),
            ]
        )

        if not existing_assignments:
            return False

        # Vérifier d'abord les chevauchements de périodes
        for assignment in existing_assignments:
            if self._periods_overlap(period, assignment.period):
                return True

        # Renforcement : exclure aussi les employés déjà assignés ce jour-là
        # même si les périodes ne se chevauchent pas exactement
        # Cela évite de suggérer des employés déjà occupés ce jour-là
        # (ex: un employé en PM ne devrait pas être suggéré pour remplacer quelqu'un en AM)
        return True

    def _periods_overlap(self, period1, period2):
        """Vérifie si deux périodes se chevauchent"""
        def norm(p):
            return (p or "").replace(" ", "").lower()

        p1 = norm(period1)
        p2 = norm(period2)

        if p1 == p2:
            return True

        if p1 == "full" or p2 == "full":
            return True

        return False

    def _get_employee_workload_info(self, employee, planning):
        """Calcule des informations sur la charge de travail de l'employé

        Optimisé pour faire une seule requête au lieu de deux.
        """
        try:
            # Récupérer toutes les affectations en une seule requête
            assignments = request.env["chc_cds_planning.planning_assignment"].search(
                [
                    ("planning_week_id", "=", planning.id),
                    ("employee_id", "=", employee.id),
                ]
            )

            assignment_count = len(assignments)

            workload_parts = []
            if assignment_count > 0:
                workload_parts.append(
                    f"{assignment_count} affectation{'s' if assignment_count > 1 else ''}"
                )

            return ", ".join(workload_parts) if workload_parts else "Disponible"

        except Exception as e:
            _logger.error(f"Erreur dans _get_employee_workload_info: {e}")
            return "Charge inconnue"

    def _find_site_by_code(self, site_code):
        """Trouver un site par son code"""
        if not site_code:
            return None
        return request.env["chc_cds_planning.site"].search(
            [("code", "=", site_code)], limit=1
        )

    def _determine_permanence_type(self, cell_data):
        """Déterminer le type de permanence basé sur les données de cellule"""
        site_code = cell_data.get("site_code", "").upper()
        site_name = cell_data.get("site_name", "").lower()

        # Pour les sites HRM, HEU, WAR, toujours utiliser TCH
        if site_code in ["HRM", "HEU", "WAR"]:
            permanence_type = request.env["chc_cds_planning.permanence_type"].search(
                [("code", "=", "TCH")], limit=1
            )
            if permanence_type:
                return permanence_type

        # Si le site_code n'est pas trouvé mais le nom contient HRM/HEU/WAR, utiliser TCH
        if not site_code or site_code == "MLE":
            if "on site hrm" in site_name or "hrm" in site_name:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "TCH")], limit=1)
                if permanence_type:
                    return permanence_type
            elif "on site heu" in site_name or "heu" in site_name:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "TCH")], limit=1)
                if permanence_type:
                    return permanence_type
            elif "on site war" in site_name or "war" in site_name:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "TCH")], limit=1)
                if permanence_type:
                    return permanence_type

        # Pour MLE, déterminer selon le type de permanence
        if site_code == "MLE":
            if "atelier" in site_name or "on site mle" in site_name:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "ATL")], limit=1)
                if permanence_type:
                    return permanence_type
            elif "fonctionnelle" in site_name:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "FCT")], limit=1)
                if permanence_type:
                    return permanence_type
            elif "technique" in site_name:
                permanence_type = request.env[
                    "chc_cds_planning.permanence_type"
                ].search([("code", "=", "TCH")], limit=1)
                if permanence_type:
                    return permanence_type

        # Par défaut, retourner TCH plutôt que le premier type trouvé (qui pourrait être "Autre")
        # Cela évite les problèmes avec les sites HRM/HEU/WAR
        default_type = request.env["chc_cds_planning.permanence_type"].search(
            [("code", "=", "TCH")], limit=1
        )
        if default_type:
            return default_type

        # En dernier recours, retourner le premier type trouvé
        return request.env["chc_cds_planning.permanence_type"].search([], limit=1)

    def _get_day_name(self, day_index):
        """Convertir l'index du jour en nom"""
        days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
        if 0 <= day_index < len(days):
            return days[day_index]
        return "monday"

    def _prepare_planning_data(self, planning):
        """Prépare les données pour l'affichage avec IDs d'affectation"""
        try:
            # S'assurer que le planning est accessible en lecture
            # On utilise sudo() pour la lecture uniquement afin de permettre à tous de voir le planning
            planning_sudo = planning.sudo()

            # Jours de la semaine
            days = []
            if planning_sudo.start_date:
                from ..utils.utils import is_public_holiday, get_public_holiday_emojis
                
                # Récupérer le calendrier par défaut pour vérifier les jours fériés
                default_calendar = request.env["resource.calendar"].search([
                    ("active", "=", True)
                ], limit=1, order="id asc")
                calendar_id = default_calendar.id if default_calendar else None
                
                day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
                for i, day_name in enumerate(day_names):
                    current_date = planning_sudo.start_date + timedelta(days=i)
                    is_holiday = is_public_holiday(request.env, current_date, calendar_id)
                    emojis = get_public_holiday_emojis(request.env, current_date, calendar_id) if is_holiday else []
                    days.append(
                        {
                            "index": i,
                            "name": day_name,
                            "date_formatted": current_date.strftime("%d/%m"),
                            "date": current_date,
                            "is_holiday": is_holiday,
                            "holiday_emojis": emojis,
                        }
                    )

            # Récupérer toutes les affectations
            # Utiliser sudo() pour la lecture uniquement afin de contourner les règles d'accès record-level
            # et permettre à tous les utilisateurs de voir le planning en lecture seule
            all_assignments = (
                request.env["chc_cds_planning.planning_assignment"]
                .sudo()
                .search([("planning_week_id", "=", planning_sudo.id)])
            )

            # Log pour débogage (à retirer en production si nécessaire)
            _logger.info(
                f"Planning {planning_sudo.id}: {len(all_assignments)} affectations trouvées pour l'utilisateur {request.env.user.name} (admin: {request.env.user.has_group('base.group_system')})"
            )

            if not all_assignments:
                return {"planning": planning_sudo, "days": days, "table_rows": []}

            table_rows = []

            # Sites isolés (HRM, HEU, WAR)
            for site_code in ["HRM", "HEU", "WAR"]:
                # Utiliser sudo() pour permettre l'accès en lecture aux sites
                site = (
                    request.env["chc_cds_planning.site"]
                    .sudo()
                    .search([("code", "=", site_code)], limit=1)
                )
                if not site:
                    continue

                row_data = {
                    "type": "site_header",
                    "site": {
                        "code": site.code,
                        "name": site.name,
                        "badge_class": f"badge-{site.code}",
                    },
                    "days_assignments": [],
                }

                for day_idx in range(5):
                    day_name = ["monday", "tuesday", "wednesday", "thursday", "friday"][
                        day_idx
                    ]
                    # Récupérer l'information is_holiday du jour correspondant
                    is_holiday = days[day_idx].get("is_holiday", False) if day_idx < len(days) else False

                    am_assignment = all_assignments.filtered(
                        lambda a: a.site_id.code == site_code
                        and a.day == day_name
                        and a.period in ["am", "full"]
                    )
                    pm_assignment = all_assignments.filtered(
                        lambda a: a.site_id.code == site_code
                        and a.day == day_name
                        and a.period == "pm"
                    )

                    am_data = self._prepare_employee_data(
                        am_assignment[0] if am_assignment else None
                    )
                    pm_data = self._prepare_employee_data(
                        pm_assignment[0] if pm_assignment else None
                    )

                    row_data["days_assignments"].append({
                        "am": am_data, 
                        "pm": pm_data,
                        "is_holiday": is_holiday
                    })

                if any(day["am"] or day["pm"] for day in row_data["days_assignments"]):
                    table_rows.append(row_data)

            # Site MLE - MLE On Site
            site_mle = (
                request.env["chc_cds_planning.site"]
                .sudo()
                .search([("code", "=", "MLE")], limit=1)
            )
            if site_mle:
                atelier_assignments = all_assignments.filtered(
                    lambda a: a.site_id.code == "MLE"
                    and a.permanence_type_id.code == "ATL"
                )

                if atelier_assignments:
                    # Organiser par jour et employé pour un affichage cohérent
                    atelier_data = {}

                    # Collecter toutes les affectations par jour
                    for day_idx in range(5):
                        day_name = [
                            "monday",
                            "tuesday",
                            "wednesday",
                            "thursday",
                            "friday",
                        ][day_idx]
                        day_assignments = atelier_assignments.filtered(
                            lambda a: a.day == day_name
                        )

                        # Trier par nom d'employé pour un ordre cohérent
                        sorted_assignments = day_assignments.sorted(
                            lambda a: a.employee_id.name
                        )
                        atelier_data[day_name] = sorted_assignments

                    # Déterminer le nombre maximum d'employés par jour
                    max_employees = (
                        max(len(atelier_data[day]) for day in atelier_data)
                        if atelier_data
                        else 0
                    )

                    # Créer les lignes d'affichage
                    for row_idx in range(max_employees):
                        row_data = {
                            "type": "atelier_employee",
                            "days_assignments": [],
                        }

                        for day_idx in range(5):
                            day_name = [
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                            ][day_idx]
                            # Récupérer l'information is_holiday du jour correspondant
                            is_holiday = days[day_idx].get("is_holiday", False) if day_idx < len(days) else False
                            
                            day_assignments = atelier_data[day_name]

                            # Prendre l'affectation à la position row_idx s'il y en a une
                            assignment = (
                                day_assignments[row_idx]
                                if row_idx < len(day_assignments)
                                else None
                            )
                            full_day_data = self._prepare_employee_data(assignment)

                            row_data["days_assignments"].append({
                                "full_day": full_day_data,
                                "is_holiday": is_holiday
                            })

                        # En-tête seulement sur la première ligne
                        if row_idx == 0:
                            row_data["show_atelier_header"] = True
                            row_data["atelier_rowspan"] = max_employees

                        table_rows.append(row_data)

                # MLE Fonctionnelle et MLE Technique

                for perm_code, perm_name, perm_type in [
                    (
                        "FCT",
                        "Perm Fonctionnelle",
                        "permanence_functional",
                    ),
                    ("TCH", "Perm Technique", "permanence_technical"),
                ]:
                    perm_assignments = all_assignments.filtered(
                        lambda a: a.site_id.code == "MLE"
                        and a.permanence_type_id.code == perm_code
                    )

                    if perm_assignments:
                        row_data = {
                            "type": perm_type,
                            "permanence": {"name": perm_name},
                            "days_assignments": [],
                        }

                        for day_idx in range(5):
                            day_name = [
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                            ][day_idx]
                            # Récupérer l'information is_holiday du jour correspondant
                            is_holiday = days[day_idx].get("is_holiday", False) if day_idx < len(days) else False

                            am_assignment = perm_assignments.filtered(
                                lambda a: a.day == day_name
                                and a.period in ["am", "full"]
                            )

                            # Filtrer les affectations PM pour ce jour
                            pm_assignment = perm_assignments.filtered(
                                lambda a: a.day == day_name and a.period == "pm"
                            )
                            pm_assignment = pm_assignment[0] if pm_assignment else None

                            am_data = self._prepare_employee_data(
                                am_assignment[0] if am_assignment else None
                            )
                            pm_data = self._prepare_employee_data(pm_assignment)

                            row_data["days_assignments"].append({
                                "am": am_data, 
                                "pm": pm_data,
                                "is_holiday": is_holiday
                            })

                        table_rows.append(row_data)

            return {"planning": planning_sudo, "days": days, "table_rows": table_rows}

        except Exception as e:
            _logger.error(
                f"Erreur dans _prepare_planning_data pour le planning {planning.id}: {e}",
                exc_info=True,
            )
            # Retourner avec le planning en sudo pour permettre l'affichage même en cas d'erreur partielle
            return {"planning": planning.sudo(), "days": [], "table_rows": []}

    @http.route("/planning/download_pdf/<int:attachment_id>", type="http", auth="user")
    def download_planning_pdf(self, attachment_id, **kwargs):
        """Route pour télécharger le PDF du planning"""
        try:
            import base64

            attachment = request.env["ir.attachment"].browse(attachment_id)
            if not self._is_valid_export_attachment(attachment):
                return request.not_found()

            # Vérifier que l'utilisateur a accès au planning (sans sudo).
            planning = request.env["chc_cds_planning.planning_weekly"].browse(
                attachment.res_id
            )
            if not planning.exists():
                return request.not_found()
            if not self._can_read_planning(planning):
                return request.not_found()

            # Décoder les données base64
            pdf_data = base64.b64decode(attachment.datas)

            # Retourner le fichier avec les en-têtes appropriés
            return request.make_response(
                pdf_data,
                headers=[
                    ("Content-Type", "application/pdf"),
                    ("X-Content-Type-Options", "nosniff"),
                    ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"),
                    ("Pragma", "no-cache"),
                    (
                        "Content-Disposition",
                        f'attachment; filename="{attachment.name}"',
                    ),
                ],
            )
        except Exception as e:
            _logger.error(f"Erreur lors du téléchargement PDF: {e}")
            return request.not_found()

    @http.route("/planning/download_pdf_batch", type="http", auth="user")
    def download_planning_pdf_batch(self, ids="", **kwargs):
        """Route pour télécharger un PDF combiné regroupant plusieurs plannings"""
        try:
            planning_ids = self._parse_batch_ids(ids)
            if not planning_ids:
                return request.not_found()

            plannings = self._get_readable_plannings(planning_ids)
            if not plannings:
                return request.not_found()

            report = request.env.ref(
                "chc_cds_planning.report_planning_weekly", raise_if_not_found=False
            )
            if not report:
                _logger.error(
                    "Rapport chc_cds_planning.report_planning_weekly introuvable"
                )
                return request.not_found()

            report_ref = "chc_cds_planning.report_planning_weekly"
            pdf_data, _format = report.sudo()._render_qweb_pdf(
                report_ref, data=None, res_ids=plannings.ids
            )

            if not pdf_data:
                _logger.error("Génération PDF groupée échouée : données vides")
                return request.not_found()

            filename = f"Plannings_{datetime.today().strftime('%Y%m%d_%H%M%S')}.pdf"

            return request.make_response(
                pdf_data,
                headers=[
                    ("Content-Type", "application/pdf"),
                    ("X-Content-Type-Options", "nosniff"),
                    ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"),
                    ("Pragma", "no-cache"),
                    ("Content-Disposition", f'attachment; filename="{filename}"'),
                ],
            )
        except Exception as e:
            _logger.error(
                f"Erreur lors du téléchargement PDF groupé: {e}", exc_info=True
            )
            return request.not_found()

    @http.route(
        "/planning/download_pdf_batch",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def download_planning_pdf_batch_post(self, ids=None, **kwargs):
        """Version JSON POST pour préparer un export batch sans querystring longue."""
        planning_ids = self._parse_batch_ids(",".join(map(str, ids or [])))
        if not planning_ids:
            return {"success": False, "error": "Paramètres invalides."}

        plannings = self._get_readable_plannings(planning_ids)
        if not plannings:
            return {"success": False, "error": "Accès refusé."}

        return {
            "success": True,
            "download_url": f"/planning/download_pdf_batch?ids={','.join(str(i) for i in planning_ids)}",
        }

    def _prepare_employee_data(self, assignment):
        """Préparer les données d'un employé avec l'ID d'affectation"""
        if not assignment:
            return None

        emp = assignment.employee_id
        # Conversion de la couleur Selection vers Integer pour JavaScript
        color_value = int(emp.color) if emp.color and emp.color.isdigit() else 0
        return {
            "code": emp.employee_code or emp.name[:5].upper(),
            "color": color_value,  # Maintenant supporte 0-24
            "employee_id": emp.id,
            "assignment_id": assignment.id,
            "period": assignment.period,
        }
