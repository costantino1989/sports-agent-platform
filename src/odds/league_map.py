"""Mapping from ESPN league slugs to The Odds API sport keys.

Only leagues The Odds API actually covers are listed. An ESPN slug not present
here yields no real odds (the caller falls back to the ESPN snapshot), so it is
safe to leave minor/youth competitions unmapped.
"""

from __future__ import annotations

# ESPN league slug -> The Odds API sport key.
DEFAULT_LEAGUE_MAP: dict[str, str] = {
    "fifa.world": "soccer_fifa_world_cup",
    "ita.1": "soccer_italy_serie_a",
    "eng.1": "soccer_epl",
    "eng.2": "soccer_efl_champ",
    "eng.3": "soccer_england_league1",
    "eng.4": "soccer_england_league2",
    "eng.league_cup": "soccer_england_efl_cup",
    "esp.1": "soccer_spain_la_liga",
    "ger.1": "soccer_germany_bundesliga",
    "ger.dfb_pokal": "soccer_germany_dfb_pokal",
    "fra.1": "soccer_france_ligue_one",
    "sco.1": "soccer_spl",
    "sui.1": "soccer_switzerland_superleague",
    "aut.1": "soccer_austria_bundesliga",
    "den.1": "soccer_denmark_superliga",
    "nor.1": "soccer_norway_eliteserien",
    "swe.1": "soccer_sweden_allsvenskan",
    "swe.2": "soccer_sweden_superettan",
    "fin.1": "soccer_finland_veikkausliiga",
    "irl.1": "soccer_league_of_ireland",
    "usa.1": "soccer_usa_mls",
    "chn.1": "soccer_china_superleague",
    "kor.1": "soccer_korea_kleague1",
    "arg.1": "soccer_argentina_primera_division",
    "bra.1": "soccer_brazil_campeonato",
    "bra.2": "soccer_brazil_serie_b",
    "uefa.champions": "soccer_uefa_champs_league",
    "uefa.europa": "soccer_uefa_europa_league",
    "conmebol.libertadores": "soccer_conmebol_copa_libertadores",
    "conmebol.sudamericana": "soccer_conmebol_copa_sudamericana",
}
