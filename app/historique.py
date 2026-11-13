"""Historique des opportunités (Performance Manager) : chaque action étudiée, de sa détection à sa résolution.

Une base par marché : trader/state/historique.db (US) et trader/paris/trader/state/historique.db (Paris).
Trois mondes jamais mélangés :
- « analyse » : ce que les agents ont décidé (validé, rejeté, données insuffisantes, bloqué, ticket prêt) ;
- « papier » : les trades fermés lus chez le courtier papier, reliés à leur opportunité ;
- les rejeux et l'historique du Voyageur (simulation) restent dans validation.json, pas ici.
"""
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

COLONNES = ("mission", "jour", "heure", "marche", "symbole", "strategie", "etat", "raison", "entree", "stop",
            "objectif", "qty", "risque_prevu", "cle_envoi", "maj")


def ouvre(chemin):
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(chemin, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS opportunites (id INTEGER PRIMARY KEY AUTOINCREMENT, %s)"
               % ", ".join(f"{c} {'REAL' if c in ('entree', 'stop', 'objectif', 'qty', 'risque_prevu') else 'TEXT'}"
                           for c in COLONNES))
    return db


def noter(db, **x):
    x = {k: v for k, v in x.items() if k in COLONNES}
    cur = db.execute("INSERT INTO opportunites (%s) VALUES (%s)" % (", ".join(x), ", ".join("?" * len(x))),
                     tuple(x.values()))
    return cur.lastrowid


def maj(db, ident, **x):
    x = {k: v for k, v in x.items() if k in COLONNES}
    if ident and x:
        db.execute("UPDATE opportunites SET %s WHERE id=?" % ", ".join(f"{k}=?" for k in x), (*x.values(), ident))


def derniere(db, symbole, jour):
    r = db.execute("SELECT * FROM opportunites WHERE symbole=? AND jour=? ORDER BY id DESC LIMIT 1",
                   (symbole, jour)).fetchone()
    return dict(r) if r else None


def _semaine(j):
    y, w, _ = date.fromisoformat(j).isocalendar()
    return f"{y}-S{w:02d}"


def _groupe(trades, cle):
    g = {}
    for t in trades:
        k = cle(t)
        d = g.setdefault(k, {"trades": 0, "gagnants": 0, "total": 0.0, "R": []})
        d["trades"] += 1
        d["gagnants"] += t["pnl"] > 0
        d["total"] = round(d["total"] + t["pnl"], 2)
        if t.get("R") is not None:
            d["R"].append(t["R"])
    for d in g.values():
        rs = d.pop("R")
        d["moyen_R"] = round(sum(rs) / len(rs), 2) if rs else None
    return dict(sorted(g.items()))


def statistiques(db, trades=()):
    """trades : trades papier fermés {date, symbol, pnl} (courtier.trades_fermes). Renvoie l'analyse des refus et
    les performances papier ventilées ; un trade papier sans opportunité connue reste compté, sans R ni heure."""
    ops = [dict(r) for r in db.execute("SELECT * FROM opportunites ORDER BY id")]
    etats = Counter(o["etat"] for o in ops)
    refus = [o for o in ops if o["etat"] in ("REJECTED", "INSUFFICIENT_DATA", "BLOCKED")]
    motifs = Counter((o["raison"] or "").split(" (")[0].split(" : ")[0][:60] for o in refus)
    papier = []
    for t in trades:
        o = derniere(db, t["symbol"], t["date"]) or {}
        r = round(t["pnl"] / o["risque_prevu"], 2) if o.get("risque_prevu") else None
        papier.append({**t, "R": r, "strategie": o.get("strategie") or "?", "heure": (o.get("heure") or "?")[:2] + "h"
                       if o.get("heure") else "?"})
    return {
        "opportunites": len(ops),
        "etats": dict(etats),
        "taux_refus": round(len(refus) / len(ops), 2) if ops else None,
        "motifs_refus": dict(motifs.most_common(6)),
        "donnees_insuffisantes": etats.get("INSUFFICIENT_DATA", 0),
        "papier": {
            "par_jour": _groupe(papier, lambda t: t["date"]),
            "par_semaine": _groupe(papier, lambda t: _semaine(t["date"])),
            "par_mois": _groupe(papier, lambda t: t["date"][:7]),
            "par_strategie": _groupe(papier, lambda t: t["strategie"]),
            "par_heure": _groupe(papier, lambda t: t["heure"]),
        },
    }
