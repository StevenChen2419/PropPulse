"""Dependency upgrade contracts: isolated multipart app and actual HS256 auth.

No production lifespan, database connection, or external HTTP is used.
"""
import json
import hashlib
import hmac
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.testclient import TestClient
import jwt
from jwt import InvalidTokenError as JWTError
from jwt.algorithms import HMACAlgorithm
from jwt.utils import base64url_encode

from app import auth


class MultipartCompatibilityTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()

        @app.post("/upload")
        async def upload(note: str = Form(), document: UploadFile = File()):
            # Reading/rewinding exercises both the in-memory and disk-backed
            # UploadFile paths used by Starlette's multipart parser.
            content = await document.read()
            await document.seek(0)
            first = await document.read(4)
            return {"filename": document.filename, "type": document.content_type,
                    "size": len(content), "note": note, "first": first.hex(),
                    "spooled": document.file._rolled}

        @app.post("/limited-form")
        async def limited_form(request: Request):
            async with request.form(max_part_size=1024) as form:
                return {"note": form["note"]}

        @app.post("/limited-urlencoded")
        async def limited_urlencoded(request: Request):
            async with request.form(max_fields=2) as form:
                return {"fields": list(form.multi_items())}

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_file_upload_memory_and_spooled_round_trip(self):
        for content, spooled in ((b"\x00\xffab-small", False), (b"\x00\xffab" * 300000, True)):
            with self.subTest(spooled=spooled):
                response = self.client.post("/upload", data={"note": "fixture"},
                    files={"document": ("fixture.bin", content, "application/octet-stream")})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"filename": "fixture.bin",
                    "type": "application/octet-stream", "size": len(content),
                    "note": "fixture", "first": "00ff6162", "spooled": spooled})

    def test_multipart_text_part_limit_rejects_oversized_field(self):
        accepted = self.client.post("/limited-form", files={"note": (None, "a" * 1024)})
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json(), {"note": "a" * 1024})
        rejected = self.client.post("/limited-form", files={"note": (None, "a" * 1025)})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("maximum size", rejected.json()["detail"])

    def test_urlencoded_form_field_limit_is_enforced(self):
        accepted = self.client.post("/limited-urlencoded", data={"first": "one", "second": "two"})
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json(), {"fields": [["first", "one"], ["second", "two"]]})
        rejected = self.client.post("/limited-urlencoded",
            data={"first": "one", "second": "two", "third": "three"})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("Too many fields", rejected.json()["detail"])


class JWTDependencyCompatibilityTests(unittest.TestCase):
    def payload(self, subject=None):
        return {"sub": subject if subject is not None else str(uuid4()),
                "exp": datetime.now(timezone.utc) + timedelta(minutes=1)}

    def test_hs256_uses_hmac_backend(self):
        self.assertIsInstance(jwt.get_algorithm_by_name("HS256"), HMACAlgorithm)
        subject = str(uuid4())
        token = auth.create_token(subject)
        self.assertEqual(jwt.get_unverified_header(token)["alg"], "HS256")
        self.assertEqual(auth.decode_subject(token), subject)

    def test_signed_non_string_subjects_rejected(self):
        for subject in (None, 123, [], {}):
            with self.subTest(subject=subject):
                payload = self.payload()
                payload["sub"] = subject
                token = jwt.encode(payload, auth.settings.JWT_SECRET, algorithm="HS256")
                with self.assertRaises(JWTError):
                    auth.decode_subject(token)

    def test_existing_standard_hs256_wire_token_remains_compatible(self):
        # Encode the previous jose wire format independently of either JWT
        # library; existing signed UUID/expiry claims require no data migration.
        subject = str(uuid4())
        payload = self.payload(subject)
        payload["exp"] = int(payload["exp"].timestamp())
        encoded = b".".join((base64url_encode(b'{"alg":"HS256","typ":"JWT"}'),
            base64url_encode(json.dumps(payload, separators=(",", ":")).encode())))
        signature = hmac.new(auth.settings.JWT_SECRET.encode(), encoded, hashlib.sha256).digest()
        token = (encoded + b"." + base64url_encode(signature)).decode()
        self.assertEqual(auth.decode_subject(token), subject)

    def test_asymmetric_and_unsigned_tokens_rejected(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        asymmetric = jwt.encode(self.payload(), pem, algorithm="RS256")
        payload = self.payload()
        payload["exp"] = int(payload["exp"].timestamp())
        unsigned = ".".join((base64url_encode(b'{"alg":"none","typ":"JWT"}').decode(),
            base64url_encode(json.dumps(payload).encode()).decode(), ""))
        for token in (asymmetric, unsigned):
            with self.subTest(algorithm=jwt.get_unverified_header(token)["alg"]):
                with self.assertRaises(JWTError):
                    auth.decode_subject(token)


if __name__ == "__main__":
    unittest.main()
