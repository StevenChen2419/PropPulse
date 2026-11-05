"""Run mounted read-only in the final image with --network none; never start DB.

Exercises installed binary wheels and password/JWT behavior after removal of
build/install tools. Outputs versions/check results, never token/secret values.
"""
from datetime import datetime, timedelta, timezone
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import UUID

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def run():
    sys.path.insert(0, "/app")
    assert os.getuid() == 10001
    versions = {canonicalize_name(d.metadata["Name"]): d.version for d in metadata.distributions()}
    for tool in ("pip", "setuptools", "wheel"):
        assert importlib.util.find_spec(tool) is None, tool
    locked = {}
    for line in Path("/app/requirements.lock.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if not requirement.marker or requirement.marker.evaluate():
            locked[canonicalize_name(requirement.name)] = str(requirement.specifier)[2:]
    assert not (versions.keys() - locked.keys()), "Unexpected distribution"
    assert all(locked[name] == version for name, version in versions.items()), "Lock mismatch"
    # colorama is a Windows-only dependency; constraints do not require installing it.
    assert locked.keys() - versions.keys() <= {"pip", "colorama"}
    for distribution in metadata.distributions():
        for value in distribution.requires or []:
            requirement = Requirement(value)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            name = canonicalize_name(requirement.name)
            assert name in versions and versions[name] in requirement.specifier, requirement.name
    for excluded in (".env", ".git", "venv", "tests", "data/odds_runs", "ml"):
        assert not Path("/app", excluded).exists(), excluded
    import numpy as np
    import pandas as pd
    import scipy
    import shap
    from sklearn.ensemble import RandomForestRegressor
    from xgboost import XGBRegressor
    x = np.array([[1., 2.], [2., 3.], [3., 4.], [4., 5.]])
    y = np.array([1., 2., 3., 4.])
    assert pd.DataFrame(x).shape == (4, 2)
    assert RandomForestRegressor(n_estimators=2, random_state=1).fit(x, y).predict(x).shape == (4,)
    model = XGBRegressor(n_estimators=2, n_jobs=1).fit(x, y)
    assert np.isfinite(shap.TreeExplainer(model).shap_values(x)).all()
    from app.auth import create_token, decode_subject, hash_password, verify_password
    import jwt
    from app.config import settings
    assert settings.production and not settings.configuration_errors()
    subject = str(UUID(int=900))
    hashed = hash_password("Invented-image-check!472")
    assert verify_password("Invented-image-check!472", hashed)
    assert not verify_password("wrong", hashed)
    assert decode_subject(create_token(subject)) == subject
    invalid = [jwt.encode({"sub": subject, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, settings.JWT_SECRET, algorithm="HS256"),
        jwt.encode({"sub": subject, "exp": datetime.now(timezone.utc) + timedelta(minutes=1)}, "", algorithm="none"),
        jwt.encode({"sub": subject, "exp": datetime.now(timezone.utc) + timedelta(minutes=1)}, settings.JWT_SECRET, algorithm="HS384")]
    for token in invalid:
        try:
            decode_subject(token)
        except jwt.InvalidTokenError:
            pass
        else:
            raise AssertionError("Invalid token accepted")
    print(json.dumps({"uid": os.getuid(), "packages": versions, "resolution": "compatible",
        "lock_match": True, "native_ml": True, "bcrypt": True, "jwt_rejections": 3,
        "private_context_excluded": True, "installer_tools_absent": True}, sort_keys=True))


if __name__ == "__main__":
    run()
