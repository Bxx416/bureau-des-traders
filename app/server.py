"""Bureau des Traders : serveur local qui fait travailler les agents trader-* ensemble.

Le Directeur enchaîne les scripts des skills (copiés dans skills/) et envoie chaque
étape au navigateur (Server-Sent Events) pour l'animation pixel art.
Le Courtier prépare le ticket ; il n'est envoyé (compte PAPIER Alpaca uniquement) qu'après un clic confirmé.
"""
import json, os, queue, re, shutil, subprocess, sys, threading, time, webbrowser
import urllib.error, urllib.parse, urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # C:\Users\benja\Trading
STATIC = Path(__file__).resolve().parent / "static"
SKILLS = ROOT / "skills"   # copie des scripts trader-* : l'app marche sans Claude Code installé
TRADER = ROOT / "trader"
CONFIG = TRADER / "config.json"
CODE = __import__("hashlib").sha1(Path(__file__).read_bytes()).hexdigest()[:12]   # version du code chargé
PORT = int(os.environ.get("BDT_PORT", 8765))   # autre port : pour tester une 2e copie à côté

AGENTS = {
    "directeur":  ("Directeur", None),
    "scanner":    ("Scanner", "trader-scanner/scan.py"),
    "news":       ("Journaliste", "trader-news/news.py"),
    "entry":      ("Guetteur", "trader-entry/entry.py"),
    "exit":       ("Stratège", "trader-exit/exit.py"),
    "timemachine":("Voyageur", "trader-timemachine/timemachine.py"),
    "budget":     ("Comptable", "trader-budget/size.py"),
    "risk":       ("Gardien", "trader-risk/check.py"),
    "broker":     ("Courtier", "trader-broker/ticket.py"),
    "alerts":     ("Sentinelle", "trader-alerts/alerts.py"),
    "analyst":    ("Analyste", "trader-analyst/facts.py"),
    "pelosi":     ("Espion", "trader-pelosi/ptr.py"),
    "fouineuse":  ("Fouineuse", str(ROOT / "app" / "agents" / "idees.py")),
    "crieur":     ("Crieur", str(ROOT / "app" / "agents" / "idees.py")),
}

def web_ideas():
    doc = json.loads((TRADER / "idees.json").read_text(encoding="utf-8"))
    return [i["symbol"] for i in doc.get("classement", [])]

TRIGGERED = re.compile(r"^\s*([A-Z][A-Z.\-]{0,9})\s+triggered\b")

TRIGGER_TIME = re.compile(r"triggered\s+(\d{1,2}):(\d{2})\s*([AP]M)")
LATE = re.compile(r"That was (\d+) minutes ago")
MAX_AGE_MIN = 30      # au-delà, l'entrée est périmée : le prix et les chances ont bougé
MAX_CANDIDATES = 6

def recent_triggers(lines):
    """Tickers « triggered », du déclenchement le plus récent au plus ancien."""
    found = []
    for line in lines:
        m, t = TRIGGERED.match(line), TRIGGER_TIME.search(line)
        if m and t:
            h, mi, ap = int(t.group(1)) % 12, int(t.group(2)), t.group(3)
            found.append(((h + (12 if ap == "PM" else 0)) * 60 + mi, m.group(1)))
    return [s for _, s in sorted(found, reverse=True)]

def favorable(tm):
    """Le trade n'est gardé que si les rejeux ET l'historique sont du bon côté."""
    mc, h = tm.get("mc") or {}, tm.get("history") or {}
    if (mc.get("avg_R") or 0) <= 0 or mc.get("p_target", 0) <= mc.get("p_stop", 1):
        return False
    return h.get("triggered", 0) < 5 or (h.get("avg_R") or 0) > 0

# Chaque mission = liste d'étapes (agent, arguments, phrase du directeur).
# shortcut: les missions sont figées ici, à rendre éditables si tu veux en créer d'autres.
def missions(symbol):
    s = (symbol or "").upper().strip()
    return {
        "matin": [
            ("alerts", ["clock"], "Sentinelle, la bourse est ouverte ?"),
            ("scanner", ["daily", "--show", "15"], "Scanner, trouve-moi les graphiques intéressants !"),
            ("news", ["--watchlist", "trader/watchlist.json", "--no-sec", "--hours", "16"], "Journaliste, des nouvelles sur ces actions ?"),
            ("pelosi", ["new", "--dry-run"], "Espion, le Congrès a acheté quoi ?"),
        ],
        "cassure": [
            ("alerts", ["clock"], "Sentinelle, quelle heure à New York ?"),
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

clients, clients_lock = [], threading.Lock()
fenetres = []  # connexions venant de la fenêtre du bureau (?app=1) : elles seules la gardent allumée
busy = threading.Lock()
history = []          # derniers événements, pour un navigateur qui se reconnecte

def emit(ev):
    history.append(ev)
    del history[:-300]
    data = json.dumps(ev, ensure_ascii=False)
    with clients_lock:
        for q in clients:
            q.put(data)

class VersJournal:
    """Sans fenêtre noire (pythonw), les messages du serveur vont dans le journal du bureau et dans app/serveur.log."""
    def __init__(self):
        self.buf, self.f = "", open(ROOT / "app" / "serveur.log", "w", encoding="utf-8")
    def write(self, t):
        self.f.write(t); self.f.flush()
        *lignes, self.buf = (self.buf + t).split("\n")
        for l in lignes:
            if l.strip():
                emit({"type": "serveur", "text": l})
        return len(t)
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = sys.stderr = VersJournal()

def run_agent(agent, args):
    script = SKILLS / AGENTS[agent][1]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, str(script), *args], cwd=ROOT, env=env,
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
PLAN = re.compile(r"^(Entry|Stop|Target)\s+(\$[\d.,]+)")

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

def say(text):
    emit({"type": "say", "agent": "directeur", "text": text})

def step(agent, args, order):
    emit({"type": "order", "agent": agent, "text": order})
    emit({"type": "step", "agent": agent, "status": "start", "cmd": " ".join([AGENTS[agent][1], *args])})
    code, lines = run_agent(agent, args)
    emit({"type": "step", "agent": agent, "status": "done" if code == 0 else "fail",
          "code": code, "summary": summary(lines)})
    return code, lines

def select_trade(candidates):
    """Teste chaque candidat (entrée récente → plan à 1R → 10 000 rejeux) et garde le premier favorable."""
    for sym in candidates[:MAX_CANDIDATES]:
        code, lines = step("entry", ["check", sym, "--setup", "orb", "--write"], f"Guetteur, {sym} : le signal est encore frais ?")
        late = next((int(m.group(1)) for m in map(LATE.search, lines) if m), 0)
        if code != 0 or not any("TRIGGERED" in l for l in lines):
            say(f"{sym} : pas de signal, au suivant."); continue
        if late > MAX_AGE_MIN:
            say(f"{sym} : signal vieux de {late} min, trop tard. Au suivant."); continue
        # Objectif à 1R : plus proche, donc atteint plus souvent (gain plus petit).
        if step("exit", ["plan", "--target", "1R", "--write"], "Stratège, stop et objectif proche (1R).")[0] != 0:
            continue
        if step("timemachine", ["run", "--write"], "Voyageur, rejoue-le 10 000 fois.")[0] != 0:
            continue
        tm = json.loads((TRADER / "timemachine.json").read_text(encoding="utf-8"))
        if favorable(tm):
            say(f"{sym} : les chances sont de notre côté. On le prépare.")
            return True
        mc, h = tm.get("mc") or {}, tm.get("history") or {}
        say(f"{sym} : défavorable (rejeux {mc.get('avg_R', 0):+.2f}R, objectif {mc.get('p_target', 0):.0%} contre stop "
            f"{mc.get('p_stop', 0):.0%} ; historique {h.get('target', 0)} gagnés / {h.get('stop', 0)} perdus). On passe.")
    say("Aucun trade favorable : aujourd'hui on ne trade pas. Ne rien faire, c'est aussi gagner.")
    return False

def run_mission(name, symbol):
    steps = missions(symbol).get(name)
    if not steps:
        return
    emit({"type": "mission", "status": "start", "name": name, "symbol": symbol})
    ok, lines = True, []
    for agent, args, order in steps:
        if agent == "analyst" and not sec_ready():
            say("Pas d'identité SEC dans ⚙ : l'Analyste saute son tour.")
            continue
        if agent == "selection":
            cands = args() if callable(args) else args or recent_triggers(lines)
            if not select_trade(cands):
                ok = False
                break
            continue
        code, lines = step(agent, args, order)
        if code != 0:
            say(f"On s'arrête là : {summary(lines)}")
            ok = False
            break
    emit({"type": "mission", "status": "end", "name": name, "ok": ok})

def sec_ready():
    ua = load_config().get("sec_user_agent", "")
    return "@" in ua and "example.com" not in ua

def load_config():
    if not CONFIG.exists():
        TRADER.mkdir(exist_ok=True)
        cfg = json.loads((SKILLS / "trader-budget" / "config.example.json").read_text(encoding="utf-8"))
        cfg["sec_user_agent"] = ""
        CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return json.loads(CONFIG.read_text(encoding="utf-8"))

EDITABLE = {"budget": float, "max_loss_per_trade_usd": float, "max_daily_loss_usd": float,
            "max_trades_per_day": int, "min_reward_risk": float, "sec_user_agent": str}
SECRETS = ("alpaca_key_id", "alpaca_secret")   # jamais renvoyées au navigateur

# ---------- Compte papier Alpaca ----------
# Papier seulement : passer au réel se fera à la main, exprès, pas par un réglage.
ALPACA = "https://paper-api.alpaca.markets"
DERNIERE_ENTREE_NY = (11, 0)   # 11h New York = 17h Paris : après, plus de nouvelle entrée
CLOTURE_AVANT_S = 600          # 10 min avant la clôture, tout est fermé

def alpaca_ok():
    cfg = load_config()
    return all(cfg.get(k) for k in SECRETS)

def alpaca(method, path, body=None):
    cfg = load_config()
    req = urllib.request.Request(ALPACA + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"APCA-API-KEY-ID": cfg.get("alpaca_key_id", ""),
                                          "APCA-API-SECRET-KEY": cfg.get("alpaca_secret", ""),
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Alpaca {e.code} : {e.read().decode(errors='replace')[:200]}") from None

def ticket_cmd(*args):
    """ticket.py sans écrire dans le journal (sortie JSON)."""
    p = subprocess.run([sys.executable, str(SKILLS / AGENTS["broker"][1]), *args], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1"),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return p.returncode, p.stdout + p.stderr

def vers_alpaca(ti):
    """Arguments du ticket (noms du MCP place_stock_order) → corps de POST /v2/orders."""
    o = {k: v for k, v in ti.items() if not k.startswith(("take_profit_", "stop_loss_"))}
    if "take_profit_limit_price" in ti:
        o["take_profit"] = {"limit_price": ti["take_profit_limit_price"]}
    if "stop_loss_stop_price" in ti:
        o["stop_loss"] = {"stop_price": ti["stop_loss_stop_price"],
                          **({"limit_price": ti["stop_loss_limit_price"]} if "stop_loss_limit_price" in ti else {})}
    return o

assert vers_alpaca({"symbol": "X", "qty": "2", "take_profit_limit_price": "11", "stop_loss_stop_price": "9"}) == \
    {"symbol": "X", "qty": "2", "take_profit": {"limit_price": "11"}, "stop_loss": {"stop_price": "9"}}

def envoyer_ticket(fingerprint):
    """Envoie le ticket n°1 au compte papier. Renvoie (code HTTP, réponse)."""
    if not alpaca_ok():
        return 400, {"error": "Ajoute tes clés Alpaca PAPIER dans ⚙ Réglages."}
    code, out = ticket_cmd("show", "--index", "1", "--json")
    try:
        t = json.loads(out)
    except json.JSONDecodeError:
        return 409, {"error": "Pas de ticket prêt : lance d'abord une mission."}
    if not t.get("ready"):
        return 409, {"error": f"Ticket pas prêt : {t.get('status')}"}
    if time.time() - (TRADER / "orders.json").stat().st_mtime > MAX_AGE_MIN * 60:
        return 409, {"error": f"Ticket vieux de plus de {MAX_AGE_MIN} min : relance une mission."}
    if not fingerprint:   # 1er appel : on montre le ticket, le navigateur demande confirmation
        return 200, {"plain": t["plain"], "max_loss": t["max_loss"], "fingerprint": t["fingerprint"]}
    if fingerprint != t["fingerprint"]:
        return 409, {"error": "Le ticket a changé entre-temps, revérifie-le."}
    ti = t["tool_input"]
    c = alpaca("GET", "/v2/clock")
    ny = datetime.fromisoformat(c["timestamp"])
    if not c["is_open"]:
        return 409, {"error": "La Bourse de New York est fermée."}
    if ti.get("side") == "buy" and (ny.hour, ny.minute) >= DERNIERE_ENTREE_NY:
        return 409, {"error": "Plus de nouvelle entrée après 17h (heure de Paris)."}
    code, out = ticket_cmd("approve", "--index", "1", "--reply", "yes")
    if code != 0:
        return 409, {"error": out.strip()[-200:]}
    try:
        o = alpaca("POST", "/v2/orders", vers_alpaca(ti))
    except (RuntimeError, OSError) as e:
        ticket_cmd("result", "--index", "1", "--status", "failed", "--note", str(e)[:200])
        return 502, {"error": str(e)}
    ticket_cmd("result", "--index", "1", "--status", "placed", "--broker-id", o["id"])
    say(f"Courtier : ordre envoyé au compte PAPIER ({t['plain']}).")
    return 200, {"ok": True, "id": o["id"]}

def gardien_cloture():
    """10 min avant la clôture, ferme tout sur le compte papier : rien ne reste ouvert la nuit."""
    fait = None
    while True:
        time.sleep(60)
        if not alpaca_ok():
            continue
        try:
            c = alpaca("GET", "/v2/clock")
            now, close = datetime.fromisoformat(c["timestamp"]), datetime.fromisoformat(c["next_close"])
            if c["is_open"] and (close - now).total_seconds() < CLOTURE_AVANT_S and fait != now.date():
                if alpaca("GET", "/v2/positions"):
                    alpaca("DELETE", "/v2/positions?cancel_orders=true")
                    say("Courtier : la clôture approche, je ferme toutes les positions du compte papier.")
                fait = now.date()
        except (RuntimeError, OSError, KeyError, ValueError) as e:
            print("Clôture papier :", e)

# ---------- Nom d'entreprise → ticker ----------
BOURSES_US = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX"}   # Nasdaq, NYSE, NYSE American, NYSE Arca (pas l'OTC)
TICKER_OK = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")

def vers_ticker(texte):
    """« nvidia » → NVDA : 1re action cotée à New York selon la recherche Yahoo. None si aucune."""
    from agents.idees import get
    try:
        d = get("https://query2.finance.yahoo.com/v1/finance/search?quotesCount=10&newsCount=0&q="
                + urllib.parse.quote(texte))
        t = next((q["symbol"] for q in d.get("quotes", [])
                  if q.get("quoteType") == "EQUITY" and q.get("exchange") in BOURSES_US), None)
    except (OSError, ValueError, KeyError):
        t = texte.upper()   # Yahoo injoignable : on tente tel quel
    return t if t and TICKER_OK.match(t) else None

# ---------- Bandeau des cours ----------
# shortcut: liste fixe, à rendre éditable dans ⚙ si on veut ses propres actions.
COURS = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones"), ("^FCHI", "CAC 40"),
         ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
         ("GC=F", "Or"), ("CL=F", "Pétrole"), ("EURUSD=X", "EUR/USD"),
         ("NVDA", "Nvidia"), ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("TSLA", "Tesla"), ("AMZN", "Amazon"), ("META", "Meta")]
cours_cache = {"t": 0.0, "data": []}

def cours():
    """Prix et variation du jour (Yahoo, gratuit, parfois différé). Gardé 60 s."""
    if time.time() - cours_cache["t"] < 60:
        return cours_cache["data"]
    from agents.idees import get
    d = get("https://query1.finance.yahoo.com/v7/finance/spark?range=1d&interval=1d&symbols="
            + urllib.parse.quote(",".join(s for s, _ in COURS)))
    meta = {r["symbol"]: r["response"][0]["meta"] for r in d["spark"]["result"] if r.get("response")}
    data = []
    for s, nom in COURS:
        m = meta.get(s) or {}
        prix, avant = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
        var = m.get("regularMarketChangePercent")
        if var is None and prix and avant:
            var = (prix / avant - 1) * 100
        if prix is not None and var is not None:
            data.append({"nom": nom, "prix": prix, "var": round(var, 2)})
    cours_cache.update(t=time.time(), data=data)
    return data

# ---------- Bilan du test papier ----------
def trades_fermes(fills):
    """Exécutions Alpaca → trades fermés : un trade se ferme quand la position de l'action revient à zéro (achats FIFO)."""
    pos, trades = {}, []
    for f in sorted(fills, key=lambda f: f["transaction_time"]):
        s = pos.setdefault(f["symbol"], {"lots": [], "pnl": 0.0})
        qty, px = float(f["qty"]), float(f["price"])
        if f["side"] == "buy":
            s["lots"].append([qty, px])
            continue
        while qty > 1e-9 and s["lots"]:
            lot = s["lots"][0]
            n = min(qty, lot[0])
            s["pnl"] += n * (px - lot[1]); lot[0] -= n; qty -= n
            if lot[0] < 1e-9:
                s["lots"].pop(0)
        if not s["lots"]:
            trades.append({"date": f["transaction_time"][:10], "symbol": f["symbol"], "pnl": round(s["pnl"], 2)})
            s["pnl"] = 0.0
    return trades

def _f(t, side, qty, px): return {"transaction_time": t, "symbol": "X", "side": side, "qty": qty, "price": px}
assert trades_fermes([_f("1", "buy", "10", "5"), _f("2", "sell", "4", "6"), _f("3", "sell", "6", "4.5"),
                      _f("4", "buy", "2", "3")]) == [{"date": "3", "symbol": "X", "pnl": 1.0}]

def bilan():
    fills, token = [], None
    while True:   # 100 exécutions par page
        page = alpaca("GET", "/v2/account/activities/FILL?direction=asc&page_size=100" + (f"&page_token={token}" if token else ""))
        fills += page
        if len(page) < 100:
            break
        token = page[-1]["id"]
    trades = trades_fermes(fills)
    pnls = [t["pnl"] for t in trades]
    serie = pire_serie = 0
    for p in pnls:
        serie = serie + 1 if p < 0 else 0
        pire_serie = max(pire_serie, serie)
    n, risque = len(pnls), load_config().get("max_loss_per_trade_usd") or 0
    compte = alpaca("GET", "/v2/account")
    return {"trades": n, "gagnants": sum(p > 0 for p in pnls), "total": round(sum(pnls), 2),
            "moyen": round(sum(pnls) / n, 2) if n else 0,
            "moyen_R": round(sum(pnls) / n / risque, 2) if n and risque else None,
            "meilleur": max(pnls, default=0), "pire": min(pnls, default=0), "pire_serie": pire_serie,
            "jours": len({t["date"] for t in trades}), "equity": round(float(compte["equity"]), 2),
            "ouvertes": len(alpaca("GET", "/v2/positions")), "derniers": trades[-10:][::-1]}

# ---------- Mises à jour au lancement ----------
# etat : verif -> propose (attend oui/non) -> maj -> pret ; les missions ne partent qu'à « pret ».
maj = {"etat": "verif", "liste": [], "pct": 0, "texte": ""}
UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")

def sh(cmd, timeout=60):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def cherche_maj():
    trouve = []
    try:
        _, out = sh([UV, "self", "update", "--dry-run"], 30)
        m = re.search(r"Would update uv from (v[\d.]+) to (v[\d.]+)", out)
        if m:
            trouve.append({"id": "uv", "nom": f"uv {m.group(1)} → {m.group(2)}", "cmd": [UV, "self", "update"]})
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        _, out = sh([UV, "python", "list", "3.12", "--output-format", "json"], 30)
        vs = json.loads(out[out.index("["):]) if "[" in out else []
        key = lambda v: tuple(v["version_parts"][k] for k in ("major", "minor", "patch"))
        inst = [v for v in vs if v.get("path")]
        dispo = [v for v in vs if not v.get("path") and v.get("variant") == "default"]
        if inst and dispo and key(max(dispo, key=key)) > key(max(inst, key=key)):
            trouve.append({"id": "python", "nom": f"Python {max(inst, key=key)['version']} → {max(dispo, key=key)['version']}",
                           "cmd": [UV, "python", "upgrade", "3.12"]})
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        pass
    x = maj_bureau()
    if x:
        trouve.append(x)
    maj.update(liste=trouve, etat="propose" if trouve else "pret")
    emit_maj()

# ---------- Nouvelle version du bureau ----------
DEPOT = "Bxx416/bureau-des-traders"   # les versions sont publiées dans ses Releases GitHub
redemarrage = threading.Event()

def version_locale():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"

def v_tuple(v):
    return tuple(int(n) for n in re.findall(r"\d+", v))

def maj_bureau():
    """Une version plus récente ? Copie de développement : git. Copie installée : dernière Release GitHub."""
    try:
        if (ROOT / ".git").exists():
            if sh(["git", "fetch", "--quiet"], 30)[0] == 0:
                code, out = sh(["git", "rev-list", "--count", "HEAD..@{u}"])
                if code == 0 and out.strip().isdigit() and int(out.strip()) > 0:
                    return {"id": "bureau", "nom": f"Bureau des Traders ({out.strip()} changement(s))",
                            "cmd": ["git", "pull", "--ff-only"]}
            return None
        from agents.idees import get
        r = get(f"https://api.github.com/repos/{DEPOT}/releases/latest")
        zip_url = next((a["browser_download_url"] for a in r.get("assets", []) if a["name"].endswith(".zip")), None)
        if zip_url and v_tuple(r["tag_name"]) > v_tuple(version_locale()):
            return {"id": "bureau", "nom": f"Bureau des Traders {version_locale()} → {r['tag_name'].lstrip('v')}",
                    "zip": zip_url}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        pass   # hors ligne, dépôt privé ou pas encore de Release : rien à proposer
    return None

def installe_zip(url):
    """Remplace les fichiers du bureau par ceux du zip publié. Jamais trader/ (réglages, clés) ni .venv."""
    import io, zipfile
    req = urllib.request.Request(url, headers={"User-Agent": "BureauDesTraders"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    racine = ROOT.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            parts = Path(info.filename).parts[1:]   # le zip contient « Bureau des Traders/… »
            if info.is_dir() or not parts or parts[0] in ("trader", ".git") or ".venv" in parts:
                continue
            cible = (ROOT / Path(*parts)).resolve()
            if not cible.is_relative_to(racine):
                raise ValueError(f"chemin refusé dans le zip : {info.filename}")
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(z.read(info))

def empreinte_serveur():
    return (ROOT / "app" / "server.py").read_bytes()

def pousse(ev):
    """Événement direct aux fenêtres ouvertes, hors historique (pas rejoué au rechargement)."""
    with clients_lock:
        for q in clients:
            q.put(json.dumps(ev, ensure_ascii=False))

def redemarrer():
    """Le code du serveur a changé : un nouveau serveur prend la place de celui-ci, la fenêtre revient seule."""
    say("Nouvelle version installée : je redémarre le bureau, la fenêtre revient dans quelques secondes.")
    pousse({"type": "redemarre"})
    time.sleep(2)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--apres-maj"], cwd=ROOT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    redemarrage.set()
    if webview:
        for w in list(webview.windows):
            w.destroy()

def veille_maj():
    """Pendant que le bureau est ouvert : toutes les 30 min, une nouvelle version est-elle publiée ?"""
    while not redemarrage.is_set():
        time.sleep(1800)
        if maj["etat"] != "pret" or busy.locked():
            continue
        x = maj_bureau()
        if x and x["nom"] != maj.get("refuse"):
            maj.update(liste=[x], etat="propose", texte="")
            emit_maj()

def emit_maj():
    # pas dans history : la fenêtre ne doit pas réapparaître au rechargement
    pousse({"type": "maj", **{k: v for k, v in maj.items() if k not in ("liste", "refuse")},
            "liste": [x["nom"] for x in maj["liste"]]})

def applique_maj():
    import zipfile
    liste, erreurs, avant = maj["liste"], [], empreinte_serveur()
    for i, x in enumerate(liste):
        maj.update(pct=int(i * 100 / len(liste)), texte=f"Mise à jour : {x['nom']}…"); emit_maj()
        try:
            if "zip" in x:
                installe_zip(x["zip"]); code, out = 0, ""
            else:
                code, out = sh(x["cmd"], 600)
        except (OSError, subprocess.TimeoutExpired, zipfile.BadZipFile, ValueError) as e:
            code, out = 1, str(e)
        if code:
            erreurs.append(x["nom"]); print(f"Mise à jour ratée ({x['nom']}) : {out.strip()[-300:]}")
    maj.update(etat="pret", pct=100, liste=[],
               texte="Mises à jour terminées." if not erreurs else "Certaines mises à jour ont échoué : " + ", ".join(erreurs))
    emit_maj()
    if any(x["id"] == "bureau" and x["nom"] not in erreurs for x in liste):
        if empreinte_serveur() != avant:
            redemarrer()
        else:   # seulement l'affichage ou les agents : un rechargement de la page suffit
            pousse({"type": "recharger"})

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # toujours la dernière version des fichiers
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/events":
            q, app = queue.Queue(), "app=1" in self.path
            with clients_lock:
                clients.append(q)
                if app:
                    fenetres.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    try:
                        data = q.get(timeout=3)  # ping fréquent : une fenêtre fermée est vue en quelques secondes
                        self.wfile.write(f"data: {data}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                with clients_lock:
                    clients.remove(q)
                    if app:
                        fenetres.remove(q)
            return
        if self.path == "/api/cours":
            try:
                return self.send_json(cours())
            except (OSError, ValueError, KeyError, IndexError) as e:
                return self.send_json({"error": str(e)}, 502)
        if self.path == "/api/bilan":
            if not alpaca_ok():
                return self.send_json({"error": "Ajoute tes clés Alpaca PAPIER dans ⚙ Réglages."}, 400)
            try:
                return self.send_json(bilan())
            except (RuntimeError, OSError, KeyError, ValueError) as e:
                return self.send_json({"error": str(e)}, 502)
        if self.path == "/api/state":
            return self.send_json({"agents": {k: v[0] for k, v in AGENTS.items()},
                                   "busy": busy.locked(), "history": history[-120:],
                                   "maj": {**{k: v for k, v in maj.items() if k != "liste"},
                                           "liste": [x["nom"] for x in maj["liste"]]},
                                   "config": {k: load_config().get(k) for k in EDITABLE},
                                   "alpaca": alpaca_ok(), "code": CODE})
        return super().do_GET()

    def do_POST(self):
        # Seul le navigateur local parle à ce serveur (il n'écoute que 127.0.0.1).
        # Une page web ouverte ailleurs peut aussi viser 127.0.0.1 : on refuse les autres origines.
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}"):
            return self.send_json({"error": "origine refusée"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self.send_json({"error": "JSON invalide"}, 400)
        if self.path == "/api/maj":
            if maj["etat"] != "propose":
                return self.send_json({"error": "rien à mettre à jour"}, 409)
            if body.get("oui"):
                maj["etat"] = "maj"
                threading.Thread(target=applique_maj, daemon=True).start()
            else:   # la même version ne sera pas reproposée pendant cette session
                maj.update(etat="pret", refuse=next((x["nom"] for x in maj["liste"] if x["id"] == "bureau"), None),
                           liste=[], texte="Mises à jour reportées."); emit_maj()
            return self.send_json({"ok": True})
        if self.path == "/api/mission":
            if maj["etat"] != "pret":
                return self.send_json({"error": "Le Directeur vérifie les mises à jour, un instant."}, 409)
            name, symbol = body.get("name"), str(body.get("symbol", "")).strip()[:40]
            if name == "action":
                if not symbol:
                    return self.send_json({"error": "Donne un ticker ou un nom, ex. TSLA ou Tesla"}, 400)
                saisi, symbol = symbol, vers_ticker(symbol)
                if not symbol:
                    return self.send_json({"error": f"« {saisi} » : aucune action cotée à New York trouvée."}, 400)
                if symbol != saisi.upper():
                    say(f"« {saisi} », c'est le ticker {symbol}.")
            if name not in missions(symbol):
                return self.send_json({"error": "mission inconnue"}, 400)
            if not busy.acquire(blocking=False):
                return self.send_json({"error": "Le Directeur est déjà sur une mission"}, 409)
            def job():
                try:
                    run_mission(name, symbol)
                finally:
                    busy.release()
            threading.Thread(target=job, daemon=True).start()
            return self.send_json({"ok": True})
        if self.path == "/api/config":
            cfg = load_config()
            for k, cast in EDITABLE.items():
                if k in body:
                    try:
                        cfg[k] = cast(body[k])
                    except (TypeError, ValueError):
                        return self.send_json({"error": f"valeur invalide pour {k}"}, 400)
            for k in SECRETS:   # champ vide = on garde la clé déjà enregistrée
                if str(body.get(k) or "").strip():
                    cfg[k] = str(body[k]).strip()
            CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            return self.send_json({"ok": True})
        if self.path == "/api/redemarrer":   # un lancement plus récent demande la place
            if busy.locked() or maj["etat"] == "maj":
                return self.send_json({"error": "occupé"}, 409)
            threading.Thread(target=redemarrer, daemon=True).start()
            return self.send_json({"ok": True})
        if self.path == "/api/envoyer":
            if not busy.acquire(blocking=False):
                return self.send_json({"error": "Le Directeur est occupé, réessaie après la mission."}, 409)
            try:
                code, rep = envoyer_ticket(str(body.get("fingerprint") or ""))
            except (RuntimeError, OSError) as e:
                code, rep = 502, {"error": str(e)}
            finally:
                busy.release()
            return self.send_json(rep, code)
        self.send_json({"error": "inconnu"}, 404)

def open_window(url):
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                shutil.which("chrome") or ""):
        if exe and Path(exe).exists():
            # profil dédié : la fenêtre du bureau ne se mélange pas aux onglets du navigateur habituel
            return subprocess.Popen([exe, f"--app={url}", "--window-size=1400,860",
                                     f"--user-data-dir={ROOT / 'app' / '.fenetre'}", "--no-first-run"])
    webbrowser.open(url)

try:
    import webview  # pywebview, installé dans app/.venv
except ImportError:
    webview = None

def icone_fenetre():
    """Met app/icone.ico sur la fenêtre et dans la barre des tâches (pywebview ne le fait pas sous Windows)."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.FindWindowW.restype = u.LoadImageW.restype = ctypes.c_void_p
        u.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT)
        u.SendMessageW.argtypes = (ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p)
        h = u.FindWindowW(None, "Bureau des Traders")
        ico = str(ROOT / "app" / "icone.ico")
        for grand, cote in ((1, 32), (0, 16)):  # WM_SETICON : ICON_BIG puis ICON_SMALL
            u.SendMessageW(h, 0x80, grand, u.LoadImageW(None, ico, 1, cote, cote, 0x10))  # IMAGE_ICON, LR_LOADFROMFILE
    except (OSError, AttributeError) as e:
        print("Icône de fenêtre non posée :", e)

def fenetre_logiciel(url):
    """Vraie fenêtre Windows (WebView2), sans navigateur ; rend la main quand on la ferme."""
    try:  # sa propre case dans la barre des tâches, au lieu d'être rangé avec Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Trading.BureauDesTraders")
    except (OSError, AttributeError):
        pass
    w = webview.create_window("Bureau des Traders", url, width=1400, height=860, min_size=(900, 600),
                              background_color="#12101c")
    w.events.shown += icone_fenetre
    webview.start(private_mode=False, storage_path=str(ROOT / "app" / ".fenetre"))

def attendre_fermeture(vu):
    """Rend la main quand plus aucune fenêtre du bureau n'est connectée."""
    debut, seul_depuis = time.time(), None
    while not redemarrage.is_set():
        with clients_lock:
            connecte = bool(fenetres)
        if connecte:
            vu, seul_depuis = True, None
        else:
            seul_depuis = seul_depuis or time.time()
            if (vu and time.time() - seul_depuis > 8) or (not vu and time.time() - debut > 90):
                return  # 8 s laissent le temps d'un rechargement ; 90 s si la fenêtre ne s'est jamais ouverte
        time.sleep(1)

if __name__ == "__main__":
    load_config()
    url = f"http://127.0.0.1:{PORT}/"
    ThreadingHTTPServer.allow_reuse_address = False  # sous Windows, sinon deux serveurs se partagent le port
    apres_maj = "--apres-maj" in sys.argv   # lancé par redemarrer() : l'ancien serveur libère le port
    for essai in range(60 if apres_maj else 1):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError:
            time.sleep(0.5)
    else:
        if apres_maj:
            sys.exit(1)
        try:   # le serveur déjà lancé a-t-il un code plus ancien ? Il passe la main (et rouvre la fenêtre)
            with urllib.request.urlopen(url + "api/state", timeout=5) as r:
                perime = json.loads(r.read()).get("code") != CODE
            if perime:
                urllib.request.urlopen(urllib.request.Request(url + "api/redemarrer", data=b"{}", method="POST"), timeout=5)
                print("Ancien serveur remplacé par la nouvelle version.")
                sys.exit(0)
        except (OSError, ValueError):
            pass   # occupé ou injoignable : on garde l'ancien comportement
        print("Le Bureau des Traders tourne déjà : j'ouvre juste la fenêtre.")
        fenetre_logiciel(url + "?app=1") if webview else open_window(url + "?app=1")
        sys.exit(0)
    print("Bureau des Traders sur", url)
    if apres_maj:
        maj.update(etat="pret", texte="")
    else:
        threading.Thread(target=cherche_maj, daemon=True).start()
    threading.Thread(target=veille_maj, daemon=True).start()
    threading.Thread(target=gardien_cloture, daemon=True).start()
    if "--no-window" in sys.argv:  # tourne jusqu'à Ctrl+C
        srv.serve_forever()
        sys.exit(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if webview:
        fenetre_logiciel(url + "?app=1")
        attendre_fermeture(vu=True)  # une 2e fenêtre ouverte entre-temps garde le bureau allumé
    else:
        # Repli navigateur. On ne surveille pas le processus Edge : si une fenêtre du bureau
        # existe déjà, Edge lui passe la main et le processus lancé meurt tout de suite.
        # Après une mise à jour, la page Edge déjà ouverte se reconnecte toute seule.
        if not apres_maj:
            open_window(url + "?app=1")
        attendre_fermeture(vu=False)
    if busy.locked():
        print("Fenêtre fermée : j'attends la fin de la mission en cours avant d'arrêter.")
    with busy:  # ne coupe pas une mission en plein milieu
        srv.shutdown()
        srv.server_close()   # libère le port tout de suite (redémarrage après mise à jour)
    print("Bureau des Traders arrêté." if not redemarrage.is_set() else "Ancien serveur arrêté, le nouveau prend la main.")
