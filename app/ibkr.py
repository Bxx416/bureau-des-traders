"""Interactive Brokers (compte PAPIER) pour la Bourse de Paris, via IB Gateway ou TWS ouvert sur ce PC.

Papier seulement : on refuse de parler à un compte dont le numéro ne commence pas par « D » (comptes démo IBKR).
"""
import asyncio, math, shutil, subprocess, sys, threading
from pathlib import Path
from contextlib import contextmanager

HOTE, CLIENT_ID = "127.0.0.1", 71
PORT_DEFAUT = 4002          # IB Gateway papier (TWS papier : 7497)
verrou = threading.Lock()   # une seule connexion à la fois


def module():
    """ib_async, installé à la demande (les testeurs mis à jour à chaud ne l'ont pas encore)."""
    try:
        import ib_async
    except ImportError:
        UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
        subprocess.run([UV, "pip", "install", "--python", sys.executable, "ib_async", "--quiet"], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import ib_async
    return ib_async


@contextmanager
def connexion(port):
    ib_async = module()
    with verrou:
        asyncio.set_event_loop(asyncio.new_event_loop())
        ib = ib_async.IB()
        try:
            ib.connect(HOTE, port or PORT_DEFAUT, clientId=CLIENT_ID, timeout=8, readonly=False)
        except (OSError, asyncio.TimeoutError, TimeoutError):
            raise RuntimeError(f"IB Gateway injoignable sur le port {port or PORT_DEFAUT} : "
                               "ouvre IB Gateway en mode Paper Trading et active l'API.") from None
        try:
            comptes = ib.managedAccounts()
            if not comptes or not all(c.startswith("D") for c in comptes):
                raise RuntimeError("Ce n'est pas un compte PAPIER IBKR (numéro en D…) : refusé.")
            yield ib, ib_async
        finally:
            ib.disconnect()
            asyncio.get_event_loop().close()


def contrat(ib_async, sym):
    base = sym.upper().removesuffix(".PA")
    return ib_async.Stock(base, "SBF", "EUR")


def arrondi(px, regles, vers=0):
    """Prix sur la grille d'Euronext (pas de cotation selon le niveau de prix). vers : +1 haut, -1 bas, 0 au plus près."""
    pas = 0.01
    for r in sorted(regles, key=lambda r: r.lowEdge):
        if px >= r.lowEdge:
            pas = r.increment
    n = px / pas
    n = math.ceil(n - 1e-9) if vers > 0 else math.floor(n + 1e-9) if vers < 0 else round(n)
    return round(n * pas, 6)


class PasEnvoye(RuntimeError):
    """Rien n'est actif chez le courtier : erreur avant placeOrder, ou ordre refusé par IBKR."""


def envoyer(ti, port, ref):
    """Ticket (champs Alpaca de ticket.py) → ordre parent + objectif + stop liés (bracket). Renvoie l'id du parent.
    ref (clé d'idempotence bdt-…) va dans orderRef de chaque ordre : on le retrouve si la réponse se perd.
    Une erreur après placeOrder remonte telle quelle : l'ordre est peut-être parti (état UNKNOWN côté serveur)."""
    parti = False
    try:
        with connexion(port) as (ib, m):
            deja = retrouver_dans(ib, ref)
            if deja:
                return deja   # déjà chez IBKR : on ne renvoie rien
            c = contrat(m, ti["symbol"])
            if not ib.qualifyContracts(c):
                raise PasEnvoye(f"{ti['symbol']} introuvable chez IBKR sur Euronext Paris.")
            d = ib.reqContractDetails(c)[0]
            regles = ib.reqMarketRule(int(d.marketRuleIds.split(",")[0])) or []
            achat = ti["side"] == "buy"
            sens, inverse = ("BUY", "SELL") if achat else ("SELL", "BUY")
            qty = float(ti["qty"])
            if ti.get("type") == "limit":
                parent = m.LimitOrder(sens, qty, arrondi(float(ti["limit_price"]), regles))
            else:
                parent = m.MarketOrder(sens, qty)
            parent.orderId, parent.transmit, parent.tif = ib.client.getReqId(), False, "DAY"
            ordres = [parent]
            if "take_profit_limit_price" in ti:
                ordres.append(m.LimitOrder(inverse, qty, arrondi(float(ti["take_profit_limit_price"]), regles),
                                           parentId=parent.orderId, tif="DAY", transmit=False))
            if "stop_loss_stop_price" in ti:   # arrondi vers l'entrée : la perte ne dépasse pas celle du ticket
                stop = arrondi(float(ti["stop_loss_stop_price"]), regles, +1 if achat else -1)
                ordres.append(m.StopOrder(inverse, qty, stop, parentId=parent.orderId, tif="DAY", transmit=False))
            ordres[-1].transmit = True   # le dernier envoie tout le groupe d'un coup
            for o in ordres:
                o.orderRef = ref
            parti = True
            for o in ordres:
                ib.placeOrder(c, o)
            ib.sleep(2)
            rejet = next((e.message for t in ib.trades() if t.order.orderId == parent.orderId
                          for e in t.log if e.errorCode and e.errorCode not in (399,)), None)
            if rejet:
                raise PasEnvoye(f"IBKR a refusé l'ordre : {rejet}")
            return str(parent.orderId)
    except PasEnvoye:
        raise
    except Exception as e:
        if not parti:
            raise PasEnvoye(str(e)) from None
        raise


def retrouver_dans(ib, ref):
    """Id IBKR du parent d'un ordre du bureau (orderRef), ouvert ou terminé ; None s'il n'existe pas."""
    for t in [*ib.reqAllOpenOrders(), *ib.reqCompletedOrders(False)]:
        if t.order.orderRef == ref and not t.order.parentId:
            return str(t.order.orderId or t.order.permId)
    return None


def retrouver(port, ref):
    with connexion(port) as (ib, m):
        return retrouver_dans(ib, ref)


def fermer_geres(port, geres):
    """Annule les ordres du bureau (orderRef bdt-…) et ne ferme que la quantité achetée par le bureau.
    geres : {symbole: quantité}. Une position ouverte à la main n'est jamais fermée. Renvoie le nombre de ventes."""
    with connexion(port) as (ib, m):
        for t in ib.reqAllOpenOrders():
            if str(t.order.orderRef or "").startswith("bdt-"):
                ib.cancelOrder(t.order)
        ib.sleep(1)
        n = 0
        for p in ib.positions():
            sym = p.contract.symbol + ".PA"
            if p.contract.currency == "EUR" and p.position > 0 and sym in geres:
                c = m.Stock(p.contract.symbol, "SBF", "EUR")
                ib.qualifyContracts(c)
                ib.placeOrder(c, m.MarketOrder("SELL", min(p.position, geres[sym]), tif="DAY"))
                n += 1
        ib.sleep(2)
        return n


def executions(port):
    """Exécutions récentes (IBKR n'en garde que quelques jours) au format de trades_fermes."""
    with connexion(port) as (ib, m):
        return [{"id": f.execution.execId, "transaction_time": f.execution.time.isoformat(),
                 "symbol": f.contract.symbol + ".PA", "side": "buy" if f.execution.side == "BOT" else "sell",
                 "qty": str(f.execution.shares), "price": str(f.execution.price),
                 "fee": str(f.commissionReport.commission if f.commissionReport else 0)}
                for f in ib.reqExecutions() if f.contract.currency == "EUR"]


def compte(port):
    with connexion(port) as (ib, m):
        v = {x.tag: x.value for x in ib.accountSummary() if x.tag in ("NetLiquidation",)}
        return {"equity": float(v.get("NetLiquidation", 0)),
                "ouvertes": sum(1 for p in ib.positions() if p.contract.currency == "EUR" and p.position)}


if __name__ == "__main__":
    class R:
        def __init__(self, low, inc): self.lowEdge, self.increment = low, inc
    g = [R(0, 0.0001), R(1, 0.0005), R(5, 0.001), R(10, 0.005), R(50, 0.01), R(100, 0.05)]
    assert arrondi(242.33, g) == 242.35 and arrondi(242.33, g, -1) == 242.30 and arrondi(242.31, g, +1) == 242.35
    assert arrondi(12.343, g) == 12.345 and arrondi(3.0, g, +1) == 3.0
    print("ok")
