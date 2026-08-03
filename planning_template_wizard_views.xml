# -*- coding: utf-8 -*-
from odoo import fields, models
from markupsafe import Markup


class PlanningTemplateWizard(models.TransientModel):
    _name = "chc_cds_planning.planning_template_wizard"
    _description = "Assistant d'application ou de création d'un modèle"

    action = fields.Selection(
        [
            ("apply", "Appliquer le modèle"),
            ("save", "Sauvegarder depuis le planning"),
        ],
        string="Action",
        required=True,
    )

    # champs liés à l'application d'un modèle
    template_id = fields.Many2one("chc_cds_planning.planning_template", string="Modèle")
    planning_id = fields.Many2one("chc_cds_planning.planning_weekly", string="Planning")

    replace_existing = fields.Boolean(
        string="Remplacer les affectations existantes",
    )

    check_availability = fields.Boolean(
        string="Vérifier la disponibilité",
    )

    # champs liés à la création d'un modèle depuis un planning
    new_template_name = fields.Char(
        string="Nom du nouveau modèle",
        default=lambda self: f"Modèle {fields.Date.today().strftime('%d/%m/%Y')}",
    )
    new_template_description = fields.Text(
        string="Description",
        help="Description",
    )
    set_new_as_default = fields.Boolean(
        string="Définir par défaut",
    )

    def action_apply_template(self):
        """Applique le modèle sur le planning choisi."""
        if self.replace_existing:
            self.planning_id.assignment_ids.with_context(skip_tracking=True).unlink()

        assignments_to_create = []

        for line in self.template_id.template_line_ids:
            if self.check_availability:
                if not self.planning_id._is_employee_available(
                    line.employee_id, line.day
                ):
                    continue

            assignments_to_create.append(
                {
                    "planning_week_id": self.planning_id.id,
                    "employee_id": line.employee_id.id,
                    "site_id": line.site_id.id,
                    "permanence_type_id": line.permanence_type_id.id,
                    "day": line.day,
                    "period": line.period,
                }
            )

        if assignments_to_create:
            self.env["chc_cds_planning.planning_assignment"].with_context(skip_tracking=True).create(assignments_to_create)

        self.planning_id.message_post(
            body=Markup(
                f"Modèle <b>{self.template_id.name}</b> appliqué : "
                f"{len(assignments_to_create)} affectations créées."
            )
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Modèle appliqué",
                "message": f'Le modèle "{self.template_id.name}" a été appliqué avec succès !',
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_save_template(self):
        """Sauvegarde le planning actuel en tant que nouveau modèle."""
        template = self.env["chc_cds_planning.planning_template"].create(
            {
                "name": self.new_template_name,
                "description": self.new_template_description,
                "is_default": self.set_new_as_default,
                "active": True,
            }
        )

        template_lines = []
        for assignment in self.planning_id.assignment_ids:
            template_lines.append(
                {
                    "template_id": template.id,
                    "employee_id": assignment.employee_id.id,
                    "site_id": assignment.site_id.id,
                    "permanence_type_id": assignment.permanence_type_id.id,
                    "day": assignment.day,
                    "period": assignment.period,
                }
            )

        if template_lines:
            self.env["chc_cds_planning.planning_template_line"].create(template_lines)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Modèle créé",
                "message": f'Le modèle "{self.new_template_name}" a été créé avec succès !',
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
