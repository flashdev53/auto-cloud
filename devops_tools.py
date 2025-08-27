#!/usr/bin/env python3
"""
DevOps Tools - Deploy & Manage Infra/App with Terraform + SSH

Usage:
  python devops_tools.py deploy --ssh-key ~/.ssh/devops_capstone --admin-user devcloud
  python devops_tools.py status
  python devops_tools.py ssh web --ssh-key ~/.ssh/devops_capstone --admin-user devcloud
  python devops_tools.py up   # terraform apply
  python devops_tools.py down # terraform destroy
"""

import json
import os
import subprocess
import time
from pathlib import Path

import click
import paramiko
import requests
from jinja2 import Template

# ----------------------------
# Constants
# ----------------------------
ROOT = Path(__file__).parent.resolve()
TF_DIR = ROOT / "terraform"
APP_DIR = ROOT / "app"
DEPLOY_DIR = ROOT / "deploy"

DEFAULT_USER = "devcloud"
DEFAULT_KEY = os.path.expanduser("~/.ssh/auto-cloud")
DEFAULT_PORT = 8000
DEFAULT_WORKERS = 3
DEFAULT_APP_DIR_NAME = "flaskapp"


# ----------------------------
# Terraform Helpers
# ----------------------------
def tf_output() -> dict:
    """Fetch Terraform outputs or fallback to env vars."""
    app_ip = os.environ.get("APP_VM_IP")
    web_ip = os.environ.get("WEB_VM_IP")
    app_priv_ip = os.environ.get("APP_PRIVATE_IP")

    if app_ip and web_ip and app_priv_ip:
        print("ℹ️  Using IPs from environment variables")
        return {
            "app_public_ip": {"value": app_ip},
            "web_public_ip": {"value": web_ip},
            "app_private_ip": {"value": app_priv_ip},
        }

    try:
        out = subprocess.check_output(
            ["terraform", "output", "-json"], cwd=TF_DIR
        )
        return json.loads(out)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"Terraform output failed: {e}")


# ----------------------------
# SSH + File Transfer Helpers
# ----------------------------
def load_private_key(path: str):
    """Try multiple key formats until one works."""
    from paramiko import Ed25519Key, RSAKey, ECDSAKey

    errors = []
    for KeyClass in (Ed25519Key, RSAKey, ECDSAKey):
        try:
            return KeyClass.from_private_key_file(path)
        except Exception as e:
            errors.append(str(e))
    raise click.ClickException(f"Could not load private key {path}. Errors: {errors}")


def ssh_client(host: str, user: str, key_path: str, timeout=30):
    """Return SSH client connection."""
    key = load_private_key(key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=user, pkey=key, timeout=timeout)
    return client


def run(ssh, cmd: str, timeout=120):
    """Run a remote command via SSH."""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out, err = stdout.read().decode(), stderr.read().decode()
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        raise click.ClickException(
            f"Command failed ({rc}): {cmd}\nSTDOUT: {out}\nSTDERR: {err}"
        )
    return out


def sftp_put_dir(sftp, local_dir: Path, remote_dir: str):
    """Recursively upload directory via SFTP."""
    local_dir = Path(local_dir)
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass

    for item in local_dir.iterdir():
        remote_path = f"{remote_dir.rstrip('/')}/{item.name}"
        if item.is_dir():
            try:
                sftp.mkdir(remote_path)
            except IOError:
                pass
            sftp_put_dir(sftp, item, remote_path)
        else:
            sftp.put(str(item), remote_path)


# ----------------------------
# Deployment Routines
# ----------------------------
def deploy_app_vm(app_ip, admin_user, key_path, port, workers, app_dir_name):
    print(f"🚀 [APP] Connecting to {app_ip} as {admin_user}")
    ssh = ssh_client(app_ip, admin_user, key_path)
    try:
        print("[APP] Installing Python environment...")
        run(ssh, "sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip")

        remote_app_dir = f"/home/{admin_user}/{app_dir_name}"
        print(f"[APP] Uploading application → {remote_app_dir}")
        sftp = ssh.open_sftp()
        try:
            run(ssh, f"mkdir -p {remote_app_dir}")
            sftp_put_dir(sftp, APP_DIR, remote_app_dir)
        finally:
            sftp.close()

        print("[APP] Setting up Python venv + requirements...")
        run(ssh, f"python3 -m venv {remote_app_dir}/venv")
        run(ssh, f"{remote_app_dir}/venv/bin/python -m pip install --upgrade pip setuptools wheel")
        run(ssh, f"{remote_app_dir}/venv/bin/pip install -r {remote_app_dir}/requirements.txt")

        svc_t = Template((DEPLOY_DIR / "gunicorn.service.j2").read_text())
        unit_text = svc_t.render(
            user=admin_user, group=admin_user, app_dir=app_dir_name, port=port, workers=workers
        )

        sftp = ssh.open_sftp()
        try:
            tmp_unit = f"/home/{admin_user}/gunicorn.service"
            with sftp.open(tmp_unit, "w") as fh:
                fh.write(unit_text)
        finally:
            sftp.close()

        print("[APP] Installing & starting gunicorn service...")
        run(ssh, f"sudo mv /home/{admin_user}/gunicorn.service /etc/systemd/system/gunicorn.service")
        run(ssh, "sudo systemctl daemon-reload")
        run(ssh, "sudo systemctl enable --now gunicorn.service")
        print("✅ [APP] Gunicorn service started.")
    finally:
        ssh.close()


def deploy_web_vm(web_ip, app_private_ip, admin_user, key_path, port):
    print(f"🌐 [WEB] Connecting to {web_ip} as {admin_user}")
    ssh = ssh_client(web_ip, admin_user, key_path)
    try:
        print("[WEB] Installing nginx...")
        run(ssh, "sudo apt-get update -y && sudo apt-get install -y nginx")

        nginx_t = Template((DEPLOY_DIR / "nginx.conf.j2").read_text())
        conf_text = nginx_t.render(app_private_ip=app_private_ip, port=port)

        sftp = ssh.open_sftp()
        try:
            tmp_conf = f"/home/{admin_user}/flaskapp_nginx.conf"
            with sftp.open(tmp_conf, "w") as fh:
                fh.write(conf_text)
        finally:
            sftp.close()

        print("[WEB] Deploying nginx config...")
        run(ssh, f"sudo mv /home/{admin_user}/flaskapp_nginx.conf /etc/nginx/conf.d/flaskapp.conf")
        run(ssh, "sudo nginx -t")
        run(ssh, "sudo systemctl restart nginx && sudo systemctl enable nginx")
        print("✅ [WEB] Nginx configured.")
    finally:
        ssh.close()


# ----------------------------
# CLI Commands
# ----------------------------
@click.group()
def cli():
    pass


@cli.command()
@click.option("--ssh-key", default=DEFAULT_KEY, help="Path to SSH private key")
@click.option("--admin-user", default=DEFAULT_USER, help="Admin username on VMs")
@click.option("--port", default=DEFAULT_PORT, help="Port where gunicorn will listen")
@click.option("--workers", default=DEFAULT_WORKERS, help="Gunicorn worker count")
@click.option("--app-dir", default=DEFAULT_APP_DIR_NAME, help="Remote app dir name")
def deploy(ssh_key, admin_user, port, workers, app_dir):
    """Deploy app VM & configure web VM (reverse proxy)."""
    outs = tf_output()
    web_public = outs.get("web_public_ip", {}).get("value")
    app_public = outs.get("app_public_ip", {}).get("value")
    app_private = outs.get("app_private_ip", {}).get("value")

    if not all([web_public, app_public, app_private]):
        raise click.ClickException("Missing Terraform outputs (web/app public/private IPs).")

    print("ℹ️  Terraform outputs:", outs)
    deploy_app_vm(app_public, admin_user, ssh_key, port, workers, app_dir)
    deploy_web_vm(web_public, app_private, admin_user, ssh_key, port)
    print(f"\n🎉 Deployment complete! → http://{web_public}/ (health: /health)")


@cli.command()
def status():
    """Check app health via /health endpoint."""
    outs = tf_output()
    web = outs.get("web_public_ip", {}).get("value")
    if not web:
        raise click.ClickException("web_public_ip missing in Terraform outputs")

    try:
        r = requests.get(f"http://{web}/health", timeout=5)
        print(f"http://{web}/health -> {r.status_code} {r.text}")
    except Exception as e:
        raise click.ClickException(f"Status check failed: {e}")


@cli.command()
@click.argument("which", type=click.Choice(["web", "app"]))
@click.option("--ssh-key", default=DEFAULT_KEY)
@click.option("--admin-user", default=DEFAULT_USER)
def ssh(which, ssh_key, admin_user):
    """SSH into a VM (web/app)."""
    outs = tf_output()
    host = outs.get(f"{which}_public_ip", {}).get("value")
    if not host:
        raise click.ClickException(f"{which}_public_ip missing in Terraform outputs")

    print(f"🔑 Launching ssh → {admin_user}@{host}")
    os.execvp("ssh", ["ssh", "-i", ssh_key, f"{admin_user}@{host}"])


@cli.command()
@click.option("--auto-approve", is_flag=True, default=False)
def up(auto_approve):
    """Terraform init + apply."""
    subprocess.check_call(["terraform", "init"], cwd=str(TF_DIR))
    cmd = ["terraform", "apply"]
    if auto_approve:
        cmd.append("-auto-approve")
    subprocess.check_call(cmd, cwd=str(TF_DIR))


@cli.command()
@click.option("--auto-approve", is_flag=True, default=False)
def down(auto_approve):
    """Terraform destroy."""
    cmd = ["terraform", "destroy"]
    if auto_approve:
        cmd.append("-auto-approve")
    subprocess.check_call(cmd, cwd=str(TF_DIR))


# ----------------------------
# Main Entry
# ----------------------------
if __name__ == "__main__":
    cli()
