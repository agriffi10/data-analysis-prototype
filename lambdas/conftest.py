"""Pytest baseline for the Lambda suites.

The control-plane ``config.py`` modules now fail fast at import when a required env
var is unset (SPEC-083 FR-001). The tests patch ``config.X`` attributes after import
(via ``fakes.install()`` etc.), but the import itself needs the required vars present,
so this conftest stamps dummy values before any test module (and its transitive
``import config``) is collected. The config fail-fast is still exercised directly by
``test_config.py``, which reloads the module with a var removed.
"""

import os

_REQUIRED_ENV = {
    "COGNITO_USER_POOL_ID": "us-east-1_testpool",
    "COGNITO_APP_CLIENT_ID": "test-app-client",
    "ADMIN_BUCKET": "admin-bkt",
    "SHARED_SPACE_BUCKET": "shared-bkt",
    "USER_SPACE_BUCKET": "user-bkt",
    "PORTAL_ROLE_ARN": "arn:aws:iam::000000000000:role/test-portal",
    "ATHENA_WORKGROUP": "test-workgroup",
    "AWS_REGION": "us-east-1",
}

for _name, _value in _REQUIRED_ENV.items():
    os.environ.setdefault(_name, _value)
