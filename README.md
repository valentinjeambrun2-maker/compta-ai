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

Ou placez les variables dans un fichier `.env` **à la racine du projet** (à côté de `server.py`) :

```
ANTHROPIC_API_KEY=sk-ant-...
```

Ce fichier est ignoré par Git. Une variable déjà définie dans l'environnement n'est jamais écrasée.

Sans clé, un moteur de règles local prend le relais (aucune donnée ne quitte la machine).
Derrière un proxy qui injecte lui-même l'en-tête `x-api-key` (secrets réseau d'un environnement cloud), lancez avec
`COMPTA_AI_PROXY=1` : l'application active Claude sans jamais manipuler la clé.

Tests : `python3 -m unittest discover tests`

## Nouveautés : comptabilité experte et IA spécialisée

* **Entretien IA d'accueil** : à la création du dossier, l'IA pose les questions utiles (foyer, revenus, patrimoine, réductions — ou
  forme juridique, TVA, social pour une entreprise). On peut répondre librement (« mariée, deux enfants nés en 2016 et 2021, salariée
  à Lyon ») : l'IA remplit tout ce qu'elle comprend. Le profil sert chaque année et produit un calendrier fiscal personnalisé.
* **Agent Impôts** : déclaration de revenus complète (2042, 2042-RICI, 2042-C-PRO, 2044, annexes 3916/2086) construite à partir du profil,
  de la comptabilité et des justificatifs lus par l'IA (bulletin de décembre, IFU, attestations CESU/garde, reçus de dons, avis d'impôt).
  Il calcule les parts, compare et applique les options favorables (frais réels, barème vs PFU, micro vs réel foncier, imposition commune
  ou séparée), liste les pièces manquantes, contrôle la cohérence, estime le solde après prélèvement à la source, puis dépose (EDI-IR via
  un tiers déclarant habilité) ou guide la saisie case par case.
* **Centre des déclarations de l'entreprise** : TVA (CA3 mensuelle/trimestrielle ou CA12), IS, liasse, DSN — préparées et transmises en un clic.
* **11 agents IA spécialisés** (expert-comptable, banque, ventes, dépenses, paie, TVA, fiscal, trésorerie, révision, analyse, impôts) :
  analyses proactives sur chaque écran, chat expert, base de connaissances hors ligne.
* **Comptabilité détaillée** : PCG complet (215 comptes), comptes auxiliaires clients/fournisseurs, lettrage automatique et manuel,
  balance âgée et score de risque client, rapprochement bancaire, recherche d'écritures, extourne, pièces jointes, régularisations de
  clôture (CCA, PCA, FNP, FAE, congés payés, provisions) suggérées par l'IA, détermination et affectation du résultat.
* **TVA internationale** : intracommunautaire, export, autoliquidation (services UE, importation, BTP), CA12 et acomptes.
* **Analyse** : soldes intermédiaires de gestion, CAF, 14 ratios commentés, seuil de rentabilité, trésorerie prévisionnelle 12 mois, budget.

## Fonctionnalités

| Domaine | Ce que fait le logiciel |
|---|---|
| **Comptabilité en partie double** | Plan comptable PCG (entreprise) ou budgétaire (particulier), journaux, refus des écritures déséquilibrées, verrouillage des périodes clôturées, montants en centimes entiers. |
| **Banque + IA** | Import CSV de n'importe quelle banque, dédoublonnage, catégorisation IA avec score de confiance, ventilation HT/TVA (TVA non récupérée sur transport de personnes et hébergement), lettrage automatique avec les factures ouvertes. |
| **Lecture de factures PDF / photo** | Claude lit directement le PDF ou la photo ; sans clé API : texte du PDF (`pdftotext` ou extracteur intégré) et OCR `tesseract` s'il est installé. |
| **Factures & devis** | Numérotation continue, mentions légales, PDF, devis → facture en un clic, envoi par e-mail. |
| **Relances clients** | Trois niveaux (J+1, J+15, mise en demeure à J+30 avec pénalités et indemnité de 40 €), facture PDF jointe, envoi SMTP, mode automatique (`POST /api/reminders/auto` à planifier). |
| **Notes de frais** | Justificatif photo/PDF lu par l'IA, barème kilométrique, règles de TVA récupérable, validation et remboursement groupé. |
| **Paie & DSN** | Fiches salariés, bulletins (cotisations URSSAF / Agirc-Arrco, réduction générale, mutuelle, prélèvement à la source taux neutre ou personnalisé), écritures de paie, virement des salaires, fichier DSN (NEODeS), livre de paie. |
| **TVA** | CA3 par taux, TVA sur les débits **ou sur les encaissements** (comptes 44574 / 44586 basculés au règlement), liquidation. |
| **Impôts entreprise** | IS (15 % / 25 %), **liasse 2033-A/B/C + 2065** avec réintégrations et déductions extra-comptables, micro-entreprise. |
| **Impôts particuliers** | IR complet + **revenus fonciers au réel (2044)** : déficit foncier imputable (10 700 €) et reportable, cases 4BA/4BB/4BC/4BD. |
| **Télédéclaration EDI** | Connecteur partenaire EDI (modes désactivé / simulation / production), journal des envois et suivi des accusés. |
| **Exports** | PDF et Excel (.xlsx) : compte de résultat, bilan, balance, journal, registre des factures, liasse, livre de paie ; bulletins, factures et devis en PDF ; FEC. |
| **Multi-utilisateurs** | Comptes, sessions sécurisées, rôles par dossier (propriétaire, comptable, lecteur), invitations, journal d'audit. |
| **Clôture & audit** | Amortissements, IS comptabilisé, verrouillage, revue automatique des anomalies, assistant IA. |

## Télédéclaration : ce qui est automatique et ce qui ne l'est pas

* **TVA, liasse, IS (professionnels)** : la DGFiP n'accepte les dépôts automatisés que via un **partenaire EDI agréé**.
  Le logiciel est prêt : il suffit de signer un contrat avec un partenaire (liste officielle sur impots.gouv.fr),
  puis de renseigner l'URL d'API et le jeton dans *Paramètres › Télédéclaration*. Le contrat d'API attendu est
  décrit dans `compta/edi.py` ; chaque partenaire ayant son propre format, l'adaptateur `HttpPartner` est à
  ajuster à celui que vous choisirez. Le mode *Simulation* teste tout le parcours sans rien envoyer.
* **DSN** : dépôt sur net-entreprises.fr (ou via le partenaire). Contrôlez le fichier avec DSN-Val avant tout dépôt réel.
* **IR (particuliers)** : la DGFiP ne propose **aucune API** de dépôt : le logiciel fournit les cases et un guide pas à pas.

## Utilisateurs et sécurité

Au premier lancement, l'application demande de créer le compte administrateur. Démo (`--demo`) :
`demo@comptaia.fr` / `demo-compta` (propriétaire) et `comptable@cabinet.fr` / `demo-compta` (comptable).

Mots de passe PBKDF2-SHA256, jetons de session stockés hachés, cookies `HttpOnly` + `SameSite=Strict`,
verrouillage après 5 échecs, protection CSRF (JSON obligatoire), en-têtes CSP. Pour une mise en ligne :
servez l'application derrière un proxy HTTPS (Caddy, nginx), avec `HOST=0.0.0.0 COMPTA_SECURE_COOKIE=1`,
et sauvegardez régulièrement `data/compta.db` (qui contient aussi les mots de passe SMTP et le jeton EDI).

## Limites à connaître avant un usage réel

* **Barèmes** : impôt (`compta/tax.py`), paie (`compta/payroll.py`, dont la réduction générale encore en formule 2025),
  barème kilométrique (`compta/expenses.py`) : à vérifier et à mettre à jour à chaque loi de finances. Les numéros de
  cases et de lignes CERFA et les codes DSN sont indicatifs.
* **Paie** : non gérés : absences, indemnités journalières, heures supplémentaires, avantages en nature, apprentis,
  conventions collectives, taxe sur les salaires.
* **Liasse** : régime simplifié (2033) uniquement ; 2033-D à G et régime normal (2050) à compléter.
* **Juridique** : en France, la tenue de comptabilité pour autrui est réservée aux experts-comptables. L'outil permet de
  tenir **sa propre** comptabilité ou de travailler **avec** son comptable (rôle « comptable »).

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
compta/filing.py     préparation et dépôt des déclarations
compta/edi.py        connecteur partenaire EDI (simulation / production)
compta/documents.py  lecture des factures PDF et photos
compta/payroll.py    paie, bulletins, DSN
compta/liasse.py     liasse fiscale 2033 / 2065
compta/foncier.py    revenus fonciers au réel (2044)
compta/sales.py      devis, e-mails, relances
compta/expenses.py   notes de frais, barème kilométrique
compta/exports.py    générateurs PDF et Excel
compta/auth.py       utilisateurs, rôles, sessions, journal d'audit
static/index.html    interface web
tests/               tests unitaires
```
