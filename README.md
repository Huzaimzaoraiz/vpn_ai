# Private AWS WireGuard VPN

This project deploys a small, self-managed WireGuard VPN on an EC2 instance and provides a protected web/API interface for adding and removing devices. It is designed for private device-to-device communication, not anonymous browsing.

WireGuard is used because it is modern, fast, well audited, and supported by Android, iOS, Windows, macOS, and Linux.

## What it does

- Creates an AWS VPC, public subnet, security group, and Ubuntu EC2 VPN host.
- Opens UDP `51820` for WireGuard and TCP `8080` for the management page/API.
- Creates client configurations once, including a QR code for mobile apps.
- Assigns each device a stable IP in `10.88.0.0/24` so devices can reach one another.
- Uses a single required `X-Admin-Token` to protect every management API request.

## Important security notes

- Restrict `admin_allowed_cidr` to *your* current public IP before applying. Do not leave the management API publicly open.
- Put the API behind HTTPS before using it on the internet. The included EC2 service listens on `8080`; use a reverse proxy/load balancer with a real certificate for production.
- The admin token and WireGuard server private key are secrets. Store them in a secret manager for a long-lived setup; never commit them.
- Do not use the API to expose arbitrary shell commands. This service only invokes WireGuard with fixed arguments.

## Deploy

Please refer to [INSTRUCTION.MD](INSTRUCTION.MD) for step-by-step instructions on how to deploy this project manually using Docker.

Once deployed and running, open the management URL (`http://SERVER_IP:8080`) in a browser or interact via the API. Enter the admin token, add a device, and import the downloaded config or scan its QR code in a WireGuard client.

## API

All calls require `X-Admin-Token: <your token>`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/peers` | List registered devices |
| `POST` | `/api/peers` | Create a device and return its configuration |
| `DELETE` | `/api/peers/{id}` | Revoke a device |

Example:

```sh
curl -X POST http://SERVER_IP:8080/api/peers \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: YOUR_TOKEN' \
  -d '{"name":"my-phone"}'
```

The response contains the complete client config once. Save it immediately; private client keys are not stored by the server.

## Routing choices

New clients use `AllowedIPs = 10.88.0.0/24`, which sends only VPN-device traffic through the tunnel. This is safest for your stated goal. If you later want the VPN to carry all internet traffic, set `FULL_TUNNEL=true` and add NAT/routing deliberately; it is intentionally not enabled by default.
