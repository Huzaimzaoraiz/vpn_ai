import base64
import ipaddress
import os
import secrets
import sqlite3
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import qrcode
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "peers.db"
WG_INTERFACE = "wg0"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
SERVER_PRIVATE_KEY = os.environ.get("WG_PRIVATE_KEY", "")
PUBLIC_ENDPOINT = os.environ.get("WG_PUBLIC_ENDPOINT", "")
WG_PORT = int(os.environ.get("WG_PORT", "51820"))
VPN_SUBNET = ipaddress.ip_network(os.environ.get("VPN_SUBNET", "10.88.0.0/24"))
SERVER_ADDRESS = os.environ.get("VPN_SERVER_ADDRESS", "10.88.0.1/24")


def run(*args: str, input_text: str | None = None) -> str:
    return subprocess.run(args, input=input_text, text=True, check=True, capture_output=True).stdout.strip()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def require_token(x_admin_token: str = Header(default="")) -> None:
    if not ADMIN_TOKEN or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(401, "Invalid admin token")


def ensure_interface() -> None:
    if not SERVER_PRIVATE_KEY or not PUBLIC_ENDPOINT:
        raise RuntimeError("WG_PRIVATE_KEY and WG_PUBLIC_ENDPOINT are required")
    exists = subprocess.run(["ip", "link", "show", WG_INTERFACE], capture_output=True).returncode == 0
    if not exists:
        run("ip", "link", "add", WG_INTERFACE, "type", "wireguard")
        run("ip", "address", "add", SERVER_ADDRESS, "dev", WG_INTERFACE)
        run("wg", "set", WG_INTERFACE, "private-key", "/dev/stdin", "listen-port", str(WG_PORT), input_text=SERVER_PRIVATE_KEY)
        run("ip", "link", "set", "up", "dev", WG_INTERFACE)


def allocate_ip(conn: sqlite3.Connection) -> str:
    assigned = {row[0] for row in conn.execute("SELECT address FROM peers")}
    for candidate in VPN_SUBNET.hosts():
        value = str(candidate)
        if value != str(ipaddress.ip_interface(SERVER_ADDRESS).ip) and value not in assigned:
            return value
    raise HTTPException(409, "VPN address pool is exhausted")


def client_config(private_key: str, address: str) -> str:
    server_public = run("wg", "pubkey", input_text=SERVER_PRIVATE_KEY)
    return f"""[Interface]
PrivateKey = {private_key}
Address = {address}/32
DNS = 1.1.1.1

[Peer]
PublicKey = {server_public}
Endpoint = {PUBLIC_ENDPOINT}:{WG_PORT}
AllowedIPs = {VPN_SUBNET}
PersistentKeepalive = 25
"""


class PeerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9 _.-]*$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS peers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, public_key TEXT UNIQUE NOT NULL,
            address TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
        )""")
    ensure_interface()
    with db() as conn:
        for peer in conn.execute("SELECT public_key, address FROM peers"):
            run("wg", "set", WG_INTERFACE, "peer", peer["public_key"], "allowed-ips", f'{peer["address"]}/32')
    yield


app = FastAPI(title="WireGuard VPN Manager", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok", "interface": WG_INTERFACE, "subnet": str(VPN_SUBNET)}


@app.get("/api/peers", dependencies=[Depends(require_token)])
def list_peers():
    with db() as conn:
        return [dict(row) for row in conn.execute("SELECT id, name, address, created_at FROM peers ORDER BY created_at DESC")]


@app.post("/api/peers", dependencies=[Depends(require_token)])
def create_peer(payload: PeerCreate):
    private_key = run("wg", "genkey")
    public_key = run("wg", "pubkey", input_text=private_key)
    peer_id = secrets.token_urlsafe(9)
    created_at = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        address = allocate_ip(conn)
        conn.execute("INSERT INTO peers VALUES (?, ?, ?, ?, ?)", (peer_id, payload.name, public_key, address, created_at))
    try:
        run("wg", "set", WG_INTERFACE, "peer", public_key, "allowed-ips", f"{address}/32")
    except Exception:
        with db() as conn:
            conn.execute("DELETE FROM peers WHERE id = ?", (peer_id,))
        raise
    config = client_config(private_key, address)
    qr = qrcode.make(config)
    output = BytesIO()
    qr.save(output, format="PNG")
    return {"id": peer_id, "name": payload.name, "address": address, "config": config,
            "qr_code_data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()}


@app.delete("/api/peers/{peer_id}", dependencies=[Depends(require_token)])
def delete_peer(peer_id: str):
    with db() as conn:
        peer = conn.execute("SELECT public_key FROM peers WHERE id = ?", (peer_id,)).fetchone()
        if not peer:
            raise HTTPException(404, "Device not found")
        conn.execute("DELETE FROM peers WHERE id = ?", (peer_id,))
    run("wg", "set", WG_INTERFACE, "peer", peer["public_key"], "remove")
    return {"deleted": peer_id}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """<!doctype html><html><head><title>VPN Manager</title><style>body{max-width:720px;margin:3rem auto;font:16px system-ui;padding:0 1rem}input,button{padding:.65rem;margin:.25rem}pre{white-space:pre-wrap;background:#f4f4f4;padding:1rem}li{margin:.5rem 0}</style></head><body><h1>WireGuard VPN</h1><p>Enter the admin token, then create a device profile. Download/save its config immediately.</p><input id=t type=password placeholder='Admin token'><button onclick='load()'>Load devices</button><hr><input id=n placeholder='Device name'><button onclick='add()'>Add device</button><div id=o></div><script>const h=()=>({'X-Admin-Token':t.value});async function load(){let r=await fetch('/api/peers',{headers:h()}),x=await r.json();o.innerHTML=r.ok?'<ul>'+x.map(p=>`<li>${p.name} — ${p.address} <button onclick="del('${p.id}')">Revoke</button></li>`).join('')+'</ul>':'Access denied'}async function add(){let r=await fetch('/api/peers',{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify({name:n.value})}),x=await r.json();if(!r.ok){o.textContent=x.detail;return}o.innerHTML='<h2>Save this once</h2><a download="'+x.name+'.conf" href="data:text/plain;charset=utf-8,'+encodeURIComponent(x.config)+'">Download config</a><pre>'+x.config.replace(/</g,'&lt;')+'</pre><img width=260 src="'+x.qr_code_data_url+'">';}async function del(id){await fetch('/api/peers/'+id,{method:'DELETE',headers:h()});load()}</script></body></html>"""
