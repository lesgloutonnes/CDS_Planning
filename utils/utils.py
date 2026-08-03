# -*- coding: utf-8 -*-
"""Utilitaires pour le module chc_cds_planning"""

from collections import defaultdict
from datetime import timedelta, datetime
import base64
import json
import logging

_logger = logging.getLogger(__name__)

# Sites distants « On Site » : libellé calendrier = nom du site (ex. On Site HEU)
ISOLATED_ON_SITE_CODES = frozenset({"HEU", "HRM", "WAR"})
DEFAULT_CALENDAR_SENDER_EMAIL = "svc_odoo_notif@chc.dom"
CALENDAR_SENDER_EMAIL_PARAM = "chc_cds_planning.calendar_sender_email"

try:
    import pytz
except Exception:  # pragma: no cover
    pytz = None


def _escape_ics_text(value):
    """Échappe une valeur texte pour le format ICS."""
    text = (value or "").replace("\\", "\\\\")
    text = text.replace(";", r"\;").replace(",", r"\,")
    text = text.replace("\r\n", r"\n").replace("\n", r"\n")
    return text


def _float_to_datetime_value(target_date, hour_float):
    """Convertit une heure décimale (ex: 7.5) en datetime local."""
    base = datetime.combine(target_date, datetime.min.time())
    hour_float = float(hour_float or 0.0)
    hours = int(hour_float)
    minutes = int(round((hour_float - hours) * 60))
    if minutes >= 60:
        hours += 1
        minutes -= 60
    return base.replace(hour=hours, minute=minutes, second=0, microsecond=0)


def _to_ics_utc_value(local_dt):
    """Convertit un datetime local Europe/Brussels en valeur UTC ICS (suffixe Z)."""
    if pytz is None:
        return local_dt.strftime("%Y%m%dT%H%M%SZ")

    brussels_tz = pytz.timezone("Europe/Brussels")
    localized = brussels_tz.localize(local_dt)
    utc_dt = localized.astimezone(pytz.UTC)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


def _build_assignment_payload(planning, assignment):
    """Prépare un payload sérialisable pour une affectation."""
    assignment_date = get_date_from_week_start_and_day(planning.start_date, assignment.day)
    attendee_email = assignment.employee_id.work_email or assignment.employee_id.user_id.email
    site_name = assignment.site_id.name or ""
    site_code = assignment.site_id.code or ""
    permanence_name = assignment.special_name or assignment.permanence_type_id.name or "Permanence"
    if (
        not assignment.special_name
        and assignment.permanence_type_id
        and assignment.permanence_type_id.code == "TCH"
        and (site_code or "").strip().upper() in ISOLATED_ON_SITE_CODES
    ):
        permanence_name = site_name or permanence_name

    return {
        "event_key": str(assignment.id),
        "uid": f"chc-planning-{planning.id}-{assignment.id}@chc.local",
        "employee_name": assignment.employee_id.name or "",
        "attendee_email": attendee_email or "",
        "day": assignment.day or "",
        "date": assignment_date.strftime("%Y-%m-%d"),
        "start_time": float(assignment.start_time or 0.0),
        "end_time": float(assignment.end_time or 0.0),
        "period": assignment.period or "",
        "site_name": site_name,
        "site_code": site_code,
        "permanence_name": permanence_name,
    }


def _load_previous_snapshot(planning):
    """Charge le snapshot JSON de la dernière publication."""
    raw = planning.publish_calendar_snapshot or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _event_changed(previous_payload, current_payload):
    """Détermine si un événement ICS doit être mis à jour."""
    tracked_fields = [
        "day",
        "date",
        "start_time",
        "end_time",
        "period",
        "site_name",
        "site_code",
        "permanence_name",
    ]
    for field_name in tracked_fields:
        if (previous_payload.get(field_name) or "") != (
            current_payload.get(field_name) or ""
        ):
            return True
    return False


def _build_delta_operations(previous_snapshot, current_snapshot):
    """Construit la liste des opérations REQUEST/CANCEL à envoyer."""
    operations = []
    previous_keys = set(previous_snapshot.keys())
    current_keys = set(current_snapshot.keys())

    # Événements supprimés: envoyer un CANCEL à l'ancien destinataire.
    for event_key in sorted(previous_keys - current_keys):
        previous_payload = previous_snapshot[event_key]
        operations.append(("CANCEL", previous_payload))

    # Nouveaux événements: envoyer un REQUEST.
    for event_key in sorted(current_keys - previous_keys):
        current_payload = current_snapshot[event_key]
        operations.append(("REQUEST", current_payload))

    # Événements existants: changement de personne ou de contenu.
    for event_key in sorted(previous_keys & current_keys):
        previous_payload = previous_snapshot[event_key]
        current_payload = current_snapshot[event_key]
        previous_email = (previous_payload.get("attendee_email") or "").strip().lower()
        current_email = (current_payload.get("attendee_email") or "").strip().lower()

        if previous_email != current_email:
            operations.append(("CANCEL", previous_payload))
            operations.append(("REQUEST", current_payload))
            continue

        if _event_changed(previous_payload, current_payload):
            operations.append(("REQUEST", current_payload))

    return operations


def build_assignment_ics(payload, attendee_email, organizer_email, method, sequence):
    """Construit un contenu ICS pour une opération REQUEST/CANCEL."""
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    date_value = datetime.strptime(payload["date"], "%Y-%m-%d").date()
    start_dt = _float_to_datetime_value(date_value, payload.get("start_time"))
    end_dt = _float_to_datetime_value(date_value, payload.get("end_time"))

    site_name = payload.get("site_name") or ""
    site_code = payload.get("site_code") or ""
    permanence_name = payload.get("permanence_name") or "Permanence"
    if site_code and site_name and permanence_name == site_name:
        summary = f"Permanence {permanence_name}"
    elif site_code:
        summary = f"Permanence {permanence_name} ({site_code})"
    else:
        summary = f"Permanence {permanence_name}"
    description = (
        "Mise à jour de planning.\n"
        f"Site: {site_name}\n"
        f"Type: {permanence_name}\n"
        f"Période: {payload.get('period') or ''}"
    )

    method = "CANCEL" if method == "CANCEL" else "REQUEST"
    status = "CANCELLED" if method == "CANCEL" else "CONFIRMED"
    attendee_partstat = "DECLINED" if method == "CANCEL" else "NEEDS-ACTION"

    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//CHC//Planning CDS//FR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "X-WR-CALNAME:Planning CDS",
        "BEGIN:VEVENT",
        f"UID:{payload['uid']}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{_to_ics_utc_value(start_dt)}",
        f"DTEND:{_to_ics_utc_value(end_dt)}",
        f"SEQUENCE:{int(sequence or 0)}",
        f"STATUS:{status}",
        f"SUMMARY:{_escape_ics_text(summary)}",
        f"DESCRIPTION:{_escape_ics_text(description)}",
        f"LOCATION:{_escape_ics_text(site_name)}",
        f"ORGANIZER:MAILTO:{organizer_email}",
        (
            "ATTENDEE;CN="
            f"{_escape_ics_text(payload.get('employee_name') or '')};"
            f"ROLE=REQ-PARTICIPANT;PARTSTAT={attendee_partstat};RSVP=TRUE:"
            f"MAILTO:{attendee_email}"
        ),
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def send_calendar_invites_for_planning(planning):
    """Envoie uniquement les invitations delta (REQUEST/CANCEL) pour un planning publié."""
    result = {
        "emails_sent": 0,
        "employees_targeted": 0,
        "missing_email_employees": [],
        "errors": [],
    }

    if not planning or not planning.start_date:
        result["errors"].append("Planning sans date de début.")
        return result

    assignments = planning.assignment_ids.filtered(lambda a: a.employee_id)
    sender_email = (
        planning.env["ir.config_parameter"]
        .sudo()
        .get_param(CALENDAR_SENDER_EMAIL_PARAM, default=DEFAULT_CALENDAR_SENDER_EMAIL)
    )
    sender_email = (sender_email or DEFAULT_CALENDAR_SENDER_EMAIL).strip()
    organizer_email = sender_email
    previous_snapshot = _load_previous_snapshot(planning)
    current_snapshot = {}
    for assignment in assignments.sorted(key=lambda a: a.id):
        payload = _build_assignment_payload(planning, assignment)
        current_snapshot[payload["event_key"]] = payload

    operations = _build_delta_operations(previous_snapshot, current_snapshot)
    impacted_emails = set()
    missing_employees = set()
    sequence = (planning.publish_calendar_sequence or 0) + 1

    for method, payload in operations:
        attendee_email = (payload.get("attendee_email") or "").strip()
        employee_name = payload.get("employee_name") or "Employé inconnu"
        if not attendee_email:
            missing_employees.add(employee_name)
            continue

        impacted_emails.add(attendee_email.lower())

        try:
            ics_content = build_assignment_ics(
                payload=payload,
                attendee_email=attendee_email,
                organizer_email=organizer_email,
                method=method,
                sequence=sequence,
            )
            filename = (
                f"planning_{method.lower()}_{payload['event_key']}_s{sequence}.ics"
            )
            attachment = (
                planning.env["ir.attachment"]
                .sudo()
                .create(
                    {
                        "name": filename,
                        "type": "binary",
                        "datas": base64.b64encode(ics_content.encode("utf-8")).decode("ascii"),
                        "res_model": "chc_cds_planning.planning_weekly",
                        "res_id": planning.id,
                        "mimetype": "text/calendar",
                    }
                )
            )

            date_label = datetime.strptime(payload["date"], "%Y-%m-%d").strftime(
                "%d/%m/%Y"
            )
            permanence_name = payload.get("permanence_name") or "Permanence"
            if method == "CANCEL":
                subject = f"Annulation calendrier - {permanence_name} - {date_label}"
                body_html = (
                    "<p>Bonjour,</p>"
                    "<p>Une permanence a été annulée dans votre calendrier.</p>"
                    "<p>Merci.</p>"
                )
            else:
                subject = f"Invitation calendrier - {permanence_name} - {date_label}"
                body_html = (
                    "<p>Bonjour,</p>"
                    "<p>Veuillez trouver ci-joint l'invitation calendrier "
                    "mise à jour pour votre permanence.</p>"
                    "<p>Merci.</p>"
                )

            mail = (
                planning.env["mail.mail"]
                .sudo()
                .create(
                    {
                        "email_to": attendee_email,
                        "email_from": sender_email,
                        "reply_to": sender_email,
                        "subject": subject,
                        "body_html": body_html,
                        "attachment_ids": [(6, 0, [attachment.id])],
                        "auto_delete": False,
                    }
                )
            )
            mail.send()
            result["emails_sent"] += 1
        except Exception as e:
            _logger.error(
                "Erreur envoi %s calendrier pour planning %s (%s): %s",
                method,
                planning.id,
                employee_name,
                e,
                exc_info=True,
            )
            result["errors"].append(f"{employee_name}: {e}")

    if not result["errors"]:
        planning.sudo().write(
            {
                "publish_calendar_snapshot": json.dumps(current_snapshot),
                "publish_calendar_sequence": sequence,
            }
        )

    result["employees_targeted"] = len(impacted_emails)
    result["missing_email_employees"] = sorted(missing_employees)
    return result


def get_batch_pdf_download_action(planning_ids):
    """Prépare une action permettant de déclencher un téléchargement PDF multi-plannings"""
    cleaned_ids = []
    seen = set()
    for pid in planning_ids or []:
        try:
            int_pid = int(pid)
        except (TypeError, ValueError):
            continue
        if int_pid <= 0 or int_pid in seen:
            continue
        seen.add(int_pid)
        cleaned_ids.append(int_pid)

    # Rester aligné avec la limite côté contrôleur HTTP.
    if len(cleaned_ids) > 50:
        cleaned_ids = cleaned_ids[:50]

    ids = [str(pid) for pid in cleaned_ids]
    if not ids:
        return None

    ids_param = ",".join(ids)
    return {
        "type": "ir.actions.act_url",
        "url": f"/planning/download_pdf_batch?ids={ids_param}",
        "target": "self",
    }


def prepare_planning_data_for_export(planning):
    """Prépare les données pour l'export PDF (similaire à _prepare_planning_data du contrôleur)"""
    day_keys = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    day_names_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]

    def norm_period(period):
        return (period or "").replace(" ", "").lower()

    def first_existing(index, keys):
        candidates = []
        for key in keys:
            candidates.extend(index.get(key, []))
        if not candidates:
            return None
        return min(candidates, key=lambda a: a.id)

    # Jours de la semaine
    days = []
    if planning.start_date:
        # Récupérer le calendrier par défaut pour vérifier les jours fériés
        default_calendar = planning.env["resource.calendar"].search([
            ("active", "=", True)
        ], limit=1, order="id asc")
        calendar_id = default_calendar.id if default_calendar else None
        
        for i, day_name in enumerate(day_names_fr):
            current_date = planning.start_date + timedelta(days=i)
            is_holiday = is_public_holiday(planning.env, current_date, calendar_id)
            days.append(
                {
                    "index": i,
                    "name": day_name,
                    "date_formatted": current_date.strftime("%d/%m"),
                    "date": current_date,
                    "is_holiday": is_holiday,
                }
            )

    # Récupérer toutes les affectations
    all_assignments = planning.env["chc_cds_planning.planning_assignment"].search(
        [("planning_week_id", "=", planning.id)],
        order="id asc",
    )

    if not all_assignments:
        return {"planning": planning, "days": days, "table_rows": [], "is_export": True}

    table_rows = []
    isolated_sites = ["HRM", "HEU", "WAR"]

    # Précharger les sites utilisés pour éviter des recherches répétées.
    sites = planning.env["chc_cds_planning.site"].search([("code", "in", isolated_sites + ["MLE"])])
    site_by_code = {site.code: site for site in sites}

    # Indexation en une passe pour éviter les filtered() répétés.
    site_index = defaultdict(list)  # (site_code, day, period_norm) -> [assignments]
    mle_perm_index = defaultdict(list)  # (perm_code, day, period_norm) -> [assignments]
    atelier_by_day = defaultdict(list)  # day -> [assignments ATL/MLE]
    special_index = defaultdict(list)  # (special_name, day, period_norm) -> [assignments]
    special_colors = {}  # special_name -> color

    for assignment in all_assignments:
        day = assignment.day
        period = norm_period(assignment.period)
        site_code = assignment.site_id.code if assignment.site_id else None
        perm_code = assignment.permanence_type_id.code if assignment.permanence_type_id else None

        if site_code in isolated_sites:
            site_index[(site_code, day, period)].append(assignment)

        if site_code == "MLE":
            if perm_code == "ATL":
                atelier_by_day[day].append(assignment)
            elif perm_code in ("FCT", "TCH"):
                mle_perm_index[(perm_code, day, period)].append(assignment)

        if assignment.special_name:
            special_name = assignment.special_name
            special_index[(special_name, day, period)].append(assignment)
            if special_name not in special_colors:
                special_colors[special_name] = assignment.special_color or "#6f42c1"

    # Trier les affectations atelier par nom employé pour garder un affichage stable.
    for day in day_keys:
        atelier_by_day[day] = sorted(
            atelier_by_day.get(day, []),
            key=lambda a: (a.employee_id.name or "", a.id),
        )

    # Sites isolés (HRM, HEU, WAR)
    for site_code in isolated_sites:
        site = site_by_code.get(site_code)
        if not site:
            continue

        row_data = {
            "type": "site_header",
            "site": {
                "code": site.code,
                "name": f"{site.name} ({site.code})",
                "badge_class": f"badge-{site.code}",
            },
            "days_assignments": [],
        }

        for day_name in day_keys:
            am_assignment = first_existing(
                site_index,
                [(site_code, day_name, "am"), (site_code, day_name, "full")],
            )
            pm_assignment = first_existing(site_index, [(site_code, day_name, "pm")])

            am_data = prepare_employee_data_for_export(am_assignment)
            pm_data = prepare_employee_data_for_export(pm_assignment)

            row_data["days_assignments"].append({"am": am_data, "pm": pm_data})

        if any(day["am"] or day["pm"] for day in row_data["days_assignments"]):
            table_rows.append(row_data)

    # Site MLE - MLE On Site
    site_mle = site_by_code.get("MLE")
    if site_mle:
        atelier_assignments = []
        for day_name in day_keys:
            atelier_assignments.extend(atelier_by_day.get(day_name, []))

        if atelier_assignments:
            atelier_data = {}
            for day_name in day_keys:
                atelier_data[day_name] = atelier_by_day.get(day_name, [])

            max_employees = (
                max(len(atelier_data[day]) for day in atelier_data)
                if atelier_data
                else 0
            )

            for row_idx in range(max_employees):
                row_data = {
                    "type": "atelier_employee",
                    "days_assignments": [],
                }

                for day_name in day_keys:
                    day_assignments = atelier_data[day_name]
                    assignment = (
                        day_assignments[row_idx]
                        if row_idx < len(day_assignments)
                        else None
                    )
                    full_day_data = prepare_employee_data_for_export(assignment)
                    row_data["days_assignments"].append({"full_day": full_day_data})

                if row_idx == 0:
                    row_data["show_atelier_header"] = True
                    row_data["atelier_rowspan"] = max_employees

                table_rows.append(row_data)

        # MLE Fonctionnelle et MLE Technique

        for perm_code, perm_name, perm_type in [
            ("FCT", "Perm Fonctionnelle", "permanence_functional"),
            ("TCH", "Perm Technique", "permanence_technical"),
        ]:
            has_perm = any(
                mle_perm_index.get((perm_code, day_name, period))
                for day_name in day_keys
                for period in ("am", "pm", "full")
            )

            if has_perm:
                row_data = {
                    "type": perm_type,
                    "permanence": {"name": perm_name},
                    "days_assignments": [],
                }

                for day_name in day_keys:
                    am_assignment = first_existing(
                        mle_perm_index,
                        [(perm_code, day_name, "am"), (perm_code, day_name, "full")],
                    )
                    pm_assignment = first_existing(
                        mle_perm_index, [(perm_code, day_name, "pm")]
                    )

                    am_data = prepare_employee_data_for_export(am_assignment)
                    pm_data = prepare_employee_data_for_export(pm_assignment)

                    row_data["days_assignments"].append(
                        {"am": am_data, "pm": pm_data}
                    )

                table_rows.append(row_data)

    # Permanences spéciales (maintenant dans assignment_ids avec special_name)
    if special_index:
        perm_names = sorted({key[0] for key in special_index.keys()})
        for perm_name in perm_names:
            perm_color = special_colors.get(perm_name, "#6f42c1")

            row_data = {
                "type": "special_permanence",
                "permanence": {
                    "name": perm_name,
                    "color": perm_color,
                },
                "days_assignments": [],
            }

            for day_name in day_keys:
                full_special = first_existing(
                    special_index, [(perm_name, day_name, "full")]
                )
                if full_special:
                    full_data = prepare_employee_data_for_export(full_special)
                    if full_data:
                        full_data["period"] = "full"
                    row_data["days_assignments"].append({"full_day": full_data})
                    continue

                am_special = first_existing(
                    special_index, [(perm_name, day_name, "am")]
                )
                pm_special = first_existing(
                    special_index, [(perm_name, day_name, "pm")]
                )
                am_data = prepare_employee_data_for_export(am_special)
                pm_data = prepare_employee_data_for_export(pm_special)
                row_data["days_assignments"].append({"am": am_data, "pm": pm_data})

            table_rows.append(row_data)

    return {
        "planning": planning,
        "days": days,
        "table_rows": table_rows,
        "is_export": True,
        "planning_state": planning.state,
    }


def prepare_employee_data_for_export(assignment):
    """Prépare les données d'un employé pour l'export (similaire au contrôleur)"""
    if not assignment:
        return None

    emp = assignment.employee_id

    color_value = int(emp.color) if emp.color and emp.color.isdigit() else 0
    color_info = emp.get_color_info() if hasattr(emp, "get_color_info") else {}
    color_hex = color_info.get("color", "#fbbf24")

    def is_light(hex_color):
        hex_color = hex_color.lstrip("#")
        if len(hex_color) != 6:
            return False
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        # Perceived luminance
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance > 0.6

    text_color = "#1f2937" if is_light(color_hex) else "#ffffff"
    color_style = f"background-color: {color_hex}; color: {text_color};"

    return {
        "code": emp.employee_code or emp.name[:5].upper(),
        "color": color_value,
        "color_style": color_style,
        "employee_id": emp.id,
        "assignment_id": assignment.id,
        "period": assignment.period,
    }


def generate_pdf_export_via_report(planning, force_regenerate=False):
    """Génère un export PDF du planning via le système de rapport Odoo (comme Print)"""
    try:
        planning_write_token = str(planning.write_date or "")

        # Cache léger: si le planning n'a pas changé depuis le dernier export, réutiliser l'attachement.
        if not force_regenerate:
            existing_attachment = planning.env["ir.attachment"].search(
                [
                    ("res_model", "=", "chc_cds_planning.planning_weekly"),
                    ("res_id", "=", planning.id),
                    ("mimetype", "=", "application/pdf"),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
            if existing_attachment:
                marker = f"[src_write_date={planning_write_token}]"
                if marker in (existing_attachment.description or ""):
                    return existing_attachment

        # Utiliser le système de rapport Odoo
        # Chercher le rapport par son external ID
        try:
            report = planning.env.ref(
                "chc_cds_planning.report_planning_weekly", raise_if_not_found=False
            )
            if not report:
                # Essayer de le trouver par son nom de modèle
                report = planning.env["ir.actions.report"].search(
                    [
                        ("model", "=", "chc_cds_planning.planning_weekly"),
                        ("report_type", "=", "qweb-pdf"),
                    ],
                    limit=1,
                )

            if not report:
                _logger.error(
                    "Le rapport chc_cds_planning.report_planning_weekly n'existe pas"
                )
                return None
        except Exception as e:
            _logger.error(f"Erreur lors de la recherche du rapport: {e}")
            return None

        # Générer le PDF via le rapport
        # _render_qweb_pdf attend le report_ref (external_id string) en premier, puis data et res_ids
        report_ref = "chc_cds_planning.report_planning_weekly"
        pdf_data, _format = report.sudo()._render_qweb_pdf(
            report_ref, data=None, res_ids=[planning.id]
        )

        if not pdf_data:
            _logger.error("Génération PDF échouée : données PDF vides")
            return None

        # Créer l'attachement
        if planning.start_date:
            week_number = planning.start_date.isocalendar()[1]
            year = planning.start_date.year
            filename = f"Planning_S{week_number}_{year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            description = (
                f"Export PDF du planning semaine {week_number}/{year} "
                f"[src_write_date={planning_write_token}]"
            )
        else:
            filename = f"Planning_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            description = f"Export PDF du planning [src_write_date={planning_write_token}]"

        # Encoder les données en base64
        pdf_data_b64 = base64.b64encode(pdf_data).decode("utf-8")

        attachment = planning.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": pdf_data_b64,
                "res_model": "chc_cds_planning.planning_weekly",
                "res_id": planning.id,
                "mimetype": "application/pdf",
                "description": description,
            }
        )

        return attachment

    except Exception as e:
        _logger.error(
            f"Erreur lors de la génération PDF via rapport: {e}", exc_info=True
        )
        return None


def check_time_overlap(assignment1, assignment2):
    """Vérifie si deux affectations ont des horaires qui se chevauchent
    
    RÈGLE SIMPLE : Un employé ne peut faire qu'UNE SEULE permanence par jour.
    Peu importe les périodes (AM, PM, Full), si c'est le même jour = CONFLIT.
    
    Args:
        assignment1: Première affectation
        assignment2: Deuxième affectation
    
    Returns:
        bool: True si les affectations se chevauchent (même jour), False sinon
    """
    # Si les deux assignments sont le même jour, c'est TOUJOURS un conflit
    # Un employé ne peut pas être à deux endroits ou faire deux périodes le même jour
    return assignment1.day == assignment2.day


def get_day_index(day_name):
    """Convertit un nom de jour de la semaine en index (0=lundi, 4=vendredi)
    
    Args:
        day_name: Nom du jour ("monday", "tuesday", etc.)
    
    Returns:
        int: Index du jour (0-4)
    
    Raises:
        ValueError: Si le nom du jour n'est pas valide
    """
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    return days.index(day_name.lower())


def get_date_from_week_start_and_day(week_start_date, day_name):
    """Convertit un jour de la semaine en date à partir d'une date de début de semaine
    
    Args:
        week_start_date: Date de début de la semaine (lundi)
        day_name: Nom du jour ("monday", "tuesday", etc.)
    
    Returns:
        datetime.date: Date correspondant au jour de la semaine
    """
    day_index = get_day_index(day_name)
    return week_start_date + timedelta(days=day_index)


def is_public_holiday(env, target_date, calendar_id=None):
    """Vérifie si une date est un jour férié public
    
    Args:
        env: Environnement Odoo
        target_date: date object à vérifier
        calendar_id: ID du calendrier de travail (optionnel, cherche dans tous les calendriers si None)
    
    Returns:
        bool: True si c'est un jour férié, False sinon
    """
    if not target_date:
        return False

    try:
        # Détection timezone-safe:
        # on convertit la journée locale (00:00→23:59:59) en UTC naïf,
        # puis on cherche un chevauchement sur resource.calendar.leaves.
        user_tz_name = getattr(getattr(env, "user", None), "tz", None) or "UTC"
        if pytz is None:
            user_tz = None
        else:
            try:
                user_tz = pytz.timezone(user_tz_name)
            except Exception:
                user_tz = pytz.UTC

        day_start_local = datetime.combine(target_date, datetime.min.time())
        day_end_local = datetime.combine(target_date, datetime.max.time())

        if user_tz is not None:
            day_start_utc = (
                user_tz.localize(day_start_local)
                .astimezone(pytz.UTC)
                .replace(tzinfo=None)
            )
            day_end_utc = (
                user_tz.localize(day_end_local).astimezone(pytz.UTC).replace(tzinfo=None)
            )
        else:
            # fallback: sans pytz, on compare en naïf (moins précis)
            day_start_utc = day_start_local
            day_end_utc = day_end_local

        domain = [
            ("date_from", "<=", day_end_utc),
            ("date_to", ">=", day_start_utc),
            ("resource_id", "=", False),  # Exclure les congés individuels (seulement jours fériés publics)
        ]

        # Filtrer par calendrier si possible, mais si rien n'est trouvé,
        # fallback sur tous les calendriers (cas fréquent si le "default calendar"
        # n'est pas celui qui porte les jours fériés importés).
        if calendar_id:
            domain_with_calendar = domain + [("calendar_id", "=", calendar_id)]
            if env["resource.calendar.leaves"].search(domain_with_calendar, limit=1):
                return True
            return bool(env["resource.calendar.leaves"].search(domain, limit=1))

        return bool(env["resource.calendar.leaves"].search(domain, limit=1))
    except Exception as e:
        _logger.warning(
            f"Erreur lors de la vérification du jour férié pour {target_date}: {e}"
        )
        return False


def get_public_holiday_emojis(env, target_date, calendar_id=None):
    """Retourne une liste d'emojis pour les jours fériés d'une date."""
    if not target_date:
        return []

    try:
        user_tz_name = getattr(getattr(env, "user", None), "tz", None) or "UTC"
        if pytz is None:
            user_tz = None
        else:
            try:
                user_tz = pytz.timezone(user_tz_name)
            except Exception:
                user_tz = pytz.UTC

        day_start_local = datetime.combine(target_date, datetime.min.time())
        day_end_local = datetime.combine(target_date, datetime.max.time())

        if user_tz is not None:
            day_start_utc = (
                user_tz.localize(day_start_local)
                .astimezone(pytz.UTC)
                .replace(tzinfo=None)
            )
            day_end_utc = (
                user_tz.localize(day_end_local).astimezone(pytz.UTC).replace(tzinfo=None)
            )
        else:
            day_start_utc = day_start_local
            day_end_utc = day_end_local

        base_domain = [
            ("date_from", "<=", day_end_utc),
            ("date_to", ">=", day_start_utc),
            ("resource_id", "=", False),  # Exclure les congés individuels (seulement jours fériés publics)
        ]

        if calendar_id:
            holidays = env["resource.calendar.leaves"].search(
                base_domain + [("calendar_id", "=", calendar_id)]
            )
            if not holidays:
                holidays = env["resource.calendar.leaves"].search(base_domain)
        else:
            holidays = env["resource.calendar.leaves"].search(base_domain)

        def _emoji_for_name(name: str) -> str:
            n = (name or "").lower()
            if "noël" in n or "noel" in n:
                return "🎄"
            if "jour de l'an" in n or "nouvel an" in n or "nouvel-an" in n:
                return "🎆"
            if "lundi de pâques" in n or "lundi de paques" in n:
                return "🥚"
            if "pâques" in n or "paques" in n:
                return "🐰"
            if "ascension" in n:
                return "♨️"
            if "pentecôte" in n or "pentecote" in n:
                return "🕊️"
            if "assomption" in n:
                return "⛪"
            if "toussaint" in n:
                return "🎃"
            if "armistice" in n:
                return "🤝"
            if "travail" in n or "1er mai" in n:
                return "🛠️"
            if "nationale" in n or "21 juillet" in n:
                return "🍺"
            return "🎉"

        deduped = []
        for h in holidays:
            e = _emoji_for_name(getattr(h, "name", ""))
            if e not in deduped:
                deduped.append(e)
        return deduped[:3]
    except Exception as e:
        _logger.warning(
            f"Erreur lors de la récupération des emojis jours fériés pour {target_date}: {e}"
        )
        return []


def is_employee_available_for_day(env, employee, week_start_date, day_name):
    """Vérifie si un employé est disponible un jour donné dans une semaine
    
    Vérifie les congés, les contraintes d'indisponibilité et les jours fériés.
    
    Args:
        env: Environnement Odoo
        employee: Enregistrement hr.employee
        week_start_date: Date de début de la semaine (lundi)
        day_name: Nom du jour ("monday", "tuesday", etc.)
    
    Returns:
        bool: True si l'employé est disponible, False sinon
    """
    if not week_start_date:
        return True

    try:
        # Convertir le jour en date
        target_date = get_date_from_week_start_and_day(week_start_date, day_name)
        day_index = get_day_index(day_name)

        # Vérifier les jours fériés publics (si c'est un jour férié, l'employé n'est pas disponible)
        # Récupérer le calendrier de travail de l'employé si disponible
        calendar_id = None
        if hasattr(employee, 'resource_calendar_id') and employee.resource_calendar_id:
            calendar_id = employee.resource_calendar_id.id
        
        if is_public_holiday(env, target_date, calendar_id):
            return False

        # Vérifier les congés
        leaves = env["hr.leave"].search(
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
        unavailabilities = env["chc_cds_planning.employee_unavailability"].search(
            [
                ("employee_id", "=", employee.id),
                ("day_of_week", "=", str(day_index)),
            ]
        )

        return not unavailabilities

    except Exception:
        # En cas d'erreur, considérer comme disponible
        return True

