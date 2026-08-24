# Manual Deployment Instructions

To deploy this VPN manager manually on a server (e.g., an Ubuntu EC2 instance, DigitalOcean Droplet, or any Linux VPS), follow these steps:

## Prerequisites
- A Linux server (Ubuntu/Debian recommended)
- Your server's public IP address

## 1. Install Docker and Docker Compose
Connect to your server via SSH and install the required packages:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
```

## 2. Copy the Project Files
Copy the contents of this project to your server. For example, you can clone your Git repository or use `scp` to transfer the files to a directory.

```bash
# Example if using git
git clone <your-repo-url> /opt/vpn-manager
cd /opt/vpn-manager
```

## 3. Configure Environment Variables
Create a `.env` file in the root of the project directory.

First, generate a WireGuard private key if you haven't already:
```bash
# Run this on a machine with wireguard tools installed to get a private key
wg genkey
```

Create the `.env` file (e.g., in `/opt/vpn-manager/.env`):
```env
# Choose a strong, long random string for your admin token
ADMIN_TOKEN=your_secure_admin_token_here

# The private key you generated
WG_PRIVATE_KEY=your_wireguard_private_key_here

# Your server's public IP address or domain name
WG_PUBLIC_ENDPOINT=your_server_public_ip
```

## 4. Run the Application
Start the services using Docker Compose:

```bash
sudo docker compose up -d --build
```

## 5. Usage
Once running, the management API will be accessible on port `8080` (e.g., `http://<your_server_public_ip>:8080`).

**Security Note:** For production use, it is highly recommended to put this behind a reverse proxy (like Nginx or Caddy) to serve the API securely over HTTPS. Do not expose the management API on the open internet without HTTPS.
