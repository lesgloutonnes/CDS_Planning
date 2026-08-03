/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { TimeOffCalendarModel } from "@hr_holidays/views/calendar/calendar_model";

/**
 * Affiche toujours le type de congé dans le titre des événements du calendrier.
 *
 * Problème :
 *   1. Le champ holiday_status_id n'est pas inclus dans les champs fetchés par
 *      le calendrier (rawRecord.holiday_status_id === undefined).
 *   2. TimeOffCalendarModel.normalizeRecord préfixe le titre avec employee_id[1],
 *      doublant le nom de l'employé quand display_name contient déjà le nom.
 *
 * Correctifs :
 *   - fetchRecords : ajoute holiday_status_id à la liste des champs demandés.
 *   - normalizeRecord : construit le titre à partir de display_name (calculé côté
 *     Python avec le type) ; si display_name n'inclut pas déjà le type, le préfixe
 *     avec holiday_status_id[1].
 */
patch(TimeOffCalendarModel.prototype, {
    async fetchRecords(data) {
        const result = await super.fetchRecords(data);
        // holiday_status_id n'est pas toujours dans fieldNames ; on relit les
        // enregistrements avec ce champ pour que normalizeRecord puisse l'utiliser.
        if (result.length && result[0].holiday_status_id === undefined) {
            const ids = result.map((r) => r.id);
            const extra = await this.orm.read("hr.leave", ids, ["holiday_status_id"]);
            const byId = Object.fromEntries(extra.map((r) => [r.id, r.holiday_status_id]));
            result.forEach((r) => {
                r.holiday_status_id = byId[r.id];
            });
        }
        return result;
    },

    normalizeRecord(rawRecord) {
        const result = super.normalizeRecord(rawRecord);

        const typeName =
            rawRecord.holiday_status_id && rawRecord.holiday_status_id[1]
                ? rawRecord.holiday_status_id[1]
                : null;

        // display_name calculé par Python contient déjà le type si tout va bien ;
        // sinon on le préfixe manuellement depuis holiday_status_id[1].
        if (rawRecord.display_name) {
            if (typeName && !rawRecord.display_name.startsWith(typeName)) {
                result.title = `${typeName} – ${rawRecord.display_name}`;
            } else {
                result.title = rawRecord.display_name;
            }
        }

        return result;
    },
});
