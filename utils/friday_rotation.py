"""Logique partagée de rotation équitable des vendredis PM MLE."""

from datetime import date, timedelta

EXCLUDED_EMPLOYEE_CODES = frozenset({"JUAPE"})
FRIDAY_PM_PERM_CODES = frozenset({"FCT", "TCH"})


def is_friday_pm_mle_assignment(assignment):
    """Vérifie si une affectation est un vendredi PM MLE FCT/TCH.

    Les permanences on site (HEU/HRM/WAR) et on site MLE (ATL) sont exclues.
    Les permanences spéciales ne comptent pas non plus.
    """
    if not assignment:
        return False
    if getattr(assignment, "special_name", None):
        return False
    if assignment.day != "friday":
        return False
    if (assignment.period or "").replace(" ", "").lower() != "pm":
        return False
    if not assignment.site_id or assignment.site_id.code != "MLE":
        return False
    if (
        not assignment.permanence_type_id
        or assignment.permanence_type_id.code not in FRIDAY_PM_PERM_CODES
    ):
        return False
    return True


def get_friday_date(week_start):
    return week_start + timedelta(days=4)


def get_planning_week_ids_for_year(env, year):
    """Retourne les IDs des plannings hebdomadaires d'une année donnée."""
    weeks = env["chc_cds_planning.planning_weekly"].search(
        [
            ("start_date", ">=", f"{year}-01-01"),
            ("start_date", "<=", f"{year}-12-31"),
        ],
        order="start_date asc",
    )
    return weeks.ids


def get_counter_field(perm_type_code):
    """Retourne le nom du champ compteur pour un type de permanence."""
    return "counter_fct" if perm_type_code == "FCT" else "counter_tch"


def get_last_date_field(perm_type_code):
    return "last_fct_date" if perm_type_code == "FCT" else "last_tch_date"


def find_best_friday_pm_candidate(
    env,
    perm_type_code,
    friday_date,
    rotation_state,
    exclude_employee_ids=None,
):
    """Sélectionne le candidat le plus équitable pour un vendredi PM MLE.

    Critères (par ordre de priorité) :
    1. Qualifié MLE + type de permanence
    2. Disponible le vendredi
    3. Non exclu (JUAPE, déjà en PM MLE cette semaine, ids exclus)
    4. Compteur le plus bas pour ce type (FCT ou TCH)
    5. En cas d'égalité : date de dernière affectation la plus ancienne
    6. En cas d'égalité : id employé (déterministe)
    """
    exclude_employee_ids = exclude_employee_ids or set()
    employees = rotation_state["employees"]
    counter_key = f"employee_friday_pm_{perm_type_code.lower()}"
    counters = rotation_state.get(counter_key, {})
    last_dates = rotation_state.get(f"last_{perm_type_code.lower()}_dates", {})

    mle_site = env["chc_cds_planning.site"].search([("code", "=", "MLE")], limit=1)
    permanence_type = env["chc_cds_planning.permanence_type"].search(
        [("code", "=", perm_type_code)], limit=1
    )
    if not mle_site or not permanence_type:
        return None

    is_available = rotation_state.get("_is_available_fn")
    candidates = []

    for emp in employees:
        if emp.employee_code in EXCLUDED_EMPLOYEE_CODES:
            continue
        if emp.id in exclude_employee_ids:
            continue
        if emp.id in rotation_state.get("friday_pm_mle_assigned", set()):
            continue
        if is_available and not is_available(emp, friday_date):
            continue

        qualification = emp.qualification_ids.filtered(
            lambda q, pt=permanence_type, site=mle_site: q.permanence_type_id.id
            == pt.id
            and q.site_id.id == site.id
        )
        if not qualification:
            continue

        count = counters.get(emp.id, 0)
        last_date = last_dates.get(emp.id)
        candidates.append((emp, count, last_date or date.min, emp.id))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[1], x[2], x[3]))
    return candidates[0][0]
