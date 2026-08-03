/** @odoo-module **/

import { Component, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";

const SESSION_PLANNING_ID_KEY = "chc_cds_planning.last_visual_planning_id";

class VisualPlanningClientAction extends Component {
    static template = "chc_cds_planning.VisualPlanningClientAction";

    setup() {
        this.iframeRef = useRef("iframe");
        onMounted(() => {
            const planningId = this._getPlanningId();
            const iframe = this.iframeRef.el;
            if (!iframe) {
                return;
            }
            if (!planningId) {
                iframe.srcdoc = `<div style="padding:16px;font-family:system-ui">Planning ID manquant.</div>`;
                return;
            }
            this._rememberPlanningId(planningId);
            iframe.src = `/web/planning/${planningId}?embedded=1`;
        });
    }

    /**
     * Garde le dernier planning affiché par onglet : survit à un F5 lorsque le client Odoo
     * réécrit le hash sans conserver planning_id.
     */
    _rememberPlanningId(id) {
        try {
            sessionStorage.setItem(SESSION_PLANNING_ID_KEY, String(id));
        } catch {
            // quota / navigation privée : ignorer
        }
    }

    _parsePositiveInt(value) {
        const n = Number(value);
        if (!Number.isFinite(n) || n <= 0 || !Number.isInteger(n)) {
            return null;
        }
        return n;
    }

    _getPlanningIdFromSession() {
        try {
            const raw = sessionStorage.getItem(SESSION_PLANNING_ID_KEY);
            return raw ? this._parsePositiveInt(raw) : null;
        } catch {
            return null;
        }
    }

    _getPlanningId() {
        // 1) Depuis les params d'action (selon le routeur)
        const fromParams = this.props?.action?.params?.planning_id;
        const parsedParams = this._parsePositiveInt(fromParams);
        if (parsedParams) {
            return parsedParams;
        }
        // 2) Depuis le hash (/web#...&planning_id=123)
        const hash = window.location.hash || "";
        const query = hash.includes("?") ? hash.split("?")[1] : hash.replace(/^#/, "");
        const params = new URLSearchParams(query);
        const fromHash = params.get("planning_id");
        const parsedHash = this._parsePositiveInt(fromHash);
        if (parsedHash) {
            return parsedHash;
        }
        // 3) Repli après F5 : hash réduit à action=…&cids=… sans planning_id
        return this._getPlanningIdFromSession();
    }
}

registry.category("actions").add("chc_cds_planning.visual_planning", VisualPlanningClientAction);

