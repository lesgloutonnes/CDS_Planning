from odoo import fields, models


class PlanningConfirmOverrideWizard(models.TransientModel):
    _name = "chc_cds_planning.confirm_override_wizard"
    _description = "Avertissement confirmation planning"

    planning_id = fields.Many2one(
        "chc_cds_planning.planning_weekly",
        string="Planning",
        required=True,
        readonly=True,
    )
    error_message = fields.Text(string="Détails des erreurs", readonly=True)
    remaining_planning_ids = fields.Text(
        string="Plannings restants",
        readonly=True,
        help="IDs des plannings restants à traiter (format JSON)"
    )
    total_confirmed_count = fields.Integer(
        string="Total confirmés",
        readonly=True,
        default=0,
        help="Nombre total de plannings confirmés (y compris ceux confirmés directement)"
    )

    def action_force_confirm(self):
        self.ensure_one()
        # Confirmer le planning actuel avec force
        # Gérer les erreurs de transaction pour éviter InFailedSqlTransaction
        try:
            self.planning_id.with_context(force_confirm=True).write({"state": "confirmed"})
        except Exception as e:
            # Propager l'erreur pour que Odoo puisse faire le rollback
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(f"Erreur lors de la confirmation forcée du planning: {e}", exc_info=True)
            raise
        
        # Incrémenter le compteur total (planning actuel + ceux déjà confirmés)
        total_count = self.total_confirmed_count + 1
        
        # Vérifier s'il y a des plannings restants à traiter
        if self.remaining_planning_ids:
            import json
            try:
                remaining_ids = json.loads(self.remaining_planning_ids)
                if remaining_ids:
                    # Récupérer les plannings restants
                    remaining_plannings = self.env["chc_cds_planning.planning_weekly"].browse(remaining_ids)
                    
                    # Traiter les plannings restants un par un
                    return self._process_remaining_plannings(remaining_plannings, total_count)
                else:
                    # Plus de plannings restants, terminer
                    return self._finalize_confirmation(total_count)
            except (json.JSONDecodeError, ValueError):
                # Erreur de parsing, terminer normalement
                return self._finalize_confirmation(total_count)
        
        # Pas de plannings restants, terminer
        return self._finalize_confirmation(total_count)

    def _process_remaining_plannings(self, remaining_plannings, current_total_count):
        """Traite les plannings restants un par un"""
        import json
        confirmed_count = current_total_count  # Compteur incluant les plannings déjà confirmés
        
        for planning in remaining_plannings:
            errors = planning._check_confirmation_errors()
            if errors:
                # Erreurs trouvées, ouvrir le wizard pour ce planning
                error_message = (
                    f"Le planning {planning.name} ne peut pas être confirmé :\n\n"
                    + "\n".join(errors)
                )
                # Préparer la liste des IDs restants (exclure le planning actuel)
                remaining_ids = [p.id for p in remaining_plannings if p.id != planning.id]
                
                # Ouvrir le wizard pour le planning suivant
                wizard_view = self.env.ref(
                    "chc_cds_planning.view_planning_confirm_override_wizard_form"
                )
                return {
                    "type": "ir.actions.act_window",
                    "res_model": "chc_cds_planning.confirm_override_wizard",
                    "view_mode": "form",
                    "view_id": wizard_view.id,
                    "target": "new",
                    "context": {
                        "default_planning_id": planning.id,
                        "default_error_message": error_message,
                        "default_remaining_planning_ids": json.dumps(remaining_ids),
                        "default_total_confirmed_count": confirmed_count,
                    },
                }
            else:
                # Pas d'erreurs, confirmer directement
                # Gérer les erreurs de transaction pour éviter InFailedSqlTransaction
                try:
                    planning.write({"state": "confirmed"})
                    confirmed_count += 1
                except Exception as e:
                    # En cas d'erreur, propager pour que Odoo puisse faire le rollback
                    import logging
                    _logger = logging.getLogger(__name__)
                    _logger.error(f"Erreur lors de la confirmation du planning {planning.id}: {e}", exc_info=True)
                    raise
        
        # Tous les plannings restants sont confirmés
        return self._finalize_confirmation(confirmed_count)

    def _finalize_confirmation(self, confirmed_count):
        """Finalise la confirmation et affiche un message de succès"""
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
                "title": "✅ Confirmation terminée",
                "message": f"{confirmed_count} planning(s) confirmé(s) avec succès.",
                "type": "success",
                "sticky": False,
                "next": action,
            },
        }
