"""Deploy the web image and central account connection on safety-monitor."""

import argparse
import os
import subprocess
import tempfile
from getpass import getpass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
RDS_ENV = ROOT / ".env.rds"
COMPOSE = [
    "sudo", "-n", "docker", "compose", "-p", "safety-stream",
    "-f", "compose.monitor.yaml", "-f", "compose.media.yaml",
]
RDS_COMPOSE = [*COMPOSE, "-f", "compose.account-rds.yaml"]
DOCKER = ["sudo", "-n", "docker"]


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, text=True, **kwargs)


def write_connection(contents):
    with tempfile.NamedTemporaryFile(mode="wb", dir=ROOT, prefix=".env.rds-", delete=False) as stream:
        stream.write(contents)
    os.replace(stream.name, RDS_ENV)


def restart(compose):
    for service in ("monitor", "web"):
        run([*compose, "up", "-d", "--no-deps", "--no-build", "--wait",
             "--wait-timeout", "150", service])


def verify_web():
    try:
        with urlopen("http://127.0.0.1:8080/api/auth/me", timeout=10):
            pass
    except HTTPError as error:
        if error.code == 401:
            return
        raise
    raise RuntimeError("The account API did not require authentication.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure-rds", action="store_true")
    parser.add_argument("--build-monitor", action="store_true", help="Rebuild the FastAPI worker as well as the web image.")
    options = parser.parse_args()

    previous_connection = RDS_ENV.read_bytes() if RDS_ENV.exists() else None
    if options.configure_rds:
        host = input("RDS endpoint: ").strip()
        user = input("RDS DB user [postgres]: ").strip() or "postgres"
        password = getpass("RDS DB password: ")
        if not host.endswith(".rds.amazonaws.com") or not all(c.isalnum() or c in ".-" for c in host) or not password:
            parser.error("Enter a valid RDS endpoint and DB password.")
        tls = urlencode({"sslmode": "verify-full", "sslrootcert": "/app/certs/global-bundle.pem"})
        url = f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:5432/safety?{tls}"
        connection = f"DATABASE_URL={url}\n".encode()
    elif previous_connection:
        connection = previous_connection
    else:
        parser.error("Run once with --configure-rds to set the production DB connection.")

    monitor = run([*COMPOSE, "ps", "-q", "monitor"], capture_output=True).stdout.strip()
    if not monitor:
        raise SystemExit("No running safety-stream monitor container.")
    build_targets = ("monitor", "web") if options.build_monitor else ("web",)
    previous_images = {
        service: run([*DOCKER, "inspect", "--format", "{{.Image}}",
                      f"safety-stream-{service}-1"], capture_output=True).stdout.strip()
        for service in build_targets
    }
    check_code = (
        "import sys, psycopg\n"
        "try:\n"
        "    with psycopg.connect(sys.stdin.read().strip(), connect_timeout=5) as db:\n"
        "        db.execute('SELECT employee_id FROM accounts LIMIT 0')\n"
        "except psycopg.Error:\n"
        "    sys.exit('RDS account verification failed. Check credentials and TLS.')\n"
    )
    url = connection.decode().removeprefix("DATABASE_URL=").strip()
    run([*DOCKER, "exec", "-i", monitor, "python", "-c", check_code], input=url)

    started_rollout = False
    try:
        write_connection(connection)
        run([*RDS_COMPOSE, "config", "--quiet"])
        run([*RDS_COMPOSE, "build", *build_targets])
        started_rollout = True
        restart(RDS_COMPOSE)
        verify_web()
    except (subprocess.CalledProcessError, OSError, RuntimeError, KeyboardInterrupt):
        if previous_connection is None:
            RDS_ENV.unlink(missing_ok=True)
        else:
            write_connection(previous_connection)
        if started_rollout:
            print("Deployment failed. Restoring the previous images and DB connection.", flush=True)
            for service, image in previous_images.items():
                run([*DOCKER, "image", "tag", image, f"safety-stream-{service}"])
            restart(RDS_COMPOSE if previous_connection is not None else COMPOSE)
        raise
    print("DEPLOY_OK")


if __name__ == "__main__":
    main()
