"""Validation historique d'un setup (remplace favorable()) : VALIDATED, REJECTED ou INSUFFICIENT_DATA.

Seules les séances passées (history de timemachine.json) comptent comme preuve. Le Monte-Carlo est une
simulation : il peut faire rejeter un trade, jamais le valider à lui seul. INSUFFICIENT_DATA n'autorise rien.

Seuils (clé "validation" de config.json, sinon DEFAUTS). Ce sont des conventions prudentes, PAS des
valeurs optimisées :
- min_trades 20 : en dessous, l'erreur type d'un taux de réussite dépasse ±11 points (√(0,25/20)).
- min_expectancy_R 0 : espérance après frais et glissement strictement positive, sur tout l'échantillon
  ET sur le dernier tiers (hors échantillon chronologique) : un setup qui ne tient plus récemment est rejeté.
- slippage_pct 0,05 : glissement estimé par côté, en % du prix (actions liquides) ; à mesurer sur les vrais
  envois papier.
- frais_par_ordre : US 0 (Alpaca papier sans commission), Paris 1,25 (minimum IBKR annoncé, à vérifier).
  Ramené en R avec max_loss_per_trade_usd : la position est dimensionnée pour risquer au plus ce montant,
  donc le vrai coût en R est au moins celui-là.
- max_drawdown_R : null = affiché seulement ; un nombre = rejet au-delà.
"""
DEFAUTS = {"min_trades": 20, "min_expectancy_R": 0.0, "slippage_pct": 0.05, "frais_par_ordre": None,
           "max_drawdown_R": None}
FRAIS_DEFAUT = {"US": 0.0, "PA": 1.25}


def seuils(cfg, marche):
    s = {**DEFAUTS, **(cfg.get("validation") or {})}
    if s["frais_par_ordre"] is None:
        s["frais_par_ordre"] = FRAIS_DEFAUT.get(marche, 0.0)
    return s


def stats(rs):
    """Statistiques d'une suite de résultats en R (ordre chronologique)."""
    n = len(rs)
    gains, pertes = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    cumul = pic = dd = 0.0
    serie = pire = 0
    for r in rs:
        cumul += r
        pic = max(pic, cumul)
        dd = max(dd, pic - cumul)
        serie = serie + 1 if r <= 0 else 0
        pire = max(pire, serie)
    return {"trades": n, "gagnants": len(gains), "perdants": len(pertes),
            "win_rate": round(len(gains) / n, 3) if n else None,
            "expectancy_R": round(sum(rs) / n, 3) if n else None,
            "profit_factor": round(sum(gains) / -sum(pertes), 2) if pertes and sum(pertes) < 0 else None,
            "max_drawdown_R": round(dd, 2), "pertes_consecutives_max": pire}


def valider(tm, cfg, marche="US"):
    s = seuils(cfg, marche)
    h, mc = tm.get("history") or {}, tm.get("mc") or {}
    risque = cfg.get("max_loss_per_trade_usd") or 0
    trades = [t for t in h.get("trades") or [] if t.get("R") is not None and t.get("entry") and t.get("stop")]
    if not risque:
        return {"etat": "INSUFFICIENT_DATA", "raisons": ["perte max par trade absente de la config"], "seuils": s}
    if h.get("trades") and len(trades) != len(h["trades"]):
        return {"etat": "INSUFFICIENT_DATA", "raisons": ["trades historiques incomplets (R, entrée ou stop manquant)"],
                "seuils": s}
    frais_R = 2 * s["frais_par_ordre"] / risque
    nets = []
    for t in sorted(trades, key=lambda t: t.get("date", "")):
        par_action = abs(t["entry"] - t["stop"])
        if par_action <= 0:
            return {"etat": "INSUFFICIENT_DATA", "raisons": [f"trade du {t.get('date')} sans risque par action"],
                    "seuils": s}
        nets.append(t["R"] - 2 * t["entry"] * s["slippage_pct"] / 100 / par_action - frais_R)
    tout, oos = stats(nets), stats(nets[len(nets) * 2 // 3:])
    # Walk-forward : la règle n'a aucun paramètre ajusté sur ces données, donc pas de ré-optimisation ;
    # on montre la stabilité tiers par tiers, dans l'ordre du temps (seul le dernier tiers décide, voir plus bas).
    tiers = [stats(nets[i * len(nets) // 3:(i + 1) * len(nets) // 3])["expectancy_R"] for i in range(3)]
    res = {"seuils": s, "historique": tout, "hors_echantillon": oos, "par_tiers_R": tiers, "frais_R": round(frais_R, 3),
           "gap_pire_R": min((t["R"] for t in trades), default=None),
           "periode": [trades[0].get("date"), trades[-1].get("date")] if trades else None,
           "sessions": h.get("sessions"),
           "simulation": {k: mc.get(k) for k in ("avg_R", "p_target", "p_stop")}}
    raisons = []
    if (mc.get("avg_R") is None) or mc.get("p_target") is None or mc.get("p_stop") is None:
        return {**res, "etat": "INSUFFICIENT_DATA", "raisons": ["simulation absente"]}
    if tout["trades"] < s["min_trades"]:
        return {**res, "etat": "INSUFFICIENT_DATA",
                "raisons": [f"{tout['trades']} trades historiques, il en faut au moins {s['min_trades']}"]}
    if mc["avg_R"] <= 0 or mc["p_target"] <= mc["p_stop"]:
        raisons.append("la simulation penche vers le stop")
    if tout["expectancy_R"] <= s["min_expectancy_R"]:
        raisons.append(f"espérance historique {tout['expectancy_R']:+.2f}R après frais")
    if oos["expectancy_R"] <= s["min_expectancy_R"]:
        raisons.append(f"espérance du dernier tiers {oos['expectancy_R']:+.2f}R après frais (hors échantillon)")
    if s["max_drawdown_R"] is not None and tout["max_drawdown_R"] > s["max_drawdown_R"]:
        raisons.append(f"drawdown {tout['max_drawdown_R']}R > {s['max_drawdown_R']}R")
    return {**res, "etat": "REJECTED" if raisons else "VALIDATED", "raisons": raisons}
