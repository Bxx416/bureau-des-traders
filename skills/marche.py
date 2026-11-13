"""Place boursière des scripts trader-* (ajout du Bureau des Traders).

BDT_MARCHE=PA : Euronext Paris. Absent ou US : New York, rien ne change.
Chaque script appelle marche.applique(globals()) après ses propres réglages New York :
les noms « eastern » gardent leur nom mais parlent alors de l'heure de Paris.
"""
import datetime
import os
import re

MARCHE = os.environ.get("BDT_MARCHE", "US").upper()
PARIS = MARCHE == "PA"
SUFFIXES = (".PA",)   # tickers Yahoo d'Euronext Paris : MC.PA, TTE.PA…

# Euronext, calendrier officiel (jours fermés et séances écourtées à 14h05).
FERIES_PA = {
    "2026-01-01": "Jour de l'an", "2026-04-03": "Vendredi saint", "2026-04-06": "Lundi de Pâques",
    "2026-05-01": "Fête du travail", "2026-12-25": "Noël", "2026-12-26": "Saint-Étienne",
    "2027-01-01": "Jour de l'an", "2027-03-26": "Vendredi saint", "2027-03-29": "Lundi de Pâques",
    "2027-05-01": "Fête du travail", "2027-12-25": "Noël", "2027-12-26": "Saint-Étienne",
}
COURTS_PA = {"2026-12-24": "Veille de Noël", "2026-12-31": "Saint-Sylvestre",
             "2027-12-24": "Veille de Noël", "2027-12-31": "Saint-Sylvestre"}

# NYSE, calendrier officiel (jours fermés et séances écourtées à 13h).
FERIES_NY = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}
COURTS_NY = {  # 1:00 p.m. ET
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}
CALENDAR_YEARS = (2026, 2027)


# ---------------------------------------------------------------- fuseaux horaires
# zoneinfo quand la base des fuseaux est là ; sinon les règles officielles (US depuis 2007, UE depuis 1996).
try:
    from zoneinfo import ZoneInfo
    _TZ = {"US": ZoneInfo("America/New_York"), "PA": ZoneInfo("Europe/Paris")}
except Exception:   # Python Windows sans le paquet tzdata
    _TZ = None


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def ny_offset_regle(utc):
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))   # 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))    # 2:00 EDT
    return -4 if start <= utc.replace(tzinfo=None) < end else -5


def _offset_tz(utc, m):
    u = utc.replace(tzinfo=datetime.timezone.utc) if utc.tzinfo is None else utc
    return int(u.astimezone(_TZ[m]).utcoffset().total_seconds() // 3600)


def ny_offset(utc):
    """Heures depuis UTC à New York : -4 en heure d'été, -5 sinon."""
    return _offset_tz(utc, "US") if _TZ else ny_offset_regle(utc)


OUVERTURE, CLOTURE, COURTE = datetime.time(9, 0), datetime.time(17, 30), datetime.time(14, 5)
FLAT_BY = "17:20"


def _dernier_dimanche(annee, mois):
    d = datetime.date(annee, mois + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def paris_offset(utc):
    """+2 en heure d'été (dernier dimanche de mars 1h UTC → dernier dimanche d'octobre 1h UTC), +1 sinon."""
    return _offset_tz(utc, "PA") if _TZ else paris_offset_regle(utc)


def paris_offset_regle(utc):
    y = utc.year
    debut = datetime.datetime.combine(_dernier_dimanche(y, 3), datetime.time(1, 0))
    fin = datetime.datetime.combine(_dernier_dimanche(y, 10), datetime.time(1, 0))
    return 2 if debut <= utc.replace(tzinfo=None) < fin else 1


def paris_to_utc(local):
    for off in (2, 1):
        utc = local - datetime.timedelta(hours=off)
        if paris_offset(utc) == off:
            return utc
    return local - datetime.timedelta(hours=1)


def ny_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if ny_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


# ---------------------------------------------------------------- place active
# Les scripts importent ces noms (anciennement recopiés dans chacun) : ils désignent New York, ou Paris
# quand BDT_MARCHE=PA.
eastern_offset = paris_offset if PARIS else ny_offset
eastern_to_utc = paris_to_utc if PARIS else ny_to_utc
NYSE_HOLIDAYS = FERIES_PA if PARIS else FERIES_NY
NYSE_EARLY_CLOSE = COURTS_PA if PARIS else COURTS_NY
OPEN, CLOSE, EARLY = (OUVERTURE, CLOTURE, COURTE) if PARIS else     (datetime.time(9, 30), datetime.time(16, 0), datetime.time(13, 0))


def to_eastern(utc):
    """UTC (avec ou sans fuseau) → heure locale de la place, sans fuseau."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(datetime.timezone.utc)
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def trading_day(d):
    """(jour de bourse ?, raison). Week-ends et jours fériés de la place."""
    if d.weekday() >= 5:
        return False, "weekend"
    name = NYSE_HOLIDAYS.get(d.isoformat())
    if name:
        return False, "NYSE holiday: " + name
    return True, ""


def yahoo(sym):
    """Ticker → symbole Yahoo. BRK.B → BRK-B à New York ; MC.PA reste MC.PA."""
    s = sym.upper()
    return s if s.endswith(SUFFIXES) else s.replace(".", "-")


def applique(g):
    """Pour Paris, remplace ce qui reste propre à New York dans le module appelant (le calendrier et le fuseau
    sont déjà ceux de la place active : importés d'ici)."""
    if not PARIS:
        return
    remplace = {
        "OPEN_MIN": 9 * 60, "CLOSE_MIN": 17 * 60 + 30, "EARLY_MIN": 14 * 60 + 5,
        "SESSION_BARS": 102,   # 9h00 → 17h30 en barres de 5 min
    }
    for k, v in remplace.items():
        if k in g:
            g[k] = v
    for k in ("DEFAULTS", "DEFAULT_CONFIG", "CONFIG_DEFAULTS"):
        if isinstance(g.get(k), dict) and "flat_by" in g[k]:
            g[k] = dict(g[k], flat_by=FLAT_BY)
    import sys
    if not isinstance(sys.stdout, _Traduit):
        sys.stdout, sys.stderr = _Traduit(sys.stdout), _Traduit(sys.stderr)


class _Traduit:
    """Les textes des scripts parlent de New York : on les remet à l'heure de Paris à l'affichage."""
    MOTS = [(re.compile(a), b) for a, b in ((r"New York", "Paris"), (r"NYSE", "Euronext"), (r" ET\b", " Paris"),
                                            (r"\b9:30\b", "9:00"), (r"\b4:00 PM\b", "5:30 PM"), (r"\$", "€"))]

    def __init__(self, f):
        self.f = f

    def write(self, t):
        for a, b in self.MOTS:
            t = a.sub(b, t)
        return self.f.write(t)

    def __getattr__(self, k):
        return getattr(self.f, k)


if __name__ == "__main__":
    u = datetime.datetime
    assert paris_offset(u(2026, 3, 29, 0, 59)) == 1 and paris_offset(u(2026, 3, 29, 1, 0)) == 2
    assert paris_offset(u(2026, 10, 25, 0, 59)) == 2 and paris_offset(u(2026, 10, 25, 1, 0)) == 1
    assert paris_to_utc(u(2026, 11, 13, 9, 0)) == u(2026, 11, 13, 8, 0)
    assert paris_to_utc(u(2026, 7, 1, 9, 0)) == u(2026, 7, 1, 7, 0)
    assert yahoo("brk.b") == "BRK-B" and yahoo("mc.pa") == "MC.PA"
    g = {"OPEN_MIN": None, "DEFAULTS": {"flat_by": "15:55"}}
    if PARIS:
        applique(g); assert g["OPEN_MIN"] == 540 and g["DEFAULTS"]["flat_by"] == FLAT_BY
        assert OPEN == OUVERTURE and NYSE_HOLIDAYS is FERIES_PA and eastern_offset is paris_offset
    else:
        assert OPEN == datetime.time(9, 30) and not trading_day(datetime.date(2026, 11, 26))[0]
    import io
    f = io.StringIO(); _Traduit(f).write("NYSE 9:30 ET, ETF $5 at 19:30")
    assert f.getvalue() == "Euronext 9:00 Paris, ETF €5 at 19:30", f.getvalue()
    if _TZ:   # zoneinfo et les règles officielles donnent la même heure, heure par heure sur 2 ans
        h = u(2026, 1, 1)
        while h < u(2028, 1, 1):
            assert ny_offset(h) == ny_offset_regle(h) and paris_offset(h) == paris_offset_regle(h), h
            h += datetime.timedelta(hours=1)
    print("ok", MARCHE, "zoneinfo" if _TZ else "règles")
