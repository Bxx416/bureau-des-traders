# Audit de Bureau des Traders (2026-11-13)

## 1. Ce qui existe vraiment

| Élément | Fichier | Rôle |
|---|---|---|
| Serveur + orchestration + courtiers + mises à jour | `app/server.py` (~1 100 lignes) | tout passe par lui |
| Interface | `app/static/` | pixel art, SSE `/api/events` |
| IBKR papier | `app/ibkr.py` | bracket Euronext, refus si compte ≠ `D…` |
| Fouineuse / Crieur | `app/agents/idees.py` | Yahoo, StockTwits, ApeWisdom |
| 11 agents | `skills/trader-*/` | scripts lancés en sous-processus, échangent par fichiers JSON dans `trader/` |
| Bourse de Paris | `skills/marche.py` | remplace horaires/fériés/fuseau dans les globals des scripts |

Chaîne de fichiers : `scan → watchlist.json → entry → entry.json → exit → plan.json → timemachine → timemachine.json → size → orders.json → check → state/risk.json → ticket → state/broker.json`.
Tout est utilisé, aucun fichier mort trouvé (le `skills/__pycache__` est un cache).

## 2. Anomalies trouvées

| # | Gravité | Problème | Statut |
|---|---|---|---|
| 1 | Critique | `favorable()` acceptait un historique de moins de 5 trades | **corrigé** (`app/validation.py`) |
| 2 | Critique | Réponse réseau perdue → ticket marqué « failed » alors que l'ordre a pu partir ; une mission relancée pouvait renvoyer le même trade | **corrigé** (clé d'idempotence, état UNKNOWN bloquant) |
| 3 | Critique | Le Gardien n'était consulté qu'en mission : à l'envoi, son verdict pouvait dater de plusieurs heures | **corrigé** (recontrôle à l'affichage et à la confirmation) |
| 4 | Critique | `check.py` laissait passer une entrée dont le seul prix était périmé | **corrigé** |
| 5 | Haute | La clôture de 15h50 fermait TOUTES les positions du compte (`DELETE /v2/positions`, `reqGlobalCancel`) | **corrigé** : seulement ce que le bureau a acheté |
| 6 | Haute | Pas de vérification du type de compte Alpaca, URL papier non verrouillée | **corrigé** (`PA…` exigé, hôte vérifié) |
| 7 | Haute | Pas d'arrêt d'urgence ni de DRY_RUN | **corrigé** |
| 8 | Haute | Voyageur : aucun frais ni glissement, entrée au cours de clôture exact, gap sous le stop compté -1R | frais/glissement ajoutés dans la validation ; le reste → phase 5 |
| 9 | Moyenne | Paris : limites copiées de New York, clés en `_usd` utilisées comme des euros ; aucune conversion | à valider par toi |
| 10 | Moyenne | Décisions lues dans stdout (regex `TRIGGERED`, `That was N minutes ago`) | phase 3 |
| 11 | Moyenne | `eastern_offset`/horaires NYSE recopiés dans 9 scripts ; `marche.py` les remplace à chaud et traduit `$→€` dans **toute** la sortie, JSON compris (« ETF » devient « ParisF ») | phase 3 |
| 12 | Basse | `check.py` : un ordre `notional` avec stop mais sans prix saute le calcul de perte (chemin peu probable, bracket exige `qty`) | **corrigé** |

## 3. Ce que la phase 2 a changé

- `app/validation.py` : VALIDATED / REJECTED / INSUFFICIENT_DATA. Historique ≥ 20 trades, espérance > 0 **après frais et glissement**, sur tout l'échantillon **et** sur le dernier tiers (hors échantillon). La simulation peut rejeter, jamais valider seule. Seuils dans `config.json` → `"validation"`. Résultat écrit dans `trader/state/validation.json`.
- `app/envois.py` : journal SQLite (`trader/state/envois.db`), intention écrite avant l'appel, clé `bdt-<jour>-<empreinte>` envoyée comme `client_order_id` (Alpaca) / `orderRef` (IBKR).
- `server.py` : `envoyer_ticket` → arrêt d'urgence, envoi inconnu, Gardien, horaires, compte papier, intention, un seul appel, réconciliation. `POST /api/arret`, `POST /api/reconcilier`. Missions de trading refusées pendant un arrêt d'urgence ou un envoi inconnu.
- `check.py` : refus sur prix périmé et sur perte non calculable.
- Interface : bouton 🛑 Arrêt d'urgence.
- `tests/test_securite.py` : 29 tests (unittest, sans dépendance).

## 4. Plan de migration proposé (phases 3 à 8)

L'arborescence cible du cahier des charges (≈ 50 fichiers) déplacerait surtout du code sans le rendre plus sûr. Ce qui apporte vraiment quelque chose :

1. **Contrats JSON** : chaque script écrit déjà un JSON ; ajouter un champ `status` normalisé (SUCCESS / FAILED / INSUFFICIENT_DATA / BLOCKED) et faire lire ces fichiers par le serveur au lieu de stdout.
2. **Horaires** : un seul module `skills/marche.py` basé sur `zoneinfo` (NYSE + Euronext), importé par les 9 scripts à la place des copies ; supprimer la traduction de stdout.
3. **Orchestrateur** : sortir `missions`, `run_mission`, `select_trade` de `server.py` vers `app/orchestrateur.py` avec un identifiant et un journal par mission.
4. **Voyageur** : entrée à l'ouverture de la barre suivante (pas la clôture), gaps sous le stop comptés à leur vrai prix, frais/glissement dans `timemachine.py`, walk-forward sur plusieurs symboles.
5. **Data Steward** : contrôles prix ≤ 0, doublons, trous de barres, horodatages dans la lecture des bougies (service, pas un agent).
6. **Performance** : historique des opportunités (accepté/refusé + raisons) dans la même base SQLite, bilan par stratégie/marché/heure.
7. **Paris** : clés de risque neutres (`max_loss_per_trade`) + devise explicite, frais IBKR réels.

Quant, QA Controller et Market Regime : fonctions déterministes dans ces modules, pas de nouveaux agents animés.

## 5. Phase 3 (faite)

- `server.py` (~500 lignes) ne garde que HTTP, mises à jour, fenêtre, cours. Découpé en :
  - `app/contexte.py` : chemins, réglages par place, arrêt d'urgence, DRY_RUN, horaires de Paris, événements ;
  - `app/orchestrateur.py` : missions, étapes, sélection, **journal de mission** (`trader/state/missions/<id>.json` : identifiant, état EN_COURS/TERMINEE/ARRETEE/INTERROMPUE, chaque étape avec code et statut SUCCESS/WARNING/FAILED/INSUFFICIENT_DATA/BLOCKED, chaque candidat refusé avec sa raison) ;
  - `app/courtier.py` : Alpaca/IBKR papier, envoi idempotent, réconciliation, clôture, bilan.
- Les décisions ne lisent plus stdout : candidats depuis `watchlist.json` (`mode: orb`, `bar_index`), signal depuis `entry.json` (`status`, `date`, `time`, `checked_at`). Âge inconnu = refus.
- Horaires : un seul calendrier dans `skills/marche.py` (zoneinfo, repli sur les règles officielles si Python n'a pas la base des fuseaux ; vérifié identique heure par heure sur 2026-2027). Les 9 copies dans les scripts sont supprimées. Sorties New York identiques avant/après.
- Traduction Paris : mots entiers seulement (« ETF » n'est plus abîmé).
- Restent pour plus tard : statut normalisé écrit par les scripts eux-mêmes, clés de risque neutres en devise, calendrier au-delà de 2027.

## 6. Phases 4-5 : Voyageur (faites)

- Entrée réaliste : ordre au marché après la clôture de la bougie de signal → achat à l'**ouverture suivante** (historique et Monte-Carlo). R reste mesuré sur le risque prévu, donc un achat plus cher que prévu coûte.
- Gaps : une ouverture déjà sous le stop sort à ce prix (perte > 1R) ; stop et objectif dans la même bougie → stop ; objectif à cours limité → prix de l'objectif. Pas de signal sur la dernière bougie.
- Données : bougies à prix ≤ 0, plus-haut/plus-bas incohérents, volume négatif ou doublons écartés ; la séance devient incomplète et ne sert plus.
- Validation : espérance par tiers dans l'ordre du temps (`par_tiers_R`, walk-forward sans ré-optimisation puisque la règle n'a pas de paramètre ajusté), pire trade (`gap_pire_R`).
- Exemple réel, ADBE (plan du 12/11, 33 trades passés) : avant −0,311R, après −0,309R par trade, pire −1,07R au lieu de −1R ; −0,40R après frais, tiers −0,15 / −0,46 / −0,58 → REJECTED.
- Pas fait : biais du survivant (Yahoo ne donne que les actions encore cotées ; la liste du scanner est celle d'aujourd'hui), backtest multi-symboles.

## 7. Phase 6 : historique et performance (faite)

- `app/historique.py` : une ligne par action étudiée dans `state/historique.db` (une base par Bourse) : mission, jour, heure du signal, stratégie, état (VALIDATED / REJECTED / INSUFFICIENT_DATA / BLOCKED / TICKET / ENVOYE / UNKNOWN), raison, entrée, stop, objectif, quantité, risque prévu, clé de l'ordre.
- Rempli par l'orchestrateur (chaque décision, puis blocage par le Comptable/Gardien ou ticket prêt avec les chiffres du Gardien) et par le Courtier (clé d'envoi et état).
- Bilan 📊 : en plus du bilan papier, taux de refus, motifs, données insuffisantes, erreurs d'envoi, trades papier par semaine / mois / heure d'entrée / stratégie, en R quand le risque prévu est connu. Le bilan s'affiche même si le courtier est injoignable.
- Séparation : décisions (historique.db), trades papier (courtier), simulations (validation.json) ne sont jamais additionnés.

## 8. Vérification finale (phases 7-8)

| Contrôle | Résultat |
|---|---|
| Tests (`app\.venv\Scripts\python.exe -m unittest discover -s tests`) | 42 OK, aussi avec le Python de base (sans zoneinfo → règles officielles) |
| Linter (ruff, règles F) sur app, skills, tests | propre |
| Auto-tests `ibkr.py`, `marche.py` (US et PA) | ok |
| Points d'entrée HTTP sur une copie (port 8799) | tous conformes : 403 autre origine, 400 JSON/mission/place invalides, 423 arrêt d'urgence, 409 ticket périmé, bilan même courtier injoignable |
| Chemins vers un compte réel | aucun : Alpaca = hôte `paper-api.alpaca.markets` vérifié + compte `PA…` (à l'envoi et au démarrage) ; IBKR = compte `D…` ; ticket marqué `paper: false` refusé |
| Interface | look pixel art intact, bouton 🛑, Bilan enrichi (vérifié dans le navigateur) |
| Paquet testeurs | nouveaux modules inclus, aucune donnée personnelle |

**Pas vérifié** : envoi réel au compte papier Alpaca (aucun ticket frais pendant la séance), tout IBKR (pas de compte ni d'IB Gateway), mission « Chasser une cassure » en séance.

### Variables d'environnement
- `BDT_PORT` : port du serveur (8765 par défaut ; 8799 pour une copie de test).
- `BDT_DRY_RUN=1` : tout se déroule sauf l'appel au courtier (aussi `"dry_run": true` dans `trader/config.json`).
- `BDT_MARCHE` : posé par le serveur pour les scripts (US ou PA), à ne pas régler soi-même.
- Clés Alpaca papier : dans ⚙ Réglages (`trader/config.json`, jamais renvoyées au navigateur ni écrites dans le code).

### Démarrer
- Double-clic sur `Bureau des Traders.exe` (ou `Bureau des Traders.bat`).
- Copie de test sans fenêtre : `BDT_PORT=8799 app\.venv\Scripts\python.exe app\server.py --no-window`, puis http://127.0.0.1:8799/.
- Arrêt d'urgence : bouton 🛑, ou créer le fichier `trader\ARRET_URGENCE`.

### Reste à faire
- Limites de risque de Paris : valeurs copiées de New York (clés `_usd` utilisées en euros), à confirmer ; frais IBKR réels à vérifier.
- Calendrier des jours fériés au-delà de 2027.
- Biais du survivant, backtest multi-actions.
- Premier envoi papier réel en séance pour valider le parcours de bout en bout.
