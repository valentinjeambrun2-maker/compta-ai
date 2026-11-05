"""Jeu de données de démonstration : une SASU de conseil et un foyer."""
from compta import pcg, bank, business

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
    con.commit()
