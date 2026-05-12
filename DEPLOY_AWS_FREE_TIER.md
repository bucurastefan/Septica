# Deploy Septica to AWS Free Tier (EC2)

This guide deploys the game on **one EC2 Free Tier** instance using Docker.

> AWS is not permanently free. Free Tier usually covers limited usage for ~12 months on new accounts.

## 1) Create EC2 instance (Free Tier)

- Launch **Ubuntu 24.04 LTS** (or Amazon Linux) on `t3.micro` / `t2.micro`.
- Security Group inbound:
  - `22` (SSH) from your IP
  - `80` (HTTP) from `0.0.0.0/0`
  - `443` (HTTPS) from `0.0.0.0/0`
- Attach an Elastic IP if you want a stable public IP.

## 2) Install Docker + Compose (Ubuntu)

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
```

## 3) Copy project and configure env

```bash
git clone https://github.com/bucurastefan/Septica.git
cd Septica
cp deploy/aws/env.ec2.sample .env.ec2
```

Edit `.env.ec2`:

- `SECRET_KEY` = long random string
- `ADMIN_PASSWORD` = strong password
- `CORS_ORIGIN` = your real domain (`https://your-domain.com`)

## 4) Configure HTTPS domain (Caddy)

Edit `deploy/aws/Caddyfile` and replace `your-domain.com` with your domain.

Point your domain DNS `A` record to your EC2 public IP.

## 5) Start app

```bash
# Run this from repository root (where ./flask_auth_app exists)
docker compose -f deploy/aws/docker-compose.ec2.yml --env-file .env.ec2 up -d --build
```

Services:
- `web`: Flask + Socket.IO app
- `caddy`: reverse proxy + automatic Let's Encrypt HTTPS

SQLite data persists in Docker volume `septica_data` mounted to `/app/data`.

## 6) Back up SQLite to S3

Create a bucket (example: `septica-db-backups`).

```bash
chmod +x deploy/aws/scripts/backup_sqlite_to_s3.sh
./deploy/aws/scripts/backup_sqlite_to_s3.sh septica-db-backups eu-north-1
```

Optional cron (daily at 03:30):

```bash
crontab -e
# Add:
30 3 * * * cd $HOME/Septica && /bin/bash ./deploy/aws/scripts/backup_sqlite_to_s3.sh septica-db-backups eu-north-1 >> /home/ubuntu/septica-backup.log 2>&1
```

## 7) Cost controls (important)

- Create **AWS Budgets** with low thresholds (for example $1, $5, $10).
- Avoid non-Free-Tier services unless needed (NAT Gateway, RDS Multi-AZ, extra load balancers).
- Monitor EC2, EBS, and data transfer monthly.

## Optional: Elastic Beanstalk

Elastic Beanstalk also works, but it still runs EC2 (same Free Tier limits, then charges).
