"""Plans comptables : Plan Comptable Général (règlement ANC 2014-03 modifié par 2022-06) et plan budgétaire particulier.
(code, libellé, taux de TVA par défaut en %). Les comptes de tiers individuels (411xxxx / 401xxxx) sont créés à la volée."""

ENTREPRISE = [
 # ---- Classe 1 : capitaux
 ("101","Capital",0),("1013","Capital souscrit - appelé, versé",0),("104","Primes liées au capital",0),("105","Écarts de réévaluation",0),
 ("106","Réserves",0),("1061","Réserve légale",0),("1063","Réserves statutaires",0),("1068","Autres réserves",0),
 ("108","Compte de l'exploitant",0),("110","Report à nouveau (solde créditeur)",0),("119","Report à nouveau (solde débiteur)",0),
 ("120","Résultat de l'exercice (bénéfice)",0),("129","Résultat de l'exercice (perte)",0),("131","Subventions d'équipement",0),
 ("139","Subventions d'investissement inscrites au compte de résultat",0),("145","Amortissements dérogatoires",0),
 ("151","Provisions pour risques",0),("153","Provisions pour pensions et obligations similaires",0),("158","Autres provisions pour charges",0),
 ("164","Emprunts auprès des établissements de crédit",0),("165","Dépôts et cautionnements reçus",0),("1681","Autres emprunts",0),
 ("1688","Intérêts courus sur emprunts",0),
 # ---- Classe 2 : immobilisations
 ("201","Frais d'établissement",0),("203","Frais de recherche et de développement",0),("205","Concessions, brevets, licences, logiciels",0),
 ("206","Droit au bail",0),("207","Fonds commercial",0),("211","Terrains",0),("213","Constructions",0),
 ("215","Installations techniques, matériel et outillage",0),("2181","Installations générales, agencements",0),
 ("2182","Matériel de transport",0),("2183","Matériel de bureau et informatique",0),("2184","Mobilier",0),
 ("231","Immobilisations corporelles en cours",0),("261","Titres de participation",0),("271","Titres immobilisés",0),
 ("275","Dépôts et cautionnements versés",0),("280","Amortissements des immobilisations incorporelles",0),
 ("281","Amortissements des immobilisations corporelles",0),("2813","Amortissements des constructions",0),
 ("28182","Amortissements du matériel de transport",0),("28183","Amortissements du matériel informatique",0),("28184","Amortissements du mobilier",0),
 ("291","Dépréciations des immobilisations corporelles",0),("296","Dépréciations des titres de participation",0),
 # ---- Classe 3 : stocks
 ("31","Matières premières",0),("32","Autres approvisionnements",0),("33","En-cours de production de biens",0),("35","Stocks de produits",0),
 ("37","Stocks de marchandises",0),("391","Dépréciations des matières premières",0),("397","Dépréciations des stocks de marchandises",0),
 # ---- Classe 4 : tiers
 ("401","Fournisseurs",0),("403","Fournisseurs - effets à payer",0),("404","Fournisseurs d'immobilisations",0),("408","Fournisseurs - factures non parvenues",0),
 ("409","Fournisseurs débiteurs (avances, avoirs à recevoir)",0),("411","Clients",0),("413","Clients - effets à recevoir",0),
 ("416","Clients douteux ou litigieux",0),("418","Clients - produits non encore facturés",0),("419","Clients créditeurs (avances reçues)",0),
 ("421","Personnel - rémunérations dues",0),("425","Personnel - avances et acomptes",0),("427","Personnel - oppositions",0),
 ("428","Personnel - charges à payer (congés payés)",0),("431","Sécurité sociale / URSSAF",0),
 ("437","Autres organismes sociaux (retraite, prévoyance, mutuelle)",0),("438","Organismes sociaux - charges à payer",0),
 ("4421","Prélèvement à la source (impôt sur le revenu)",0),("444","État - impôt sur les bénéfices",0),("445","État - TVA",0),
 ("44551","TVA à décaisser",0),("44562","TVA déductible sur immobilisations",0),("44566","TVA déductible sur biens et services",0),
 ("445662","TVA déductible intracommunautaire",0),("44567","Crédit de TVA à reporter",0),("44571","TVA collectée",0),
 ("4452","TVA due intracommunautaire / autoliquidée",0),("44574","TVA collectée en attente (encaissements)",0),
 ("44581","Acomptes de TVA (régime simplifié)",0),("44583","Remboursement de crédit de TVA demandé",0),
 ("44586","TVA déductible en attente (encaissements)",0),("4458","TVA à régulariser",0),("447","Autres impôts, taxes et versements assimilés",0),
 ("448","État - charges à payer",0),("451","Groupe",0),("455","Associés - comptes courants",0),("457","Associés - dividendes à payer",0),
 ("462","Créances sur cessions d'immobilisations",0),("467","Notes de frais à rembourser",0),("468","Divers - charges à payer et produits à recevoir",0),
 ("471","Compte d'attente",0),("476","Différences de conversion - actif",0),("477","Différences de conversion - passif",0),
 ("486","Charges constatées d'avance",0),("487","Produits constatés d'avance",0),("491","Dépréciations des comptes clients",0),
 # ---- Classe 5 : financiers
 ("503","Valeurs mobilières de placement - actions",0),("508","Autres valeurs mobilières",0),("511","Valeurs à l'encaissement",0),
 ("512","Banque",0),("5121","Banque - compte secondaire",0),("514","Chèques postaux",0),("517","Autres organismes financiers (Stripe, PayPal…)",0),
 ("519","Concours bancaires courants",0),("530","Caisse",0),("580","Virements internes",0),("590","Dépréciations des VMP",0),
 # ---- Classe 6 : charges
 ("601","Achats de matières premières",20),("602","Achats d'autres approvisionnements",20),("6037","Variation des stocks de marchandises",0),
 ("604","Achats d'études et prestations de services",20),("605","Achats de matériel, équipements et travaux",20),
 ("606","Achats non stockés (énergie, fournitures)",20),("6061","Fournitures non stockables (eau, énergie)",20),("6063","Petit équipement",20),
 ("6064","Fournitures administratives",20),("607","Achats de marchandises",20),("609","Rabais, remises, ristournes obtenus",20),
 ("611","Sous-traitance générale",20),("612","Redevances de crédit-bail",20),("613","Locations",20),("6132","Locations immobilières",20),
 ("6135","Locations mobilières",20),("614","Charges locatives et de copropriété",20),("615","Entretien et réparations",20),
 ("616","Primes d'assurance",0),("617","Études et recherches",20),("618","Documentation, séminaires, divers",20),
 ("621","Personnel extérieur à l'entreprise",20),("622","Honoraires",20),("6226","Honoraires (expert-comptable, avocat)",20),
 ("623","Publicité, publications",20),("6234","Cadeaux à la clientèle",20),("624","Transports de biens",20),
 ("625","Déplacements, missions",20),("6251","Indemnités kilométriques",0),("6256","Missions (hébergement, repas)",10),
 ("6257","Réceptions et restaurant",10),("626","Frais postaux et télécommunications",20),("627","Services bancaires",0),
 ("628","Divers services extérieurs (abonnements, logiciels)",20),("6281","Cotisations professionnelles",0),
 ("631","Taxes sur rémunérations (administration des impôts)",0),("633","Taxes sur rémunérations (autres organismes)",0),
 ("635","Impôts et taxes (CFE, etc.)",0),("63511","Cotisation foncière des entreprises (CFE)",0),("6354","Droits d'enregistrement",0),
 ("637","Autres impôts et taxes",0),("641","Rémunérations du personnel",0),("6411","Salaires et appointements",0),
 ("6412","Congés payés",0),("6413","Primes et gratifications",0),("644","Rémunération du travail de l'exploitant / dirigeant",0),
 ("645","Charges sociales",0),("6451","Cotisations URSSAF",0),("6453","Cotisations aux caisses de retraite",0),
 ("646","Cotisations sociales personnelles de l'exploitant",0),("647","Autres charges sociales (mutuelle, médecine du travail)",0),
 ("648","Autres charges de personnel",0),("651","Redevances pour concessions, brevets, licences",20),("654","Pertes sur créances irrécouvrables",0),
 ("658","Charges diverses de gestion courante",0),("661","Charges d'intérêts",0),("6615","Intérêts des comptes courants",0),
 ("665","Escomptes accordés",0),("666","Pertes de change",0),("668","Autres charges financières",0),
 ("671","Charges exceptionnelles sur opérations de gestion",0),("6712","Pénalités et amendes",0),
 ("675","Valeurs comptables des éléments d'actif cédés",0),("678","Autres charges exceptionnelles",0),
 ("681","Dotations aux amortissements et provisions - exploitation",0),("6811","Dotations aux amortissements des immobilisations",0),
 ("6815","Dotations aux provisions d'exploitation",0),("6817","Dotations aux dépréciations des actifs circulants",0),
 ("686","Dotations financières",0),("687","Dotations exceptionnelles",0),("691","Participation des salariés",0),
 ("695","Impôt sur les bénéfices",0),("699","Produits - reports en arrière des déficits",0),
 # ---- Classe 7 : produits
 ("701","Ventes de produits finis",20),("704","Travaux",20),("706","Prestations de services",20),("707","Ventes de marchandises",20),
 ("7071","Ventes de marchandises - UE (exonérées)",0),("7072","Ventes de marchandises - export",0),("7061","Prestations de services - UE (autoliquidation)",0),
 ("708","Produits des activités annexes",20),("709","Rabais, remises, ristournes accordés",20),("713","Variation des stocks (en-cours, produits)",0),
 ("72","Production immobilisée",0),("74","Subventions d'exploitation",0),("752","Revenus des immeubles non affectés",0),
 ("758","Produits divers de gestion courante",0),("761","Produits de participations",0),("762","Produits des autres immobilisations financières",0),
 ("764","Revenus des valeurs mobilières de placement",0),("765","Escomptes obtenus",0),("766","Gains de change",0),
 ("768","Autres produits financiers",0),("771","Produits exceptionnels sur opérations de gestion",0),
 ("775","Produits des cessions d'éléments d'actif",0),("777","Quote-part des subventions d'investissement virée au résultat",0),
 ("778","Autres produits exceptionnels",0),("781","Reprises sur amortissements et provisions - exploitation",0),
 ("786","Reprises sur provisions financières",0),("787","Reprises sur provisions exceptionnelles",0),("791","Transferts de charges d'exploitation",0),
 # ---- Classe 8 : engagements (hors bilan)
 ("801","Engagements donnés",0),("802","Engagements reçus",0),("809","Contrepartie des engagements",0),
]

PARTICULIER = [
 ("512","Compte courant",0),("5121","Livret / épargne",0),("530","Espèces",0),("471","Compte d'attente",0),
 ("700","Salaires et traitements",0),("701","Pensions et retraites",0),("702","Allocations chômage",0),("703","Indemnités journalières",0),
 ("710","Revenus fonciers (loyers)",0),("711","Revenus non commerciaux (BNC)",0),("712","Revenus commerciaux (BIC)",0),
 ("720","Revenus de capitaux mobiliers",0),("721","Plus-values de cession de titres",0),("730","Prestations sociales (CAF, APL)",0),
 ("740","Pensions alimentaires reçues",0),("790","Autres revenus",0),
 ("600","Logement (loyer, crédit, charges)",0),("601","Énergie et eau",0),("605","Charges foncières (bien loué)",0),("606","Intérêts d'emprunt (bien loué)",0),
 ("610","Alimentation",0),("620","Transport",0),("621","Véhicule (carburant, entretien, assurance)",0),("630","Santé",0),
 ("640","Loisirs et culture",0),("645","Abonnements (téléphone, internet, streaming)",0),("650","Impôts et taxes",0),
 ("660","Dons aux associations (66 %)",0),("661","Dons aux organismes d'aide aux personnes (75 %)",0),("670","Garde d'enfants hors domicile",0),
 ("680","Emploi à domicile (ménage, soutien scolaire)",0),("690","Scolarité et formation",0),("691","Pension alimentaire versée",0),
 ("692","Versements PER (épargne retraite)",0),("695","Assurances",0),("699","Autres dépenses",0),
]

def chart(kind):
    return ENTREPRISE if kind == "entreprise" else PARTICULIER

def seed(con, entity_id, kind):
    con.executemany("INSERT OR IGNORE INTO accounts(entity_id,code,label,tva_rate) VALUES(?,?,?,?)",
                    [(entity_id, c, l, t) for c, l, t in chart(kind)])

def classe(code):
    return {"1": "Capitaux", "2": "Immobilisations", "3": "Stocks", "4": "Tiers", "5": "Financiers", "6": "Charges", "7": "Produits", "8": "Engagements"}.get(code[:1], "")
