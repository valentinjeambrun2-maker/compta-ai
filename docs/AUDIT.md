# Audit ComptaIA : outils, attentes professionnelles, plan

Date : novembre 2026. Méthode : lecture du code (aucune exécution sur les écrans sauf où indiqué). Les références `fichier:ligne` sont indicatives.
Statut des constats : **vérifié** = reproduit ou relu directement ; **lu** = constat d'audit par lecture du code, à confirmer lors de la correction de l'outil.

## 1. Attentes de référence

Ce qu'un professionnel attend d'un logiciel de comptabilité et de déclarations, et où ComptaIA se situe.

- **Facturation électronique (réforme française).** La réception des factures électroniques est obligatoire pour toutes les entreprises assujetties à la TVA depuis le 1er septembre 2026. L'émission s'impose aux PME et TPE à partir du 1er septembre 2027. Les échanges passent par des plateformes agréées, et l'e-reporting suit le même calendrier. Source : [La Fabrique du Net](https://www.lafabriquedunet.fr/logiciels/tendances/facturation-electronique-2026-obligations-calendrier), [Quadient](https://www.quadient.com/fr/news/nouvelles-dates-pour-la-reforme-du-e-invoicing). **ComptaIA : ABSENT** (pas de lecture de factures électroniques structurées, pas de Factur-X).
- **Automatisation bancaire.** Rapprochement automatique, catégorisation par IA, intégrations, module de révision pour les cabinets. Source : [comparatif Tiime / Pennylane](https://comparepdp.com/articles/tiime-vs-pennylane). Les sources ne détaillent pas les règles personnalisables : à vérifier sur un essai gratuit. **ComptaIA : PARTIEL**, puis PRÉSENT pour les règles après la livraison de la banque.
- **Exigences légales de tenue comptable.** Fichier des écritures comptables (FEC, art. A47 A-1 du livre des procédures fiscales), piste d'audit fiable (aucune écriture validée supprimée ni modifiée sans trace), TVA et IS au bon compte, mentions légales sur les factures. **ComptaIA : PARTIEL** (FEC présent, suppression possible).
- **Particuliers.** Déclaration pré-remplie et expliquée case par case, simulation frais réels ou forfait, calendrier fiscal avec rappels. Référence : Taxfix, Hiboo, impots.gouv. **ComptaIA : PARTIEL à PRÉSENT** (Agent Impôts complet, mais erreurs de calcul et de dépôt en priorité 0).

## 2. Constats transversaux, par priorité

### Priorité 0 : intégrité comptable et sécurité

| # | Constat | Outil | Preuve | Statut |
|---|---|---|---|---|
| 1 | L'IS est comptabilisé au **44551** « TVA à décaisser » au lieu du **444**. Il gonfle la TVA due et apparaît comme TVA au bilan. | Impôts & liasse, TVA, États financiers | `compta/business.py:167`, `compta/pcg.py:34` | **vérifié** (3 relectures) · **corrigé** : IS au 444 sur le résultat fiscal, reclassement des exercices passés |
| 2 | Une écriture **validée** est supprimée physiquement (`DELETE FROM entries`). Aucune contre-passation, aucune trace du contenu. | Comptabilité, Clôture | `server.py:200-210` | **vérifié** |
| 3 | Option SMTP « Aucune » : identifiant et mot de passe sont envoyés **en clair**. | Paramètres | `compta/sales.py:69-78`, `static/index.html` | **vérifié** |
| 4 | Le **dernier propriétaire** peut être rétrogradé en lecteur : aucun contrôle dans `add_member`. Le dossier n'a plus de gestionnaire. | Paramètres | `compta/auth.py` (`add_member`) | **vérifié** |
| 5 | Mots de passe SMTP et jeton EDI stockés **en clair** en base. | Paramètres, Déclarations | `compta/db.py:117-123` | lu |
| 6 | Le lecteur voit salaires, NIR et bulletins. | Paie, Paramètres | `server.py:360-362, 393` | lu |
| 7 | La DSN part **toujours en test** : le réglage `edi_test` est ignoré, donc aucune DSN de production. | Paie | `server.py:408`, `compta/payroll.py:154` | lu |
| 8 | « Voir » une déclaration insère une ligne « prête » ; le statut relit la dernière ligne. Une obligation déposée redevient « prête », avec risque de double dépôt. | Déclarations | `compta/filing.py:46-50`, `compta/obligations.py:9-11` | **vérifié** (test qui échoue sur l'ancien code) · **corrigé** |
| 9 | Les accusés de télédéclaration ne mettent pas à jour la déclaration : elle reste « transmise ». | Déclarations | `compta/edi.py:117-119` | **vérifié** (test) · **corrigé** |
| 10 | La liquidation de TVA datée du dernier jour de la période est relue dans la CA3, qui affiche alors 0 €. | TVA | `compta/tax.py:204-212`, `index.html:354` | **vérifié** (test qui échoue sur l'ancien code) · **corrigé** |
| 11 | La liquidation partielle ne solde pas 4452, 445662 ni 44562, pourtant comptés dans la CA3. | TVA | `compta/tax.py:246-249` | **vérifié** · **corrigé** |
| 12 | Le journal est limité à 500 écritures et la recherche à 300, sans avertissement. | Comptabilité | `compta/ledger.py:19,112` | lu |
| 13 | **Déficit foncier faux** : les intérêts sont retranchés des loyers avant imputation. 8 320 € sont imputés sur le revenu global au lieu de 6 320 €, et les 2 000 € d'intérêts ne sont pas reportés. Le test fige l'erreur. | Mes impôts | `compta/foncier.py:29-30`, `tests/test_compta.py:130-134` | **vérifié** (calcul et test relus) |
| 14 | Le dépôt ne contrôle que la présence des cases : une déclaration avec salaire estimé ou une annexe 3916 bloquante passe « prête ». Le connecteur partenaire n'appelle pas le contrôle. | Mes impôts | `compta/filing.py:33-41`, `compta/edi.py:82-83` | lu |
| 15 | Justificatifs **écrasés** : deux IFU ou deux employeurs, seul le dernier compte. Un reçu importé deux fois compte deux fois. | Mes impôts | `compta/tax_agent.py:99-100, 153-155, 180-195` | lu |
| 16 | **Estimation d'impôt fausse hors ligne** : calcul sans profil, une seule part, salaires nets bancaires. L'assistant la reprend. | Agents IA, Assistant | `compta/business.py:196`, `compta/ai.py:166-167` | lu |
| 17 | Profil : en mode règles, « mon mari est salarié » écrase l'activité du déclarant. Une réponse non reconnue est effacée sans message. | Profil | `compta/profile.py:263-266, 656-657` | lu |

### Priorité 1 : fonctionnel pour un professionnel

- **Facturation** : mentions légales absentes du PDF (vendeur, n° TVA, capital, RCS, adresse client), pas d'avoir, pas d'acompte ni de règlement partiel, devis refusé facturable (`exports.py:232-268`, `business.py:39-40`, `db.py:27-30`, `sales.py:36-41`).
- **Relances** : sans SMTP, un brouillon compte comme « envoyé » et fait monter le niveau de relance (`sales.py:109, 134`). Erreur SMTP en milieu de lot : mails partis, transaction annulée, doublons ensuite.
- **Facture électronique** : aucune lecture de facture structurée reçue (Factur-X, UBL, CII).
- **Tiers** : le solde se calcule par préfixe `LIKE` et le code auxiliaire ne prend que 6 caractères : « Dupont SAS » et « Dupont Martin » peuvent se confondre (`compta/tiers.py:17,50`, à reproduire). La balance âgée ne suit pas le grand livre (`tiers.py:128` contre `tiers.py:52`).
- **Notes de frais** : le cumul annuel kilométrique n'est jamais transmis, donc la première tranche s'applique toujours (`expenses.py:29`). Le carburant est à 100 % de TVA récupérable alors que l'interface annonce 80 % (`expenses.py:11`, `index.html:488`).
- **Paie** : CSG (abattement plafonné à 4 PASS) et mutuelle (part patronale jamais déduite de l'assiette du PAS) à corriger avec tests (`payroll.py:33, 102`). Entrées et sorties sans prorata (`payroll.py:117-119`), `date_sortie` ignorée (`db.py:40`). Congés payés absents.
- **Clôture** : CCA calculée `12 − mois`, donc un paiement de décembre ne produit rien (`closing.py:100`). Les suggestions ne sont pas marquées comme passées : deux clics comptabilisent deux fois (`closing.py:91-116`). Aucune checklist, et `business.audit` n'est jamais appelé depuis l'écran.
- **Analyse** : la prévision de TVA ignore 44574 et 44586, donc elle sous-estime la TVA (`analysis.py:152`). La TVA à 20 % est codée en dur (`analysis.py:75-76`). Le point de départ est le solde comptable, non rapproché de la banque.
- **États financiers** : classement des comptes par signe. Les amortissements créditeurs passent au passif au lieu d'être déduits de l'actif (`ledger.py:139-140`). Pas de N-1. Numérotation FEC non chronologique après une saisie antidatée (`ledger.py:156-162`, à valider).
- **Impôts & liasse** : SIREN de la 2065 mal extrait quand le SIRET est saisi sans espaces (`liasse.py:96`, `server.py:105-107`). Acomptes d'IS jamais suivis. L'IS se calcule sur le résultat comptable, la 2065 sur le résultat fiscal (`business.py:162-167`, `liasse.py:94`).
- **Mes impôts (particulier)** : dons de l'association classés à 66 % (`compta/ai.py:72`) ; solde du prélèvement à la source nul sans taux (`tax_agent.py:266-268`) ; test d'auto-éligibilité qui lit la valeur forfaitaire au lieu des frais réels (`tax_agent.py:368`) ; plafonnement de la pension et du PER à vérifier (`tax.py:111`).

## 3. État par outil

Ordre du menu : chaque outil a une fiche (fonctionne, défauts, écarts, améliorations). Les écarts sont marqués PRÉSENT / PARTIEL / ABSENT.

### Entreprise

**Tableau de bord** : alertes et chiffres clés présents. Comparatif N-1 absent. Corrigé dans la navigation : outil listé à l'accueil.

**Banque & IA** : *amélioré dans cette itération (voir §4).* Import CSV tolérant, dédoublonnage. Restaient : rapprochement avec les écritures déjà saisies, mémoire des choix, encodage. Multi-banques ABSENT (format CSV seulement).

**Factures** : numérotation continue et relances J+1, J+15, J+30 présentes. Mentions, avoirs, acomptes, Factur-X et relances fiables à traiter (voir §2).

**Devis** : du devis à la facture en un clic. Refus facturable (à corriger).

**Clients & fournisseurs** : compte auxiliaire par tiers, lettrage contrôlé et délettrage présents. Solde par préfixe, balance âgée non reliée au grand livre, lettrage manuel qui ne solde pas la facture (`tiers.py:139-147`).

**Notes de frais** : écriture équilibrée et remboursement groupé présents. Kilométrique, carburant, modification et suppression d'une note, remboursement non relié au relevé (à corriger).

**Paie** : bulletins PDF, cotisations 2026 par tranche, écritures équilibrées et idempotentes présents. DSN de production, CSG, mutuelle, prorata, congés payés à traiter.

**Comptabilité** : équilibre contrôlé, recherche multicritère, verrouillage des périodes présents. Suppression d'écritures validées (priorité 0), journal limité, pas de modèles d'écritures, pas de contre-passation tracée.

**États financiers** : bilan équilibré, FEC à 18 colonnes présents. Classement par nature, N-1 et numérotation à traiter.

**Analyse & trésorerie** : SIG, CAF et trésorerie sur 12 mois avec alerte présents. TVA prévisionnelle, point de départ, emprunts et scénarios à traiter.

**Déclarations** : calendrier TVA, CA12, IS, liasse, DSN et EDI sandbox présents. Priorité 0 : « Voir » qui insère, accusés non propagés, pas de bouton « déposée », pas de rappels J-7 et J-1 alors que le SMTP existe.

**TVA** : pré-remplissage depuis le grand livre, ventilation par taux, TVA sur encaissements câblée, intracom, export, autoliquidation présents. Liquidation et autoliquidation (comptée deux fois en case 08, taux 2,1 % absent) à corriger.

**Impôts & liasse** : liasse 2033 et 2065 générées avec contrôle d'équilibre, IR et IS PME paramétrés présents. IS au 444, SIREN, acomptes et contrôles 2065 à traiter.

**Clôture** : verrouillage, amortissements linéaires au prorata, extournes sans double extourne présents. Checklist absente, CCA, suggestions à marquer, suppression à remplacer.

**Profil** : entretien IA question par question, réponses libres multi-champs, profil corrigeable à tout moment. Défauts : calendrier titré 2027 mais calculé pour 2026 (`static/v2.js:104`, `server.py:642`) ; « L'IA comparera » rattachement et pension sans aucun code (`profile.py:46-47`, `tax_agent.py:263-265`).

**Agents IA** : 11 agents ; analyses locales toujours visibles ; base hors ligne fiable sur les règles courantes ; repli automatique si Claude échoue. Défauts : `is\b` et `ir\b` ne correspondent jamais (`ai.py:166`) ; l'historique de chat reste d'un dossier à l'autre (`static/v2.js:331`) ; l'agent de Budget et d'Exports côté particulier est l'Expert-comptable d'entreprise (`agents.py:200-203`).

**Paramètres** : rôles appliqués côté serveur, PBKDF2 à 600 000 itérations, cookie HttpOnly et SameSite=Strict présents. Priorité 0 : SMTP en clair, dernier propriétaire, journal d'audit non fiable (pas de connexions ni d'échecs), sauvegarde et export complet absents.

### Particulier

**Mes impôts (Agent Impôts)** : calcul IR complet hors ligne (parts, décote, plafonnement, réductions, PFU ou barème), options comparées avec gain, provenance case par case, contrôles de cohérence. Priorité 0 : foncier faux, dépôt sans contrôle, justificatifs écrasés (§2). Écarts : 2042 explicitée case par case PARTIEL ; simulateur d'impact ABSENT ; justificatifs par année et case PARTIEL ; calendrier et rappels PARTIEL ; mode hors ligne PRÉSENT.

**Budget** : l'écran budget est réservé à l'entreprise, mais le particulier voit l'état de résultat (`static/v2.js:8, 302-306`). Le budget annuel est divisé par 12 (`analysis.py:167`). Le moteur budgétaire par compte, avec écart et taux, est présent.

**Exports** : PDF et Excel présents. L'export est titré « Compte de résultat » (`exports.py:315`), le FEC est proposé à un particulier (`index.html:407`), et ni la 2042 ni les justificatifs ne sont exportables (`server.py:504`). Hors ligne : PRÉSENT.

**Profil (particulier)** : mêmes constats que côté entreprise, avec le défaut d'effacement des réponses non reconnues (§2, ligne 17).

**Agents IA (particulier)** : mêmes constats que côté entreprise, plus l'estimation d'impôt fausse hors ligne (§2, ligne 16).

## 4. Ce qui est livré dans cette itération

1. **Accueil** (`b5258a1`) : 17 outils en entreprise, 8 en particulier, avec logo, nom et description. Navigation réduite à « ← Tous les outils ». TVA rendue accessible. En-tête mobile corrigé.
2. **Banque & IA** (`dcf6586`) :
   - *Mémoire des choix* : un compte choisi pour un libellé est repris aux imports suivants (confiance 0,95, mention « Règle mémorisée »). La validation en lot n'apprend rien. Vérifié dans le navigateur : validation puis réimport, règle appliquée.
   - *Doublons probables* : une opération au même montant qu'une écriture saisie à la main (±3 jours) reste en attente, confiance 0,3, et n'est jamais validée en lot.
   - *Encodage* : relevés en Windows-1252 lus correctement. Vérifié avec un relevé réel (accents conservés).
   - Tests : `tests/test_bank_memory.py` (7), suite complète verte (50).
3. **Comptabilité** (commit de l'itération suivante) :
   - *Suppression remplacée par une annulation* : une contre-passation datée du jour est passée ; l'écriture d'origine reste en base, reliée à son annulation. La ligne de relevé bancaire rattachée repasse à valider. Refusé si l'écriture est lettrée, liée à une facture, ou dans une période clôturée. L'action est tracée dans le journal d'audit.
   - *Pas de limite silencieuse* : le journal et la recherche sont paginés (200 par page, « Afficher plus »), avec le total réel. Les exports restent complets.
   - *Affichage* : une écriture annulée porte « annulée », sa contre-passation « contre-passation ». « Annuler » n'apparaît que lorsque l'action est possible ; « facture » et « lettrée » signalent les cas refusés.
   - Non traité : identifiant de l'utilisateur sur chaque écriture (`created_by`), modèles d'écritures.
   - Tests : `tests/test_comptabilite.py` (9). Vérifié dans le navigateur : annulation, refus sur facture, total et pagination.
4. **Impôts & liasse (entreprise)** :
   - *IS au 444* : l'IS est calculé sur le résultat fiscal (même calcul que la 2065) et comptabilisé au 444, plus au compte de TVA 44551. Il ne fausse plus la TVA ni l'analyse de trésorerie.
   - *Reclassement* : un IS déjà passé au 44551 se corrige par une écriture de correction (44551 → 444). L'écriture d'origine n'est pas modifiée ; la correction est datée du premier jour ouvert ; l'opération ne se fait qu'une fois. Bouton « Reclasser l'IS » dans la liasse. Vérifié dans le navigateur : 500 € reclassés, contrôle disparu.
   - *SIREN* : les 9 premiers chiffres du SIRET, espaces retirés d'abord (un SIRET sans espaces donnait 11 chiffres).
   - *Acomptes* : le solde d'IS (2572) est net des acomptes versés au 444 pendant l'exercice.
   - *Contrôles* de la liasse : IS au 44551 à reclasser, IS comptabilisé différent du calcul, IS non encore comptabilisé.
   - Tests : `tests/test_impots_entreprise.py` (5). Suite complète : 64 tests verts.
   - Non traité : SIRET normalisé à la saisie, bouton dédié aux acomptes d'IS.
5. **TVA** :
   - *CA3 stable après liquidation* : l'écriture de liquidation est ignorée par la CA3, qui affichait 0 € une fois la période liquidée. Seule la liquidation est exclue ; la bascule à l'encaissement et l'acompte restent comptés. Reproduit par un test qui échoue sur l'ancien code.
   - *Liquidation complète* : elle solde 44571 et 4452 (collectée), 44566, 445662 et 44562 (déductible), vers 44551 ou 44567. Une seule fois par période : un second passage est refusé.
   - *TVA sur immobilisations* : le formulaire demande un taux ; la TVA déductible va au 44562, le coût HT reste la base d'amortissement. Aucune TVA en franchise.
   - *Lignes de taux* : le taux 2,1 % et une ligne « autres taux » s'affichent, le détail totalise la TVA brute.
   - *Périodicité* : l'écran TVA propose mensuel ou trimestriel (période `AAAA-Tn`, comme les échéances).
   - Tests : `tests/test_tva.py` (9). Suite complète : 73 tests verts. Vérifié dans le navigateur : CA3 trimestrielle inchangée après liquidation, second passage refusé, immobilisation de 1 000 € HT avec 200 € au 44562.
   - Non traité : affectation des lignes du CERFA pour l'autoliquidation (à contrôler avec le formulaire officiel), bouton d'acompte du régime simplifié, report du crédit de TVA antérieur.
6. **Déclarations** :
   - *Une déclaration déposée n'est plus rouverte* : « Voir » n'insère plus de ligne « prête » (cause du retour à « à déclarer » et du risque de double dépôt). Une déclaration déposée ou transmise ne peut plus être retransmise. Un seul brouillon par type et période, mis à jour sur place ; dans les bases existantes avec doublons, la ligne déposée l'emporte.
   - *Mode manuel* : bouton « Marquer comme déposée », dans le résultat et dans la liste. Les échéances ne restent plus « en retard » après dépôt, et le guide pas-à-pas n'est plus effacé au bout de 1,8 s.
   - *Accusés EDI* : l'accusé de réception met aussi à jour la déclaration (déposée, simulée en test, ou en erreur).
   - *Contrôles de cohérence* qui peuvent se déclencher : montants de TVA non négatifs, TVA nette égale à la collectée moins la déductible, liasse équilibrée. Les erreurs s'affichent à l'écran.
   - *Confirmation* avant « Tout préparer et transmettre », avec le nombre de déclarations et un bilan.
   - Tests : `tests/test_declarations.py` (11) ; 10 échouent sur l'ancien code. Suite complète : 84 tests verts. Vérifié dans le navigateur en mode manuel.
   - Non traité : rappels par e-mail à J-7 et J-1, contrôles de cohérence pour la DSN, l'IS et la CA12.

## 5. Ordre proposé pour la suite

Un outil par itération, un commit et un push par outil. L'ordre suit le risque pour le professionnel.

1. **Comptabilité** : *fait* (voir §4, item 3). Restent `created_by` et les modèles d'écritures.
2. **Impôts** : entreprise *fait* (voir §4, item 4). Reste côté particulier : foncier corrigé et test mis à jour, dépôt verrouillé sur contrôle complet, justificatifs cumulés, source unique du calcul d'impôt utilisée par l'assistant. La TVA est faite (voir §4, item 5).
3. **Déclarations** : *fait* (voir §4, item 6). Restent les rappels J-7 et J-1.
4. **Paramètres** : SMTP sans identifiants en clair, garde du dernier propriétaire, droits sur les salaires et NIR, journal d'audit réel.
5. **Paie** : DSN liée à `edi_test`, CSG, mutuelle, prorata.
6. **Factures et Devis** : mentions légales dans le PDF, avoirs, règlements partiels, relances fiables, lecture des factures électroniques reçues.
7. **Tiers**, **Notes de frais**, **Clôture**, **États financiers**, **Analyse**.
8. **Profil, Agents IA, Budget et Exports** (particulier) : titre du calendrier, mémoire des réponses, agent dédié, budget réservé au budget, export sans FEC.

## 6. Limites

- Taux et barèmes (PAS, cotisations 2026, seuils, barème kilométrique, échéance CA3 trimestrielle) ne sont pas confirmés par cet audit : à vérifier à la correction de chaque outil.
- Les constats « lu » ne sont pas reproduits ; les « vérifié » l'ont été par relecture directe ou par exécution.
- Les attentes professionnelles s'appuient sur deux recherches publiques et sur la pratique du métier, pas sur une enquête auprès d'utilisateurs.
- Les constats fiscaux du particulier (foncier, dépôt, justificatifs, dons) sont des lectures de code : aucun scénario n'a encore été exécuté. Le barème 2026 (`tax.py:26`) et les seuils sont à confirmer sur les textes officiels avant toute correction.
- Les tests des fonctions IA avec Claude n'ont pas été lancés : la clé n'était pas présente dans l'environnement de la session.
