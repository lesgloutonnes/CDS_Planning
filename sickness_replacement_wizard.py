<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_public_holidays_import_wizard_form" model="ir.ui.view">
        <field name="name">chc_cds_planning.public_holidays_import_wizard.form</field>
        <field name="model">chc_cds_planning.public_holidays_import_wizard</field>
        <field name="arch" type="xml">
            <form string="Importer les jours fériés publics">
                <sheet>
                    <group>
                        <group>
                            <field name="year" />
                            <field name="country_id" />
                            <field name="calendar_id" 
                                   options="{'no_create': True}"
                                   help="Calendrier de travail pour lequel importer les jours fériés. Si vide, utilise le calendrier par défaut." />
                        </group>
                    </group>
                    <div class="alert alert-info" role="alert">
                        <p>
                            <strong>Information :</strong> Ce wizard importe automatiquement 
                            les jours fériés belges pour l'année sélectionnée.
                        </p>
                        <p>
                            Les jours fériés suivants seront importés :
                        </p>
                        <ul>
                            <li>Jour de l'an (1er janvier)</li>
                            <li>Lundi de Pâques</li>
                            <li>Fête du Travail (1er mai)</li>
                            <li>Ascension</li>
                            <li>Lundi de Pentecôte</li>
                            <li>Fête Nationale belge (21 juillet)</li>
                            <li>Assomption (15 août)</li>
                            <li>Toussaint (1er novembre)</li>
                            <li>Armistice (11 novembre)</li>
                            <li>Noël (25 décembre)</li>
                        </ul>
                    </div>
                </sheet>
                <footer>
                    <button
                        name="action_import_holidays"
                        string="Importer"
                        type="object"
                        class="btn-primary"
                    />
                    <button string="Annuler" class="btn-secondary" special="cancel" />
                </footer>
            </form>
        </field>
    </record>

    <record id="action_public_holidays_import_wizard" model="ir.actions.act_window">
        <field name="name">Importer les jours fériés</field>
        <field name="res_model">chc_cds_planning.public_holidays_import_wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
    </record>
</odoo>
