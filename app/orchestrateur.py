"""Orchestrateur : les missions, leurs étapes, la sélection d'un trade et le journal de chaque mission.
Le serveur ne fait que lui transmettre les demandes."""
import json, os, re, subprocess, sys
from contextlib import closing
from datetime import datetime, timezone
import envois, historique, validation
from contexte import (horaires, base_historique, jour_marche, AGENTS, MARCHES, MAX_AGE_MIN, SKILLS, arret_urgence, base, dossier, emit, load_config, marche, say, sec_ready, web_ideas)

MAX_CANDIDATES = 6

def recent_triggers():
    """Tickers du dernier scan d'ouverture (watchlist.json), du déclenchement le plus récent au plus ancien."""
    try:
        w = json.loads((dossier() / "watchlist.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if w.get("mode") != "orb":
        return []
    hits = [h for h in w.get("hits") or [] if h.get("symbol") and h.get("bar_index") is not None]
    return [h["symbol"] for h in sorted(hits, key=lambda h: h["bar_index"], reverse=True)]


def age_signal(e, m):
    """Minutes entre la bougie de déclenchement (entry.json, heure de la place) et le contrôle du Guetteur.
    None si une donnée manque : un signal dont on ne connaît pas l'âge ne passe pas."""
    try:
        local = datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %I:%M %p")
        vers_utc = horaires.paris_to_utc if m == "PA" else horaires.ny_to_utc
        controle = datetime.fromisoformat(e["checked_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        return (controle - vers_utc(local)).total_seconds() / 60
    except (KeyError, TypeError, ValueError):
        return None


# Chaque mission = liste d'étapes (agent, arguments, phrase du directeur).
# shortcut: les missions sont figées ici, à rendre éditables si tu veux en créer d'autres.
US_SEULEMENT = {"analyst", "pelosi", "fouineuse", "crieur"}   # SEC, Congrès, Yahoo/StockTwits US
# Agents qui informent sans décider : un code ≠ 0 (rien de neuf, société étrangère absente de la SEC…)
# ne coupe pas la mission. Les contrôles (signal, plan, rejeux, taille, Gardien, ticket) restent bloquants.
INFO_SEULEMENT = {"news", "analyst", "pelosi"}

def missions(symbol):
    s = (symbol or "").upper().strip()
    toutes = {
        "matin": [
            ("alerts", ["clock"], "Sentinelle, la bourse est ouverte ?"),
            ("scanner", ["daily", "--show", "15"], "Scanner, trouve-moi les graphiques intéressants !"),
            ("news", ["--watchlist", "trader/watchlist.json", "--no-sec", "--hours", "16"], "Journaliste, des nouvelles sur ces actions ?"),
            ("pelosi", ["new", "--dry-run"], "Espion, le Congrès a acheté quoi ?"),
        ],
        "cassure": [
            ("alerts", ["clock"], f"Sentinelle, quelle heure à {MARCHES[marche()]} ?"),
            ("scanner", ["orb", "--show", "15"], "Scanner, quelles actions cassent leur range d'ouverture ?"),
            ("entry", ["watchlist"], "Guetteur, laquelle déclenche une entrée ?"),
            ("selection", None, ""),
            ("budget", ["--write"], "Comptable, combien d'actions avec notre budget ?"),
            ("risk", [], "Gardien, ça respecte nos règles ?"),
            ("broker", ["show"], "Courtier, prépare le ticket (sans l'envoyer)."),
        ],
        "action": [
            ("news", ["--tickers", s, "--no-sec", "--hours", "24"], f"Journaliste, quoi de neuf sur {s} ?"),
            ("analyst", [s], f"Analyste, les derniers résultats de {s} ?"),
            ("selection", [s], ""),
            ("budget", ["--write"], "Comptable, taille de la position ?"),
            ("risk", [], "Gardien, vérification des règles."),
            ("broker", ["show"], "Courtier, le ticket pour validation humaine."),
        ],
        "web": [
            ("alerts", ["clock"], "Sentinelle, la bourse est ouverte ?"),
            ("fouineuse", ["yahoo"], "Fouineuse, qu'est-ce qui bouge sur Yahoo ?"),
            ("crieur", ["foule"], "Crieur, de quoi parlent les traders en ligne ?"),
            ("selection", web_ideas, ""),
            ("budget", ["--write"], "Comptable, combien d'actions ?"),
            ("risk", [], "Gardien, ça respecte nos règles ?"),
            ("broker", ["show"], "Courtier, prépare le ticket (sans l'envoyer)."),
        ],
        "surveiller": [
            ("alerts", ["check"], "Sentinelle, une alerte a sonné ?"),
        ],
    }
    if marche() == "US":
        return toutes
    # Ailleurs qu'à New York : sans les agents US ; « Idées du web » n'a plus rien à chercher.
    # Volumes plus faibles à Paris : plancher journalier 200 000 actions au lieu de 1 million.
    toutes["matin"][1] = ("scanner", ["daily", "--show", "15", "--min-volume", "200000"], toutes["matin"][1][2])
    return {k: [e for e in v if e[0] not in US_SEULEMENT] for k, v in toutes.items() if k != "web"}

def run_agent(agent, args):
    script = SKILLS / AGENTS[agent][1]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", BDT_MARCHE=marche())
    p = subprocess.Popen([sys.executable, str(script), *args], cwd=base(), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = []
    for line in p.stdout:
        line = line.rstrip()
        lines.append(line)
        emit({"type": "line", "agent": agent, "text": line})
    try:
        code = p.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        p.kill(); code = -1
    return code, lines

# Du plus parlant au moins parlant : la bulle montre la première ligne qui correspond.
PRIORITY = [re.compile(p, re.I) for p in (
    r"^Leans|^Favou?rs|coin flip|^Verdict",
    r"\b(WAITING|TRIGGERED|EXPIRED|PASS|BLOCK|READY)\b",
    r"vs yesterday|matched|NYSE|refus",
    r"Wrote")]

NOISE = re.compile(r"financial advice|^Next:|^A scan is|^usage:|not a list of stocks", re.I)

PLAN = re.compile(r"^(Entry|Stop|Target)\s+([$€][\d.,]+)")

def summary(lines):
    useful = [l.strip() for l in lines if l.strip() and not NOISE.search(l)]
    plan = dict(m.groups() for m in map(PLAN.match, useful) if m)
    if len(plan) == 3:
        return f"Entrée {plan['Entry']} · Stop {plan['Stop']} · Objectif {plan['Target']}"
    for pat in PRIORITY:
        for l in useful:
            if pat.search(l):
                return l[:180]
    return useful[-1][:180] if useful else "(rien à dire)"

# ---------- Journal de mission ----------
# Une mission = un identifiant, son état, chaque étape (agent, code, statut) et chaque décision avec sa raison,
# dans trader/state/missions/<id>.json (réécrit après chaque étape : rien ne se perd si le bureau s'arrête).
en_cours = {}


def journal(**x):
    if "etapes" not in en_cours:   # hors mission (sélection appelée seule)
        return
    en_cours["etapes"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **x})
    f = dossier(en_cours["marche"]) / "state" / "missions" / f"{en_cours['id']}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(en_cours, indent=1, ensure_ascii=False), encoding="utf-8")


def statut(agent, code):
    """SUCCESS, FAILED ou BLOCKED (refus du Gardien) ; WARNING et INSUFFICIENT_DATA viennent du Directeur."""
    if code == 0:
        return "SUCCESS"
    if agent in INFO_SEULEMENT:
        return "WARNING"
    return "BLOCKED" if agent == "risk" and code == 1 else "FAILED"


def step(agent, args, order):
    emit({"type": "order", "agent": agent, "text": order})
    emit({"type": "step", "agent": agent, "status": "start", "cmd": " ".join([AGENTS[agent][1], *args])})
    code, lines = run_agent(agent, args)
    resume = summary(lines)
    emit({"type": "step", "agent": agent, "status": "done" if code == 0 else "fail", "code": code, "summary": resume})
    journal(agent=agent, args=args, code=code, statut=statut(agent, code), resume=resume)
    return code, lines


def decision(sym, etat, raison, e=None):
    """Décision sur un candidat : dite, mise au journal de mission et dans l'historique des opportunités."""
    journal(agent="selection", symbol=sym, statut=etat, resume=raison)
    say(f"{sym} : {raison}")
    e = e or {}
    try:
        plan = json.loads((dossier() / "plan.json").read_text(encoding="utf-8")) if etat == "VALIDATED" else {}
    except (OSError, ValueError):
        plan = {}
    with closing(base_historique()) as h:
        en_cours["opportunite"] = historique.noter(
            h, mission=en_cours.get("id"), jour=e.get("date") or jour_marche(), heure=e.get("bar_start"),
            marche=marche(), symbole=sym, strategie=e.get("setup") or "orb", etat=etat, raison=raison,
            entree=plan.get("entry") or e.get("price"), stop=plan.get("stop"), objectif=plan.get("target"),
            maj=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def suite_opportunite(agent, code, resume):
    """Après la sélection : un blocage (taille, Gardien, ticket) ou le ticket prêt, avec les chiffres du Gardien."""
    ident = en_cours.get("opportunite")
    if not ident:
        return
    if code != 0:
        with closing(base_historique()) as h:
            historique.maj(h, ident, etat="BLOCKED", raison=f"{AGENTS[agent][0]} : {resume}")
    elif agent == "broker":
        try:
            r = json.loads((dossier() / "state" / "risk.json").read_text(encoding="utf-8"))["results"][0]
        except (OSError, ValueError, KeyError, IndexError):
            r = {}
        with closing(base_historique()) as h:
            historique.maj(h, ident, etat="TICKET", raison="ticket prêt, en attente de ton clic",
                           qty=r.get("amount"), risque_prevu=r.get("max_loss"), entree=r.get("entry_ref"),
                           stop=r.get("stop"), objectif=r.get("target"))


def select_trade(candidates):
    """Teste chaque candidat (entrée récente → plan à 1R → 10 000 rejeux → historique) et garde le premier validé."""
    if not candidates:
        journal(agent="selection", statut="INSUFFICIENT_DATA", resume="aucun candidat")
    for sym in candidates[:MAX_CANDIDATES]:
        code, _ = step("entry", ["check", sym, "--setup", "orb", "--write"], f"Guetteur, {sym} : le signal est encore frais ?")
        try:
            e = json.loads((dossier() / "entry.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            e = {}
        if code != 0 or e.get("symbol") != sym or e.get("status") != "triggered":
            decision(sym, "REJECTED", f"pas de signal ({e.get('status', 'rien')}), au suivant.", e)
            continue
        age = age_signal(e, marche())
        if age is None:
            decision(sym, "INSUFFICIENT_DATA", "âge du signal inconnu, on ne prend pas le risque.", e)
            continue
        if age > MAX_AGE_MIN:
            decision(sym, "REJECTED", f"signal vieux de {age:.0f} min, trop tard. Au suivant.", e)
            continue
        # Objectif à 1R : plus proche, donc atteint plus souvent (gain plus petit).
        if step("exit", ["plan", "--target", "1R", "--write"], "Stratège, stop et objectif proche (1R).")[0] != 0:
            decision(sym, "INSUFFICIENT_DATA", "le Stratège n'a pas pu faire de plan. Au suivant.", e)
            continue
        if step("timemachine", ["run", "--write"], "Voyageur, rejoue-le 10 000 fois.")[0] != 0:
            decision(sym, "INSUFFICIENT_DATA", "le Voyageur n'a pas pu rejouer le setup (données). Au suivant.", e)
            continue
        tm = json.loads((dossier() / "timemachine.json").read_text(encoding="utf-8"))
        v = validation.valider(tm, load_config(), marche())
        (dossier() / "state").mkdir(exist_ok=True)
        (dossier() / "state" / "validation.json").write_text(
            json.dumps({"symbol": sym, "at": envois.maintenant(), **v}, indent=1, ensure_ascii=False), encoding="utf-8")
        hs = v.get("historique") or {}
        if v["etat"] == "VALIDATED":
            decision(sym, "VALIDATED", f"VALIDÉ sur {hs['trades']} séances passées (espérance {hs['expectancy_R']:+.2f}R "
                                       f"après frais, {hs['win_rate']:.0%} gagnants). On le prépare.", e)
            return True
        decision(sym, v["etat"], f"{'données insuffisantes' if v['etat'] == 'INSUFFICIENT_DATA' else 'rejeté'} "
                                 f"({' ; '.join(v['raisons'])}). On passe.", e)
    say("Aucun trade favorable : aujourd'hui on ne trade pas. Ne rien faire, c'est aussi gagner.")
    return False


def run_mission(name, symbol):
    steps = missions(symbol).get(name)
    if not steps:
        return
    en_cours.clear()
    en_cours.update(id=f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{name}", mission=name, symbol=symbol,
                    marche=marche(), etat="EN_COURS", etapes=[])
    emit({"type": "mission", "status": "start", "name": name, "symbol": symbol, "id": en_cours["id"]})
    ok = True
    try:
        for agent, args, order in steps:
            if arret_urgence() and name != "surveiller":
                say("Arrêt d'urgence : mission interrompue.")
                en_cours["etat"] = "INTERROMPUE"
                ok = False
                break
            if agent == "analyst" and not sec_ready():
                say("Pas d'identité SEC dans ⚙ : l'Analyste saute son tour.")
                journal(agent=agent, statut="WARNING", resume="pas d'identité SEC, étape sautée")
                continue
            if agent == "selection":
                cands = args() if callable(args) else args or recent_triggers()
                if not select_trade(cands):
                    ok = False
                    break
                continue
            code, lines = step(agent, args, order)
            suite_opportunite(agent, code, summary(lines))
            if code != 0 and agent in INFO_SEULEMENT:
                say(f"Rien d'utilisable de ce côté ({summary(lines)}), on continue sans.")
                continue
            if code != 0:   # étape critique ratée : on ne poursuit jamais
                say(f"On s'arrête là : {summary(lines)}")
                ok = False
                break
    except Exception as e:
        ok = False
        journal(agent="directeur", statut="FAILED", resume=f"erreur : {e}")
        raise
    finally:
        if en_cours.get("etat") == "EN_COURS":
            en_cours["etat"] = "TERMINEE" if ok else "ARRETEE"
        journal(agent="directeur", statut="SUCCESS" if ok else "BLOCKED", resume=f"mission {en_cours.get('etat', '').lower()}")
        emit({"type": "mission", "status": "end", "name": name, "ok": ok})
        en_cours.clear()
