# Bureau des Traders

Logiciel Windows où une équipe d'agents en pixel art cherche des idées de day trading sur les actions américaines. Le Directeur répartit les missions, chaque agent fait son travail (scan des graphiques, news, calcul du stop, 10 000 rejeux, taille de position, contrôle du risque) et le Courtier prépare un ticket d'ordre.

> ⚠️ **Outil d'aide et d'apprentissage, pas un conseil financier.** Aucun ordre ne part sans ton clic, et seulement vers un compte **PAPIER** (argent fictif). Les performances passées ou simulées ne garantissent rien. Le trading peut faire perdre tout le capital engagé.

## Prérequis

- Windows 10 ou 11, avec une connexion internet
- Un compte **Alpaca** gratuit en mode Paper Trading (voir plus bas)

Rien d'autre : l'installateur s'occupe de Python.

## Installation

1. Décompresse `Bureau-des-Traders.zip` où tu veux (clic droit → *Extraire tout*).
2. Double-clique sur **`Installer.bat`**.
   - Si Windows affiche « Windows a protégé votre ordinateur », clique sur *Informations complémentaires* → *Exécuter quand même*. Le logiciel n'est pas signé numériquement, c'est pour ça que Windows ne connaît pas l'éditeur.
3. Choisis le dossier d'installation. Un dossier « Bureau des Traders » est créé dedans.
4. Attends quelques minutes la première fois. L'installateur :
   - copie les fichiers ;
   - installe [uv](https://docs.astral.sh/uv/) (le gestionnaire Python d'Astral) s'il n'est pas déjà là ;
   - installe Python 3.12 et pywebview (la fenêtre de l'app) dans le dossier de l'application ;
   - crée `Bureau des Traders.exe` et un raccourci sur le Bureau et dans le menu Démarrer.

Le zip décompressé peut ensuite être supprimé.

## Brancher ton compte Alpaca PAPIER

1. Crée un compte sur [alpaca.markets](https://alpaca.markets). Un e-mail suffit, c'est gratuit.
2. Sur [app.alpaca.markets](https://app.alpaca.markets), passe sur le compte **Paper Trading** (menu du compte en haut à gauche) et choisis le montant fictif. Prends la somme que tu traderais vraiment, pour que le test soit réaliste.
3. Sur la page d'accueil du compte papier, encadré **API Keys** → **Generate New Keys**. Note la *Key ID* (commence par `PK`) et le *Secret* (affiché une seule fois).
4. Dans le Bureau des Traders, ouvre **⚙ Réglages**, colle les deux clés, mets le **Budget** au même montant que ton compte papier, puis clique sur **Enregistrer**.

**Ne donne jamais tes clés à personne**, même pas à l'auteur du logiciel. Chaque testeur utilise son propre compte.

## Réglages

| Réglage | Rôle |
|---|---|
| Budget | La somme du compte. Le Comptable ne dépense jamais plus |
| Perte max par trade | Ce que tu perds si le stop est touché. Sert à calculer le nombre d'actions |
| Perte max par jour | Une fois atteinte, plus aucun trade jusqu'au lendemain |
| Trades max par jour | Limite le nombre de trades par jour |
| Gain/risque minimum | Laisse **1** : la stratégie vise un gain égal au risque (1R) |
| Identité SEC | Facultatif. « Prénom Nom e-mail » pour que l'Analyste lise les résultats des entreprises sur le site de la SEC |

## Utilisation

La Bourse de New York est ouverte de **15h30 à 22h** (heure de Paris), du lundi au vendredi.

| Bouton | Ce qu'il fait |
|---|---|
| ☀ Préparer la journée | Repérage : graphiques intéressants, news, achats du Congrès. Pas de ticket |
| 🌐 Idées du web | Actions qui bougent sur Yahoo, StockTwits et Reddit, puis tri strict et ticket |
| ⚡ Chasser une cassure | Le principal : cassures du range d'ouverture, tri strict et ticket |
| 🔍 Étudier une action | Tape un ticker (ex. TSLA) : news, résultats, ticket si le signal est bon |
| 🔔 Vérifier les alertes | Un prix surveillé a-t-il été touché ? |
| 📤 Envoyer le ticket | Envoie le ticket au compte papier, après ta confirmation |
| 📊 Bilan du test papier | Trades fermés, % de gagnants, gain moyen par trade, pire série de pertes (lu sur ton compte Alpaca) |

**Journée type** : ☀ vers 15h30, ⚡ vers 15h45 (à relancer jusqu'à 17h), puis 📤 si un ticket sort.

Le ticket s'affiche dans le **Journal** à droite. Tu peux aussi cliquer sur un agent pour voir son dernier travail.

**Sécurités intégrées :**
- un trade n'est gardé que si le signal a moins de 30 min et que 10 000 rejeux et l'historique sont favorables ;
- chaque ordre part avec son stop et son objectif enregistrés **chez Alpaca**, donc ils restent actifs même si ton PC s'éteint ;
- pas de nouvel achat après 17h (heure de Paris) ;
- toutes les positions papier sont fermées 10 min avant la clôture, si l'application est ouverte ;
- l'adresse du serveur Alpaca est celle du compte papier, écrite dans le code. Aucun réglage ne permet de passer en argent réel.

## Faire le test

1. Trade en papier pendant **2 à 3 mois**, jusqu'à **au moins 100 trades fermés**. Avec moins, le hasard pèse plus lourd que la stratégie.
2. Ne change pas les réglages en cours de route, sinon les résultats ne sont plus comparables.
3. Ouvre **📊 Bilan du test papier** de temps en temps, et juge seulement à la fin :
   - **gain moyen par trade** : positif ou négatif ? C'est le chiffre principal ;
   - **pire série de pertes** : est-ce que tu l'aurais supportée avec du vrai argent ?
   - **% de gagnants** : avec un objectif à 1R, il faut plus de 50 % de gagnants pour être positif.
4. Le papier est plus optimiste que le réel : en vrai, les ordres sont parfois exécutés à un prix moins bon. Un résultat juste au-dessus de zéro en papier peut devenir négatif en réel.

## Confidentialité

- Tout tourne sur ton PC. Il n'y a aucun serveur de l'auteur, aucune statistique envoyée, aucun compte à créer chez l'auteur.
- Tes réglages et tes clés Alpaca sont dans `trader\config.json`, dans le dossier d'installation, et ne quittent jamais ton PC, sauf vers Alpaca pour passer les ordres.
- L'application contacte seulement : Alpaca (ordres papier), Yahoo Finance, Stooq, Nasdaq Trader, StockTwits, ApeWisdom, la SEC et le site de la Chambre des représentants (données publiques), et GitHub pour vérifier les mises à jour.

## Désinstallation

Double-clique sur **`Desinstaller.bat`** dans le dossier d'installation. Il supprime les raccourcis et tout le dossier, y compris tes réglages et tes clés. Ton compte Alpaca n'est pas touché. Tu peux aussi supprimer ou régénérer tes clés depuis le site d'Alpaca.

uv et Python restent installés (`%USERPROFILE%\.local\bin`). Ils peuvent servir à d'autres logiciels. Pour les retirer : `uv cache clean`, puis supprime `uv.exe` et `uvx.exe` de ce dossier.

## Problèmes fréquents

- **« Python du bureau introuvable » au lancement** : relance `Installer.bat` et choisis le même dossier. Tes réglages sont gardés.
- **« Pas de ticket prêt »** : lance d'abord une mission. Si le Directeur dit « aujourd'hui on ne trade pas », aucun trade n'a passé les filtres. C'est normal et fréquent.
- **« Ticket vieux de plus de 30 min »** : relance la mission, le prix a bougé depuis.
- **Erreur Alpaca 401/403** : clés fausses ou de compte réel. Régénère des clés **papier** et recolle-les dans ⚙.

## Mises à jour

Au lancement, puis toutes les 30 min, le Directeur regarde si une nouvelle version est publiée. Si oui, il te propose de l'installer. Tu n'as pas besoin de fermer l'application : la page se recharge, ou la fenêtre disparaît et revient toute seule en quelques secondes. Tes réglages et tes clés sont gardés. Si tu réponds « Non », la même version ne sera plus proposée avant le prochain lancement.

## Pour l'auteur : publier une version

1. Augmente le numéro dans `VERSION` (par exemple `1.0.1`).
2. Fabrique le paquet :
   ```powershell
   powershell -ExecutionPolicy Bypass -File installer\creer-paquet.ps1
   ```
   Le script crée `dist\Bureau-des-Traders.zip`. Le dossier `trader\` (tes réglages et tes clés) n'y est jamais inclus.
3. Publie une Release GitHub dont le tag est ce numéro, avec le zip en pièce jointe :
   ```powershell
   gh release create v1.0.1 dist\Bureau-des-Traders.zip --title "v1.0.1" --notes "Ce qui change"
   ```

Les copies installées interrogent `api.github.com` sur le dépôt `Bxx416/bureau-des-traders`. Ça ne marche que si le dépôt est **public**. Un dépôt privé ne répond pas aux testeurs, et ils ne voient alors aucune mise à jour.

## Licence

Voir [LICENSE](LICENSE) : tous droits réservés, utilisation personnelle gratuite autorisée.
