# -*- coding: utf-8 -*-

from odoo import api, models
from odoo.exceptions import AccessDenied


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        """Normalise le login en minuscules lors de la création"""
        for vals in vals_list:
            if 'login' in vals and vals['login']:
                vals['login'] = vals['login'].lower()
        return super(ResUsers, self).create(vals_list)

    def write(self, vals):
        """Normalise le login en minuscules lors de la modification"""
        if 'login' in vals and vals['login']:
            vals['login'] = vals['login'].lower()
        return super(ResUsers, self).write(vals)

    @classmethod
    def _login(cls, db, login, password, user_agent_env):
        """Surcharge de la méthode _login pour rendre l'email insensible à la casse"""
        # Recherche insensible à la casse de l'utilisateur
        with cls.pool.cursor() as cr:
            env = api.Environment(cr, 1, {})
            # Recherche avec ilike pour être insensible à la casse
            user = env['res.users'].search([('login', 'ilike', login)], limit=1)
            if not user:
                raise AccessDenied()
            # Utiliser le login réel de l'utilisateur trouvé pour l'authentification
            real_login = user.login
            # Appeler la méthode parente avec le login réel trouvé
            return super(ResUsers, cls)._login(db, real_login, password, user_agent_env)
