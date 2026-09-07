"""Destination catalogue for the Anywhere search.

Deliberately data, not code. Adding a country means adding rows here and a
tariff in fares.py; nothing else changes. `rail` is a corridor-quality hint
(0-1) standing in for how well connected the city is to the long-distance
network — Paris and Frankfurt are 1.0, Split is 0.3 because getting there by
train is genuinely miserable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Destination:
    name: str
    country: str
    lat: float
    lon: float
    rail: float
    blurb: str


_ROWS = [
    # name, country, lat, lon, rail-quality, one-line reason to go
    ("Berlin", "DE", 52.520, 13.405, 0.90, "Museums, nightlife, cheap for a capital"),
    ("Hamburg", "DE", 53.551, 9.994, 0.85, "Harbour city, Elbphilharmonie"),
    ("München", "DE", 48.137, 11.576, 0.90, "Beer gardens and the Alps an hour away"),
    ("Köln", "DE", 50.938, 6.960, 0.90, "Cathedral, Rhine, easy weekend"),
    ("Frankfurt am Main", "DE", 50.111, 8.682, 1.00, "Skyline, apple wine, best rail hub"),
    ("Dresden", "DE", 51.050, 13.737, 0.75, "Baroque old town, Saxon Switzerland nearby"),
    ("Leipzig", "DE", 51.340, 12.374, 0.75, "Bach, lakes, still affordable"),
    ("Stuttgart", "DE", 48.776, 9.183, 0.80, "Vineyards inside the city"),
    ("Nürnberg", "DE", 49.452, 11.077, 0.80, "Medieval core, Christmas market"),
    ("Freiburg", "DE", 47.999, 7.842, 0.70, "Black Forest gateway, sunniest city"),
    ("Heidelberg", "DE", 49.399, 8.672, 0.70, "Castle over the Neckar"),
    ("Bremen", "DE", 53.079, 8.802, 0.70, "Hanseatic, compact, underrated"),
    ("Rostock", "DE", 54.092, 12.099, 0.60, "Baltic beaches at Warnemünde"),

    ("Wien", "AT", 48.208, 16.373, 0.90, "Coffee houses and imperial everything"),
    ("Salzburg", "AT", 47.810, 13.055, 0.70, "Alpine baroque, Mozart"),
    ("Innsbruck", "AT", 47.269, 11.404, 0.70, "Mountains from the platform"),
    ("Graz", "AT", 47.071, 15.439, 0.60, "Styrian food, student city"),

    ("Zürich", "CH", 47.377, 8.541, 0.95, "Lake, old town, expensive"),
    ("Bern", "CH", 46.948, 7.447, 0.80, "UNESCO arcades, very walkable"),
    ("Basel", "CH", 47.559, 7.588, 0.85, "Art museums, Rhine swimming"),
    ("Genève", "CH", 46.204, 6.143, 0.85, "Lake Geneva, Mont Blanc views"),
    ("Interlaken", "CH", 46.686, 7.863, 0.65, "Jungfrau region base camp"),
    ("Luzern", "CH", 47.050, 8.309, 0.75, "Covered bridge, lake steamers"),

    ("Amsterdam", "NL", 52.370, 4.895, 0.95, "Canals, Rijksmuseum, bikes"),
    ("Rotterdam", "NL", 51.924, 4.478, 0.85, "Modern architecture, port"),
    ("Utrecht", "NL", 52.091, 5.122, 0.85, "Amsterdam without the crowds"),
    ("Maastricht", "NL", 50.851, 5.691, 0.70, "Roman roots, closest Dutch city"),

    ("Brussel", "BE", 50.851, 4.352, 0.95, "Beer, waffles, art nouveau"),
    ("Brugge", "BE", 51.209, 3.224, 0.75, "Canals and medieval streets"),
    ("Antwerpen", "BE", 51.219, 4.402, 0.80, "Diamonds, fashion, Rubens"),
    ("Gent", "BE", 51.054, 3.717, 0.75, "Bruges without the tour buses"),
    ("Luxembourg", "LU", 49.611, 6.130, 0.70, "Fortress city, free transport"),

    ("Paris", "FR", 48.857, 2.352, 1.00, "It is Paris"),
    ("Lyon", "FR", 45.764, 4.836, 0.85, "France's food capital"),
    ("Strasbourg", "FR", 48.573, 7.752, 0.75, "Half-timbered, half-German"),
    ("Marseille", "FR", 43.297, 5.370, 0.80, "Calanques and bouillabaisse"),
    ("Nice", "FR", 43.700, 7.265, 0.70, "Riviera, old town, beach"),
    ("Bordeaux", "FR", 44.838, -0.579, 0.75, "Wine and 18th-century stone"),
    ("Toulouse", "FR", 43.605, 1.444, 0.70, "Pink brick, cassoulet"),

    ("Milano", "IT", 45.464, 9.190, 0.95, "Design, Duomo, aperitivo"),
    ("Roma", "IT", 41.903, 12.496, 0.90, "Two thousand years, densely packed"),
    ("Venezia", "IT", 45.440, 12.316, 0.80, "No cars, all water"),
    ("Firenze", "IT", 43.770, 11.256, 0.85, "Renaissance, Tuscany at the door"),
    ("Bologna", "IT", 44.494, 11.343, 0.90, "Porticoes and the best food in Italy"),
    ("Torino", "IT", 45.070, 7.687, 0.80, "Arcades, chocolate, Alps"),
    ("Napoli", "IT", 40.852, 14.268, 0.80, "Pizza, chaos, Pompeii nearby"),
    ("Verona", "IT", 45.438, 10.993, 0.80, "Arena opera, Lake Garda"),

    ("Barcelona", "ES", 41.385, 2.173, 0.90, "Gaudí, beach, late dinners"),
    ("Madrid", "ES", 40.417, -3.704, 0.95, "Prado, tapas, rooftops"),
    ("València", "ES", 39.470, -0.377, 0.80, "Paella's home, futuristic quarter"),
    ("Sevilla", "ES", 37.389, -5.984, 0.80, "Flamenco and orange trees"),
    ("Bilbao", "ES", 43.263, -2.935, 0.55, "Guggenheim and pintxos"),
    ("San Sebastián", "ES", 43.318, -1.981, 0.50, "Most Michelin stars per head"),
    ("Lisboa", "PT", 38.722, -9.139, 0.55, "Trams, tiles, Atlantic light"),
    ("Porto", "PT", 41.158, -8.629, 0.55, "Port wine and the Douro"),

    ("København", "DK", 55.677, 12.568, 0.90, "Design, cycling, hygge"),
    ("Aarhus", "DK", 56.163, 10.203, 0.70, "Compact, young, coastal"),
    ("Stockholm", "SE", 59.329, 18.069, 0.80, "Archipelago capital"),
    ("Göteborg", "SE", 57.709, 11.974, 0.75, "Seafood and canals"),
    ("Malmö", "SE", 55.605, 13.003, 0.80, "Bridge ride from Copenhagen"),
    ("Oslo", "NO", 59.914, 10.752, 0.70, "Fjord at the end of the street"),
    ("Bergen", "NO", 60.393, 5.325, 0.55, "Fjords and wooden wharf"),
    ("Helsinki", "FI", 60.170, 24.938, 0.45, "Saunas and Baltic design"),

    ("Praha", "CZ", 50.076, 14.437, 0.80, "Old town, cheap beer"),
    ("Brno", "CZ", 49.195, 16.608, 0.70, "Functionalist architecture, students"),
    ("Český Krumlov", "CZ", 48.811, 14.317, 0.40, "Storybook riverside town"),
    ("Warszawa", "PL", 52.230, 21.011, 0.80, "Rebuilt old town, strong food scene"),
    ("Kraków", "PL", 50.065, 19.945, 0.75, "Best-preserved Polish old town"),
    ("Wrocław", "PL", 51.108, 17.038, 0.70, "Islands, bridges, dwarves"),
    ("Gdańsk", "PL", 54.352, 18.646, 0.65, "Hanseatic Baltic port"),
    ("Budapest", "HU", 47.498, 19.040, 0.80, "Thermal baths and ruin bars"),
    ("Bratislava", "SK", 48.148, 17.107, 0.70, "An hour from Vienna"),
    ("Ljubljana", "SI", 46.056, 14.506, 0.60, "Small, green, walkable"),
    ("Zagreb", "HR", 45.815, 15.982, 0.55, "Austro-Hungarian, underrated"),
    ("Split", "HR", 43.508, 16.440, 0.30, "Diocletian's palace, islands"),

    ("London", "GB", 51.507, -0.128, 0.85, "Eurostar from Brussels"),
    ("Edinburgh", "GB", 55.953, -3.189, 0.60, "Castle, closes, festivals"),
    ("Dublin", "IE", 53.350, -6.260, 0.35, "Flight only, but cheap ones"),
    ("Athína", "GR", 37.984, 23.728, 0.30, "Acropolis, flights not trains"),
    ("București", "RO", 44.427, 26.103, 0.45, "Cheap, changing fast"),
    ("Sofia", "BG", 42.698, 23.322, 0.40, "Mountains at the tram terminus"),
    ("Rīga", "LV", 56.949, 24.105, 0.35, "Art nouveau capital"),
    ("Tallinn", "EE", 59.437, 24.754, 0.30, "Walled medieval core"),
    ("Vilnius", "LT", 54.687, 25.280, 0.35, "Baroque old town, very cheap"),
]

DESTINATIONS: tuple[Destination, ...] = tuple(
    Destination(n, c, la, lo, r, b) for n, c, la, lo, r, b in _ROWS
)
