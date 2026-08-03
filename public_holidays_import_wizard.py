<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_template_wizard_form" model="ir.ui.view">
        <field name="name">chc_cds_planning.planning_template_wizard.form</field>
        <field name="model">chc_cds_planning.planning_template_wizard</field>
        <field name="arch" type="xml">
            <form string="Assistant modèle de planning">
                <sheet>
                    <!-- Champ requis pour les conditions -->
                    <field name="action" invisible="1" />

                    <!-- application -->
                    <group>
                        <field name="template_id" required="1"
                            options="{'no_create': True, 'no_edit': True}"
                            invisible="action != 'apply'" />
                        <field name="planning_id" required="1"
                            options="{'no_create': True, 'no_edit': True}"
                            invisible="action != 'apply'" />
                        <field name="replace_existing" invisible="action != 'apply'" />
                        <field name="check_availability" invisible="action != 'apply'" />
                    </group>

                    <!-- sauvegarde -->
                    <group>
                        <field name="planning_id" readonly="1" invisible="action != 'save'" />
                        <field name="new_template_name" required="1" invisible="action != 'save'" />
                        <field name="set_new_as_default" invisible="action != 'save'" />
                        <field name="new_template_description" invisible="action != 'save'" />
                    </group>

                </sheet>

                <footer>
                    <button name="action_apply_template"
                        string="Appliquer"
                        type="object"
                        class="btn-primary"
                        invisible="action != 'apply'"
                        context="{'set_action': 'apply'}" />

                    <button name="action_save_template"
                        string="Créer le modèle"
                        type="object"
                        class="btn-primary"
                        invisible="action != 'save'"
                        context="{'set_action': 'save'}" />

                    <button string="Annuler" class="btn-secondary" special="cancel" />
                </footer>
            </form>
        </field>
    </record>
</odoo>