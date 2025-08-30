# Auto Cloud – End-to-End Cloud Infrastructure Automation

This project is an **end-to-end cloud automation toolkit** that provisions infrastructure and deploys applications on **Azure** using:

- **Terraform** for Infrastructure as Code (IaC)  
- **Python automation** (`devops_tools.py`) for deployment and orchestration  
- **GitHub Actions** for CI/CD pipeline  

It is designed to give **Cloud Engineers / DevOps Engineers** a practical foundation in real-world workflows combining IaC, automation, and CI/CD.

---

## Project Description

Modern cloud engineering requires a **repeatable, automated, and version-controlled process** to manage infrastructure and deploy applications.  

This project demonstrates how to:

1. **Provision infrastructure with Terraform**  
   - Creates Azure resource groups, networks, and virtual machines  
   - Exposes public IPs for app + web servers  

2. **Deploy apps with Python automation**  
   - Custom tool `devops_tools.py` handles:
     - Collecting Terraform outputs  
     - Falling back to environment variables (from GitHub Secrets)  
     - SSH into VMs and deploying app code  
     - Configuration templating (via Jinja2)  

3. **Automate workflows with GitHub Actions**  
   - CI/CD runs on every push  
   - Secrets handled securely  
   - Terraform plan & apply automated  
   - Deploy tool executed post-infra creation  

This project gives you a **real-world DevOps lab** to practice:  
✅ Infrastructure as Code  
✅ Secret management  
✅ CI/CD pipelines  
✅ Automated deployment  

---

## Architecture
            ┌─────────────────────┐
            │     GitHub Repo     │
            └───────┬─────────────┘
                    │ Push to main
                    ▼
          ┌────────────────────────┐
          │  GitHub Actions CI/CD  │
          └───────┬────────────────┘
                  │
                  ▼
         ┌─────────────────┐
         │   Terraform IaC │
         │ (Azure VMs, IPs)│
         └───────┬─────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │  Python Deploy Tool    │
    │  (SSH + Jinja2 + App)  │
    └──────────┬─────────────┘
               │
               ▼
       ┌─────────────────┐
       │ Azure App + Web │
       │     Servers     │
       └─────────────────┘


---

## Tech Stack

- **Cloud Provider:** Microsoft Azure  
- **IaC Tool:** Terraform  
- **Language:** Python 3.10+  
  - [click](https://palletsprojects.com/p/click/) – CLI handling  
  - [paramiko](http://www.paramiko.org/) – SSH connections  
  - [jinja2](https://palletsprojects.com/p/jinja/) – Config templating  
  - [requests](https://docs.python-requests.org/) – HTTP utilities  
- **CI/CD:** GitHub Actions  

---

## 📂 Project Structure

.
├── app/                  # Application code (your web/app services)
│   └── requirements.txt  # Python dependencies
├── terraform/            # Terraform IaC configurations
│   ├── main.tf           # Core infra definition
│   ├── variables.tf      # Configurable inputs
│   └── outputs.tf        # Exported values (VM IPs)
├── devops_tools.py       # Python deployment + orchestration script
├── .github/workflows/    # GitHub Actions CI/CD workflows
│   └── deploy.yml
└── README.md             # Project documentation


---

## Secrets Configuration

The project relies on **GitHub Secrets** for sensitive values. Configure under  
`Settings > Secrets and variables > Actions`.

| Secret Name            | Purpose                                  |
|------------------------|------------------------------------------|
| `ARM_CLIENT_ID`        | Azure Service Principal Client ID        |
| `ARM_CLIENT_SECRET`    | Azure Service Principal Client Secret    |
| `ARM_SUBSCRIPTION_ID`  | Azure Subscription ID                    |
| `ARM_TENANT_ID`        | Azure Tenant ID                          |
| `SSH_PUBLIC_KEY`       | Public SSH key for VM access             |
| `SSH_PRIVATE_KEY`      | Private SSH key (for deployment)         |
| `APP_VM_IP`            | App VM IP (Terraform output fallback)    |
| `WEB_VM_IP`            | Web VM IP (Terraform output fallback)    |

---

## CI/CD Workflow (GitHub Actions)

- **Trigger:** Push to `main`  
- **Steps:**
  1. Checkout code  
  2. Install Python dependencies  
  3. Install + configure Terraform  
  4. Run `terraform init && terraform apply`  
  5. Export IPs → environment variables  
  6. Run `python devops_tools.py deploy`  

Logs and status are viewable in **GitHub Actions > Runs**.

---

## Running Locally

### 1. Clone repository
```bash
git clone https://github.com/flashdev53/auto-cloud.git
cd auto-cloud
2. Python setup
python -m venv venv
source venv/bin/activate
pip install -r app/requirements.txt
pip install click paramiko jinja2 requests
```
### 3. Terraform setup
```bash
cd terraform
terraform init
terraform apply -auto-approve -var "ssh_public_key=$(cat ~/.ssh/id_rsa.pub)"
```

### 4. Deploy app
```bash
python ../devops_tools.py deploy
```

## Deployment Flow

- Terraform provisions Azure infrastructure

- Python tool deploys app onto created VMs

- GitHub Actions ensures automation for every push

- App accessible via APP_VM_IP + WEB_VM_IP

## Roadmap

 Add automatic Terraform → Secrets sync

 Add monitoring (Prometheus + Grafana)

 Add staging & production environments

 Dockerize app + orchestrate with Kubernetes

## 🤝 Contributing

Fork the repo

Create a feature branch

Commit changes

Open a PR 