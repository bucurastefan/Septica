#!/bin/bash
# Run this once on a fresh Ubuntu 22.04 / 24.04 EC2 instance.
# Usage:  chmod +x setup.sh && ./setup.sh
set -e

echo "==> Updating system packages"
sudo apt-get update -y && sudo apt-get upgrade -y

echo "==> Installing Docker (official script)"
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"

echo "==> Installing Nginx and Certbot"
sudo apt-get install -y nginx certbot python3-certbot-nginx

echo "==> Enabling Nginx"
sudo systemctl enable nginx
sudo systemctl start nginx

echo "==> Installing Git (usually pre-installed)"
sudo apt-get install -y git

echo ""
echo "============================================================"
echo "  Setup complete."
echo "  IMPORTANT: Log out and back in so Docker group takes effect."
echo "  Then run the deployment steps from the README."
echo "============================================================"
