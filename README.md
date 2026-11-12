# Bureau des Traders

Logiciel Windows où une équipe d'agents en pixel art prépare des idées de trades : le Directeur répartit les missions (préparer la journée, idées du web, chasser une cassure, étudier une action, vérifier les alertes) et chaque agent lance son script.

> Outil d'aide, pas un conseil financier. Aucun ordre n'est envoyé : le Courtier prépare seulement le ticket.

## Prérequis

- Windows 10 ou 11 (WebView2)
- [uv](https://docs.astral.sh/uv/) et Python 3.12
- Les skills Claude Code `trader-*` installés dans `~/.claude/skills` (les agents lancent leurs scripts)

## Installation

```bash
uv venv app/.venv --python 3.12
uv pip install --python app/.venv/Scripts/python.exe pywebview
app/compiler-exe.bat
```

Puis double-clic sur `Bureau des Traders.exe`.

## Ce qu'il fait au lancement

- Le Directeur vérifie les mises à jour (uv, Python, et ce dépôt) et demande avant d'installer.
- Fermer la fenêtre arrête tout.
- Les réglages (budget, pertes max) se font dans ⚙ Réglages et sont gardés dans `trader/config.json`, qui n'est pas publié.
