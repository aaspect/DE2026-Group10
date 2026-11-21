#!/usr/bin/env bash
# Sets the Airflow UI login from the environment, then starts all Airflow components.
set -euo pipefail

# Airflow's simple auth manager reads passwords from this JSON file and generates a random one for
# any user missing from it. Writing the file on every start keeps the login equal to .env.
python - <<'PYTHON'
import json
import os
from pathlib import Path

passwords = {os.environ["AIRFLOW_ADMIN_USER"]: os.environ["AIRFLOW_ADMIN_PASSWORD"]}
passwords_file = Path(os.environ["AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE"])
passwords_file.write_text(json.dumps(passwords))
PYTHON

# Under UID 0 (rootless Podman), the base /entrypoint exports PYTHONPATH pointing to Airflow's
# site-packages, which leaks into isolated venvs (/opt/venvs/*). PYTHONUSERBASE already lets
# Airflow find its own packages without polluting venvs.
unset PYTHONPATH

exec airflow standalone
