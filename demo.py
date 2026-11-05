"""Jeu de données de démonstration : une SASU de conseil et un foyer."""
from compta import pcg, bank, business, auth, sales, expenses, payroll, db

ENT_CSV = """Date;Libellé;Débit;Crédit
05/01/2026;VIR SEPA CLIENT ACME FACTURE FA-2026-0001;;6000,00
06/01/2026;PRLV URSSAF COTISATIONS;820,00;
08/01/2026;CB OVH CLOUD;35,88;
10/01/2026;PRLV LOYER BUREAU REGUS;1200,00;
12/01/2026;CB RESTAURANT LE PETIT ZINC;84,50;
15/01/2026;CB SNCF VOYAGES;142,00;
18/01/2026;PRLV ORANGE PRO;59,99;
20/01/2026;CB GOOGLE ADS;300,00;
25/01/2026;FRAIS TENUE DE COMPTE;12,00;
28/01/2026;PRLV AXA ASSURANCE RC PRO;95,00;
02/02/2026;VIR STRIPE PAYOUT;;2400,00
04/02/2026;CB MYSTERE SARL;230,00;
"""

PAR_CSV = """date,libelle,montant
2026-01-02,VIR SALAIRE ENTREPRISE XYZ,2950.00
2026-01-03,PRLV LOYER FONCIA,-950.00
2026-01-05,CB CARREFOUR MARKET,-123.45
2026-01-09,CB PHARMACIE CENTRALE,-18.90
2026-01-12,PRLV NETFLIX,-13.49
2026-01-15,DON RESTOS DU COEUR,-100.00
2026-01-20,PAJEMPLOI CRECHE,-420.00
2026-01-25,CESU MENAGE,-250.00
2026-02-02,VIR SALAIRE ENTREPRISE XYZ,2950.00
"""

def load(con):
    e1 = con.execute("INSERT INTO entities(name,kind,legal_form,tva_regime,siret,address) VALUES(?,?,?,?,?,?)",
                     ("Studio Conseil SASU", "entreprise", "SASU", "reel", "123 456 789 00012", "10 rue de la République, 69002 Lyon")).lastrowid
    pcg.seed(con, e1, "entreprise")
    business.create_invoice(con, e1, "sale", "ACME SA", "2026-01-03", [{"label": "Mission de conseil — janvier", "qty": 5, "unit_price": 1000, "tva_rate": 20}])
    business.create_invoice(con, e1, "sale", "Beta SAS", "2026-02-10", [{"label": "Audit", "qty": 1, "unit_price": 1500, "tva_rate": 20}], due="2026-03-10")
    business.add_asset(con, e1, "MacBook Pro", "2026-01-15", 2400, 3)
    bank.import_rows(con, e1, bank.parse_csv(ENT_CSV))
    e2 = con.execute("INSERT INTO entities(name,kind,tva_regime) VALUES(?,?,?)", ("Foyer Martin", "particulier", "aucune")).lastrowid
    pcg.seed(con, e2, "particulier")
    bank.import_rows(con, e2, bank.parse_csv(PAR_CSV))
    bank.validate_confident(con, e2, .8)
    # Utilisateurs et rôles
    owner = auth.create_user(con, "demo@comptaia.fr", "Valentin (dirigeant)", "demo-compta", is_admin=False)
    cpt = auth.create_user(con, "comptable@cabinet.fr", "Cabinet Durand (comptable)", "demo-compta")
    for eid in (e1, e2):
        con.execute("INSERT INTO memberships(user_id,entity_id,role) VALUES(?,?,'proprietaire')", (owner, eid))
    con.execute("INSERT INTO memberships(user_id,entity_id,role) VALUES(?,?,'comptable')", (cpt, e1))
    # Paie, devis, notes de frais
    db.set_setting(con, e1, "effectif", 1)
    db.set_setting(con, e1, "edi_mode", "sandbox")
    con.execute("INSERT INTO employees(entity_id,nom,prenom,nir,naissance,emploi,statut,contrat,date_entree,brut,mutuelle) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (e1, "Durand", "Alice", "2850375123456", "1985-03-12", "Consultante junior", "non-cadre", "CDI", "2025-09-01", 280000, 6000))
    payroll.run_payroll(con, e1, "2026-01")
    q = sales.create_quote(con, e1, "Gamma SAS", "2026-02-15", [{"label": "Refonte du site web", "qty": 1, "unit_price": 3000},
                                                                 {"label": "Maintenance mensuelle", "qty": 12, "unit_price": 49}], email="compta@gamma.fr")
    sales.set_quote_status(con, e1, q, "envoye")
    con.execute("UPDATE invoices SET email='factures@beta-sas.fr' WHERE entity_id=? AND party='Beta SAS'", (e1,))
    expenses.create(con, e1, "2026-01-22", "Valentin", "Déjeuner client — Brasserie Georges", "restaurant", ttc=68.40)
    expenses.create(con, e1, "2026-01-29", "Valentin", "", "", km=186, cv=5)
    con.commit()
