from odoo import fields, models


class Employee(models.Model):
    _inherit = "hr.employee"

    employee_code = fields.Char(
        string="Code Employé", help="Code d'identification court (ex: ROMAC, PIMAC)"
    )

    color = fields.Selection(
        [
            ("0", "🟨 Jaune"),
            ("1", "🟥 Rouge"),
            ("2", "🟩 Vert"),
            ("3", "🔵 Bleu"),
            ("4", "🟪 Violet"),
            ("5", "🌸 Rose"),
            ("6", "🟧 Orange"),
            ("7", "🧊 Turquoise"),
            ("8", "🍏 Vert pomme"),
            ("9", "🍤 Corail"),
            ("10", "🥉 Bronze"),
            ("11", "🥇 Or"),
            ("12", "🍇 Prune"),
            ("13", "🔮 Lavande"),
            ("14", "🐚 Saumon"),
            ("15", "🟤 Brun"),
            ("16", "💖 Magenta"),
            ("17", "🌌 Bleu nuit"),
            ("18", "🌲 Vert forêt"),
            ("19", "👜 Beige"),
            ("20", "⚫ Noir"),
            ("21", "⚪ Blanc"),
            ("22", "📎 Gris foncé"),
            ("23", "🔘 Gris clair"),
            ("24", "🥮 Ocre"),
            ("25", "🍷 Bordeaux"),
            ("26", "🌿 Menthe"),
            ("27", "🧼 Bleu pastel"),
            ("28", "🧢 Bleu pétrole"),
            ("29", "🧱 Rouille"),
            ("30", "❄️ Menthe glaciale"),
            ("31", "🌿 Vert mousse"),
            ("32", "🍮 Crème"),
            ("33", "🥔 Kaki clair"),
            ("34", "🥈 Argent"),
            ("35", "🧱 Cuivre"),
            ("36", "🍑 Pêche"),
            ("37", "🧀 Moutarde"),
            ("38", "🍂 Terracotta"),
        ],
        string="Couleur Planning",
        default="0",
        help="Couleur utilisée pour l'affichage dans le planning visuel",
    )

    min_days_per_week = fields.Integer(
        string="Jours min. par semaine",
        default=1,
        help="Nombre minimum de jours par semaine que l'employé doit etre affecter au planning",
    )

    max_days_per_week = fields.Integer(
        string="Jours max. par semaine",
        default=3,
        help="Nombre maximum de jours par semaine que l'employé peut etre affecter au planning",
    )

    skin_enabled = fields.Boolean(
        string="Activer skin bulle",
        default=False,
        help="Active un habillage visuel superposé à la couleur de bulle dans le planning",
    )

    skin_type = fields.Selection(
        [
            ("sakura", "🌸 Pétales de cerisier"),
            ("johnny_wolf_moon", "🐺🌕 Johnny Legend"),
            ("birthday_party", "🎂🎈 Anniversaire"),
            ("carni", "🌿🦠🦟☠️ Carni"),
        ],
        string="Skin bulle",
        default="sakura",
        help="Motif décoratif appliqué sur la bulle du planning",
    )

    qualification_ids = fields.One2many(
        "chc_cds_planning.employee_qualifications",
        "employee_id",
        string="Qualifications",
    )

    unavailability_ids = fields.One2many(
        "chc_cds_planning.employee_unavailability",
        "employee_id",
        string="Indisponibilités",
    )

    assignment_ids = fields.One2many(
        "chc_cds_planning.planning_assignment",
        "employee_id",
        string="Affectations",
    )

    def get_color_value(self):
        """Retourne la valeur numérique de la couleur pour JavaScript"""
        return int(self.color) if self.color else 0

    def get_color_info(self):
        """Retourne les informations de couleur pour cet employé"""
        color_mapping = {
            0: {"color": "#fbbf24", "name": "Jaune", "emoji": "🟨"},
            1: {"color": "#ef4444", "name": "Rouge", "emoji": "🟥"},
            2: {"color": "#10b981", "name": "Vert", "emoji": "🟩"},
            3: {"color": "#3b82f6", "name": "Bleu", "emoji": "🔵"},
            4: {"color": "#8b5cf6", "name": "Violet", "emoji": "🟪"},
            5: {"color": "#ec4899", "name": "Rose", "emoji": "🌸"},
            6: {"color": "#f97316", "name": "Orange", "emoji": "🟧"},
            7: {"color": "#06b6d4", "name": "Turquoise", "emoji": "🧊"},
            8: {"color": "#84cc16", "name": "Vert pomme", "emoji": "🍏"},
            9: {"color": "#ff6b6b", "name": "Corail", "emoji": "🍤"},
            10: {"color": "#cd7f32", "name": "Bronze", "emoji": "🥉"},
            11: {"color": "#ffd700", "name": "Or", "emoji": "🥇"},
            12: {"color": "#7c2d92", "name": "Prune", "emoji": "🍇"},
            13: {"color": "#a78bfa", "name": "Lavande", "emoji": "🔮"},
            14: {"color": "#fb7185", "name": "Saumon", "emoji": "🐚"},
            15: {"color": "#8b4513", "name": "Brun", "emoji": "🟤"},
            16: {"color": "#d946ef", "name": "Magenta", "emoji": "💖"},
            17: {"color": "#243c5a", "name": "Bleu nuit", "emoji": "🌌"},
            18: {"color": "#228B22", "name": "Vert forêt", "emoji": "🌲"},
            19: {"color": "#ffe4b5", "name": "Beige", "emoji": "👜"},
            20: {"color": "#000000", "name": "Noir", "emoji": "⚫"},
            21: {"color": "#ffffff", "name": "Blanc", "emoji": "⚪"},
            22: {"color": "#6b7280", "name": "Gris foncé", "emoji": "📎"},
            23: {"color": "#9ca3af", "name": "Gris clair", "emoji": "🔘"},
            24: {"color": "#cc7722", "name": "Ocre", "emoji": "🥮"},
            25: {"color": "#800020", "name": "Bordeaux", "emoji": "🍷"},
            26: {"color": "#98ff98", "name": "Menthe", "emoji": "🌿"},
            27: {"color": "#aec6cf", "name": "Bleu pastel", "emoji": "🧼"},
            28: {"color": "#004e64", "name": "Bleu pétrole", "emoji": "🧢"},
            29: {"color": "#b7410e", "name": "Rouille", "emoji": "🧱"},
            30: {"color": "#d0f0c0", "name": "Menthe glaciale", "emoji": "❄️"},
            31: {"color": "#758e67", "name": "Vert mousse", "emoji": "🌿"},
            32: {"color": "#f3e5ab", "name": "Crème", "emoji": "🍮"},
            33: {"color": "#c3b091", "name": "Kaki clair", "emoji": "🥔"},
            34: {"color": "#c0c0c0", "name": "Argent", "emoji": "🥈"},
            35: {"color": "#b87333", "name": "Cuivre", "emoji": "🧱"},
            36: {"color": "#ffe5b4", "name": "Pêche", "emoji": "🍑"},
            37: {"color": "#e1ad01", "name": "Moutarde", "emoji": "🧀"},
            38: {"color": "#e2725b", "name": "Terracotta", "emoji": "🍂"},
        }
        color_index = int(self.color) if self.color else 0
        return color_mapping.get(color_index, color_mapping[0])
