"""Bureau des Traders : serveur local qui fait travailler les agents trader-* ensemble.

Le Directeur enchaîne les scripts des skills (copiés dans skills/) et envoie chaque
étape au navigateur (Server-Sent Events) pour l'animation pixel art.
Le Courtier prépare le ticket ; il n'est envoyé (compte PAPIER Alpaca uniquement) qu'après un clic confirmé.
"""
import json, os, queue, re, shutil, subprocess, sys, threading, time, webbrowser
import urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import envois
from contexte import (AGENTS, ARRET, CONFIG, EDITABLE, GLOBAL, MARCHES, ROOT, SECRETS, VersJournal, arret_urgence, busy, clients, clients_lock, config_marche, config_racine, dossier, dry_run, fenetres, history, load_config, marche, pousse, say)
from orchestrateur import (missions, run_mission)
from courtier import (alpaca_ok, bilan, envoyer_ticket, gardien_cloture, journal_envois, reconcilier)

STATIC = Path(__file__).resolve().parent / "static"

CODE = __import__("hashlib").sha1(Path(__file__).read_bytes()).hexdigest()[:12]   # version du code chargé

PORT = int(os.environ.get("BDT_PORT", 8765))   # autre port : pour tester une 2e copie à côté

if sys.stdout is None:
    sys.stdout = sys.stderr = VersJournal()

# ---------- Nom d'entreprise → ticker ----------
BOURSES = {"US": {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX"},   # Nasdaq, NYSE, NYSE American, NYSE Arca (pas l'OTC)
           "PA": {"PAR"}}                                       # Euronext Paris

TICKER_OK = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")

def vers_ticker(texte):
    """« nvidia » → NVDA, « lvmh » → MC.PA : 1re action de la Bourse active selon la recherche Yahoo. None si aucune."""
    from agents.idees import get
    try:
        d = get("https://query2.finance.yahoo.com/v1/finance/search?quotesCount=10&newsCount=0&q="
                + urllib.parse.quote(texte))
        t = next((q["symbol"] for q in d.get("quotes", [])
                  if q.get("quoteType") == "EQUITY" and q.get("exchange") in BOURSES[marche()]), None)
    except (OSError, ValueError, KeyError):
        t = texte.upper()   # Yahoo injoignable : on tente tel quel
    if t and marche() == "PA" and not t.endswith(".PA"):
        t = None   # une action de New York tapée en mode Paris
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
                                   "alpaca": alpaca_ok(), "code": CODE, "arret": arret_urgence(),
                                   "dry_run": dry_run(), "inconnus": len(envois.bloquants(journal_envois())), "marche": marche(), "marches": MARCHES})
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
                    return self.send_json({"error": f"« {saisi} » : aucune action cotée à {MARCHES[marche()]} trouvée."}, 400)
                if symbol != saisi.upper():
                    say(f"« {saisi} », c'est le ticker {symbol}.")
            if name not in missions(symbol):
                return self.send_json({"error": "mission inconnue"}, 400)
            if name != "surveiller" and arret_urgence():
                return self.send_json({"error": "Arrêt d'urgence actif."}, 423)
            if name != "surveiller" and envois.bloquants(journal_envois()):
                return self.send_json({"error": "Un envoi est dans un état inconnu : réconcilie-le d'abord."}, 409)
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
            if "marche" in body and body["marche"] not in MARCHES:
                return self.send_json({"error": "place inconnue"}, 400)
            if body.get("marche", marche()) != marche() and busy.locked():
                return self.send_json({"error": "Attends la fin de la mission pour changer de Bourse."}, 409)
            m = marche()
            racine = config_racine()
            regles = racine if m == "US" else config_marche(m)
            for k, cast in EDITABLE.items():
                if k in body and str(body[k]).strip() != "":
                    try:
                        (racine if k in GLOBAL else regles)[k] = cast(body[k])
                    except (TypeError, ValueError):
                        return self.send_json({"error": f"valeur invalide pour {k}"}, 400)
            for k in SECRETS:   # champ vide = on garde la clé déjà enregistrée
                if str(body.get(k) or "").strip():
                    racine[k] = str(body[k]).strip()
            if m != "US":
                (dossier(m) / "config.json").write_text(json.dumps(regles, indent=2, ensure_ascii=False), encoding="utf-8")
            if "marche" in body:   # après les règles : elles vont à la place qu'on quitte
                racine["marche"] = body["marche"]
            CONFIG.write_text(json.dumps(racine, indent=2, ensure_ascii=False), encoding="utf-8")
            if "marche" in body and body["marche"] != m:
                config_marche(body["marche"])
                say(f"On passe à la Bourse de {MARCHES[body['marche']]}.")
            return self.send_json({"ok": True})
        if self.path == "/api/redemarrer":   # un lancement plus récent demande la place
            if busy.locked() or maj["etat"] == "maj":
                return self.send_json({"error": "occupé"}, 409)
            threading.Thread(target=redemarrer, daemon=True).start()
            return self.send_json({"ok": True})
        if self.path == "/api/arret":   # arrêt d'urgence : effet immédiat, même pendant une mission
            if body.get("actif"):
                ARRET.write_text(envois.maintenant(), encoding="utf-8")
                say("ARRÊT D'URGENCE : plus aucune mission de trading ni aucun envoi.")
            elif ARRET.exists():
                ARRET.unlink()
                say("Arrêt d'urgence levé.")
            return self.send_json({"ok": True, "arret": arret_urgence()})
        if self.path == "/api/reconcilier":
            if not busy.acquire(blocking=False):
                return self.send_json({"error": "Le Directeur est occupé."}, 409)
            try:
                reste = reconcilier()
            finally:
                busy.release()
            return self.send_json({"ok": not reste, "inconnus": [r["cle"] for r in reste]})
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
