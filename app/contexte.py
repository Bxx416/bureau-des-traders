"""Contexte partagé : chemins, réglages par place boursière, horaires de Paris, événements vers la fenêtre."""
import json, os, shutil, sys, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))
import marche as horaires   # calendrier des places (skills/marche.py)

ROOT = Path(__file__).resolve().parent.parent          # C:\Users\benja\Trading

SKILLS = ROOT / "skills"   # copie des scripts trader-* : l'app marche sans Claude Code installé

TRADER = ROOT / "trader"

CONFIG = TRADER / "config.json"

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

MAX_AGE_MIN = 30      # au-delà, l'entrée est périmée : le prix et les chances ont bougé

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

def say(text):
    emit({"type": "say", "agent": "directeur", "text": text})

def sec_ready():
    ua = load_config().get("sec_user_agent", "")
    return "@" in ua and "example.com" not in ua

def config_racine():
    if not CONFIG.exists():
        TRADER.mkdir(exist_ok=True)
        cfg = json.loads((SKILLS / "trader-budget" / "config.example.json").read_text(encoding="utf-8"))
        cfg["sec_user_agent"] = ""
        CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return json.loads(CONFIG.read_text(encoding="utf-8"))

# ---------- Places boursières ----------
# US : tout reste dans trader/ comme avant. PA (Euronext Paris) : trader/paris/trader/, ses propres
# règles, plan, ordres et limites du jour ; les scripts reçoivent BDT_MARCHE=PA (skills/marche.py).
MARCHES = {"US": "New York", "PA": "Paris"}

GLOBAL = ("marche", "sec_user_agent", "ibkr_port")   # réglages communs, rangés dans trader/config.json

PARIS_DEFAUT = {"no_entries_before": "09:15", "no_entries_after": "17:00", "flat_by": "17:20", "broker": "ibkr"}

def marche():
    m = config_racine().get("marche", "US")
    return m if m in MARCHES else "US"

def base(m=None):
    return ROOT if (m or marche()) == "US" else TRADER / "paris"

def dossier(m=None):
    return base(m) / "trader"

def config_marche(m):
    """Config des règles de la place m ; pour Paris, créée au 1er usage à partir de celle de New York."""
    f = dossier(m) / "config.json"
    if not f.exists():
        dossier(m).mkdir(parents=True, exist_ok=True)
        cfg = {k: v for k, v in config_racine().items() if k not in SECRETS + GLOBAL}
        f.write_text(json.dumps({**cfg, **PARIS_DEFAUT}, indent=2, ensure_ascii=False), encoding="utf-8")
        shutil.copy(SKILLS / "marche-paris.txt", dossier(m) / "universe.txt")
    return json.loads(f.read_text(encoding="utf-8"))

def load_config():
    """Réglages communs + règles de la place active (celles-ci gagnent)."""
    r = config_racine()
    return r if marche() == "US" else {**r, **config_marche(marche())}

EDITABLE = {"budget": float, "max_loss_per_trade_usd": float, "max_daily_loss_usd": float,
            "max_trades_per_day": int, "min_reward_risk": float, "sec_user_agent": str, "ibkr_port": int}

SECRETS = ("alpaca_key_id", "alpaca_secret")   # jamais renvoyées au navigateur

def dry_run():
    return os.environ.get("BDT_DRY_RUN") == "1" or bool(config_racine().get("dry_run"))

ARRET = TRADER / "ARRET_URGENCE"   # tant que ce fichier existe : ni mission de trading ni envoi

def arret_urgence():
    return ARRET.exists()

DERNIERE_ENTREE_PARIS = (17, 0)

def heure_paris():
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    return utc + timedelta(hours=horaires.paris_offset(utc))

def cloture_paris(local):
    """Heure de clôture d'Euronext ce jour-là (datetime local), ou None si fermé toute la journée."""
    d = local.date().isoformat()
    if local.weekday() >= 5 or d in horaires.FERIES_PA:
        return None
    return datetime.combine(local.date(), horaires.COURTE if d in horaires.COURTS_PA else horaires.CLOTURE)

def paris_ouvert(local):
    c = cloture_paris(local)
    return bool(c) and datetime.combine(local.date(), horaires.OUVERTURE) <= local < c

assert paris_ouvert(datetime(2026, 11, 13, 10, 0)) and not paris_ouvert(datetime(2026, 11, 14, 10, 0))

assert not paris_ouvert(datetime(2026, 12, 24, 14, 10)) and not paris_ouvert(datetime(2026, 11, 13, 17, 30))

def pousse(ev):
    """Événement direct aux fenêtres ouvertes, hors historique (pas rejoué au rechargement)."""
    with clients_lock:
        for q in clients:
            q.put(json.dumps(ev, ensure_ascii=False))


def base_historique(m=None):
    """Historique des opportunités de la place m (app/historique.py)."""
    import historique
    return historique.ouvre(dossier(m) / "state" / "historique.db")


def jour_marche(m=None):
    """Date du jour à la Bourse m (New York ou Paris), au format AAAA-MM-JJ."""
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    ny = utc + timedelta(hours=horaires.ny_offset(utc))
    return (heure_paris() if (m or marche()) == "PA" else ny).date().isoformat()
