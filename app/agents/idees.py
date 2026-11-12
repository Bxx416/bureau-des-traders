"""Idées du web : les actions qui bougent ou dont on parle aujourd'hui.

  idees.py yahoo   La Fouineuse : tendances, plus fortes hausses et volumes anormaux (Yahoo Finance)
  idees.py foule   Le Crieur : les plus citées sur StockTwits et Reddit (via ApeWisdom)

Écrit trader/idees.json. Ce ne sont que des idées : le Guetteur et le Voyageur les vérifient ensuite.
Sources gratuites, non officielles, sans compte. Rien n'est acheté.
"""
import json, re, sys, time, urllib.request
from pathlib import Path

OUT = Path("trader/idees.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
TICKER = re.compile(r"^[A-Z]{1,5}$")
MIN_PRICE, MIN_VOLUME, MAX_PER_LIST = 5.0, 1_000_000, 15


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def screener(name):
    d = get(f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={name}&count=50")
    return d["finance"]["result"][0]["quotes"]


def liquide(q):
    return (q.get("quoteType") == "EQUITY" and TICKER.match(q.get("symbol", ""))
            and (q.get("regularMarketPrice") or 0) >= MIN_PRICE and (q.get("regularMarketVolume") or 0) >= MIN_VOLUME)


def yahoo():
    idees = []
    gagnants = [q for q in screener("day_gainers") if liquide(q)][:MAX_PER_LIST]
    print(f"Plus fortes hausses (prix >= {MIN_PRICE:g} $, volume >= {MIN_VOLUME:,}) :")
    for q in gagnants:
        print(f"  {q['symbol']:<6} {q['regularMarketPrice']:>9.2f} $  {q['regularMarketChangePercent']:+6.1f} %")
        idees.append({"symbol": q["symbol"], "pourquoi": f"hausse {q['regularMarketChangePercent']:+.1f} %"})
    vus, anormaux = set(), []
    for q in screener("most_actives") + gagnants:
        moy = q.get("averageDailyVolume3Month") or 0
        if liquide(q) and moy and q["symbol"] not in vus:
            vus.add(q["symbol"])
            x = q["regularMarketVolume"] / moy
            if x >= 2:
                anormaux.append((x, q))
    anormaux.sort(key=lambda p: -p[0])
    print("Volumes anormaux (au moins 2 fois la moyenne de 3 mois) :")
    for x, q in anormaux[:MAX_PER_LIST]:
        print(f"  {q['symbol']:<6} {q['regularMarketPrice']:>9.2f} $  volume x{x:.1f}")
        idees.append({"symbol": q["symbol"], "pourquoi": f"volume x{x:.1f}"})
    tend = [q["symbol"] for q in get("https://query1.finance.yahoo.com/v1/finance/trending/US?count=25")["finance"]["result"][0]["quotes"]]
    tend = [s for s in tend if TICKER.match(s)][:MAX_PER_LIST]
    print("Tendances Yahoo : " + ", ".join(tend))
    idees += [{"symbol": s, "pourquoi": "tendance Yahoo"} for s in tend]
    return idees


def foule():
    idees = []
    st = [s["symbol"] for s in get("https://api.stocktwits.com/api/2/trending/symbols.json")["symbols"]]
    st = [s for s in st if TICKER.match(s)][:MAX_PER_LIST]
    print("Tendances StockTwits : " + ", ".join(st))
    idees += [{"symbol": s, "pourquoi": "tendance StockTwits"} for s in st]
    rd = get("https://apewisdom.io/api/v1.0/filter/all-stocks/page/1")["results"]
    print("Les plus citées sur Reddit (24 h) :")
    for r in [r for r in rd if TICKER.match(r["ticker"])][:MAX_PER_LIST]:
        avant = r.get("mentions_24h_ago") or 0
        print(f"  {r['ticker']:<6} {r['mentions']:>5} citations (la veille : {avant})")
        idees.append({"symbol": r["ticker"], "pourquoi": f"{r['mentions']} citations Reddit"})
    return idees


def classer(doc):
    """Une action trouvée par plusieurs sources passe devant."""
    score, raisons = {}, {}
    for src in ("yahoo", "foule"):
        for i in doc.get(src, []):
            score[i["symbol"]] = score.get(i["symbol"], 0) + 1
            raisons.setdefault(i["symbol"], []).append(i["pourquoi"])
    ordre = sorted(score, key=lambda s: -score[s])
    return [{"symbol": s, "signaux": score[s], "pourquoi": raisons[s]} for s in ordre]


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("yahoo", "foule"):
        print(__doc__); return 2
    src = sys.argv[1]
    try:
        idees = yahoo() if src == "yahoo" else foule()
    except Exception as e:  # source en panne : on le dit, sans planter la mission
        print(f"Source indisponible : {e}"); return 1
    doc = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    doc[src] = idees
    doc["mis_a_jour"] = time.strftime("%Y-%m-%d %H:%M")
    doc["classement"] = classer(doc)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    top = [f"{i['symbol']} ({i['signaux']})" for i in doc["classement"][:8]]
    print(f"{len(idees)} idées. Classement (nombre de signaux) : " + ", ".join(top))
    print("Ce ne sont que des idées : le Guetteur et le Voyageur vont les vérifier.")
    return 0


if __name__ == "__main__":
    assert [i["symbol"] for i in classer({"yahoo": [{"symbol": "A", "pourquoi": "x"}, {"symbol": "B", "pourquoi": "y"}],
                                          "foule": [{"symbol": "B", "pourquoi": "z"}]})] == ["B", "A"]
    sys.exit(main())
