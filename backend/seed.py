"""
Run: python seed.py
Creates synthetic NBA data only in an empty, separately provisioned
proppulse_demo PostgreSQL database with PROPPULSE_DEMO_MODE=true.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
import random
from app.database import engine, SessionLocal
from app.models import Base, Player, Prop, FatigueScore, User, Interaction
from passlib.context import CryptContext
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from app.services.demo_guard import (
    DemoOperationRefused, require_demo_dataset, require_demo_environment,
)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_tables():
    require_demo_environment(engine)
    if inspect(engine).get_table_names():
        with Session(bind=engine) as db:
            require_demo_dataset(db)
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

PLAYERS = [
    # (name, team, team_abbr, position, age, jersey)
    ("LeBron James",       "Los Angeles Lakers",       "LAL", "SF",  39, "23"),
    ("Stephen Curry",      "Golden State Warriors",    "GSW", "PG",  36, "30"),
    ("Nikola Jokic",       "Denver Nuggets",           "DEN", "C",   29, "15"),
    ("Luka Doncic",        "Dallas Mavericks",         "DAL", "PG",  25, "77"),
    ("Giannis Antetokounmpo","Milwaukee Bucks",        "MIL", "PF",  29, "34"),
    ("Kevin Durant",       "Phoenix Suns",             "PHX", "SF",  35, "35"),
    ("Joel Embiid",        "Philadelphia 76ers",       "PHI", "C",   30, "21"),
    ("Jayson Tatum",       "Boston Celtics",           "BOS", "SF",  26, "0"),
    ("Damian Lillard",     "Milwaukee Bucks",          "MIL", "PG",  33, "0"),
    ("Anthony Davis",      "Los Angeles Lakers",       "LAL", "C",   31, "3"),
    ("Shai Gilgeous-Alexander","Oklahoma City Thunder","OKC", "PG",  26, "2"),
    ("Donovan Mitchell",   "Cleveland Cavaliers",      "CLE", "SG",  27, "45"),
    ("Devin Booker",       "Phoenix Suns",             "PHX", "SG",  27, "1"),
    ("Tyrese Haliburton",  "Indiana Pacers",           "IND", "PG",  24, "0"),
    ("Ja Morant",          "Memphis Grizzlies",        "MEM", "PG",  24, "12"),
    ("Bam Adebayo",        "Miami Heat",               "MIA", "C",   26, "13"),
    ("Anthony Edwards",    "Minnesota Timberwolves",   "MIN", "SG",  22, "5"),
    ("Cade Cunningham",    "Detroit Pistons",          "DET", "PG",  23, "2"),
    ("Paolo Banchero",     "Orlando Magic",            "ORL", "PF",  21, "5"),
    ("Victor Wembanyama",  "San Antonio Spurs",        "SAS", "C",   20, "1"),
]

PROP_TYPES = {
    "points":   (15.5, 35.5),
    "assists":  (3.5,  10.5),
    "rebounds": (4.5,  13.5),
    "threes":   (1.5,  5.5),
    "blocks":   (0.5,  2.5),
    "steals":   (0.5,  2.5),
    "pra":      (30.5, 55.5),   # points+rebounds+assists
}

OPPONENTS = ["LAL","GSW","BOS","MIA","PHX","DAL","DEN","MIL","PHI","OKC"]

# Fatigue profiles: some players are tired, some fresh
FATIGUE_PROFILES = {
    "LeBron James":             (0.82, True,  4, 38.5, 0.15, 0.3),
    "Stephen Curry":            (0.45, False, 3, 32.1, 0.05, 0.2),
    "Nikola Jokic":             (0.35, False, 3, 31.8, -0.1, 0.15),
    "Luka Doncic":              (0.71, True,  4, 37.2, 0.2,  0.35),
    "Giannis Antetokounmpo":    (0.68, False, 4, 36.4, 0.1,  0.25),
    "Kevin Durant":             (0.55, False, 3, 34.0, 0.08, 0.2),
    "Joel Embiid":              (0.88, True,  5, 34.5, 0.25, 0.4),
    "Jayson Tatum":             (0.62, False, 4, 35.1, 0.12, 0.22),
    "Damian Lillard":           (0.73, True,  4, 34.8, 0.18, 0.28),
    "Anthony Davis":            (0.79, True,  4, 36.2, 0.22, 0.38),
    "Shai Gilgeous-Alexander":  (0.30, False, 3, 33.5, -0.05,0.18),
    "Donovan Mitchell":         (0.48, False, 3, 33.0, 0.02, 0.2),
    "Devin Booker":             (0.52, False, 3, 33.8, 0.06, 0.22),
    "Tyrese Haliburton":        (0.41, False, 3, 32.5, 0.0,  0.19),
    "Ja Morant":                (0.44, False, 3, 31.5, 0.04, 0.21),
    "Bam Adebayo":              (0.38, False, 3, 32.0, -0.02,0.17),
    "Anthony Edwards":          (0.55, False, 4, 34.2, 0.09, 0.23),
    "Cade Cunningham":          (0.47, False, 3, 33.4, 0.03, 0.2),
    "Paolo Banchero":           (0.42, False, 3, 32.8, 0.01, 0.19),
    "Victor Wembanyama":        (0.60, False, 4, 29.5, 0.15, 0.32),
}

def compute_risk_flags(profile):
    fatigue_score, back_to_back, games_7d, mins, mins_trend, volatility = profile
    flags = []
    shap_reasons = []
    if back_to_back:
        flags.append("back-to-back")
        shap_reasons.append("Back-to-back game tonight")
    if games_7d >= 4:
        flags.append("heavy-workload")
        shap_reasons.append(f"Heavy workload: {games_7d} games in 7 days")
    if mins > 35:
        flags.append("high-minutes")
        shap_reasons.append(f"High minutes load: {mins:.1f} avg last 7 days")
    if mins_trend > 0.1:
        flags.append("minutes-trending-up")
        shap_reasons.append("Minutes trending upward this week")
    if volatility > 0.3:
        flags.append("high-volatility")
        shap_reasons.append("High recent performance volatility")
    return flags, shap_reasons

def seed():
    require_demo_environment(engine)
    db = SessionLocal()
    try:
        require_demo_dataset(db)
        if any(db.query(model).first() is not None
               for model in (Player, Prop, FatigueScore, User, Interaction)):
            raise DemoOperationRefused(
                "Demo seed refused: the database is not empty. Existing records "
                "and user selections are preserved; no automatic reset is supported."
            )

        # Seed players
        player_objs = {}
        for name, team, abbr, pos, age, jersey in PLAYERS:
            p = Player(
                name=name, team=team, team_abbr=abbr,
                position=pos, age=age, jersey_number=jersey, sport="NBA"
            )
            db.add(p)
            player_objs[name] = p
        db.commit()
        print(f"Seeded {len(player_objs)} players.")

        # Seed fatigue scores
        for name, player in player_objs.items():
            profile = FATIGUE_PROFILES.get(name, (0.4, False, 3, 30.0, 0.0, 0.2))
            fatigue_score, back_to_back, games_7d, mins, mins_trend, volatility = profile
            flags, shap_reasons = compute_risk_flags(profile)
            fs = FatigueScore(
                player_id=player.id,
                fatigue_score=fatigue_score,
                workload_score=min(1.0, games_7d / 5.0),
                back_to_back=back_to_back,
                games_in_7d=games_7d,
                rolling_minutes_7d=mins,
                minutes_trend=mins_trend,
                performance_volatility=volatility,
                risk_flags=flags,
                shap_reasons=shap_reasons,
            )
            db.add(fs)
        db.commit()
        print("Seeded fatigue scores.")

        # Seed props (4 props per player across different prop types)
        props = []
        game_time_base = datetime.utcnow() + timedelta(hours=6)
        for name, player in player_objs.items():
            prop_type_sample = random.sample(list(PROP_TYPES.keys()), min(4, len(PROP_TYPES)))
            for pt in prop_type_sample:
                lo, hi = PROP_TYPES[pt]
                line = round(random.uniform(lo, hi) * 2) / 2  # round to .5
                movement = round(random.uniform(-1.5, 1.5) * 2) / 2
                line_24h = line - movement
                over_odds = random.choice([-115, -110, -105, +100, +105])
                under_odds = -130 - over_odds if over_odds > 0 else -130 + abs(over_odds + 110)
                opp = random.choice([a for a in OPPONENTS if a != player.team_abbr])
                prop = Prop(
                    player_id=player.id,
                    prop_type=pt,
                    line=line,
                    line_24h_ago=line_24h,
                    over_odds=over_odds,
                    under_odds=under_odds,
                    sportsbook="Demo",
                    odds_event_id=f"demo:{player.id}",
                    odds_sport_key="demo",
                    game_time=game_time_base + timedelta(minutes=random.randint(0, 240)),
                    opponent=opp,
                    is_home=random.choice([True, False]),
                    popularity_count=random.randint(5, 200),
                )
                db.add(prop)
                props.append(prop)
        db.commit()
        print(f"Seeded {len(props)} props.")

        # Seed demo users
        users_data = [
            ("nba_heavy@demo.com", "NBA Heavy Bettor", ["NBA"], ["points","assists"], "demo123"),
            ("nfl_casual@demo.com", "NFL Casual",       ["NFL","NBA"], ["touchdowns"], "demo123"),
            ("new_user@demo.com",   "New User",         [], [],                        "demo123"),
        ]
        user_objs = []
        for email, username, sports, prop_types, password in users_data:
            fav_players = []
            if sports == ["NBA"]:
                fav_players = [player_objs["LeBron James"].id, player_objs["Stephen Curry"].id]
            u = User(
                email=email,
                username=username,
                hashed_password=pwd_ctx.hash(password),
                fav_sports=sports,
                fav_players=[str(pid) for pid in fav_players],
                fav_prop_types=prop_types,
            )
            db.add(u)
            user_objs.append(u)
        db.commit()
        print("Seeded 3 demo users.")

        # Seed interactions for NBA heavy bettor
        nba_user = user_objs[0]
        nba_props = [p for p in props if p.prop_type in ("points", "assists")]
        for prop in random.sample(nba_props, min(30, len(nba_props))):
            action = random.choice(["like", "like", "save", "click", "add_to_slip"])
            db.add(Interaction(user_id=nba_user.id, prop_id=prop.id, action=action))
        db.commit()
        print("Seeded interactions for demo user 1.")

        print("\nDone. Demo credentials:")
        print("  nba_heavy@demo.com  / demo123")
        print("  nfl_casual@demo.com / demo123")
        print("  new_user@demo.com   / demo123")

    finally:
        db.close()

if __name__ == "__main__":
    create_tables()
    seed()
