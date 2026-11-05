# ComptaIA — comptabilité et fiscalité automatisées par l'IA

Logiciel de comptabilité **pour entreprises et particuliers**, avec catégorisation bancaire par IA,
facturation, états financiers, TVA, clôture, et **préparation automatique des déclarations d'impôts**.

Zéro dépendance : Python 3.10+ et SQLite (bibliothèque standard).

## Démarrer

```bash
python3 server.py --demo        # http://127.0.0.1:8000 avec 2 dossiers de démonstration
```

Pour activer l'IA générative (Claude) :

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # optionnel : COMPTA_MODEL=claude-opus-5-5
python3 server.py
```

Sans clé, un moteur de règles local prend le relais (aucune donnée ne quitte la machine).

Tests : `python3 -m unittest discover tests`

## Fonctionnalités

| Domaine | Ce que fait le logiciel |
|---|---|
| **Comptabilité en partie double** | Plan comptable PCG (entreprise) ou budgétaire (particulier), journaux VE/AC/BQ/OD, refus des écritures déséquilibrées, verrouillage des périodes clôturées, montants en centimes entiers (aucune erreur d'arrondi). |
| **Banque + IA** | Import CSV de n'importe quelle banque (détection auto des colonnes, formats de date et de nombre), dédoublonnage, catégorisation IA avec score de confiance, ventilation HT/TVA automatique, **lettrage automatique** avec les factures ouvertes (pas de double comptage du CA). |
| **Facturation** | Factures de vente à numérotation continue obligatoire, mentions légales, impression PDF, factures d'achat, extraction IA depuis le texte d'une facture fournisseur, suivi des règlements et des retards. |
| **États financiers** | Balance, grand livre, compte de résultat, bilan (contrôle d'équilibre), tableau de bord mensuel. |
| **TVA** | Déclaration CA3 par taux (20 / 10 / 5,5 %), écriture de liquidation, gestion de la franchise en base. |
| **Impôts** | IR complet (quotient familial et son plafonnement, décote, abattement 10 %, micro-BIC/BNC, micro-foncier, PFU, prélèvements sociaux, dons, emploi à domicile, garde d'enfants) avec **cases 2042 pré-remplies depuis les opérations bancaires** ; IS (15 % / 25 %) et acomptes ; cotisations micro-entrepreneur. |
| **Clôture** | Amortissements linéaires prorata temporis, IS comptabilisé, verrouillage de l'exercice, export **FEC** conforme (18 colonnes). |
| **Audit IA** | Revue automatique type expert-comptable : balance, compte d'attente, découvert, factures échues, ruptures de numérotation, frais de réception, seuil de franchise TVA, biens à immobiliser. |
| **Assistant** | Questions en langage naturel sur le dossier (TVA, résultat, optimisation…). |

## Télédéclaration : ce qui est automatique et ce qui ne l'est pas

Le logiciel **calcule, contrôle et prépare** chaque déclaration, puis :

* **TVA / IS (professionnels)** : dépôt automatique via le connecteur EDI (`compta/filing.py`) dès qu'un
  **partenaire EDI agréé DGFiP** est configuré (`EDI_PARTNER_URL`, `EDI_PARTNER_TOKEN`). La DGFiP n'accepte
  les dépôts automatisés que par ce canal.
* **IR (particuliers)** : la DGFiP ne propose **aucune API** de dépôt. Le logiciel fournit les cases exactes
  et un guide pas-à-pas pour la saisie sur impots.gouv.fr (environ 5 minutes).

## Limites à connaître avant un usage réel

* **Barèmes fiscaux** : paramétrés dans `compta/tax.py` (revenus 2025). Ils doivent être vérifiés et mis à jour
  à chaque loi de finances ; les numéros de cases sont indicatifs.
* **Cas non couverts** : paie complète (DSN), liasse fiscale 2033/2050 au format EDI-TDFC, TVA sur les encaissements,
  revenus fonciers au réel (2044), plus-values, IFI, multi-devises, consolidation.
* **Sécurité** : le serveur écoute sur `127.0.0.1` sans authentification. Avant toute mise en ligne : comptes
  utilisateurs, HTTPS, chiffrement et sauvegardes de la base.
* **Juridique** : en France, la tenue de comptabilité pour autrui et la certification sont réservées aux
  experts-comptables (ordonnance de 1945). Cet outil permet à une entreprise ou un particulier de tenir **sa
  propre** comptabilité ; il ne se substitue pas à la responsabilité d'un professionnel pour les dossiers complexes.

## Architecture

```
server.py            API REST + fichiers statiques (http.server)
compta/db.py         schéma SQLite
compta/pcg.py        plans comptables
compta/ledger.py     moteur en partie double, états, FEC
compta/bank.py       import CSV, lettrage, comptabilisation
compta/ai.py         catégorisation, extraction de factures, assistant (Claude ou règles)
compta/tax.py        IR, IS, CA3, micro-entreprise
compta/business.py   factures, immobilisations, clôture, audit, pré-remplissage 2042
compta/filing.py     préparation et dépôt des déclarations (connecteur EDI)
static/index.html    interface web
tests/               tests unitaires
```
