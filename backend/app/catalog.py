"""German city and airport catalogue.

Station IDs (DB EVA numbers) are deliberately *not* hardcoded for most
entries. They change, and getting one wrong produces a plausible-looking
journey to the wrong place. Instead each city carries a search string that
the DB `/locations` endpoint resolves once and we cache forever.

Coordinates are city-centre reference points, used only when the caller does
not supply a precise address.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Airport:
    iata: str
    name: str
    station_query: str        # how to find its rail station in the DB API
    lat: float
    lon: float
    has_rail: bool = True     # some German airports need a bus or taxi


@dataclass(frozen=True, slots=True)
class City:
    key: str
    name: str
    lat: float
    lon: float
    station_query: str
    airports: tuple[str, ...]  # IATA codes, most convenient first


AIRPORTS: dict[str, Airport] = {
    a.iata: a
    for a in [
        Airport("FRA", "Frankfurt", "Frankfurt(M) Flughafen Fernbahnhof", 50.037, 8.562),
        Airport("MUC", "München", "München Flughafen Terminal", 48.354, 11.786),
        Airport("BER", "Berlin Brandenburg", "Berlin Brandenburg Flughafen", 52.366, 13.503),
        Airport("DUS", "Düsseldorf", "Düsseldorf Flughafen", 51.278, 6.766),
        Airport("HAM", "Hamburg", "Hamburg Airport", 53.630, 9.988),
        Airport("CGN", "Köln/Bonn", "Köln/Bonn Flughafen", 50.866, 7.143),
        Airport("STR", "Stuttgart", "Stuttgart Flughafen/Messe", 48.690, 9.222),
        Airport("HAJ", "Hannover", "Hannover Flughafen", 52.461, 9.685),
        Airport("NUE", "Nürnberg", "Nürnberg Flughafen", 49.499, 11.078),
        Airport("LEJ", "Leipzig/Halle", "Leipzig/Halle Flughafen", 51.424, 12.222),
        Airport("BRE", "Bremen", "Bremen Flughafen", 53.047, 8.787),
        Airport("DTM", "Dortmund", "Holzwickede/Dortmund Flughafen", 51.518, 7.612, False),
        Airport("FMO", "Münster/Osnabrück", "Münster/Osnabrück Flughafen", 52.135, 7.685, False),
        Airport("DRS", "Dresden", "Dresden Flughafen", 51.134, 13.767),
    ]
}

_CITIES: list[City] = [
    City("berlin", "Berlin", 52.5200, 13.4050, "Berlin Hbf", ("BER",)),
    City("hamburg", "Hamburg", 53.5511, 9.9937, "Hamburg Hbf", ("HAM",)),
    City("muenchen", "München", 48.1372, 11.5755, "München Hbf", ("MUC",)),
    City("koeln", "Köln", 50.9375, 6.9603, "Köln Hbf", ("CGN", "DUS")),
    City("frankfurt", "Frankfurt am Main", 50.1109, 8.6821, "Frankfurt(Main)Hbf", ("FRA",)),
    City("stuttgart", "Stuttgart", 48.7758, 9.1829, "Stuttgart Hbf", ("STR",)),
    City("duesseldorf", "Düsseldorf", 51.2277, 6.7735, "Düsseldorf Hbf", ("DUS", "CGN")),
    City("dortmund", "Dortmund", 51.5136, 7.4653, "Dortmund Hbf", ("DTM", "DUS", "CGN")),
    City("essen", "Essen", 51.4556, 7.0116, "Essen Hbf", ("DUS", "DTM")),
    City("duisburg", "Duisburg", 51.4344, 6.7623, "Duisburg Hbf", ("DUS",)),
    City("bochum", "Bochum", 51.4818, 7.2162, "Bochum Hbf", ("DTM", "DUS")),
    City("leipzig", "Leipzig", 51.3397, 12.3731, "Leipzig Hbf", ("LEJ", "BER")),
    City("bremen", "Bremen", 53.0793, 8.8017, "Bremen Hbf", ("BRE", "HAM")),
    City("dresden", "Dresden", 51.0504, 13.7373, "Dresden Hbf", ("DRS", "BER")),
    City("hannover", "Hannover", 52.3759, 9.7320, "Hannover Hbf", ("HAJ",)),
    City("nuernberg", "Nürnberg", 49.4521, 11.0767, "Nürnberg Hbf", ("NUE", "MUC")),
    City("mannheim", "Mannheim", 49.4875, 8.4660, "Mannheim Hbf", ("FRA", "STR")),
    City("karlsruhe", "Karlsruhe", 49.0069, 8.4037, "Karlsruhe Hbf", ("STR", "FRA")),
    City("freiburg", "Freiburg", 47.9990, 7.8421, "Freiburg(Breisgau) Hbf", ("STR",)),
    City("muenster", "Münster", 51.9607, 7.6261, "Münster(Westf)Hbf", ("FMO", "DTM")),
    City("bielefeld", "Bielefeld", 52.0302, 8.5325, "Bielefeld Hbf", ("HAJ", "DTM")),
    City("bonn", "Bonn", 50.7374, 7.0982, "Bonn Hbf", ("CGN",)),
    City("aachen", "Aachen", 50.7753, 6.0839, "Aachen Hbf", ("CGN", "DUS")),
    City("wuppertal", "Wuppertal", 51.2562, 7.1508, "Wuppertal Hbf", ("DUS",)),
    City("mainz", "Mainz", 49.9929, 8.2473, "Mainz Hbf", ("FRA",)),
    City("wiesbaden", "Wiesbaden", 50.0782, 8.2398, "Wiesbaden Hbf", ("FRA",)),
    City("kassel", "Kassel", 51.3127, 9.4797, "Kassel-Wilhelmshöhe", ("FRA", "HAJ")),
    City("erfurt", "Erfurt", 50.9787, 11.0328, "Erfurt Hbf", ("LEJ",)),
    City("magdeburg", "Magdeburg", 52.1205, 11.6276, "Magdeburg Hbf", ("BER", "LEJ")),
    City("rostock", "Rostock", 54.0924, 12.0991, "Rostock Hbf", ("HAM", "BER")),
    City("kiel", "Kiel", 54.3233, 10.1228, "Kiel Hbf", ("HAM",)),
    City("luebeck", "Lübeck", 53.8655, 10.6866, "Lübeck Hbf", ("HAM",)),
    City("braunschweig", "Braunschweig", 52.2689, 10.5268, "Braunschweig Hbf", ("HAJ",)),
    City("osnabrueck", "Osnabrück", 52.2799, 8.0472, "Osnabrück Hbf", ("FMO", "HAJ")),
    City("augsburg", "Augsburg", 48.3705, 10.8978, "Augsburg Hbf", ("MUC",)),
    City("regensburg", "Regensburg", 49.0134, 12.1016, "Regensburg Hbf", ("MUC", "NUE")),
    City("wuerzburg", "Würzburg", 49.7913, 9.9534, "Würzburg Hbf", ("NUE", "FRA")),
    City("ulm", "Ulm", 48.4011, 9.9876, "Ulm Hbf", ("STR", "MUC")),
    City("heidelberg", "Heidelberg", 49.3988, 8.6724, "Heidelberg Hbf", ("FRA", "STR")),
    City("koblenz", "Koblenz", 50.3569, 7.5890, "Koblenz Hbf", ("CGN", "FRA")),
    City("saarbruecken", "Saarbrücken", 49.2402, 6.9969, "Saarbrücken Hbf", ("FRA",)),
]

CITIES: dict[str, City] = {c.key: c for c in _CITIES}


def find_city(text: str) -> City | None:
    """Loose lookup so 'munich', 'München' and 'muenchen' all work."""
    needle = (
        text.strip()
        .lower()
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )
    aliases = {
        "munich": "muenchen", "cologne": "koeln", "nuremberg": "nuernberg",
        "hanover": "hannover", "brunswick": "braunschweig", "frankfurt am main": "frankfurt",
        "frankfurt(main)": "frankfurt", "duesseldorf": "duesseldorf",
    }
    needle = aliases.get(needle, needle)
    if needle in CITIES:
        return CITIES[needle]
    for city in _CITIES:
        if city.name.lower().startswith(text.strip().lower()):
            return city
    return None
