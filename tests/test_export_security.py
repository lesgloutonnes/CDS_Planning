from odoo.tests.common import SavepointCase

from ..controllers.planning_controller import PlanningController


class TestExportSecurityHelpers(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PlanningController()

    def test_parse_batch_ids_valid_and_deduplicated(self):
        ids = self.controller._parse_batch_ids("10,20,20,30")
        self.assertEqual(ids, [10, 20, 30])

    def test_parse_batch_ids_rejects_invalid_values(self):
        ids = self.controller._parse_batch_ids("10,abc,30")
        self.assertEqual(ids, [])

    def test_parse_batch_ids_rejects_too_many_values(self):
        raw = ",".join(str(i) for i in range(1, 80))
        ids = self.controller._parse_batch_ids(raw)
        self.assertEqual(ids, [])

    def test_is_valid_export_attachment(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "test.pdf",
                "type": "binary",
                "datas": "dGVzdA==",
                "res_model": "chc_cds_planning.planning_weekly",
                "res_id": 1,
                "mimetype": "application/pdf",
            }
        )
        self.assertTrue(self.controller._is_valid_export_attachment(attachment))

    def test_is_valid_export_attachment_rejects_wrong_model(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "test.pdf",
                "type": "binary",
                "datas": "dGVzdA==",
                "res_model": "res.partner",
                "res_id": 1,
                "mimetype": "application/pdf",
            }
        )
        self.assertFalse(self.controller._is_valid_export_attachment(attachment))
