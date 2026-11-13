"""Journal des envois au courtier (SQLite, une base par marché).

L'intention est écrite AVANT l'appel réseau (état SUBMITTING) ; la clé d'idempotence est unique,
donc le même ticket ne peut pas partir deux fois. Une réponse perdue laisse l'envoi en UNKNOWN :
plus rien ne part tant qu'il n'est pas réconcilié avec le courtier.
Les états CREATED / PENDING_APPROVAL vivent dans orders.json (ticket.py : READY = en attente de ton oui).
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ETATS = {"SUBMITTING", "SUBMITTED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "UNKNOWN", "DRY_RUN"}
BLOQUANTS = ("SUBMITTING", "UNKNOWN")
CHEZ_LE_COURTIER = ("SUBMITTING", "SUBMITTED", "PARTIALLY_FILLED", "FILLED", "UNKNOWN")

# Statuts Alpaca → nos états (https://docs.alpaca.markets/docs/orders-at-alpaca)
ALPACA = {"new": "SUBMITTED", "accepted": "SUBMITTED", "pending_new": "SUBMITTED", "accepted_for_bidding": "SUBMITTED",
          "held": "SUBMITTED", "pending_replace": "SUBMITTED", "replaced": "SUBMITTED", "pending_cancel": "SUBMITTED",
          "partially_filled": "PARTIALLY_FILLED", "filled": "FILLED", "done_for_day": "SUBMITTED",
          "canceled": "CANCELLED", "expired": "CANCELLED", "stopped": "SUBMITTED", "suspended": "SUBMITTED",
          "calculated": "SUBMITTED", "rejected": "REJECTED"}


class DejaEnvoye(Exception):
    pass


def maintenant():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ouvre(chemin):
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(chemin, isolation_level=None)   # autocommit : chaque écriture est sur disque tout de suite
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS envois (cle TEXT PRIMARY KEY, jour TEXT, marche TEXT, symbole TEXT,
                  side TEXT, qty REAL, fingerprint TEXT, etat TEXT, broker_id TEXT, note TEXT, cree TEXT, maj TEXT)""")
    return db


def cle(fingerprint, jour):
    return f"bdt-{jour}-{fingerprint[:24]}"


def intention(db, k, jour, marche, ti, fingerprint):
    try:
        db.execute("INSERT INTO envois VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (k, jour, marche, ti["symbol"], ti.get("side"), float(ti["qty"]), fingerprint,
                    "SUBMITTING", None, None, maintenant(), maintenant()))
    except sqlite3.IntegrityError:
        raise DejaEnvoye(f"ce ticket a déjà été envoyé (clé {k})") from None


def maj(db, k, etat, broker_id=None, note=None):
    assert etat in ETATS, etat
    db.execute("UPDATE envois SET etat=?, broker_id=COALESCE(?, broker_id), note=COALESCE(?, note), maj=? WHERE cle=?",
               (etat, broker_id, note, maintenant(), k))


def bloquants(db):
    return [dict(r) for r in db.execute(f"SELECT * FROM envois WHERE etat IN {BLOQUANTS}")]


def geres(db, jour):
    """{symbole: quantité achetée par le bureau ce jour-là} : seules ces positions peuvent être fermées par lui."""
    q = {}
    for r in db.execute(f"SELECT symbole, qty FROM envois WHERE jour=? AND side='buy' AND etat IN {CHEZ_LE_COURTIER}",
                        (jour,)):
        q[r["symbole"]] = q.get(r["symbole"], 0) + r["qty"]
    return q
