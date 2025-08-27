#!/usr/bin/env python3
"""
devops_tools.py

Usage examples:
  python devops_tools.py deploy --ssh-key ~/.ssh/devops_capstone --admin-user devcloud
  python devops_tools.py status
  python devops_tools.py ssh web --ssh-key ~/.ssh/devops_capstone --admin-user devcloud
  python devops_tools.py up   # runs terraform apply
  python devops_tools.py down # runs terraform destroy
"""

import json
import os
import subprocess
from pathlib import Path
import time

import click
import paramiko
from jinja2 import Template
import requests

ROOT = Path(__file__).parent.resolve()
TF_DIR = ROOT / "terraform"
APP_DIR = ROOT / "app"
DEPLOY_DIR = ROOT / "deploy"

DEFAULT_USER = "devcloud"                       # change if your username differs
DEFAULT_KEY = os.path.expanduser("~/.ssh/auto-cloud")
DEFAULT_PORT = 8000
DEFAULT_WORKERS = 3
DEFAULT_APP_DIR_NAME = "flaskapp"               # change if you used different folder on VM

# ---------- helpers ----------
def tf_output():
    try:
        out = subprocess.check_output(
            ["terraform", "output", "-json"], cwd=TF_DIR
        )
        return json.loads(out)
    except subprocess.CalledProcessError:
        print("Terraform output failed, falling back to environment variables...")
        return {
            "app_public_ip": {"value": os.environ.get("APP_VM_IP")},
            "web_public_ip": {"value": os.environ.get("WEB_VM_IP")},
        }

def load_private_key(path):
    from paramiko import Ed25519Key, RSAKey, ECDSAKey
    path = str(path)
    errors = []
    for KeyClass in (Ed25519Key, RSAKey, ECDSAKey):
        try:
            return KeyClass.from_private_key_file(path)
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(f"Could not load private key {path}. Errors: {errors}")

def ssh_client(host, user, key_path, timeout=30):
    key = load_private_key(key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=user, pkey=key, timeout=timeout)
    return client

def run(ssh, cmd, timeout=120):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        raise RuntimeError(f"Command failed ({rc}): {cmd}\nSTDOUT: {out}\nSTDERR: {err}")
    return out

def sftp_put_dir(sftp, local_dir: Path, remote_dir: str):
    local_dir = Path(local_dir)
    # create remote dir if necessary
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass
    for item in local_dir.iterdir():
        remote_path = remote_dir.rstrip("/") + "/" + item.name
        if item.is_dir():
            try:
                sftp.mkdir(remote_path)
            except IOError:
                pass
            sftp_put_dir(sftp, item, remote_path)
        else:
            sftp.put(str(item), remote_path)

# ---------- deployment routines ----------
def deploy_app_vm(app_ip, admin_user, key_path, port, workers, app_dir_name):
    print(f"[app] connecting to {app_ip} as {admin_user}")
    ssh = ssh_client(app_ip, admin_user, key_path)
    try:
        # ensure apt & python venv present
        print("[app] updating apt and installing python3-venv...")
        run(ssh, "sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip")

        # create remote app directory and upload
        remote_app_dir = f"/home/{admin_user}/{app_dir_name}"
        print(f"[app] uploading app to {remote_app_dir} ...")
        sftp = ssh.open_sftp()
        try:
            # create remote app dir
            run(ssh, f"mkdir -p {remote_app_dir}")
            sftp_put_dir(sftp, APP_DIR, remote_app_dir)
        finally:
            sftp.close()

        # create venv and install deps
        print("[app] creating venv and installing requirements...")
        run(ssh, f"python3 -m venv {remote_app_dir}/venv")
        run(ssh, f"{remote_app_dir}/venv/bin/python -m pip install --upgrade pip setuptools wheel")
        run(ssh, f"{remote_app_dir}/venv/bin/pip install -r {remote_app_dir}/requirements.txt")

        # render and upload systemd unit
        svc_t = Template((DEPLOY_DIR / "gunicorn.service.j2").read_text())
        unit_text = svc_t.render(user=admin_user, group=admin_user, app_dir=app_dir_name, port=port, workers=workers)
        sftp = ssh.open_sftp()
        try:
            tmp_unit = f"/home/{admin_user}/gunicorn.service"
            with sftp.open(tmp_unit, "w") as fh:
                fh.write(unit_text)
        finally:
            sftp.close()

        # move into systemd dir and enable service
        print("[app] installing systemd unit and starting service...")
        run(ssh, f"sudo mv /home/{admin_user}/gunicorn.service /etc/systemd/system/gunicorn.service")
        run(ssh, "sudo systemctl daemon-reload")
        run(ssh, "sudo systemctl enable --now gunicorn.service")
        print("[app] gunicorn service started.")
    finally:
        ssh.close()

def deploy_web_vm(web_ip, app_private_ip, admin_user, key_path, port):
    print(f"[web] connecting to {web_ip} as {admin_user}")
    ssh = ssh_client(web_ip, admin_user, key_path)
    try:
        print("[web] updating apt and installing nginx...")
        run(ssh, "sudo apt-get update -y && sudo apt-get install -y nginx")

        # render nginx config
        nginx_t = Template((DEPLOY_DIR / "nginx.conf.j2").read_text())
        conf_text = nginx_t.render(app_private_ip=app_private_ip, port=port)

        sftp = ssh.open_sftp()
        try:
            tmp_conf = f"/home/{admin_user}/flaskapp_nginx.conf"
            with sftp.open(tmp_conf, "w") as fh:
                fh.write(conf_text)
        finally:
            sftp.close()

        print("[web] placing nginx conf and restarting nginx...")
        run(ssh, f"sudo mv /home/{admin_user}/flaskapp_nginx.conf /etc/nginx/conf.d/flaskapp.conf")
        run(ssh, "sudo nginx -t")
        run(ssh, "sudo systemctl restart nginx")
        run(ssh, "sudo systemctl enable nginx")
        print("[web] nginx configured.")
    finally:
        ssh.close()

# ---------- CLI ----------
@click.group()
def cli():
    pass

@cli.command()
@click.option("--ssh-key", default=DEFAULT_KEY, help="Path to SSH private key")
@click.option("--admin-user", default=DEFAULT_USER, help="Admin username on VMs")
@click.option("--port", default=DEFAULT_PORT, help="Port where gunicorn will listen on App VM")
@click.option("--workers", default=DEFAULT_WORKERS, help="Gunicorn worker count")
@click.option("--app-dir", default=DEFAULT_APP_DIR_NAME, help="Remote folder name for app on VM")
def deploy(ssh_key, admin_user, port, workers, app_dir):
    """Deploy app to the app VM and configure web VM (reverse proxy)."""
    outs = tf_output()
    web_public = outs.get("web_public_ip")
    app_public = outs.get("app_public_ip")
    app_private = outs.get("app_private_ip")

    if not all([web_public, app_public, app_private]):
        raise click.Abort("Missing terraform outputs. Ensure 'terraform apply' completed and outputs exist.")

    print("Terraform outputs:", web_public, app_public, app_private)
    deploy_app_vm(app_public, admin_user, ssh_key, port, workers, app_dir)
    deploy_web_vm(web_public, app_private, admin_user, ssh_key, port)
    print(f"Deployed. Visit: http://{web_public}/ (health: /health)")

@cli.command()
def status():
    outs = tf_output()
    web = outs.get("web_public_ip")
    if not web:
        raise click.Abort("web_public_ip missing in terraform outputs")
    try:
        r = requests.get(f"http://{web}/health", timeout=5)
        print(f"http://{web}/health -> {r.status_code} {r.text}")
    except Exception as e:
        print("status check failed:", e)

@cli.command()
@click.argument("which", type=click.Choice(["web", "app"]))
@click.option("--ssh-key", default=DEFAULT_KEY)
@click.option("--admin-user", default=DEFAULT_USER)
def ssh(which, ssh_key, admin_user):
    outs = tf_output()
    host = outs.get(f"{which}_public_ip")
    if not host:
        raise click.Abort(f"{which}_public_ip missing from terraform outputs")
    print(f"Launching local ssh to {admin_user}@{host}")
    os.execvp("ssh", ["ssh", "-i", ssh_key, f"{admin_user}@{host}"])

@cli.command()
@click.option("--auto-approve", is_flag=True, default=False)
def up(auto_approve):
    """terraform init + apply"""
    subprocess.check_call(["terraform", "init"], cwd=str(TF_DIR))
    cmd = ["terraform", "apply"]
    if auto_approve:
        cmd.append("-auto-approve")
    subprocess.check_call(cmd, cwd=str(TF_DIR))

@cli.command()
@click.option("--auto-approve", is_flag=True, default=False)
def down(auto_approve):
    cmd = ["terraform", "destroy"]
    if auto_approve:
        cmd.append("-auto-approve")
    subprocess.check_call(cmd, cwd=str(TF_DIR))

if __name__ == "__main__":
    cli()
