"""Credential-free, staging-only PostgreSQL TLS probe. No authentication or SQL."""
import argparse
import json
import socket
import ssl
import struct

HOST = "db.ggaddhffmgwpgsskfksx.supabase.co"
PORT = 5432
SSL_REQUEST = struct.pack("!II", 8, 80877103)

def probe(cafile=None):
    """Require certificate and hostname validation; never send credentials."""
    context = ssl.create_default_context(cafile=cafile)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((HOST, PORT), timeout=5) as sock:
        sock.sendall(SSL_REQUEST)
        if sock.recv(1) != b"S":
            raise RuntimeError("TLS unavailable")
        with context.wrap_socket(sock, server_hostname=HOST) as encrypted:
            return {"tls": encrypted.version(), "peer_verified": True}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca-file", help="Trusted CA file from staging database settings")
    args = parser.parse_args()
    try:
        result = probe(args.ca_file)
    except (OSError, RuntimeError, ValueError):
        print(json.dumps({"status": "FAIL", "stage": "network_or_tls"}))
        return 1
    print(json.dumps({"status": "PASS", **result}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
