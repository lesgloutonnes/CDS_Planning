"""Tests unitaires de la logique de rotation vendredi PM (sans serveur Odoo)."""

from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from utils.friday_rotation import (
    EXCLUDED_EMPLOYEE_CODES,
    find_best_friday_pm_candidate,
    is_friday_pm_mle_assignment,
)


class FakeQualification(SimpleNamespace):
    pass


class FakeEmployee(SimpleNamespace):
    pass


class FakeSite(SimpleNamespace):
    pass


class FakePermType(SimpleNamespace):
    pass


class FakeAssignment(SimpleNamespace):
    pass


class FakeEnv:
    """Environnement minimal pour find_best_friday_pm_candidate."""

    def __init__(self, mle_site, perm_types):
        self._mle_site = mle_site
        self._perm_types = perm_types

    def __getitem__(self, model_name):
        return self

    def search(self, domain, limit=None):
        for item in domain:
            if len(item) == 3 and item[0] == "code" and item[1] == "=":
                code = item[2]
                if code == "MLE":
                    return self._mle_site
                if code in self._perm_types:
                    return self._perm_types[code]
            if len(item) == 3 and item[0] == "code" and item[1] == "in":
                # permanence_type search with in — unused here
                pass
        return FakeSite(id=None, code=None)


class FakeRecordset(list):
    def filtered(self, func):
        return FakeRecordset(x for x in self if func(x))


def _make_employees():
    mle = FakeSite(id=1, code="MLE")
    fct = FakePermType(id=10, code="FCT")
    tch = FakePermType(id=20, code="TCH")

    employees = []
    for i, code in enumerate(
        ["JEDEL", "ANSCH", "ROMAC", "ALBAS", "JOMAR", "PIMAC", "EMDEV", "GRMOR", "JUAPE"]
    ):
        emp = FakeEmployee(
            id=i + 1,
            name=code,
            employee_code=code,
            qualification_ids=FakeRecordset(),
        )
        # Tous sauf JUAPE : FCT+TCH MLE pour les tests d'équité
        if code != "JUAPE":
            emp.qualification_ids = FakeRecordset(
                [
                    FakeQualification(permanence_type_id=fct, site_id=mle),
                    FakeQualification(permanence_type_id=tch, site_id=mle),
                ]
            )
        else:
            emp.qualification_ids = FakeRecordset(
                [
                    FakeQualification(permanence_type_id=tch, site_id=mle),
                ]
            )
        employees.append(emp)
    return employees, mle, fct, tch


class TestFridayRotationHelpers(unittest.TestCase):
    def test_is_friday_pm_mle_assignment(self):
        mle = FakeSite(id=1, code="MLE")
        war = FakeSite(id=2, code="WAR")
        fct = FakePermType(id=10, code="FCT")
        atelier = FakePermType(id=30, code="ATL")

        ok = FakeAssignment(
            day="friday",
            period="pm",
            site_id=mle,
            permanence_type_id=fct,
        )
        self.assertTrue(is_friday_pm_mle_assignment(ok))

        self.assertFalse(
            is_friday_pm_mle_assignment(
                FakeAssignment(
                    day="friday", period="pm", site_id=war, permanence_type_id=fct
                )
            )
        )
        self.assertFalse(
            is_friday_pm_mle_assignment(
                FakeAssignment(
                    day="friday", period="full", site_id=mle, permanence_type_id=atelier
                )
            )
        )

    def test_juape_excluded(self):
        self.assertIn("JUAPE", EXCLUDED_EMPLOYEE_CODES)

    def test_rotation_balances_over_52_weeks(self):
        employees, mle, fct, tch = _make_employees()
        eligible = [e for e in employees if e.employee_code != "JUAPE"]
        env = FakeEnv(mle, {"FCT": fct, "TCH": tch})

        rotation_state = {
            "employees": eligible,
            "employee_friday_pm_fct": {e.id: 0 for e in eligible},
            "employee_friday_pm_tch": {e.id: 0 for e in eligible},
            "last_fct_dates": {},
            "last_tch_dates": {},
            "friday_pm_mle_assigned": set(),
            "_is_available_fn": lambda emp, d: True,
        }

        start = date(2026, 1, 2)  # vendredi
        for week in range(52):
            friday = start + timedelta(weeks=week)
            rotation_state["friday_pm_mle_assigned"] = set()

            for perm_code, counter_key, last_key in (
                ("FCT", "employee_friday_pm_fct", "last_fct_dates"),
                ("TCH", "employee_friday_pm_tch", "last_tch_dates"),
            ):
                candidate = find_best_friday_pm_candidate(
                    env, perm_code, friday, rotation_state
                )
                self.assertIsNotNone(candidate, f"Semaine {week} {perm_code}")
                self.assertNotEqual(candidate.employee_code, "JUAPE")
                rotation_state["friday_pm_mle_assigned"].add(candidate.id)
                rotation_state[counter_key][candidate.id] += 1
                rotation_state[last_key][candidate.id] = friday

        fct_counts = list(rotation_state["employee_friday_pm_fct"].values())
        tch_counts = list(rotation_state["employee_friday_pm_tch"].values())

        # 8 éligibles, 52 créneaux → ~6.5 chacun, écart ≤ 1
        self.assertEqual(len(fct_counts), 8)
        self.assertLessEqual(max(fct_counts) - min(fct_counts), 1)
        self.assertLessEqual(max(tch_counts) - min(tch_counts), 1)
        self.assertEqual(sum(fct_counts), 52)
        self.assertEqual(sum(tch_counts), 52)

    def test_already_assigned_are_skipped(self):
        employees, mle, fct, tch = _make_employees()
        eligible = [e for e in employees if e.employee_code != "JUAPE"]
        env = FakeEnv(mle, {"FCT": fct, "TCH": tch})
        jedel = next(e for e in eligible if e.employee_code == "JEDEL")
        ansch = next(e for e in eligible if e.employee_code == "ANSCH")

        rotation_state = {
            "employees": eligible,
            "employee_friday_pm_fct": {e.id: 0 for e in eligible},
            "employee_friday_pm_tch": {e.id: 0 for e in eligible},
            "last_fct_dates": {},
            "last_tch_dates": {},
            "friday_pm_mle_assigned": set(),
            "_is_available_fn": lambda emp, d: True,
        }
        # JEDEL a le compteur le plus bas mais est déjà pris
        rotation_state["employee_friday_pm_fct"][jedel.id] = 0
        for e in eligible:
            if e.id != jedel.id:
                rotation_state["employee_friday_pm_fct"][e.id] = 5

        candidate = find_best_friday_pm_candidate(
            env,
            "FCT",
            date(2026, 3, 6),
            rotation_state,
            exclude_employee_ids={jedel.id},
        )
        self.assertIsNotNone(candidate)
        self.assertNotEqual(candidate.id, jedel.id)
        # Parmi ceux à 5, tie-break par id → ANSCH (id plus petit que les autres à 5? )
        # ANSCH id=2, ROMAC=3, ... JEDEL=1 excluded. Min id among count=5 is ANSCH=2
        self.assertEqual(candidate.id, ansch.id)


if __name__ == "__main__":
    unittest.main()
