# -*- coding: utf-8 -*-
from datetime import date, datetime, time

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError


class PublicHolidaysImportWizard(models.TransientModel):
    _name = "chc_cds_planning.public_holidays_import_wizard"
    _description = "Assistant d'importation des jours fériés publics"

    year = fields.Integer(
        string="Année",
        required=True,
        default=lambda self: date.today().year,
        help="Année pour laquelle importer les jours fériés",
    )

    country_id = fields.Many2one(
        "res.country",
        string="Pays",
        default=lambda self: self._get_default_country(),
        required=True,
        help="Pays pour lequel importer les jours fériés",
    )

    calendar_id = fields.Many2one(
        "resource.calendar",
        string="Calendrier de travail",
        help="Calendrier de travail pour lequel importer les jours fériés. Si vide, utilise le calendrier par défaut.",
    )


    def _get_default_country(self):
        """Retourne la Belgique par défaut"""
        belgium = self.env["res.country"].search([("code", "=", "BE")], limit=1)
        return belgium.id if belgium else False

    def _get_default_calendar(self):
        """Retourne le calendrier de travail par défaut"""
        # Chercher le calendrier par défaut (généralement celui avec le nom "Standard" ou le premier actif)
        default_calendar = self.env["resource.calendar"].search([
            ("active", "=", True)
        ], limit=1, order="id asc")
        
        return default_calendar.id if default_calendar else False

    def _get_holiday_model(self):
        """Retourne le modèle à utiliser pour les jours fériés
        
        Utilise resource.calendar.leaves (modèle standard Odoo pour les jours fériés)
        """
        if "resource.calendar.leaves" not in self.env.registry:
            raise UserError(
                "Le modèle 'resource.calendar.leaves' n'est pas disponible. "
                "Veuillez vérifier que le module de base Odoo est correctement installé."
            )
        return "resource.calendar.leaves"

    def _convert_date_to_datetime(self, holiday_date):
        """Convertit une date en datetime UTC pour Odoo
        
        Args:
            holiday_date: date object (sans heure)
        
        Returns:
            tuple: (date_from, date_to) en datetime UTC
        """
        # Format "jour férié de travail" demandé: 07:30 → 18:00 (heure locale utilisateur)
        # On convertit ensuite en UTC naïf pour le stockage Odoo, sans débordement sur la veille.

        user_tz_name = self.env.user.tz or "UTC"
        try:
            user_tz = pytz.timezone(user_tz_name)
        except Exception:
            user_tz = pytz.UTC

        date_from_local = user_tz.localize(datetime.combine(holiday_date, time(7, 30, 0)))
        date_to_local = user_tz.localize(datetime.combine(holiday_date, time(18, 0, 0)))

        date_from = date_from_local.astimezone(pytz.UTC).replace(tzinfo=None)
        date_to = date_to_local.astimezone(pytz.UTC).replace(tzinfo=None)

        return date_from, date_to

    def action_import_holidays(self):
        """Importe les jours fériés pour l'année sélectionnée"""
        self.ensure_one()

        # Vérifier que le pays est sélectionné
        if not self.country_id:
            raise UserError("Veuillez sélectionner un pays.")

        # Détecter le modèle à utiliser
        holiday_model = self._get_holiday_model()

        # Récupérer ou utiliser le calendrier par défaut
        calendar = self.calendar_id
        if not calendar:
            calendar_id = self._get_default_calendar()
            if not calendar_id:
                raise UserError(
                    "Aucun calendrier de travail trouvé. "
                    "Veuillez créer un calendrier de travail ou en sélectionner un dans le wizard."
                )
            calendar = self.env["resource.calendar"].browse(calendar_id)

        # Générer les jours fériés belges
        holidays_list = self._get_belgian_holidays(self.year)

        # Créer les jours fériés un par un
        created_count = 0

        for holiday_date, holiday_name in holidays_list:
            # Convertir la date en datetime UTC
            date_from, date_to = self._convert_date_to_datetime(holiday_date)

            # Supprimer tous les jours fériés qui se chevauchent avec cette date
            overlapping = self.env[holiday_model].search([
                ("calendar_id", "=", calendar.id),
            ]).filtered(
                lambda h: h.date_from and h.date_to and
                isinstance(h.date_from, datetime) and isinstance(h.date_to, datetime) and
                h.date_from <= date_to and h.date_to >= date_from
            )
            
            # Supprimer les chevauchements avant de créer
            if overlapping:
                overlapping.unlink()

            # Créer le jour férié
            try:
                self.env[holiday_model].create({
                    "name": holiday_name,
                    "date_from": date_from,
                    "date_to": date_to,
                    "calendar_id": calendar.id,
                })
                created_count += 1
            except Exception as e:
                # Si erreur malgré la suppression préventive, propager l'erreur
                raise UserError(
                    f"Impossible de créer le jour férié '{holiday_name}' ({holiday_date.strftime('%d/%m/%Y')}). "
                    f"Erreur: {str(e)}"
                )

        # Message de confirmation
        message = f"{created_count} jour(s) férié(s) importé(s)" if created_count > 0 else "Aucun jour férié importé"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Importation terminée",
                "message": f"Année {self.year}: {message}",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _get_belgian_holidays(self, year):
        """Génère la liste des jours fériés belges pour une année donnée
        
        Retourne une liste de tuples (date, nom)
        """
        holidays_list = []

        # Jours fériés fixes en Belgique
        fixed_holidays = [
            (1, 1, "Jour de l'an"),
            (5, 1, "Fête du Travail"),
            (7, 21, "Fête Nationale belge"),
            (8, 15, "Assomption"),
            (11, 1, "Toussaint"),
            (11, 11, "Armistice"),
            (12, 25, "Noël"),
        ]

        for month, day, name in fixed_holidays:
            try:
                holiday_date = date(year, month, day)
                holidays_list.append((holiday_date, name))
            except ValueError:
                # Date invalide (ne devrait pas arriver)
                continue

        # Jours fériés variables (calculés)
        # Pâques et jours associés
        easter_date = self._calculate_easter(year)
        holidays_list.append((easter_date, "Pâques"))
        holidays_list.append(
            (easter_date + self._timedelta_days(1), "Lundi de Pâques")
        )
        holidays_list.append(
            (easter_date + self._timedelta_days(39), "Ascension")
        )
        holidays_list.append(
            (easter_date + self._timedelta_days(50), "Lundi de Pentecôte")
        )

        # Trier par date
        holidays_list.sort(key=lambda x: x[0])

        return holidays_list

    def _calculate_easter(self, year):
        """Calcule la date de Pâques pour une année donnée (algorithme de Gauss)"""
        # Algorithme de Gauss pour calculer Pâques
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1

        return date(year, month, day)

    def _timedelta_days(self, days):
        """Helper pour créer un timedelta (compatibilité)"""
        from datetime import timedelta

        return timedelta(days=days)
