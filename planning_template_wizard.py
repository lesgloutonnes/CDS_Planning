<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_planning_confirm_override_wizard_form" model="ir.ui.view">
        <field name="name">chc_cds_planning.confirm_override_wizard.form</field>
        <field name="model">chc_cds_planning.confirm_override_wizard</field>
        <field name="arch" type="xml">
            <form string="Erreur de validation">
                <sheet>
                    <group>
                        <label for="error_message" string="Détails des erreurs" />
                        <field name="error_message" nolabel="1" readonly="1" />
                    </group>
                </sheet>
                <footer>
                    <button name="action_force_confirm" type="object"
                        string="Confirmer de force" class="btn-warning" />
                    <button string="Annuler" special="cancel" class="btn-secondary" />
                </footer>
            </form>
        </field>
    </record>
</odoo>
