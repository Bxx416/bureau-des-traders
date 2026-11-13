"""Tests de sécurité et de régression (stdlib unittest ; aussi lancés par pytest s'il est installé).

    app\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v

Aucun appel réseau : le courtier est simulé.
"""
import json, os, subprocess, sys, tempfile, time, unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "skills")]
import envois, historique, validation   # noqa: E402
import contexte, courtier, orchestrateur, server   # noqa: E402,F401

CFG = {"max_loss_per_trade_usd": 5.0}
MC_OK = {"avg_R": 0.2, "p_target": 0.55, "p_stop": 0.40}


def trades(rs, entry=100.0, stop=99.0):
    return [{"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "R": r, "entry": entry, "stop": stop}
            for i, r in enumerate(rs)]


def tm(rs, mc=MC_OK):
    return {"mc": mc, "history": {"sessions": 59, "triggered": len(rs), "trades": trades(rs)}}


class Validation(unittest.TestCase):
    def test_regression_petit_echantillon_ne_passe_plus(self):
        # ancien favorable() : triggered < 5 → True
        v = validation.valider(tm([1.0, 1.0, 1.0]), CFG)
        self.assertEqual(v["etat"], "INSUFFICIENT_DATA")

    def test_aucun_historique(self):
        self.assertEqual(validation.valider({"mc": MC_OK, "history": {}}, CFG)["etat"], "INSUFFICIENT_DATA")

    def test_valide(self):
        v = validation.valider(tm([1.0, -1.0, 1.0] * 8), CFG)
        self.assertEqual(v["etat"], "VALIDATED", v["raisons"])
        self.assertEqual(v["historique"]["trades"], 24)

    def test_frais_peuvent_rejeter(self):
        # +0,1R brut par trade, mais 1,25 € x 2 / 5 € = 0,5R de frais à Paris
        v = validation.valider(tm([0.1] * 24), CFG, "PA")
        self.assertEqual(v["etat"], "REJECTED")

    def test_hors_echantillon_negatif(self):
        v = validation.valider(tm([1.0] * 16 + [-1.0] * 8), CFG)
        self.assertEqual(v["etat"], "REJECTED")
        self.assertTrue(any("dernier tiers" in r for r in v["raisons"]))

    def test_simulation_seule_ne_valide_pas_et_peut_rejeter(self):
        v = validation.valider(tm([1.0, -1.0, 1.0] * 8, {"avg_R": -0.1, "p_target": 0.3, "p_stop": 0.6}), CFG)
        self.assertEqual(v["etat"], "REJECTED")

    def test_sans_perte_max_config(self):
        self.assertEqual(validation.valider(tm([1.0] * 30), {})["etat"], "INSUFFICIENT_DATA")

    def test_stats(self):
        s = validation.stats([1, -1, -1, 2, -1])
        self.assertEqual((s["gagnants"], s["perdants"], s["pertes_consecutives_max"], s["max_drawdown_R"]), (2, 3, 2, 2))
        self.assertEqual(s["profit_factor"], 1.0)


import importlib.util   # noqa: E402
_spec = importlib.util.spec_from_file_location("timemachine", ROOT / "skills/trader-timemachine/timemachine.py")
tmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tmod)


class Voyageur(unittest.TestCase):
    def test_gap_sous_le_stop_au_vrai_prix(self):
        self.assertEqual(tmod.sortie(95, 96, 94, 98, 104, True), ("stop", 95))      # ouverture déjà sous le stop
        self.assertEqual(tmod.sortie(100, 105, 97, 98, 104, True), ("stop", 98))    # stop et objectif : le stop
        self.assertEqual(tmod.sortie(106, 107, 105, 98, 104, True), ("target", 104))
        self.assertIsNone(tmod.sortie(100, 103, 99, 98, 104, True))
        self.assertEqual(tmod.sortie(105, 106, 104, 102, 96, False), ("stop", 105))  # vente à découvert

    def session(self, opens):
        bars = []
        for i in range(tmod.SESSION_BARS):
            o = opens.get(i, 100.0)
            bars.append({"o": o, "h": o + 0.5, "l": o - 0.5, "c": o})
        return bars

    def test_historique_entre_a_l_ouverture_suivante(self):
        D = self.session({i: 100.0 for i in range(6)})
        D[3] = {"o": 100, "h": 102, "l": 100, "c": 101.0}   # cassure : clôture au-dessus du range (100,5)
        D[4] = {"o": 101.5, "h": 101.6, "l": 99.0, "c": 99.2}   # ouverture 101,5 puis touche le stop
        rule = {"or_minutes": 15, "stop_rule": "or_low", "target_r": 1.0}
        h = tmod.history_replay([("2026-11-02", D)], rule, 20)
        t = h["trades"][0]
        self.assertEqual((t["entry"], t["fill"], t["outcome"]), (101.0, 101.5, "stop"))
        self.assertLess(t["R"], -1)   # acheté plus cher que prévu : la perte dépasse 1R

    def test_bougies_incoherentes_ecartees(self):
        ts = 1794580200   # 2026-11-13 9:30 New York, sur la grille de 5 min
        res = {"meta": {}, "timestamp": [ts, ts + 300, ts + 300, ts + 600],
               "indicators": {"quote": [{"open": [10, 10, 10, -1], "high": [11, 11, 11, 11], "low": [9, 9, 9, 9],
                                         "close": [10, 10, 10, 10], "volume": [1, 1, 1, 1]}]}}
        _, bars, dropped = tmod.parse_bars(res, tmod.datetime.datetime(2026, 11, 14))
        self.assertEqual((len(bars), dropped["incoherent"], dropped["duplicate"]), (2, 1, 1))


class Performance(unittest.TestCase):
    def test_statistiques_separent_analyse_et_papier(self):
        d = tempfile.TemporaryDirectory()
        db = historique.ouvre(Path(d.name) / "h.db")
        historique.noter(db, jour="2026-11-13", heure="10:05", symbole="AAPL", strategie="orb", etat="ENVOYE",
                         raison="ordre papier envoyé", risque_prevu=5.0)
        historique.noter(db, jour="2026-11-13", symbole="MSFT", etat="REJECTED", raison="signal vieux de 40 min, trop tard")
        historique.noter(db, jour="2026-11-13", symbole="NVDA", etat="INSUFFICIENT_DATA", raison="données insuffisantes (3 trades)")
        st = historique.statistiques(db, [{"date": "2026-11-13", "symbol": "AAPL", "pnl": 5.0},
                                          {"date": "2026-11-14", "symbol": "TSLA", "pnl": -2.0}])
        self.assertEqual((st["opportunites"], st["taux_refus"], st["donnees_insuffisantes"]), (3, 0.67, 1))
        self.assertEqual(st["papier"]["par_heure"]["10h"], {"trades": 1, "gagnants": 1, "total": 5.0, "moyen_R": 1.0})
        self.assertEqual(st["papier"]["par_heure"]["?"]["moyen_R"], None)   # trade sans opportunité : pas de R inventé
        self.assertEqual(st["papier"]["par_semaine"]["2026-S46"]["trades"], 2)
        db.close()
        d.cleanup()


class Journal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = envois.ouvre(Path(self.dir.name) / "e.db")

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_double_envoi_refuse(self):
        ti = {"symbol": "AAPL", "side": "buy", "qty": "3"}
        envois.intention(self.db, "k", "2026-11-13", "US", ti, "fp")
        with self.assertRaises(envois.DejaEnvoye):
            envois.intention(self.db, "k", "2026-11-13", "US", ti, "fp")

    def test_bloquants_et_geres(self):
        envois.intention(self.db, "a", "2026-11-13", "US", {"symbol": "AAPL", "side": "buy", "qty": "3"}, "fa")
        envois.intention(self.db, "b", "2026-11-13", "US", {"symbol": "MSFT", "side": "buy", "qty": "2"}, "fb")
        envois.maj(self.db, "a", "FILLED", "id1")
        envois.maj(self.db, "b", "REJECTED")
        self.assertEqual(envois.bloquants(self.db), [])
        self.assertEqual(envois.geres(self.db, "2026-11-13"), {"AAPL": 3.0})
        envois.maj(self.db, "a", "UNKNOWN")
        self.assertEqual(len(envois.bloquants(self.db)), 1)


class Papier(unittest.TestCase):
    def test_url_live_refusee(self):
        for url in ("https://api.alpaca.markets/v2/orders", "http://paper-api.alpaca.markets/v2",
                    "https://paper-api.alpaca.markets.evil.com/v2"):
            with self.assertRaises(RuntimeError):
                courtier.url_papier(url)
        courtier.url_papier("https://paper-api.alpaca.markets/v2/orders")

    def test_compte_live_refuse(self):
        with mock.patch.object(courtier, "alpaca", return_value={"account_number": "123456"}):
            with self.assertRaises(RuntimeError):
                courtier.compte_papier_alpaca()
        with mock.patch.object(courtier, "alpaca", return_value={"account_number": "PA3XYZ"}):
            courtier.compte_papier_alpaca()


class FauxCourtier:
    """Alpaca simulé : enregistre chaque appel."""
    def __init__(self, post=None, retrouve=None):
        self.appels, self.post, self.retrouve = [], post, retrouve

    def __call__(self, method, path, body=None):
        self.appels.append((method, path))
        if path == "/v2/clock":
            return {"timestamp": "2026-11-13T10:00:00-05:00", "is_open": True, "next_close": "2026-11-13T16:00:00-05:00"}
        if path == "/v2/account":
            return {"account_number": "PA1TEST"}
        if method == "POST":
            if isinstance(self.post, Exception):
                raise self.post
            return self.post
        if "by_client_order_id" in path:
            if isinstance(self.retrouve, Exception):
                raise self.retrouve
            return self.retrouve
        raise AssertionError(path)

    def posts(self):
        return sum(1 for m, _ in self.appels if m == "POST")


TICKET = {"ready": True, "status": "READY", "plain": "Buy 3 AAPL", "max_loss": 3.0, "fingerprint": "abc123",
          "tool_input": {"symbol": "AAPL", "side": "buy", "qty": "3", "type": "market", "time_in_force": "day"}}


class Envoi(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        (d / "orders.json").write_text("{}")
        self.db = envois.ouvre(d / "e.db")
        self.ticket_appels = []

        def ticket_cmd(*args, agent="broker"):
            self.ticket_appels.append(args)
            return (0, json.dumps(TICKET)) if args[0] == "show" else (0, "")
        self.patches = [mock.patch.object(courtier, n, v) for n, v in {
            "marche": lambda: "US", "alpaca_ok": lambda: True, "arret_urgence": lambda: False, "dry_run": lambda: False,
            "journal_envois": lambda m=None: self.db, "dossier": lambda m=None: d, "ticket_cmd": ticket_cmd,
            "gardien_controle": lambda: None, "say": lambda t: None,
            "base_historique": lambda m=None: historique.ouvre(d / "h.db")}.items()]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.db.close()
        self.dir.cleanup()

    def envoyer(self, faux, fp="abc123"):
        with mock.patch.object(courtier, "alpaca", faux):
            return courtier.envoyer_ticket(fp)

    def test_sans_confirmation_rien_ne_part(self):
        c = FauxCourtier(post={"id": "1", "status": "accepted"})
        code, rep = self.envoyer(c, fp="")
        self.assertEqual((code, c.posts()), (200, 0))
        self.assertIn("fingerprint", rep)

    def test_envoi_normal_puis_doublon(self):
        c = FauxCourtier(post={"id": "o1", "status": "accepted"})
        self.assertEqual(self.envoyer(c)[0], 200)
        self.assertEqual(self.envoyer(c)[0], 409)   # même ticket, même jour : clé déjà utilisée
        self.assertEqual(c.posts(), 1)

    def test_reponse_perdue_retrouvee(self):
        c = FauxCourtier(post=TimeoutError("timed out"), retrouve={"id": "o9", "status": "new"})
        code, rep = self.envoyer(c)
        self.assertEqual((code, rep.get("id"), c.posts()), (200, "o9", 1))

    def test_reponse_perdue_inconnue_bloque_tout(self):
        c = FauxCourtier(post=TimeoutError("timed out"), retrouve=OSError("réseau coupé"))
        self.assertEqual(self.envoyer(c)[0], 502)
        self.assertEqual(envois.bloquants(self.db)[0]["etat"], "UNKNOWN")
        self.assertEqual(self.envoyer(c)[0], 409)   # aucun nouvel envoi tant que ce n'est pas réconcilié
        self.assertEqual(c.posts(), 1)

    def test_reconciliation(self):
        c = FauxCourtier(post=TimeoutError("x"), retrouve=OSError("x"))
        self.envoyer(c)
        c.retrouve = courtier.RefusCourtier(404, "not found")
        with mock.patch.object(courtier, "alpaca", c):
            self.assertEqual(courtier.reconcilier(), [])
        self.assertEqual(self.db.execute("SELECT etat FROM envois").fetchone()[0], "REJECTED")

    def test_refus_du_courtier(self):
        c = FauxCourtier(post=courtier.RefusCourtier(422, "insufficient buying power"))
        self.assertEqual(self.envoyer(c)[0], 502)
        self.assertEqual(envois.bloquants(self.db), [])

    def test_gardien_ne_peut_pas_etre_contourne(self):
        c = FauxCourtier(post={"id": "1", "status": "accepted"})
        with mock.patch.object(courtier, "gardien_controle", lambda: "perte journalière atteinte"):
            code, rep = self.envoyer(c)
        self.assertEqual((code, c.posts()), (409, 0))
        self.assertNotIn(("approve", "--index", "1", "--reply", "yes"), self.ticket_appels)

    def test_arret_urgence(self):
        c = FauxCourtier(post={"id": "1", "status": "accepted"})
        with mock.patch.object(courtier, "arret_urgence", lambda: True):
            self.assertEqual(self.envoyer(c)[0], 423)
        self.assertEqual(c.appels, [])

    def test_dry_run(self):
        c = FauxCourtier(post={"id": "1", "status": "accepted"})
        with mock.patch.object(courtier, "dry_run", lambda: True):
            self.assertTrue(self.envoyer(c)[1].get("dry_run"))
        self.assertEqual(c.posts(), 0)

    def test_ticket_compte_reel_refuse(self):
        c = FauxCourtier(post={"id": "1", "status": "accepted"})
        with mock.patch.dict(TICKET, paper=False):
            self.assertEqual((self.envoyer(c)[0], c.posts()), (409, 0))

    def test_ticket_perime(self):
        old = time.time() - 3600
        os.utime(Path(self.dir.name) / "orders.json", (old, old))
        c = FauxCourtier(post={"id": "1", "status": "accepted"})
        self.assertEqual((self.envoyer(c)[0], c.posts()), (409, 0))


class Cloture(unittest.TestCase):
    def test_positions_non_gerees_jamais_fermees(self):
        appels = []

        def alpaca(method, path, body=None):
            appels.append((method, path))
            if path.startswith("/v2/orders?"):
                return [{"id": "p1", "client_order_id": "bdt-x", "status": "filled",
                         "legs": [{"id": "l1", "status": "held"}, {"id": "l2", "status": "new"}]},
                        {"id": "m1", "client_order_id": "manuel", "status": "new", "legs": []}]
            if path == "/v2/positions/AAPL":
                return {"qty": "8"}   # 5 achetées par le bureau + 3 à la main
            return {}
        with mock.patch.object(courtier, "alpaca", alpaca):
            self.assertEqual(courtier.fermer_geres_alpaca({"AAPL": 5.0}, "2026-11-13"), 1)
        deletes = [p for m, p in appels if m == "DELETE"]
        self.assertEqual(deletes, ["/v2/orders/l1", "/v2/orders/l2", "/v2/positions/AAPL?qty=5"])
        self.assertFalse(any("MSFT" in p or "m1" in p for _, p in appels))


class Mission(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = Path(self.dir.name)
        self.p = [mock.patch.object(orchestrateur, n, v) for n, v in {
            "dossier": lambda m=None: self.d, "marche": lambda: "US", "load_config": lambda: CFG,
            "arret_urgence": lambda: False, "say": lambda t: None, "emit": lambda e: None,
            "base_historique": lambda m=None: historique.ouvre(self.d / "h.db")}.items()]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.dir.cleanup()

    def journal(self):
        return json.loads(next((self.d / "state" / "missions").glob("*.json")).read_text(encoding="utf-8"))

    def test_arret_sur_echec_critique_et_journal(self):
        faits = []
        etapes = {"t": [("alerts", ["clock"], ""), ("risk", [], ""), ("broker", [], "")]}

        def run_agent(agent, args):
            faits.append(agent)
            return (1 if agent == "risk" else 0), ["boom"]
        with mock.patch.object(orchestrateur, "missions", lambda s: etapes),                 mock.patch.object(orchestrateur, "run_agent", run_agent):
            orchestrateur.run_mission("t", "")
        self.assertEqual(faits, ["alerts", "risk"])   # le Courtier n'est jamais appelé
        j = self.journal()
        self.assertEqual(j["etat"], "ARRETEE")
        self.assertEqual([e["statut"] for e in j["etapes"]], ["SUCCESS", "BLOCKED", "BLOCKED"])

    def test_agent_d_information_ne_bloque_pas(self):
        faits = []
        etapes = {"t": [("news", [], ""), ("analyst", [], ""), ("risk", [], "")]}

        def run_agent(agent, args):
            faits.append(agent)
            return (0 if agent == "risk" else 1), ["facts: SAP: no quarterly revenue"]
        with mock.patch.object(orchestrateur, "missions", lambda s: etapes), \
                mock.patch.object(orchestrateur, "run_agent", run_agent), \
                mock.patch.object(orchestrateur, "sec_ready", lambda: True):
            orchestrateur.run_mission("t", "")
        self.assertEqual(faits, ["news", "analyst", "risk"])
        j = self.journal()
        self.assertEqual((j["etat"], [e["statut"] for e in j["etapes"]][:3]), ("TERMINEE", ["WARNING", "WARNING", "SUCCESS"]))

    def opportunites(self):
        with closing(historique.ouvre(self.d / "h.db")) as db:
            return [dict(r) for r in db.execute("SELECT * FROM opportunites ORDER BY id")]

    def test_historique_suit_l_opportunite_jusqu_au_blocage(self):
        self.entry()
        (self.d / "timemachine.json").write_text(json.dumps(tm([1.0, -1.0, 1.0] * 8)))
        (self.d / "plan.json").write_text(json.dumps({"entry": 101, "stop": 100, "target": 102}))
        etapes = {"t": [("selection", ["AAPL"], ""), ("budget", [], ""), ("risk", [], ""), ("broker", [], "")]}

        def run_agent(agent, args):
            return (1 if agent == "risk" else 0), ["BLOCK loss: over your max"]
        with mock.patch.object(orchestrateur, "missions", lambda s: etapes),                 mock.patch.object(orchestrateur, "run_agent", run_agent):
            orchestrateur.run_mission("t", "")
        o = self.opportunites()
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["symbole"], o[0]["etat"], o[0]["heure"] is None, o[0]["stop"]), ("AAPL", "BLOCKED", True, 100))
        self.assertIn("Gardien", o[0]["raison"])
        self.assertTrue(o[0]["mission"].endswith("-t"))

    def test_refus_enregistre_avec_sa_raison(self):
        self.entry(status="waiting")
        self.selection()
        o = self.opportunites()
        self.assertEqual((o[0]["etat"], o[0]["raison"]), ("REJECTED", "pas de signal (waiting), au suivant."))

    def entry(self, **x):
        e = {"symbol": "AAPL", "status": "triggered", "date": "2026-11-13", "time": "10:00 AM",
             "checked_at": "2026-11-13T15:10:00Z", **x}
        (self.d / "entry.json").write_text(json.dumps(e))

    def selection(self):
        etapes = []

        def step(agent, args, order):
            etapes.append(agent)
            return 0, []
        with mock.patch.object(orchestrateur, "step", step):
            return orchestrateur.select_trade(["AAPL"]), etapes

    def test_age_du_signal(self):
        e = {"date": "2026-11-13", "time": "10:00 AM", "checked_at": "2026-11-13T15:10:00Z"}
        self.assertEqual(orchestrateur.age_signal(e, "US"), 10)            # 10h00 New York = 15h00 UTC en hiver
        self.assertEqual(orchestrateur.age_signal(e, "PA"), 6 * 60 + 10)   # 10h00 Paris = 9h00 UTC
        self.assertIsNone(orchestrateur.age_signal({"date": "2026-11-13"}, "US"))

    def test_signal_perime_refuse(self):
        self.entry(checked_at="2026-11-13T16:00:00Z")   # 60 min
        self.assertEqual(self.selection(), (False, ["entry"]))

    def test_signal_sans_heure_refuse(self):
        self.entry(time=None)
        self.assertEqual(self.selection(), (False, ["entry"]))

    def test_selection_refuse_donnees_insuffisantes(self):
        self.entry()
        (self.d / "timemachine.json").write_text(json.dumps(tm([1.0, 1.0])))
        self.assertEqual(self.selection(), (False, ["entry", "exit", "timemachine"]))
        v = json.loads((self.d / "state" / "validation.json").read_text(encoding="utf-8"))
        self.assertEqual(v["etat"], "INSUFFICIENT_DATA")

    def test_selection_valide(self):
        self.entry()
        (self.d / "timemachine.json").write_text(json.dumps(tm([1.0, -1.0, 1.0] * 8)))
        self.assertTrue(self.selection()[0])

    def test_candidats_du_scan_les_plus_recents_d_abord(self):
        (self.d / "watchlist.json").write_text(json.dumps({"mode": "orb", "hits": [
            {"symbol": "A", "bar_index": 3}, {"symbol": "B", "bar_index": 7}, {"symbol": "C"}]}))
        self.assertEqual(orchestrateur.recent_triggers(), ["B", "A"])
        (self.d / "watchlist.json").write_text(json.dumps({"mode": "daily", "hits": [{"symbol": "A", "bar_index": 3}]}))
        self.assertEqual(orchestrateur.recent_triggers(), [])


class Horaires(unittest.TestCase):
    def test_paris_independant_de_new_york(self):
        self.assertTrue(contexte.paris_ouvert(datetime(2026, 11, 26, 10, 0)))    # Thanksgiving : Paris ouvert
        self.assertFalse(contexte.paris_ouvert(datetime(2026, 12, 25, 10, 0)))   # Noël
        self.assertTrue(contexte.paris_ouvert(datetime(2026, 11, 13, 17, 29)))
        self.assertFalse(contexte.paris_ouvert(datetime(2026, 11, 13, 17, 30)))

    def test_changement_heure_paris(self):
        import marche
        self.assertEqual(marche.paris_offset(datetime(2026, 7, 1, 12)), 2)
        self.assertEqual(marche.paris_offset(datetime(2026, 12, 1, 12)), 1)


class DonneesPerimees(unittest.TestCase):
    def gardien(self, as_of):
        d = Path(tempfile.mkdtemp()) / "trader"
        (d / "state").mkdir(parents=True)
        (d / "config.json").write_text(json.dumps({"budget": 1000, "max_loss_per_trade_usd": 5}))
        (d / "orders.json").write_text(json.dumps({"orders": [{
            "symbol": "AAPL", "side": "buy", "qty": "1", "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "110", "stop_loss_stop_price": "95"}]}))
        (d / "prices.json").write_text(json.dumps({"as_of": as_of, "prices": {"AAPL": 100}}))
        p = subprocess.run([sys.executable, str(ROOT / "skills/trader-risk/check.py"), "--json", "--no-write",
                            "--now", "2026-11-13 10:15"], cwd=d.parent, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONUTF8="1"))
        return p.returncode, json.loads(p.stdout)["results"][0]

    def test_prix_perime_bloque(self):
        code, r = self.gardien("2026-11-13T08:00:00-05:00")
        self.assertEqual((code, r["verdict"]), (1, "BLOCK"))
        self.assertTrue(any("stale" in x for x in r["reasons"]), r["reasons"])

    def test_prix_frais_passe(self):
        self.assertEqual(self.gardien("2026-11-13T10:14:00-05:00")[1]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
