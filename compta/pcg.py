"""Plans comptables : PCG simplifié (entreprise) et plan budgétaire (particulier).
(code, libellé, taux de TVA par défaut en %)"""

ENTREPRISE = [
 ("101","Capital",0),("108","Compte de l'exploitant",0),("119","Report à nouveau",0),("164","Emprunts auprès des établissements de crédit",0),
 ("2183","Matériel de bureau et informatique",0),("2184","Mobilier",0),("2182","Matériel de transport",0),("281","Amortissements des immobilisations corporelles",0),
 ("401","Fournisseurs",0),("411","Clients",0),("421","Personnel - rémunérations dues",0),("431","Sécurité sociale / URSSAF",0),
 ("44551","TVA à décaisser",0),("44566","TVA déductible sur biens et services",0),("44567","Crédit de TVA à reporter",0),("44571","TVA collectée",0),
 ("455","Associés - comptes courants",0),("471","Compte d'attente",0),("512","Banque",0),("530","Caisse",0),
 ("606","Achats non stockés (énergie, fournitures)",20),("607","Achats de marchandises",20),("611","Sous-traitance générale",20),
 ("613","Locations",20),("615","Entretien et réparations",20),("616","Primes d'assurance",0),("618","Documentation, divers",20),
 ("622","Honoraires",20),("623","Publicité, publications",20),("625","Déplacements, missions",20),("6257","Réceptions et restaurant",10),
 ("626","Frais postaux et télécommunications",20),("627","Services bancaires",0),("628","Divers services extérieurs",20),
 ("635","Impôts et taxes (CFE, etc.)",0),("641","Rémunérations du personnel",0),("645","Charges sociales",0),("646","Cotisations sociales exploitant",0),
 ("661","Charges d'intérêts",0),("681","Dotations aux amortissements",0),("695","Impôt sur les bénéfices",0),
 ("706","Prestations de services",20),("707","Ventes de marchandises",20),("708","Produits des activités annexes",20),
 ("758","Produits divers de gestion",0),("761","Produits financiers",0),
]

PARTICULIER = [
 ("512","Compte courant",0),("530","Espèces",0),("471","Compte d'attente",0),
 ("700","Salaires et traitements",0),("701","Pensions et retraites",0),("710","Revenus fonciers (loyers)",0),("711","Revenus non commerciaux (BNC)",0),
 ("712","Revenus commerciaux (BIC)",0),("720","Revenus de capitaux mobiliers",0),("790","Autres revenus",0),
 ("600","Logement (loyer, crédit, charges)",0),("610","Alimentation",0),("620","Transport",0),("630","Santé",0),("640","Loisirs et culture",0),
 ("650","Impôts et taxes",0),("660","Dons aux associations",0),("670","Garde d'enfants hors domicile",0),("680","Emploi à domicile (ménage, soutien scolaire)",0),
 ("690","Scolarité et formation",0),("695","Assurances",0),("699","Autres dépenses",0),
]

def chart(kind):
    return ENTREPRISE if kind == "entreprise" else PARTICULIER

def seed(con, entity_id, kind):
    con.executemany("INSERT OR IGNORE INTO accounts(entity_id,code,label,tva_rate) VALUES(?,?,?,?)",
                    [(entity_id, c, l, t) for c, l, t in chart(kind)])
