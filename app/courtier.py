"""Courtier : comptes PAPIER Alpaca (New York) et IBKR (Paris), envoi idempotent, réconciliation, clôture, bilan."""
import json, os, subprocess, sys, threading, time
import urllib.error, urllib.parse, urllib.request
from contextlib import closing
from datetime import datetime
import ibkr, envois, historique
from contexte import (base_historique, AGENTS, DERNIERE_ENTREE_PARIS, MAX_AGE_MIN, SECRETS, SKILLS, arret_urgence, base, cloture_paris, config_racine, dossier, dry_run, heure_paris, load_config, marche, paris_ouvert, say)

# ---------- Compte papier Alpaca ----------
# Papier seulement : passer au réel se fera à la main, exprès, pas par un réglage.
ALPACA = "https://paper-api.alpaca.markets"

DERNIERE_ENTREE_NY = (11, 0)   # 11h New York = 17h Paris : après, plus de nouvelle entrée

CLOTURE_AVANT_S = 600          # 10 min avant la clôture, tout est fermé

def alpaca_ok():
    cfg = load_config()
    return all(cfg.get(k) for k in SECRETS)

class RefusCourtier(RuntimeError):
    """Le courtier a répondu (code HTTP) : on sait ce qui s'est passé, contrairement à une réponse perdue."""
    def __init__(self, code, texte):
        super().__init__(f"Alpaca {code} : {texte}")
        self.code = code

def url_papier(url):
    if urllib.parse.urlsplit(url).hostname != "paper-api.alpaca.markets" or not url.startswith("https://"):
        raise RuntimeError(f"URL de courtier refusée (pas le compte PAPIER) : {url}")
    return url

def alpaca(method, path, body=None):
    cfg = load_config()
    req = urllib.request.Request(url_papier(ALPACA + path), method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"APCA-API-KEY-ID": cfg.get("alpaca_key_id", ""),
                                          "APCA-API-SECRET-KEY": cfg.get("alpaca_secret", ""),
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RefusCourtier(e.code, e.read().decode(errors="replace")[:200]) from None

def ticket_cmd(*args, agent="broker"):
    """Script d'un agent sans écrire dans le journal (ticket.py par défaut, sortie JSON)."""
    p = subprocess.run([sys.executable, str(SKILLS / AGENTS[agent][1]), *args], cwd=base(),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", BDT_MARCHE=marche()),
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

def journal_envois(m=None):
    return envois.ouvre(dossier(m) / "state" / "envois.db")

def gardien_controle():
    """Le Gardien (check.py) refait son contrôle avec les chiffres du moment ; None si PASS, sinon la raison."""
    code, out = ticket_cmd("--json", agent="risk")
    if code == 0:
        return None
    try:
        r = json.loads(out[out.index("{"):])
        return "; ".join(x for o in r.get("results", []) for x in o.get("reasons", []))[:200] or "refus"
    except ValueError:
        return out.strip()[-200:] or "refus du Gardien"

def compte_papier_alpaca():
    n = str(alpaca("GET", "/v2/account").get("account_number", ""))
    if not n.startswith("PA"):   # les comptes papier Alpaca sont numérotés PA…
        raise RuntimeError("Ce n'est pas un compte PAPIER Alpaca : refusé.")

def envoyer_ticket(fingerprint):
    """Envoie le ticket n°1 au compte papier (Alpaca à New York, IBKR à Paris). Renvoie (code HTTP, réponse).
    Le Gardien contrôle avant d'afficher le ticket, à la confirmation, puis juste avant l'envoi."""
    pa = marche() == "PA"
    if arret_urgence():
        return 423, {"error": "Arrêt d'urgence actif : aucun envoi."}
    if not pa and not alpaca_ok():
        return 400, {"error": "Ajoute tes clés Alpaca PAPIER dans ⚙ Réglages."}
    db = journal_envois()
    if envois.bloquants(db):
        return 409, {"error": "Un envoi précédent est dans un état inconnu : réconcilie-le avant tout nouvel envoi."}
    refus = gardien_controle()
    if refus:
        return 409, {"error": f"Gardien : {refus}"}
    code, out = ticket_cmd("show", "--index", "1", "--json")
    try:
        t = json.loads(out)
    except json.JSONDecodeError:
        return 409, {"error": "Pas de ticket prêt : lance d'abord une mission."}
    if t.get("paper") is False:   # config « paper »: false : le bureau ne parle qu'aux comptes papier
        return 409, {"error": "Ce ticket vise un compte RÉEL : refusé, le bureau n'envoie qu'en papier."}
    if not t.get("ready"):
        return 409, {"error": f"Ticket pas prêt : {t.get('status')}"}
    if time.time() - (dossier() / "orders.json").stat().st_mtime > MAX_AGE_MIN * 60:
        return 409, {"error": f"Ticket vieux de plus de {MAX_AGE_MIN} min : relance une mission."}
    if not fingerprint:   # 1er appel : on montre le ticket, le navigateur demande confirmation
        return 200, {"plain": t["plain"], "max_loss": t["max_loss"], "fingerprint": t["fingerprint"]}
    if fingerprint != t["fingerprint"]:
        return 409, {"error": "Le ticket a changé entre-temps, revérifie-le."}
    ti = t["tool_input"]
    if pa:
        local = heure_paris()
        if not paris_ouvert(local):
            return 409, {"error": "La Bourse de Paris est fermée."}
        if ti.get("side") == "buy" and (local.hour, local.minute) >= DERNIERE_ENTREE_PARIS:
            return 409, {"error": "Plus de nouvelle entrée après 17h (heure de Paris)."}
    else:
        c = alpaca("GET", "/v2/clock")
        ny = datetime.fromisoformat(c["timestamp"])
        if not c["is_open"]:
            return 409, {"error": "La Bourse de New York est fermée."}
        if ti.get("side") == "buy" and (ny.hour, ny.minute) >= DERNIERE_ENTREE_NY:
            return 409, {"error": "Plus de nouvelle entrée après 17h (heure de Paris)."}
        compte_papier_alpaca()
    code, out = ticket_cmd("approve", "--index", "1", "--reply", "yes")
    if code != 0:
        return 409, {"error": out.strip()[-200:]}
    jour = (heure_paris() if pa else datetime.fromisoformat(c["timestamp"])).date().isoformat()
    k = envois.cle(t["fingerprint"], jour)
    try:
        envois.intention(db, k, jour, marche(), ti, t["fingerprint"])
    except envois.DejaEnvoye as e:
        return 409, {"error": str(e)}
    if dry_run():
        envois.maj(db, k, "DRY_RUN", note="rien envoyé")
        ticket_cmd("result", "--index", "1", "--status", "failed", "--note", "DRY_RUN : rien envoyé")
        say(f"Courtier : mode DRY_RUN, l'ordre n'est PAS envoyé ({t['plain']}).")
        return 200, {"ok": True, "dry_run": True}
    etat, oid, err = soumettre(pa, ti, k)
    envois.maj(db, k, etat, oid, err)
    with closing(base_historique()) as h:
        o = historique.derniere(h, ti["symbol"], jour)
        if o:   # l'opportunité garde la trace de son ordre (clé d'idempotence et état chez le courtier)
            historique.maj(h, o["id"], cle_envoi=k, etat="ENVOYE" if etat not in ("REJECTED", "UNKNOWN") else etat,
                           raison=err or "ordre papier envoyé")
    if etat == "UNKNOWN":
        say("Courtier : pas de réponse claire du courtier. Plus aucun envoi tant que ce n'est pas réconcilié.")
        return 502, {"error": f"Réponse du courtier perdue ({err}). Ordre en état INCONNU : rien ne sera renvoyé."}
    if etat == "REJECTED":
        ticket_cmd("result", "--index", "1", "--status", "failed", "--note", (err or "")[:200])
        return 502, {"error": err}
    ticket_cmd("result", "--index", "1", "--status", "placed", "--broker-id", oid)
    say(f"Courtier : ordre envoyé au compte PAPIER {'IBKR' if pa else 'Alpaca'} ({t['plain']}).")
    return 200, {"ok": True, "id": oid}

def soumettre(pa, ti, k):
    """Un seul appel au courtier, jamais de nouvel essai. → (état, id courtier, erreur)."""
    if pa:
        try:
            return "SUBMITTED", ibkr.envoyer(ti, load_config().get("ibkr_port"), k), None
        except ibkr.PasEnvoye as e:
            return "REJECTED", None, str(e)
        except Exception as e:   # parti ou pas ? on ne sait pas
            return "UNKNOWN", None, str(e)[:200]
    try:
        r = alpaca("POST", "/v2/orders", {**vers_alpaca(ti), "client_order_id": k})
        return envois.ALPACA.get(r.get("status"), "SUBMITTED"), r["id"], None
    except RefusCourtier as e:
        if e.code < 500:
            return "REJECTED", None, str(e)
        err = str(e)
    except (OSError, ValueError, KeyError) as e:   # délai dépassé, connexion coupée, réponse illisible
        err = str(e)[:200]
    return (*retrouver_alpaca(k), err)

def retrouver_alpaca(k):
    """L'ordre est-il arrivé chez Alpaca ? On le cherche par sa clé (client_order_id)."""
    try:
        r = alpaca("GET", "/v2/orders:by_client_order_id?client_order_id=" + urllib.parse.quote(k))
        return envois.ALPACA.get(r.get("status"), "SUBMITTED"), r["id"]
    except RefusCourtier as e:
        if e.code == 404:
            return "ABSENT", None
    except (OSError, ValueError, KeyError):
        pass
    return "UNKNOWN", None

def reconcilier():
    """Envois en SUBMITTING/UNKNOWN : on demande au courtier ce qu'il en est. Renvoie les envois encore bloquants."""
    db = journal_envois()
    for e in envois.bloquants(db):
        if e["marche"] == "PA":
            try:
                oid = ibkr.retrouver(load_config().get("ibkr_port"), e["cle"])
                etat = "SUBMITTED" if oid else "ABSENT"
            except Exception:
                etat, oid = "UNKNOWN", None
        else:
            etat, oid = retrouver_alpaca(e["cle"])
        if etat == "ABSENT":   # le courtier répond et ne l'a pas : il n'est jamais parti
            envois.maj(db, e["cle"], "REJECTED", note="absent chez le courtier après vérification")
        elif etat != "UNKNOWN":
            envois.maj(db, e["cle"], etat, oid)
            if etat != "CANCELLED":
                ticket_cmd("result", "--index", "1", "--status", "placed", "--broker-id", oid)
    return envois.bloquants(db)

ORDRE_OUVERT = {"new", "accepted", "pending_new", "partially_filled", "held", "accepted_for_bidding", "pending_replace"}

def fermer_geres_alpaca(geres, jour):
    """Annule les ordres du bureau (clé bdt-… et leurs jambes) et ne vend que ce que le bureau a acheté.
    Une position ouverte à la main sur le même compte n'est jamais touchée au-delà de cette quantité."""
    n = 0
    for sym, qty_bureau in geres.items():
        q = urllib.parse.quote(sym)
        for o in alpaca("GET", f"/v2/orders?status=all&nested=true&limit=500&after={jour}T00:00:00Z&symbols={q}"):
            if str(o.get("client_order_id", "")).startswith("bdt-"):
                for x in [o, *(o.get("legs") or [])]:
                    if x.get("status") in ORDRE_OUVERT:
                        alpaca("DELETE", f"/v2/orders/{x['id']}")
        try:
            pos = float(alpaca("GET", f"/v2/positions/{q}")["qty"])
        except RefusCourtier as e:
            if e.code == 404:
                continue   # déjà fermée (stop ou objectif touché)
            raise
        a_vendre = min(pos, qty_bureau)
        if a_vendre > 0:
            alpaca("DELETE", f"/v2/positions/{q}?qty={a_vendre:g}")
            n += 1
    return n

def gardien_cloture():
    """10 min avant la clôture, ferme les positions ouvertes par le bureau : rien ne reste ouvert la nuit."""
    fait = None
    threading.Thread(target=gardien_paris, daemon=True).start()
    if alpaca_ok():   # au démarrage : les clés enregistrées sont-elles bien celles d'un compte papier ?
        try:
            compte_papier_alpaca()
        except RuntimeError as e:
            say(f"Courtier : ATTENTION, {e} Aucun envoi ne partira avec ces clés.")
        except OSError:
            pass   # hors ligne : on revérifie de toute façon à chaque envoi
    while True:
        time.sleep(60)
        if not alpaca_ok():
            continue
        try:
            c = alpaca("GET", "/v2/clock")
            now, close = datetime.fromisoformat(c["timestamp"]), datetime.fromisoformat(c["next_close"])
            if c["is_open"] and (close - now).total_seconds() < CLOTURE_AVANT_S and fait != now.date():
                if reconcilier_marche("US"):
                    say("Courtier : un envoi reste inconnu, je ferme quand même ce que le bureau a ouvert.")
                jour = now.date().isoformat()
                if fermer_geres_alpaca(envois.geres(journal_envois("US"), jour), jour):
                    say("Courtier : la clôture approche, je ferme les positions ouvertes par le bureau.")
                fait = now.date()
        except (RuntimeError, OSError, KeyError, ValueError) as e:
            print("Clôture papier :", e)

def reconcilier_marche(m):
    """reconcilier() pour la place m, sans changer la place affichée."""
    return reconcilier() if marche() == m else envois.bloquants(journal_envois(m))

def garde_executions():
    """IBKR n'en rend que quelques jours : on les garde dans trader/paris/trader/executions.json pour le bilan."""
    f = dossier("PA") / "executions.json"
    vues = {e["id"]: e for e in (json.loads(f.read_text(encoding="utf-8")) if f.exists() else [])}
    vues.update({e["id"]: e for e in ibkr.executions(config_racine().get("ibkr_port"))})
    f.write_text(json.dumps(list(vues.values()), indent=1), encoding="utf-8")
    return list(vues.values())

def gardien_paris():
    """Pendant la séance de Paris (si on y a déjà préparé un ticket) : relève les exécutions toutes les 5 min,
    et 10 min avant la clôture ferme tout sur le compte papier IBKR."""
    fait, derniere_erreur, tour = None, None, 0
    while True:
        time.sleep(60)
        tour += 1
        local = heure_paris()
        if not (dossier("PA") / "orders.json").exists() or not paris_ouvert(local):
            continue
        try:
            if (cloture_paris(local) - local).total_seconds() < CLOTURE_AVANT_S and fait != local.date():
                geres = envois.geres(journal_envois("PA"), local.date().isoformat())
                if geres and ibkr.fermer_geres(config_racine().get("ibkr_port"), geres):
                    say("Courtier : la clôture de Paris approche, je ferme les positions ouvertes par le bureau (IBKR).")
                fait = local.date()
            if tour % 5 == 0 or fait == local.date():
                garde_executions()
            derniere_erreur = None
        except Exception as e:   # le fil ne doit jamais mourir en silence
            if str(e) != derniere_erreur:
                print("Paris, compte papier IBKR :", e)
            derniere_erreur = str(e)

# ---------- Bilan du test papier ----------
def trades_fermes(fills):
    """Exécutions Alpaca → trades fermés : un trade se ferme quand la position de l'action revient à zéro (achats FIFO)."""
    pos, trades = {}, []
    for f in sorted(fills, key=lambda f: f["transaction_time"]):
        s = pos.setdefault(f["symbol"], {"lots": [], "pnl": 0.0})
        qty, px = float(f["qty"]), float(f["price"])
        s["pnl"] -= float(f.get("fee") or 0)   # frais IBKR (Alpaca n'en a pas)
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

assert trades_fermes([{**_f("1", "buy", "10", "5"), "fee": "1.25"}, {**_f("2", "sell", "10", "6"), "fee": "1.25"}]) \
    == [{"date": "2", "symbol": "X", "pnl": 7.5}]

def bilan():
    """Bilan papier du courtier + analyse des opportunités. Sans courtier joignable, l'analyse reste affichée."""
    try:
        b = bilan_courtier()
    except (RuntimeError, OSError, KeyError, ValueError) as e:
        b = {**stats([]), "erreur_courtier": str(e)[:200]}
    db = journal_envois()
    with closing(base_historique()) as h:
        b["analyse"] = historique.statistiques(h, b.pop("_trades", []))
    b["analyse"]["erreurs_execution"] = db.execute(
        "SELECT COUNT(*) FROM envois WHERE etat IN ('REJECTED', 'UNKNOWN')").fetchone()[0]
    return b

def bilan_courtier():
    if marche() == "PA":
        t = trades_fermes(garde_executions())
        return {**stats(t), "_trades": t, **ibkr.compte(config_racine().get("ibkr_port"))}
    if not alpaca_ok():
        raise RuntimeError("Ajoute tes clés Alpaca PAPIER dans ⚙ Réglages.")
    fills, token = [], None
    while True:   # 100 exécutions par page
        page = alpaca("GET", "/v2/account/activities/FILL?direction=asc&page_size=100" + (f"&page_token={token}" if token else ""))
        fills += page
        if len(page) < 100:
            break
        token = page[-1]["id"]
    compte = alpaca("GET", "/v2/account")
    t = trades_fermes(fills)
    return {**stats(t), "_trades": t, "equity": round(float(compte["equity"]), 2),
            "ouvertes": len(alpaca("GET", "/v2/positions"))}

def stats(trades):
    pnls = [t["pnl"] for t in trades]
    serie = pire_serie = 0
    for p in pnls:
        serie = serie + 1 if p < 0 else 0
        pire_serie = max(pire_serie, serie)
    n, risque = len(pnls), load_config().get("max_loss_per_trade_usd") or 0
    return {"trades": n, "gagnants": sum(p > 0 for p in pnls), "total": round(sum(pnls), 2),
            "moyen": round(sum(pnls) / n, 2) if n else 0,
            "moyen_R": round(sum(pnls) / n / risque, 2) if n and risque else None,
            "meilleur": max(pnls, default=0), "pire": min(pnls, default=0), "pire_serie": pire_serie,
            "jours": len({t["date"] for t in trades}), "derniers": trades[-10:][::-1]}
