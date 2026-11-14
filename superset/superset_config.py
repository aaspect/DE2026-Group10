"""Superset settings for the local stack. Values come from compose.yaml and .env."""

import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_METADATA_DB_URI"]
