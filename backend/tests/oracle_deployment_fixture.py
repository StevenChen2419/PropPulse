"""Explicit local rehearsal only: certificates and visibly invented sports rows."""
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID


def certificates():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    root = Path("/proof")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Oracle rehearsal local CA")])
    now = datetime.now(timezone.utc)
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), True).sign(key, hashes.SHA256()))
    (root / "cloudflare_client_ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for kind, usage in (("origin", ExtendedKeyUsageOID.SERVER_AUTH), ("client", ExtendedKeyUsageOID.CLIENT_AUTH)):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.example.com" if kind == "origin" else "Local edge client")])
        cert = (x509.CertificateBuilder().subject_name(leaf).issuer_name(name)
                .public_key(private.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("api.example.com"), x509.DNSName("app.example.com")]), False)
                .add_extension(x509.ExtendedKeyUsage([usage]), False).sign(key, hashes.SHA256()))
        (root / (kind + "_cert.pem")).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (root / (kind + "_key.pem")).write_bytes(private.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    print("Disposable local CA/server/client certificates created; public TLS unverified")


def seed():
    if os.environ.get("ORACLE_REHEARSAL_ACK") != "invented-disposable-oracle-only":
        raise RuntimeError("Explicit local fixture acknowledgement required")
    if any(k.upper().startswith("PG") for k in os.environ if k != "PG_DATABASE"):
        raise RuntimeError("Ambient libpq routing forbidden")
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.engine import make_url
    sys.path.insert(0, "/app")
    from app import models as m
    value = Path("/run/secrets/database_url").read_text().strip()
    url = make_url(value)
    if (url.host != "db" or url.database != "proppulse_rehearsal" or url.username != "pp_owner"
            or url.port != 5432 or url.query):
        raise RuntimeError("Only the new rehearsal database is allowed")
    engine = create_engine(url)
    with engine.connect() as conn:
        if conn.execute(text("select current_database(), current_user")).one() != ("proppulse_rehearsal", "pp_owner"):
            raise RuntimeError("Physical fixture target mismatch")
        if conn.execute(text("select version_num from alembic_version")).scalar() != "20261022_05":
            raise RuntimeError("Migrate explicitly before fixtures")
        if conn.execute(text("select count(*) from props")).scalar():
            raise RuntimeError("Fixture refuses existing sports data")
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    uid = lambda n: str(UUID(int=n))
    with Session(engine) as db, db.begin():
        db.add(m.Player(id=uid(200), name="Invented Oracle rehearsal player", team="Fixture Away", team_abbr="FIX", sport="NBA"))
        db.add(m.Event(id=uid(100), provider="offline_fixture", sport_key="basketball_nba",
                       provider_event_id="fixture-oracle-100", home_team="Fixture Home", away_team="Fixture Away",
                       scheduled_start_at=now + timedelta(days=2)))
        db.flush()
        db.add(m.Prop(id=uid(300), player_id=uid(200), event_id=uid(100), prop_type="points",
                      line=20.5, line_24h_ago=20.5, sportsbook="FanDuel", over_odds=-110, under_odds=-115,
                      odds_sport_key="basketball_nba", odds_event_id="fixture-oracle-100",
                      game_time=now + timedelta(days=2), opponent="Fixture Home", is_home=False, is_active=True))
        db.flush()
        db.add(m.PropBook(prop_id=uid(300), sportsbook="FanDuel", line=20.5, over_odds=-110, under_odds=-115,
                          provider_observed_at=now, ingested_at=now, updated_at=now))
    engine.dispose()
    print(json.dumps({"fixture": "invented isolated rows only", "prop": uid(300)}))


if __name__ == "__main__":
    {"certificates": certificates, "seed": seed}[sys.argv[1]]()
