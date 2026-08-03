from odoo import api, fields, models
from odoo.exceptions import ValidationError


class L1GuardCalendar(models.Model):
    _name = "chc_cds_planning.l1_guard_calendar"
    _description = "Calendrier de garde L1"
    _order = "date_start"

    name = fields.Char(string="Semaine de garde", compute="_compute_name", store=True)
    date_start = fields.Date(string="A partir de 18h", required=True)
    date_end = fields.Date(string="Jusqu'a 7h", required=True)
    l1_code = fields.Char(string="L1 Penta", required=True)
    employee_id = fields.Many2one(
        "hr.employee",
        string="L1 Nom",
        default=lambda self: self._default_employee_l1(),
        ondelete="restrict",
    )

    @api.model
    def _default_employee_l1(self):
        employee = self.env["hr.employee"].search(
            [("employee_code", "=", "ADVER")], limit=1
        )
        if not employee:
            employee = self.env["hr.employee"].search(
                [("name", "ilike", "Adrien Verschueren")], limit=1
            )
        return employee.id

    @api.depends("date_start", "date_end")
    def _compute_name(self):
        for record in self:
            if record.date_start and record.date_end:
                record.name = "%s - %s" % (record.date_start, record.date_end)
            else:
                record.name = "Semaine de garde"

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for record in self:
            if record.date_end < record.date_start:
                raise ValidationError(
                    "La date de fin de garde doit etre posterieure ou egale a la date de debut."
                )
