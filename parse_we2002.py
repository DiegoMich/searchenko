"""
WE2002 / Winning Eleven 2002 Player Database Extractor
Reads player names, teams, and stats from the PSX game disc.

Usage:
  python parse_we2002.py
  python parse_we2002.py --decompressed <path_to_raw_bin>

Outputs:
  players.json  — player data array
  index.html    — self-contained search page (players.json embedded)
  parse_diagnostic.txt — analysis log
"""

import json
import struct
import sys
import statistics
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
DISC        = Path("F:/")
EXE_PATH    = DISC / "SLPM_870.56"
DATSEL_PATH = DISC / "BIN/DATSEL.BIN"

OUT_DIR     = Path(__file__).parent
OUTPUT_JSON = OUT_DIR / "players.json"
OUTPUT_HTML = OUT_DIR / "index.html"
DIAGNOSTIC  = OUT_DIR / "parse_diagnostic.txt"

# ── Name block constants ──────────────────────────────────────────────────────
NAME_BLOCK_OFFSET = 0x046780
NAME_SLOT_SIZE    = 10
NAME_BLOCK_SLOTS  = 1472
FIRST_REAL_SLOT   = 12

# ── Team boundary table ───────────────────────────────────────────────────────
# (first_slot_index, team_name)
# Verified against player names: each entry = start of that team's 23-player squad
TEAM_BOUNDARIES = [
    (12,   "Republic of Ireland"),
    (35,   "Scotland"),
    (58,   "Wales"),
    (80,   "England"),
    (104,  "Portugal"),
    (127,  "Spain"),
    (150,  "France"),
    (173,  "Belgium"),
    (196,  "Netherlands"),
    (219,  "Switzerland"),
    (242,  "Italy"),
    (265,  "Czech Republic"),
    (288,  "Germany"),
    (311,  "Denmark"),
    (334,  "Norway"),
    (357,  "Sweden"),
    (380,  "Finland"),
    (403,  "Poland"),
    (426,  "Slovakia"),
    (449,  "Austria"),
    (472,  "Hungary"),
    (495,  "Yugoslavia"),
    (518,  "Croatia"),
    (541,  "Yugoslavia B"),
    (564,  "Romania"),
    (587,  "Bulgaria"),
    (610,  "Greece"),
    (633,  "Turkey"),
    (656,  "Ukraine"),
    (679,  "Russia"),
    (702,  "Morocco"),
    (725,  "Tunisia"),
    (748,  "Egypt"),
    (771,  "Nigeria"),
    (794,  "Cameroon"),
    (817,  "South Africa"),
    (840,  "Senegal"),
    (863,  "USA"),
    (886,  "Mexico"),
    (909,  "Costa Rica"),
    (932,  "Colombia"),
    (955,  "Brazil"),
    (978,  "Peru"),
    (1001, "Chile"),
    (1024, "Paraguay"),
    (1047, "Uruguay"),
    (1070, "Argentina"),
    (1093, "Ecuador"),
    (1116, "Japan"),
    (1139, "South Korea"),
    (1162, "China"),
    (1185, "Iran"),
    (1208, "Saudi Arabia"),
    (1231, "Australia"),
    (1254, "World Stars"),
    (1277, "World Stars II"),
    (1300, "Classic England"),
    (1323, "Classic France"),
    (1346, "Classic Netherlands"),
    (1369, "Classic Italy"),
    (1392, "Classic Germany"),
    (1415, "Classic Brazil"),
    (1438, "Classic Argentina"),
]

POSITION_LABELS   = {0:"GK", 1:"CB", 2:"SB", 3:"DH", 4:"SH", 5:"OH", 6:"CF", 7:"WG"}
POSITION_CATEGORY = {0:"GK", 1:"DF", 2:"DF", 3:"MF", 4:"MF", 5:"MF", 6:"FW", 7:"FW"}

# ── Club team data (SELECT.BIN) ────────────────────────────────────────────────
SELECT_PATH  = DISC / "SELECT.BIN"
SELECT4_PATH = DISC / "SELECT4.BIN"

# The 32 club teams present in the game (confirmed from SELECT.BIN string table)
CLUB_TEAMS_ORDERED = [
    "BOCA JUNIOR", "D.KIEV", "GALATASARAY", "OLYMPIAKOS",
    "B.LEVER", "BAYERN", "B.DORTMUND",
    "ROMA", "FIORENT", "PARMA", "LAZIO", "MILAN", "JUVENTUS", "INTER",
    "PSV EIN", "FEYENOORD", "AJAX",
    "BORDEAU", "PARIS S.G.", "O.MARSEILLE", "MONACO",
    "DEPORTIVO", "VALENCIA", "R.MADRI", "BARCELONA",
    "ASTON VILLA", "NEWCASTLE", "LEEDS UTD", "LIVERPOOL",
    "CHELSEA", "ARSENAL", "MAN UTD",
]

# SELECT.BIN: player name block at offset 0x1808, 462 players in 10-byte slots
SELECT_BLOCK_OFFSET = 0x1808
SELECT_BLOCK_COUNT  = 462
SELECT_SLOT_SIZE    = 10

# SELECT.BIN: 12-byte bit-packed player stat records
SELECT_STATS_NAT_OFFSET  = 0x265EC   # 1449 national team player records
SELECT_STATS_NAT_COUNT   = 1449
SELECT_STATS_CLUB_OFFSET = 0x2BB0C   # 462 club/ML player records
SELECT_STATS_CLUB_COUNT  = 462
SELECT4_COSTS_OFFSET        = 0x002174  # 1242 × 1-byte ML costs for regular teams (nat_idx 0-1241)
SELECT4_COSTS_COUNT         = 1242
SELECT4_SPECIAL_COSTS_OFFSET = 0x002622  # 207 × 1-byte ML costs for special teams (nat_idx 1242-1448)
SELECT4_SPECIAL_START        = 1242      # nat_idx where special teams begin

# Player → club team mapping (based on ~2001-02 season rosters)
# Keys match the names as they appear in SELECT.BIN.
PLAYER_CLUB_MAP = {
    # ── MAN UTD ────────────────────────────────────────────────────────────────
    "Irwin":       "MAN UTD",   "Brown":      "MAN UTD",   "Wallwork":   "MAN UTD",
    "May":         "MAN UTD",   "Butt":       "MAN UTD",   "Chadwick":   "MAN UTD",
    "Blanc":       "MAN UTD",   "Silvestre":  "MAN UTD",   "V.D.Gouw":   "MAN UTD",
    "Yorke":       "MAN UTD",
    # ── ARSENAL ────────────────────────────────────────────────────────────────
    "Adams":       "ARSENAL",   "Dixon":      "ARSENAL",   "Parlour":    "ARSENAL",
    "Jeffers":     "ARSENAL",   "Grimandi":   "ARSENAL",   "Bergkamp":   "ARSENAL",
    "Inamoto":     "ARSENAL",   "Edu":        "ARSENAL",
    # ── CHELSEA ────────────────────────────────────────────────────────────────
    "Le Saux":     "CHELSEA",   "Terry":      "CHELSEA",   "Morris":     "CHELSEA",
    "Redknapp":    "CHELSEA",   "Gallas":     "CHELSEA",   "Zola":       "CHELSEA",
    "Di Matteo":   "CHELSEA",   "De Goey":    "CHELSEA",   "Bogarde":    "CHELSEA",
    "Ferrer":      "CHELSEA",   "Gudjohnsen": "CHELSEA",
    # ── LEEDS UTD ──────────────────────────────────────────────────────────────
    "McPhail":     "LEEDS UTD", "Matteo":     "LEEDS UTD", "Bowyer":     "LEEDS UTD",
    "Woodgate":    "LEEDS UTD", "Duberry":    "LEEDS UTD", "Mills":      "LEEDS UTD",
    "Batty":       "LEEDS UTD", "Wilcox":     "LEEDS UTD", "Bridges":    "LEEDS UTD",
    "A.Smith":     "LEEDS UTD", "Robinson":   "LEEDS UTD", "Dacourt":    "LEEDS UTD",
    # ── NEWCASTLE ──────────────────────────────────────────────────────────────
    "A.Hughes":    "NEWCASTLE", "S.Caldwell": "NEWCASTLE", "Griffin":    "NEWCASTLE",
    "Dyer":        "NEWCASTLE", "Cort":       "NEWCASTLE", "Shearer":    "NEWCASTLE",
    "Lee":         "NEWCASTLE", "Harper":     "NEWCASTLE", "Distin":     "NEWCASTLE",
    "Marcelino":   "NEWCASTLE",
    # ── LIVERPOOL ──────────────────────────────────────────────────────────────
    "Henchoz":     "LIVERPOOL", "Vignal":     "LIVERPOOL", "Diomede":    "LIVERPOOL",
    "Arphexad":    "LIVERPOOL", "Heggem":     "LIVERPOOL", "Babbel":     "LIVERPOOL",
    # ── ASTON VILLA ────────────────────────────────────────────────────────────
    "A.Wright":    "ASTON VILLA","Hendrie":   "ASTON VILLA","Vassell":   "ASTON VILLA",
    "Barry":       "ASTON VILLA","Stone":     "ASTON VILLA","Merson":    "ASTON VILLA",
    "Dublin":      "ASTON VILLA","Myhill":    "ASTON VILLA","Ginola":    "ASTON VILLA",
    "Kachloul":    "ASTON VILLA","Schmeichel":"ASTON VILLA",
    # ── BARCELONA ──────────────────────────────────────────────────────────────
    "Gerard":      "BARCELONA",  "Gabri":     "BARCELONA",  "Dani":      "BARCELONA",
    "Reina":       "BARCELONA",  "Geovanni":  "BARCELONA",  "Saviola":   "BARCELONA",
    "Rochemback":  "BARCELONA",
    # ── REAL MADRID (R.MADRI) ──────────────────────────────────────────────────
    "Pavon":       "R.MADRI",    "Guti":      "R.MADRI",    "M.Salgado": "R.MADRI",
    "I.Campo":     "R.MADRI",    "Cesar":     "R.MADRI",    "Solari":    "R.MADRI",
    # ── VALENCIA ───────────────────────────────────────────────────────────────
    "Rufete":      "VALENCIA",   "Marchena":  "VALENCIA",   "Albelda":   "VALENCIA",
    "Vicente":     "VALENCIA",   "Palop":     "VALENCIA",   "Carboni":   "VALENCIA",
    "Farinos":     "VALENCIA",   "E.Costa":   "VALENCIA",
    # ── DEPORTIVO ──────────────────────────────────────────────────────────────
    "Donato":      "DEPORTIVO",  "Fran":      "DEPORTIVO",  "Capdevila": "DEPORTIVO",
    "Helder":      "DEPORTIVO",  "Cristobal": "DEPORTIVO",  "Djalminha": "DEPORTIVO",
    "Scaloni":     "DEPORTIVO",  "Pandiani":  "DEPORTIVO",
    # ── PARIS S.G. ─────────────────────────────────────────────────────────────
    "Letizi":      "PARIS S.G.", "Domi":      "PARIS S.G.", "Mendy":     "PARIS S.G.",
    "E.Cisse":     "PARIS S.G.", "Ronaldinho":"PARIS S.G.",
    # ── O.MARSEILLE ────────────────────────────────────────────────────────────
    "Hemdani":     "O.MARSEILLE","Diawara":   "O.MARSEILLE","V.Buyten":  "O.MARSEILLE",
    "Bakayoko":    "O.MARSEILLE","Moreau":    "O.MARSEILLE","Sommeil":   "O.MARSEILLE",
    # ── MONACO ─────────────────────────────────────────────────────────────────
    "Giuly":       "MONACO",     "Prso":      "MONACO",     "Nonda":     "MONACO",
    "Bernardi":    "MONACO",     "Lamouchi":  "MONACO",
    # ── BORDEAU (Bordeaux) ─────────────────────────────────────────────────────
    "Dugarry":     "BORDEAU",    "Bonnissel": "BORDEAU",    "Jurietti":  "BORDEAU",
    "Dalmat":      "BORDEAU",
    # ── AJAX ───────────────────────────────────────────────────────────────────
    "V.D.Vaart":   "AJAX",       "V.D.Meyde": "AJAX",       "Pasanen":   "AJAX",
    "Mido":        "AJAX",       "Maxwell":   "AJAX",
    # ── PSV EIN ────────────────────────────────────────────────────────────────
    "Zoetebier":   "PSV EIN",    "Bouma":     "PSV EIN",    "Ooijer":    "PSV EIN",
    "Vennegoor":   "PSV EIN",    "Lodewijks": "PSV EIN",    "E.Addo":    "PSV EIN",
    # ── FEYENOORD ──────────────────────────────────────────────────────────────
    "Bosvelt":     "FEYENOORD",  "S.Ono":     "FEYENOORD",
    # ── JUVENTUS ───────────────────────────────────────────────────────────────
    "Ferrara":     "JUVENTUS",   "Conte":     "JUVENTUS",   "Rampulla":  "JUVENTUS",
    "Pessotto":    "JUVENTUS",   "C.Zenoni":  "JUVENTUS",   "Emerson":   "JUVENTUS",
    "Appiah":      "JUVENTUS",
    # ── MILAN (AC Milan) ───────────────────────────────────────────────────────
    "Ambrosini":   "MILAN",      "S.Rossi":   "MILAN",      "Bierhoff":  "MILAN",
    "Kaladze":     "MILAN",      "Serginho":  "MILAN",      "Redondo":   "MILAN",
    "Leonardo":    "MILAN",      "Athirson":  "MILAN",
    # ── INTER ──────────────────────────────────────────────────────────────────
    "C.Zanetti":   "INTER",      "Ventola":   "INTER",      "Ze Elias":  "INTER",
    "Kallon":      "INTER",      "Frey":      "INTER",
    # ── LAZIO ──────────────────────────────────────────────────────────────────
    "Peruzzi":     "LAZIO",      "Negro":     "LAZIO",      "Favalli":   "LAZIO",
    "S.Inzaghi":   "LAZIO",      "Fuser":     "LAZIO",      "Colonnese": "LAZIO",
    # ── ROMA ───────────────────────────────────────────────────────────────────
    "Antonioli":   "ROMA",       "Panucci":   "ROMA",       "A.Cassano": "ROMA",
    "Pelizzoli":   "ROMA",       "Aldair":    "ROMA",       "Zebina":    "ROMA",
    # ── FIORENTINA (FIORENT) ───────────────────────────────────────────────────
    "Di Livio":    "FIORENT",    "Chiesa":    "FIORENT",    "Adani":     "FIORENT",
    "Torricelli":  "FIORENT",    "Maresca":   "FIORENT",
    # ── PARMA ──────────────────────────────────────────────────────────────────
    "Di Vaio":     "PARMA",      "Benarrivo": "PARMA",      "D.Baggio":  "PARMA",
    "H.Nakata":    "PARMA",      "Vamberto":  "PARMA",
    # ── BAYERN ─────────────────────────────────────────────────────────────────
    "Jeremies":    "BAYERN",     "Effenberg": "BAYERN",     "Tarnat":    "BAYERN",
    "Sagnol":      "BAYERN",     "Kuffour":   "BAYERN",
    # ── BAYER LEVERKUSEN (B.LEVER) ────────────────────────────────────────────
    "Kirsten":     "B.LEVER",    "Brdaric":   "B.LEVER",    "Ze Roberto":"B.LEVER",
    # ── BORUSSIA DORTMUND (B.DORTMUND) ────────────────────────────────────────
    "Kohler":      "B.DORTMUND", "Metzelder": "B.DORTMUND", "Herrlich":  "B.DORTMUND",
    "Bobic":       "B.DORTMUND", "Dede":      "B.DORTMUND", "M.Amoroso": "B.DORTMUND",
    "Smolarek":    "B.DORTMUND",
    # ── GALATASARAY ────────────────────────────────────────────────────────────
    "Umit Karan":  "GALATASARAY","Emrah":     "GALATASARAY","Bulent":    "GALATASARAY",
    "Taffarel":    "GALATASARAY",
    # ── OLYMPIAKOS ─────────────────────────────────────────────────────────────
    "Anatolakis":  "OLYMPIAKOS", "Giannakopo":"OLYMPIAKOS",
    # ── DINAMO KYIV (D.KIEV) ───────────────────────────────────────────────────
    "Bialkevich":  "D.KIEV",
    # ── BOCA JUNIORS (BOCA JUNIOR) ────────────────────────────────────────────
    "Riquelme":    "BOCA JUNIOR","Schelotto": "BOCA JUNIOR","Delgado":   "BOCA JUNIOR",
    "Schiavi":     "BOCA JUNIOR","Burdisso":  "BOCA JUNIOR","Battaglia": "BOCA JUNIOR",
    "Takahara":    "BOCA JUNIOR",
}

# Slot-range fallback teams: if a player isn't in PLAYER_CLUB_MAP,
# assign based on their position in the SELECT.BIN name block.
# These ranges are approximate and cover the major national groupings.
CLUB_FALLBACK_RANGES = [
    (0,   49,  "ENGLAND"),         # British/English Premier League pool
    (50,  67,  "DEPORTIVO"),       # Portuguese-speaking players in Spain
    (68,  95,  "SPAIN"),           # Spanish club players
    (96,  171, "FRANCE"),          # French club players
    (172, 207, "NETHERLANDS"),     # Dutch/Belgian club players
    (208, 221, "NETHERLANDS"),     # Dutch/Italian transition
    (222, 299, "ITALY"),           # Italian Serie A
    (300, 348, "EUROPE"),          # Scandinavian/Eastern European
    (349, 432, "SOUTH AMERICA"),   # South American + Japanese
    (433, 461, "EUROPE"),          # Mixed international
]


def decode_we_record(b):
    """Decode a 12-byte bit-packed WE2002 player stat record.

    Format reverse-engineered from thyddralisk/WE2002-editor-2.0 (C++ source).
    All stats are in range 12–19.  Height in cm (148–211).  Age 15–46.
    Returns a dict, or None if the bytes look like padding/garbage.
    """
    c = [v & 0xFF for v in b[:12]]
    if all(x == 0x00 for x in c) or all(x == 0xFF for x in c):
        return None
    pos   = c[0] & 0x07
    h     = 148 + ((c[2] >> 4) & 0x0F) + ((c[3] << 4) & 0x30)
    build = (c[4] >> 2) & 0x07
    age   = 15  + ((c[4] >> 5) & 0x07) + ((c[5] << 3) & 0x18)
    ref   = 12  + ((c[5] >> 2) & 0x07)                          # reflexes
    str_  = 12  + ((c[5] >> 6) & 0x03) + ((c[6] << 2) & 0x04)  # strength
    sta   = 12  + ((c[6] >> 1) & 0x07)                          # stamina
    drb   = 12  + ((c[6] >> 4) & 0x07)                          # dribbling
    spd   = 12  + ((c[6] >> 7) & 0x01) + ((c[7] << 1) & 0x06)  # speed
    acc   = 12  + ((c[7] >> 2) & 0x07)                          # acceleration
    atk   = 12  + ((c[7] >> 5) & 0x07)                          # attack
    def_  = 12  + (c[8] & 0x07)                                  # defense
    sht_p = 12  + ((c[8] >> 3) & 0x07)                          # shot power
    sht_a = 12  + ((c[8] >> 6) & 0x03) + ((c[9] << 2) & 0x04)  # shot accuracy
    pas   = 12  + ((c[9] >> 1) & 0x07)                          # passing
    tec   = 12  + ((c[9] >> 4) & 0x07)                          # technique
    head  = 12  + ((c[9] >> 7) & 0x01) + ((c[10] << 1) & 0x06) # heading
    jump  = 12  + ((c[10] >> 2) & 0x07)                         # jump
    curve = 12  + ((c[10] >> 5) & 0x07)                         # curve/effect
    aggr  = 12  + (c[11] & 0x07)                                 # aggression
    if h < 148 or h > 211 or age > 40:
        return None
    return {
        "position":   POSITION_LABELS.get(pos, "?"),
        "category":   POSITION_CATEGORY.get(pos, "?"),
        "height":     h,
        "build":      build,
        "age":        age,
        "reflexes":   ref,
        "strength":   str_,
        "stamina":    sta,
        "dribbling":  drb,
        "speed":      spd,
        "acceleration": acc,
        "attack":     atk,
        "defense":    def_,
        "shot_power": sht_p,
        "shot_acc":   sht_a,
        "passing":    pas,
        "technique":  tec,
        "heading":    head,
        "jump":       jump,
        "curve":      curve,
        "aggression": aggr,
    }


def load_nat_stats(select_bytes):
    """Read SELECT_STATS_NAT_COUNT × 12-byte records."""
    records = []
    for i in range(SELECT_STATS_NAT_COUNT):
        off = SELECT_STATS_NAT_OFFSET + i * 12
        rec = decode_we_record(select_bytes[off:off + 12])
        records.append(rec)
    return records


def load_club_stats(select_bytes):
    """Read SELECT_STATS_CLUB_COUNT × 12-byte records."""
    records = []
    for i in range(SELECT_STATS_CLUB_COUNT):
        off = SELECT_STATS_CLUB_OFFSET + i * 12
        rec = decode_we_record(select_bytes[off:off + 12])
        records.append(rec)
    return records


def load_nat_costs():
    """Read ML costs from SELECT4.BIN for all 1449 nat-team players.

    Two separate arrays:
      - Regular teams (nat_idx 0-1241):  offset 0x2174, 1242 bytes
      - Special teams (nat_idx 1242-1448): offset 0x2622, 207 bytes
        (World Stars I/II + Classic England/France/Netherlands/Italy/Germany/Brazil/Argentina)
    """
    total = SELECT4_SPECIAL_START + 207  # 1449
    try:
        data = SELECT4_PATH.read_bytes()
        costs = []
        # Regular teams
        for i in range(SELECT4_COSTS_COUNT):
            val = data[SELECT4_COSTS_OFFSET + i]
            costs.append(val if val > 0 else None)
        # Special teams
        for i in range(207):
            val = data[SELECT4_SPECIAL_COSTS_OFFSET + i]
            costs.append(val if val > 0 else None)
        return costs
    except Exception:
        return [None] * total


def assign_club_team(slot_idx, name):
    """Look up club team for a SELECT.BIN player."""
    if name in PLAYER_CLUB_MAP:
        return PLAYER_CLUB_MAP[name]
    # Fallback by slot range
    for lo, hi, default in CLUB_FALLBACK_RANGES:
        if lo <= slot_idx <= hi:
            return default
    return "League Teams"


def extract_club_players(select_bytes, club_stat_records, nat_cost_by_name=None):
    """Extract 462 club/ML players from SELECT.BIN name block with stats."""
    players = []
    for slot in range(SELECT_BLOCK_COUNT):
        off = SELECT_BLOCK_OFFSET + slot * SELECT_SLOT_SIZE
        chunk = select_bytes[off:off + SELECT_SLOT_SIZE]
        nul = chunk.find(0)
        name_bytes = chunk[:nul] if nul >= 0 else chunk
        try:
            name = name_bytes.decode("ascii").strip()
        except UnicodeDecodeError:
            name = ""
        if not name or not name[0].isalpha() or len(name) < 2:
            continue
        team    = assign_club_team(slot, name)
        stats   = club_stat_records[slot] if slot < len(club_stat_records) else None
        ml_cost = nat_cost_by_name.get(name) if nat_cost_by_name else None
        players.append(_make_player(10000 + slot, name, team, stats, ml_cost))
    return players

def _make_player(pid, name, team, stats, ml_cost=None):
    """Build a player dict from decoded stat record (or None for all-null stats)."""
    if stats:
        return {
            "id":           pid,
            "name":         name,
            "team":         team,
            "position":     stats["position"],
            "category":     stats["category"],
            "height":       stats["height"],
            "age":          stats["age"],
            "ml_cost":      ml_cost,
            # In-game stat names (all 12–19)
            "offense":      stats["attack"],
            "defense":      stats["defense"],
            "body_balance": stats["strength"],
            "stamina":      stats["stamina"],
            "speed":        stats["speed"],
            "acceleration": stats["acceleration"],
            "response":     stats["reflexes"],
            "jump_power":   stats["jump"],
            "head_acc":     stats["heading"],
            "technique":    stats["technique"],
            "pass_acc":     stats["passing"],
            "shoot_power":  stats["shot_power"],
            "shoot_acc":    stats["shot_acc"],
            "dribble":      stats["dribbling"],
            "curve":        stats["curve"],
        }
    return {
        "id":           pid,
        "name":         name,
        "team":         team,
        "position":     None,
        "category":     None,
        "height":       None,
        "age":          None,
        "ml_cost":      ml_cost,
        "offense":      None,
        "defense":      None,
        "body_balance": None,
        "stamina":      None,
        "speed":        None,
        "acceleration": None,
        "response":     None,
        "jump_power":   None,
        "head_acc":     None,
        "technique":    None,
        "pass_acc":     None,
        "shoot_power":  None,
        "shoot_acc":    None,
        "dribble":      None,
        "curve":        None,
    }


diag_lines = []

def log(msg):
    print(msg)
    diag_lines.append(msg)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE A — Name extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_names(exe_bytes):
    """Extract all 10-byte player name slots from the executable."""
    results = []
    for i in range(NAME_BLOCK_SLOTS):
        start = NAME_BLOCK_OFFSET + i * NAME_SLOT_SIZE
        raw = exe_bytes[start:start + NAME_SLOT_SIZE]
        nul = raw.find(0)
        chunk = raw[:nul] if nul >= 0 else raw
        try:
            s = chunk.decode("ascii").strip()
            if s and s[0].isalpha() and len(s) >= 2:
                results.append((i, s))
        except UnicodeDecodeError:
            pass
    return results


def assign_team(slot_idx):
    team = "Unknown"
    for start, name in TEAM_BOUNDARIES:
        if slot_idx >= start:
            team = name
        else:
            break
    return team


# ─────────────────────────────────────────────────────────────────────────────
# PHASE B — Decompression attempts
# ─────────────────────────────────────────────────────────────────────────────

def try_rle_konami_a(data, skip=16):
    """Konami ctrl-byte RLE variant A."""
    out = bytearray()
    i = skip
    try:
        while i < len(data):
            ctrl = data[i]; i += 1
            if ctrl < 0x80:
                count = ctrl + 1
                out.extend(data[i:i + count]); i += count
            else:
                count = (ctrl & 0x7F) + 3
                if i < len(data):
                    byte = data[i]; i += 1
                    out.extend(bytes([byte] * count))
    except IndexError:
        pass
    return bytes(out)


def try_rle_konami_b(data, skip=16):
    """Konami ctrl-byte RLE variant B."""
    out = bytearray()
    i = skip
    try:
        while i < len(data):
            ctrl = data[i]; i += 1
            if ctrl == 0xFF:
                if i < len(data):
                    out.append(data[i]); i += 1
            elif ctrl < 0x80:
                count = ctrl + 2
                out.extend(data[i:i + count]); i += count
            else:
                count = (ctrl & 0x7F) + 3
                if i < len(data):
                    byte = data[i]; i += 1
                    out.extend(bytes([byte] * count))
    except IndexError:
        pass
    return bytes(out)


def try_lzss(data, skip=16):
    """LZSS with 8-bit flag bitmask."""
    out = bytearray()
    i = skip
    try:
        while i < len(data):
            flags = data[i]; i += 1
            for bit in range(7, -1, -1):
                if not (flags >> bit & 1):
                    if i < len(data):
                        out.append(data[i]); i += 1
                else:
                    if i + 1 >= len(data):
                        break
                    ref = (data[i] << 8) | data[i + 1]; i += 2
                    length = (ref >> 12) + 3
                    offset = ref & 0xFFF
                    if offset == 0:
                        break
                    start_pos = len(out) - offset
                    for k in range(length):
                        src = start_pos + k
                        out.append(out[src] if 0 <= src < len(out) else 0)
    except (IndexError, ValueError):
        pass
    return bytes(out)


def score_decompressed(data, stat_lo=40, stat_hi=99, window=23):
    """Fraction of 23-byte windows with 15+ bytes in the stat range."""
    if len(data) < window:
        return 0.0
    hits = 0
    total = len(data) // window
    for i in range(0, total * window, window):
        chunk = data[i:i + window]
        in_range = sum(1 for b in chunk if stat_lo <= b <= stat_hi)
        if in_range >= 15:
            hits += 1
    return hits / max(1, total)


def find_best_decompressor(raw_data):
    strategies = [
        ("RLE-A skip=16",  lambda d: try_rle_konami_a(d, 16)),
        ("RLE-A skip=8",   lambda d: try_rle_konami_a(d, 8)),
        ("RLE-A skip=4",   lambda d: try_rle_konami_a(d, 4)),
        ("RLE-A skip=0",   lambda d: try_rle_konami_a(d, 0)),
        ("RLE-B skip=16",  lambda d: try_rle_konami_b(d, 16)),
        ("RLE-B skip=8",   lambda d: try_rle_konami_b(d, 8)),
        ("LZSS skip=16",   lambda d: try_lzss(d, 16)),
        ("LZSS skip=8",    lambda d: try_lzss(d, 8)),
        ("raw skip=256",   lambda d: d[256:]),
        ("raw skip=16",    lambda d: d[16:]),
        ("raw no-skip",    lambda d: d),
    ]
    best_score = -1
    best_name = None
    best_data = None
    for name, fn in strategies:
        try:
            dec = fn(raw_data)
            score = score_decompressed(dec)
            log(f"  [{name}] -> {len(dec):,} bytes, stat-score={score:.4f}")
            if score > best_score:
                best_score, best_name, best_data = score, name, dec
        except Exception as e:
            log(f"  [{name}] FAILED: {e}")
    return best_name, best_score, best_data


# ─────────────────────────────────────────────────────────────────────────────
# PHASE C — Record structure discovery
# ─────────────────────────────────────────────────────────────────────────────

CANDIDATE_RECORD_SIZES = [28, 32, 36, 40, 48, 56, 64, 80, 96, 128]


def probe_record_sizes(dec_data):
    log("\n=== Phase C: Probing record sizes ===")
    results = []
    for R in CANDIDATE_RECORD_SIZES:
        for hdr in [0, 4, 8, 16, 32]:
            remaining = len(dec_data) - hdr
            if remaining < R * 100:
                continue
            if remaining % R != 0:
                continue
            count = remaining // R
            if not (300 <= count <= 6000):
                continue
            pos_hits = 0
            height_hits = 0
            for rec in range(min(50, count)):
                rec_start = hdr + rec * R
                if rec_start + 2 >= len(dec_data):
                    break
                b0 = dec_data[rec_start]
                b1 = dec_data[rec_start + 1]
                if b0 in (0, 1, 2, 3):
                    pos_hits += 1
                if 155 <= b1 <= 210:
                    height_hits += 1
            sample = min(50, count)
            pos_frac = pos_hits / sample if sample > 0 else 0
            hgt_frac = height_hits / sample if sample > 0 else 0
            score = pos_frac + hgt_frac
            log(f"  R={R:3d} hdr={hdr:2d} -> count={count:4d}  pos={pos_frac:.2f}  hgt={hgt_frac:.2f}")
            results.append((R, hdr, count, pos_frac, hgt_frac, score))
    results.sort(key=lambda x: -x[5])
    return results


def probe_field_offsets(dec_data, record_size, header_offset, count):
    log(f"\n=== Phase C: Field scan (record_size={record_size}, header={header_offset}) ===")
    field_stats = []
    for off in range(record_size):
        values = []
        for rec in range(min(300, count)):
            idx = header_offset + rec * record_size + off
            if idx < len(dec_data):
                values.append(dec_data[idx])
        if not values:
            continue
        mean = sum(values) / len(values)
        stddev = statistics.stdev(values) if len(values) > 1 else 0
        stat_frac = sum(1 for v in values if 40 <= v <= 99) / len(values)
        field_stats.append((off, mean, stddev, stat_frac))
    field_stats.sort(key=lambda x: -x[3])
    log("  offset  mean  stddev  stat_frac")
    for off, mean, stddev, sf in field_stats[:20]:
        log(f"  [{off:3d}]  {mean:5.1f}  {stddev:6.2f}   {sf:.3f}")
    return field_stats


# Standard WE-series field layout (byte offset within record, byte count)
WE_FIELD_LAYOUT = [
    ("position",   0, 1),
    ("height",     1, 1),
    ("weight",     2, 1),
    ("attack",     4, 1),
    ("defense",    5, 1),
    ("speed",      6, 1),
    ("shooting",   7, 1),
    ("passing",    8, 1),
    ("dribbling",  9, 1),
    ("stamina",   10, 1),
    ("ml_cost",   12, 2),   # 2-byte little-endian Masters League cost
]


def extract_record_stats(dec_data, record_size, header_offset, count, field_stats):
    records = []
    # Check if standard WE layout fits (byte 0 should be position 0-3)
    pos_vals = [
        dec_data[header_offset + r * record_size + 0]
        for r in range(min(100, count))
        if header_offset + r * record_size < len(dec_data)
    ]
    pos_in_range = sum(1 for v in pos_vals if v in (0, 1, 2, 3)) / max(1, len(pos_vals))
    layout = WE_FIELD_LAYOUT if pos_in_range >= 0.5 else []

    if not layout:
        log("  Standard WE layout doesn't fit - trying auto-detect")
        stat_fields = ["attack", "defense", "speed", "shooting", "passing", "dribbling", "stamina"]
        high_frac = [(off, sf) for off, mean, stddev, sf in field_stats if sf >= 0.50]
        layout = [(stat_fields[i], off, 1) for i, (off, sf) in enumerate(high_frac[:len(stat_fields)])]

    log(f"  Using layout: {[f for f,_,_ in layout]}")

    for rec in range(count):
        base = header_offset + rec * record_size
        if base + record_size > len(dec_data):
            break
        r = {}
        for field_name, off, size in layout:
            abs_off = base + off
            if abs_off + size > len(dec_data):
                r[field_name] = None
                continue
            if size == 1:
                r[field_name] = dec_data[abs_off]
            elif size == 2:
                r[field_name] = struct.unpack_from("<H", dec_data, abs_off)[0]
        records.append(r)
    return records


# ─────────────────────────────────────────────────────────────────────────────
# PHASE D — Build player objects
# ─────────────────────────────────────────────────────────────────────────────

def build_players(names_with_slots, nat_stat_records, nat_costs=None):
    """Build national-team player list from SLPM name slots + SELECT.BIN nat stat records."""
    players = []
    for slot_idx, name in names_with_slots:
        if slot_idx < FIRST_REAL_SLOT:
            continue
        team     = assign_team(slot_idx)
        nat_idx  = slot_idx - FIRST_REAL_SLOT          # index into nat stat records
        stats    = nat_stat_records[nat_idx] if nat_idx < len(nat_stat_records) else None
        ml_cost  = nat_costs[nat_idx] if nat_costs and nat_idx < len(nat_costs) else None
        players.append(_make_player(slot_idx, name, team, stats, ml_cost))
    return players


# ─────────────────────────────────────────────────────────────────────────────
# HTML template (self-contained, players embedded as JS literal)
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Searchenko 1.0</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh}
header{background:#161b22;border-bottom:1px solid #30363d;padding:.75rem 1rem;display:flex;align-items:center;gap:.75rem}
header h1{font-size:1.1rem;font-weight:700;color:#58a6ff}
header .sub{font-size:.8rem;color:#8b949e}
.main{max-width:1400px;margin:0 auto;padding:1rem}
footer{text-align:center;padding:2rem 1rem;font-size:.78rem;color:#6e7681;border-top:1px solid #21262d;margin-top:2rem}
.top-bar{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:.75rem;align-items:center}
.top-bar input[type=search]{flex:1 1 200px;padding:.45rem .7rem;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#e6edf3;font-size:.9rem}
.top-bar select{padding:.45rem .7rem;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#e6edf3;font-size:.85rem;flex:0 1 160px}
.top-bar input[type=search]:focus,.top-bar select:focus{outline:none;border-color:#58a6ff}
.filter-toggle{background:#1f2937;border:1px solid #30363d;border-radius:6px;padding:.4rem .75rem;color:#8b949e;cursor:pointer;font-size:.82rem;white-space:nowrap}
.filter-toggle:hover{color:#e6edf3}
#filter-panel{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:.75rem 1rem;margin-bottom:.75rem;display:none}
#filter-panel.open{display:block}
#filter-panel h3{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:#8b949e;margin-bottom:.5rem}
.slider-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.5rem .75rem}
.slider-row{display:flex;align-items:center;gap:.4rem;font-size:.8rem}
.slider-row label{width:5rem;color:#8b949e;white-space:nowrap}
.slider-row input[type=range]{flex:1;accent-color:#58a6ff}
.slider-row output{width:2.5rem;text-align:right;color:#e6edf3;font-size:.78rem}
.reset-btn{margin-top:.5rem;padding:.3rem .7rem;background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:5px;cursor:pointer;font-size:.8rem}
.reset-btn:hover{border-color:#58a6ff;color:#58a6ff}
.sort-bar{display:flex;align-items:center;flex-wrap:wrap;gap:.35rem;margin-bottom:.75rem;font-size:.8rem}
.sort-bar>span{color:#8b949e;margin-right:.15rem}
.sort-btn{background:#1f2937;border:1px solid #30363d;color:#8b949e;padding:.25rem .55rem;border-radius:5px;cursor:pointer;font-size:.78rem;white-space:nowrap}
.sort-btn:hover{border-color:#58a6ff;color:#e6edf3}
.sort-btn.active{background:#1d4ed8;border-color:#3b82f6;color:#fff}
.sort-dir{font-size:.65rem;margin-left:.15rem}
.result-count{font-size:.78rem;color:#8b949e;margin-bottom:.5rem}
#results{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:.65rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:.75rem;transition:border-color .15s}
.card:hover{border-color:#58a6ff}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:.4rem;margin-bottom:.15rem}
.card-name{font-size:1rem;font-weight:600;color:#e6edf3;line-height:1.2}
.pos-badge{padding:.15rem .4rem;border-radius:4px;font-size:.7rem;font-weight:700;white-space:nowrap;flex-shrink:0}
.cost-badge{padding:.15rem .4rem;border-radius:4px;font-size:.7rem;font-weight:700;white-space:nowrap;flex-shrink:0;background:#f6c90e;color:#0d1117}
.pos-GK{background:#7c3aed;color:#fff}
.pos-CB,.pos-SB{background:#1d4ed8;color:#fff}
.pos-DH,.pos-SH,.pos-OH{background:#059669;color:#fff}
.pos-CF,.pos-WG{background:#dc2626;color:#fff}
.pos-q{background:#374151;color:#9ca3af}
.card-team{font-size:.75rem;color:#8b949e;margin-bottom:.35rem}
.card-meta{display:flex;gap:.5rem;font-size:.73rem;color:#6e7681;margin-bottom:.45rem}
.meta-pill{background:#1f2937;padding:.1rem .35rem;border-radius:3px}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:repeat(8,auto);grid-auto-flow:column;gap:.2rem .4rem}
.stat-row{display:flex;align-items:center;gap:.3rem}
.stat-label{width:2.8rem;font-size:.7rem;color:#8b949e;text-align:right}
.bar-bg{flex:1;height:5px;background:#21262d;border-radius:3px;overflow:hidden}
.bar-fill{height:100%;border-radius:3px;background:linear-gradient(to right,#e53e3e,#f6c90e)}
.stat-num{width:1.8rem;font-size:.7rem;text-align:right;color:#e6edf3}
.stat-num.hi{color:#f6c90e;font-weight:600}
.no-stats{font-size:.75rem;color:#6e7681;font-style:italic;margin-top:.25rem}
@media(max-width:640px){
  header{flex-direction:column;align-items:flex-start;gap:.3rem}
  header .sub{font-size:.75rem}
  .main{padding:.5rem}
  .top-bar{flex-direction:column;align-items:stretch}
  .top-bar input[type=search],.top-bar select,.filter-toggle{width:100%;flex:1 1 auto;font-size:.95rem}
  .top-bar select{flex:1 1 auto}
  #filter-panel{padding:.6rem .5rem}
  .slider-grid{grid-template-columns:1fr}
  .slider-row{gap:.5rem}
  .slider-row label{width:6.5rem;font-size:.82rem}
  .slider-row input[type=range]{min-width:0}
  .sort-bar{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;padding-bottom:.35rem;gap:.3rem;scrollbar-width:none}
  .sort-bar::-webkit-scrollbar{display:none}
  .sort-btn,.sort-bar>span{flex-shrink:0}
  #results{grid-template-columns:1fr;gap:.5rem}
  .card{padding:.65rem}
  .card-name{font-size:.95rem}
  .stat-grid{grid-template-columns:1fr 1fr;grid-template-rows:repeat(8,auto);grid-auto-flow:column}
  .bar-bg{height:6px}
}
</style>
</head>
<body>
<header>
  <h1>Searchenko 1.0</h1>
  <span class="sub">Winning Eleven 2002 &mdash; PlayStation 1 &mdash; National teams + Club teams</span>
</header>
<div class="main">

<div class="top-bar">
  <input type="search" id="q" placeholder="Search player name&hellip;" oninput="scheduleFilter(250)" autocomplete="off">
  <select id="teamSel" onchange="scheduleFilter()"><option value="">All Teams</option></select>
  <select id="posSel" onchange="scheduleFilter()">
    <option value="">All Positions</option>
    <option value="GK">GK &mdash; Goalkeeper</option>
    <option value="CB">CB &mdash; Centre Back</option>
    <option value="SB">SB &mdash; Side Back</option>
    <option value="DH">DH &mdash; Defensive Mid</option>
    <option value="SH">SH &mdash; Side Mid</option>
    <option value="OH">OH &mdash; Offensive Mid</option>
    <option value="CF">CF &mdash; Centre Forward</option>
    <option value="WG">WG &mdash; Winger</option>
  </select>
  <button class="filter-toggle" id="filterToggle" onclick="toggleFilters()">&#9650; Stat Filters</button>
</div>

<div id="filter-panel" class="open">
  <h3>Minimum values &mdash; drag to filter</h3>
  <div class="slider-grid" id="sliderGrid"></div>
  <button class="reset-btn" onclick="resetFilters()">Reset all filters</button>
</div>

<div class="sort-bar">
  <span>Sort:</span>
  <button class="sort-btn active" id="s-name"         onclick="setSort('name')">Name <span class="sort-dir" id="d-name">&#9650;</span></button>
  <button class="sort-btn"        id="s-team"         onclick="setSort('team')">Team</button>
  <button class="sort-btn"        id="s-offense"      onclick="setSort('offense')">OFF</button>
  <button class="sort-btn"        id="s-defense"      onclick="setSort('defense')">DEF</button>
  <button class="sort-btn"        id="s-body_balance" onclick="setSort('body_balance')">BAL</button>
  <button class="sort-btn"        id="s-stamina"      onclick="setSort('stamina')">STA</button>
  <button class="sort-btn"        id="s-speed"        onclick="setSort('speed')">SPD</button>
  <button class="sort-btn"        id="s-acceleration" onclick="setSort('acceleration')">ACC</button>
  <button class="sort-btn"        id="s-response"     onclick="setSort('response')">RES</button>
  <button class="sort-btn"        id="s-jump_power"   onclick="setSort('jump_power')">JMP</button>
  <button class="sort-btn"        id="s-head_acc"     onclick="setSort('head_acc')">HDR</button>
  <button class="sort-btn"        id="s-technique"    onclick="setSort('technique')">TEC</button>
  <button class="sort-btn"        id="s-pass_acc"     onclick="setSort('pass_acc')">PAS</button>
  <button class="sort-btn"        id="s-shoot_power"  onclick="setSort('shoot_power')">SHP</button>
  <button class="sort-btn"        id="s-shoot_acc"    onclick="setSort('shoot_acc')">SHA</button>
  <button class="sort-btn"        id="s-dribble"      onclick="setSort('dribble')">DRB</button>
  <button class="sort-btn"        id="s-curve"        onclick="setSort('curve')">CRV</button>
  <button class="sort-btn"        id="s-height"       onclick="setSort('height')">HGT</button>
  <button class="sort-btn"        id="s-age"          onclick="setSort('age')">Age</button>
  <button class="sort-btn"        id="s-ml_cost"      onclick="setSort('ml_cost')">Cost</button>
</div>

<div class="result-count" id="resultCount"></div>
<div id="results"></div>
</div>

<script>
const PLAYERS = __PLAYERS_JSON__;
let _filterTimer=null, _renderFrame=null;
let _currentList=[], _renderedCount=0, _scrollObserver=null;
const PAGE=60;
const STAT_FIELDS = ["offense","defense","body_balance","stamina","speed","acceleration","response","jump_power","head_acc","technique","pass_acc","shoot_power","shoot_acc","dribble","curve"];
const STAT_LABELS = {offense:"OFF",defense:"DEF",body_balance:"BAL",stamina:"STA",speed:"SPD",acceleration:"ACC",response:"RES",jump_power:"JMP",head_acc:"HDR",technique:"TEC",pass_acc:"PAS",shoot_power:"SHP",shoot_acc:"SHA",dribble:"DRB",curve:"CRV"};
const STAT_FULL  = {offense:"Offense",defense:"Defense",body_balance:"Body Balance",stamina:"Stamina",speed:"Speed",acceleration:"Acceleration",response:"Response",jump_power:"Jump Power",head_acc:"Head Accuracy",technique:"Technique",pass_acc:"Pass Accuracy",shoot_power:"Shoot Power",shoot_acc:"Shoot Accuracy",dribble:"Dribble",curve:"Curve"};
const SLIDER_DEFS = [
  {key:"offense",      label:"Offense",      min:12, max:19},
  {key:"defense",      label:"Defense",      min:12, max:19},
  {key:"body_balance", label:"Body Balance", min:12, max:19},
  {key:"stamina",      label:"Stamina",      min:12, max:19},
  {key:"speed",        label:"Speed",        min:12, max:19},
  {key:"acceleration", label:"Acceleration", min:12, max:19},
  {key:"response",     label:"Response",     min:12, max:19},
  {key:"jump_power",   label:"Jump Power",   min:12, max:19},
  {key:"head_acc",     label:"Head Acc.",    min:12, max:19},
  {key:"technique",    label:"Technique",    min:12, max:19},
  {key:"pass_acc",     label:"Pass Acc.",    min:12, max:19},
  {key:"shoot_power",  label:"Shoot Power",  min:12, max:19},
  {key:"shoot_acc",    label:"Shoot Acc.",   min:12, max:19},
  {key:"dribble",      label:"Dribble",      min:12, max:19},
  {key:"curve",        label:"Curve",        min:12, max:19},
  {key:"height",       label:"Height cm",    min:158, max:205},
  {key:"age",          label:"Max Age",      min:15,  max:40, isMax:true},
  {key:"ml_cost",      label:"Max Cost",     min:0,   max:60, isMax:true},
];
let sortKey="name", sortDir=1;
const sliderValues={};
SLIDER_DEFS.forEach(d => sliderValues[d.key] = d.isMax ? d.max : d.min);

(function init(){
  const teams=[...new Set(PLAYERS.map(p=>p.team))].filter(Boolean).sort();
  const sel=document.getElementById("teamSel");
  teams.forEach(t=>{const o=document.createElement("option");o.value=t;o.textContent=t;sel.appendChild(o);});
  const grid=document.getElementById("sliderGrid");
  SLIDER_DEFS.forEach(d=>{
    const hasData=PLAYERS.some(p=>p[d.key]!==null&&p[d.key]!==undefined);
    if(!hasData) return;
    const row=document.createElement("div"); row.className="slider-row";
    const lbl=document.createElement("label"); lbl.htmlFor="sl-"+d.key; lbl.textContent=d.label;
    const inp=document.createElement("input"); inp.type="range"; inp.id="sl-"+d.key;
    inp.min=d.min; inp.max=d.max; inp.value=d.isMax?d.max:d.min;
    const out=document.createElement("output"); out.id="out-"+d.key; out.textContent=d.isMax?d.max:d.min;
    inp.addEventListener("input",()=>{sliderValues[d.key]=+inp.value;out.textContent=inp.value;scheduleFilter();});
    row.appendChild(lbl); row.appendChild(inp); row.appendChild(out); grid.appendChild(row);
  });
  applyFilters();
})();

function toggleFilters(){
  const p=document.getElementById("filter-panel");
  const btn=document.getElementById("filterToggle");
  p.classList.toggle("open");
  btn.textContent=p.classList.contains("open")?"\\u25b2 Stat Filters":"\\u25bc Stat Filters";
}
function resetFilters(){
  SLIDER_DEFS.forEach(d=>{
    const inp=document.getElementById("sl-"+d.key);
    const out=document.getElementById("out-"+d.key);
    if(!inp) return;
    const val=d.isMax?d.max:d.min;
    inp.value=val; if(out) out.textContent=val; sliderValues[d.key]=val;
  });
  applyFilters();
}
function scheduleFilter(delay){
  document.getElementById("resultCount").textContent="Filtering\u2026";
  if(_filterTimer) clearTimeout(_filterTimer);
  _filterTimer=setTimeout(applyFilters, delay||120);
}
function applyFilters(){
  _filterTimer=null;
  const q=document.getElementById("q").value.trim().toLowerCase();
  const team=document.getElementById("teamSel").value;
  const pos=document.getElementById("posSel").value;
  let filtered=PLAYERS.filter(p=>{
    if(q&&!p.name.toLowerCase().includes(q)) return false;
    if(team&&p.team!==team) return false;
    if(pos&&p.position!==pos&&p.category!==pos) return false;
    for(const d of SLIDER_DEFS){
      const v=sliderValues[d.key]; const pv=p[d.key];
      if(d.isMax){if(v<d.max&&pv!=null&&pv>v) return false;}
      else{if(v>d.min&&(pv==null||pv<v)) return false;}
    }
    return true;
  });
  filtered.sort((a,b)=>{
    let va=a[sortKey],vb=b[sortKey];
    const nil=sortDir>0?-Infinity:Infinity;
    if(va==null) va=nil; if(vb==null) vb=nil;
    if(typeof va==="string") return sortDir*va.localeCompare(vb);
    return sortDir*(va-vb);
  });
  const countEl=document.getElementById("resultCount");
  countEl.textContent=filtered.length.toLocaleString()+" of "+PLAYERS.length.toLocaleString()+" players";
  render(filtered);
}
function setSort(key){
  if(sortKey===key){sortDir=-sortDir;}
  else{sortKey=key; sortDir=(key==="name"||key==="team")?1:-1;}
  document.querySelectorAll(".sort-btn").forEach(b=>b.classList.remove("active"));
  const btn=document.getElementById("s-"+key); if(btn) btn.classList.add("active");
  document.querySelectorAll(".sort-dir").forEach(s=>s.textContent="");
  const dir=document.getElementById("d-"+key); if(dir) dir.textContent=sortDir>0?"\\u25b2":"\\u25bc";
  applyFilters();
}
function render(players){
  if(_renderFrame) cancelAnimationFrame(_renderFrame);
  if(_scrollObserver) _scrollObserver.disconnect();
  _currentList=players;
  _renderedCount=0;
  _renderFrame=requestAnimationFrame(()=>{
    _renderFrame=null;
    const container=document.getElementById("results");
    container.innerHTML="";
    const sentinel=document.createElement("div");
    sentinel.id="scroll-sentinel";
    container.appendChild(sentinel);
    appendCards();
    _scrollObserver=new IntersectionObserver(entries=>{
      if(entries[0].isIntersecting) appendCards();
    },{rootMargin:"400px"});
    _scrollObserver.observe(sentinel);
  });
}
function appendCards(){
  if(_renderedCount>=_currentList.length){
    if(_scrollObserver){_scrollObserver.disconnect();_scrollObserver=null;}
    return;
  }
  const container=document.getElementById("results");
  const sentinel=document.getElementById("scroll-sentinel");
  const frag=document.createDocumentFragment();
  const end=Math.min(_renderedCount+PAGE,_currentList.length);
  for(let i=_renderedCount;i<end;i++) frag.appendChild(makeCard(_currentList[i]));
  container.insertBefore(frag,sentinel);
  _renderedCount=end;
  if(_renderedCount>=_currentList.length&&_scrollObserver){
    _scrollObserver.disconnect();_scrollObserver=null;
  }
}
function makeCard(p){
  const card=document.createElement("div"); card.className="card";
  const pos=p.position||"?";
  const posCls=["GK","CB","SB","DH","SH","OH","CF","WG"].includes(pos)?"pos-"+pos:"pos-q";
  const metaParts=[];
  if(p.height) metaParts.push(p.height+" cm");
  if(p.age)    metaParts.push("age "+p.age);
  const costBadge=p.ml_cost!=null?"<span class=\\"cost-badge\\">"+p.ml_cost+"pts</span>":"";
  const hasStats=STAT_FIELDS.some(f=>p[f]!=null);
  card.innerHTML=
    "<div class=\\"card-top\\"><div class=\\"card-name\\">"+esc(p.name)+"</div>"+
    "<div style=\\"display:flex;gap:.3rem;flex-shrink:0\\"><span class=\\"pos-badge "+posCls+"\\">"+esc(pos)+"</span>"+costBadge+"</div></div>"+
    "<div class=\\"card-team\\">"+esc(p.team||"Unknown")+"</div>"+
    (metaParts.length?"<div class=\\"card-meta\\">"+metaParts.map(m=>"<span class=\\"meta-pill\\">"+m+"</span>").join("")+"</div>":"")+
    (hasStats?renderStats(p):"<div class=\\"no-stats\\">Stats not decoded</div>");
  return card;
}
function renderStats(p){
  const rows=STAT_FIELDS.map(f=>{
    const v=p[f]; if(v==null) return "";
    const pct=((v-12)/7*100).toFixed(1);
    const numCls=v>=17?" hi":"";
    return "<div class=\\"stat-row\\"><span class=\\"stat-label\\" title=\\""+STAT_FULL[f]+"\\">"+STAT_LABELS[f]+"</span>"+
           "<div class=\\"bar-bg\\"><div class=\\"bar-fill\\" style=\\"width:"+pct+"%\\"></div></div>"+
           "<span class=\\"stat-num"+numCls+"\\">"+v+"</span></div>";
  }).join("");
  return "<div class=\\"stat-grid\\">"+rows+"</div>";
}
function esc(s){
  if(!s) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
</script>
<footer>By Micha + Claude 2026</footer>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log("=== WE2002 Parser ===\n")

    log(f"Reading {EXE_PATH} ...")
    exe_bytes = EXE_PATH.read_bytes()

    # ── Phase A — Names ───────────────────────────────────────────────────────
    log("\n=== Phase A: Extracting player names ===")
    names_with_slots = extract_names(exe_bytes)
    valid_names = [(i, n) for i, n in names_with_slots if i >= FIRST_REAL_SLOT]
    log(f"  Found {len(names_with_slots)} name slots total")
    log(f"  Valid player names (slot >= {FIRST_REAL_SLOT}): {len(valid_names)}")
    if valid_names:
        log(f"  First: slot {valid_names[0][0]} = '{valid_names[0][1]}'")
        log(f"  Last:  slot {valid_names[-1][0]} = '{valid_names[-1][1]}'")

    # ── Phase B — Stats from SELECT.BIN ─────────────────────────────────────
    log(f"\n=== Phase B: Loading stats from {SELECT_PATH} ===")
    try:
        select_bytes = SELECT_PATH.read_bytes()
        log(f"  SELECT.BIN size: {len(select_bytes):,} bytes")

        nat_stats  = load_nat_stats(select_bytes)
        club_stats = load_club_stats(select_bytes)

        nat_valid  = sum(1 for r in nat_stats  if r is not None)
        club_valid = sum(1 for r in club_stats if r is not None)
        log(f"  National team stat records: {len(nat_stats)} ({nat_valid} valid)")
        log(f"  Club/ML stat records:       {len(club_stats)} ({club_valid} valid)")
    except Exception as e:
        log(f"  ERROR reading SELECT.BIN: {e}")
        nat_stats, club_stats = [], []

    nat_costs = load_nat_costs()
    log(f"  ML costs loaded:            {sum(1 for c in nat_costs if c)} regular + special (from SELECT4.BIN)")

    # Build name -> ml_cost lookup from national team players (for club player cost carry-over)
    nat_cost_by_name = {}
    for slot_idx, name in valid_names:
        nat_idx = slot_idx - FIRST_REAL_SLOT
        if nat_idx < len(nat_costs) and nat_costs[nat_idx] is not None:
            nat_cost_by_name.setdefault(name, nat_costs[nat_idx])

    # ── Phase C — Club players ────────────────────────────────────────────────
    log(f"\n=== Phase C: Extracting club/ML players ===")
    try:
        club_players = extract_club_players(select_bytes, club_stats, nat_cost_by_name)
        log(f"  Club players extracted: {len(club_players)}")
        log(f"  With stats: {sum(1 for p in club_players if p['offense'] is not None)}")
    except Exception as e:
        log(f"  WARNING: Could not extract club players: {e}")
        club_players = []

    # ── Phase D — Build output ────────────────────────────────────────────────
    log("\n=== Phase D: Building output ===")
    players = build_players(valid_names, nat_stats, nat_costs)
    players.extend(club_players)
    log(f"  National team players: {len(players) - len(club_players)}")
    log(f"  Club players: {len(club_players)}")
    log(f"  Total players: {len(players)}")
    log(f"  Distinct teams: {len(set(p['team'] for p in players))}")
    if players:
        log(f"  First: {players[0]}")

    json_str = json.dumps(players, ensure_ascii=False)
    OUTPUT_JSON.write_text(json_str, encoding="utf-8")
    log(f"\n  Written: {OUTPUT_JSON}  ({len(json_str):,} bytes)")

    html = HTML_TEMPLATE.replace("__PLAYERS_JSON__", json_str)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    log(f"  Written: {OUTPUT_HTML}  ({len(html):,} bytes)")

    # ── Sample stat verification ─────────────────────────────────────────────
    log("\n=== Sample: first England player stats ===")
    # England starts at TEAM_BOUNDARIES slot 80; nat_idx = slot - 12 = 68
    for slot_idx, name in valid_names:
        if assign_team(slot_idx) == "England":
            nat_idx = slot_idx - FIRST_REAL_SLOT
            r = nat_stats[nat_idx] if nat_idx < len(nat_stats) and nat_stats[nat_idx] else None
            if r:
                log(f"  {name}: {r['position']} h={r['height']} age={r['age']} "
                    f"atk={r['attack']} def={r['defense']} spd={r['speed']}")
            break

    DIAGNOSTIC.write_text("\n".join(diag_lines), encoding="utf-8")
    log(f"\n  Diagnostic log: {DIAGNOSTIC}")
    log(f"\nDone! Open {OUTPUT_HTML} in your browser.")


if __name__ == "__main__":
    main()
