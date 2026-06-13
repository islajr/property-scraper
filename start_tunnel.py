import subprocess
import time
import json
import urllib.request
import sys
import os
import socket
import select
import threading

# ── Local Proxy Configuration ────────────────────────────────────────────────
PROXY_PORT = 8118

def handle_proxy_client(client_socket):
    try:
        request = client_socket.recv(4096)
        if not request:
            return
        
        first_line = request.decode('utf-8', errors='ignore').split('\n')[0]
        words = first_line.split()
        if len(words) < 2:
            return
        
        method, url = words[0], words[1]
        
        if method == 'CONNECT':
            host, port = url.split(':')
            port = int(port)
            remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote_socket.connect((host, port))
            client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            if url.startswith('http://'):
                url = url[7:]
            parts = url.split('/')
            host_parts = parts[0].split(':')
            host = host_parts[0]
            port = int(host_parts[1]) if len(host_parts) > 1 else 80
            remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote_socket.connect((host, port))
            remote_socket.sendall(request)
            
        sockets = [client_socket, remote_socket]
        while True:
            r, _, _ = select.select(sockets, [], [], 15)
            if not r:
                break
            for s in r:
                data = s.recv(4096)
                if not data:
                    return
                if s is client_socket:
                    remote_socket.sendall(data)
                else:
                    client_socket.sendall(data)
    except Exception:
        pass
    finally:
        try: client_socket.close()
        except: pass

def start_local_proxy():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PROXY_PORT))
    server.listen(100)
    print(f"[*] Local residential proxy listening on port {PROXY_PORT}")
    while True:
        client, _ = server.accept()
        threading.Thread(target=handle_proxy_client, args=(client,), daemon=True).start()

# ── Main Tunnel Orchestration ────────────────────────────────────────────────
def get_ngrok_url():
    """Poll ngrok's local API to retrieve the active public tunnel URL."""
    try:
        req = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels")
        data = json.loads(req.read().decode())
        tunnels = data.get("tunnels", [])
        for tunnel in tunnels:
            if tunnel.get("proto") == "tcp":
                public_url = tunnel.get("public_url")
                # Convert tcp://4.tcp.ngrok.io:12345 to http://4.tcp.ngrok.io:12345
                if public_url.startswith("tcp://"):
                    return public_url.replace("tcp://", "http://")
        return None
    except Exception:
        return None

def update_github_secret(new_url):
    """Use the GitHub CLI to update the PROXY_URL secret in the repository."""
    print(f"[*] Updating GitHub repository secret 'PROXY_URL' to: {new_url}")
    try:
        # Check if gh CLI is installed and authenticated
        subprocess.run(["gh", "auth", "status"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[!] Error: GitHub CLI ('gh') is not installed or not authenticated.")
        print("[!] Please install the GitHub CLI and run 'gh auth login' to enable auto-secret updates.")
        print(f"[!] Alternatively, manually set the PROXY_URL secret on GitHub to: {new_url}")
        return False

    try:
        # Update the secret in the repository (automatically resolves repository context)
        subprocess.run(["gh", "secret", "set", "PROXY_URL", "--body", new_url], check=True)
        print("[+] GitHub Secret 'PROXY_URL' updated successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[!] Failed to update secret via GitHub CLI: {e}")
        return False

def main():
    # 1. Start the proxy server in a background thread
    proxy_thread = threading.Thread(target=start_local_proxy, daemon=True)
    proxy_thread.start()
    
    # 2. Launch ngrok
    print("[*] Starting ngrok tunnel...")
    ngrok_proc = None
    try:
        # Run ngrok as a subprocess. Ensure ngrok is in your system PATH.
        ngrok_proc = subprocess.Popen(
            ["ngrok", "tcp", str(PROXY_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except FileNotFoundError:
        print("[!] Error: 'ngrok' binary was not found in your PATH.")
        print("[!] Please download ngrok and verify that running 'ngrok' works in your terminal.")
        sys.exit(1)

    # 3. Poll local API until tunnel is established
    print("[*] Waiting for ngrok tunnel to establish...")
    public_url = None
    retries = 20
    for i in range(retries):
        time.sleep(1)
        public_url = get_ngrok_url()
        if public_url:
            break
            
    if not public_url:
        print("[!] Timeout: Could not retrieve tunnel URL from ngrok's local API.")
        if ngrok_proc:
            ngrok_proc.terminate()
        sys.exit(1)

    print(f"[+] Tunnel established successfully: {public_url}")

    # 4. Auto-update secret
    update_github_secret(public_url)

    # 5. Keep running until interrupted
    print("\n[+] Tunnel is active. Keep this script running to proxy your GitHub Actions runs.")
    print("[+] Press Ctrl+C to terminate.")
    
    try:
        # Keep waiting on the ngrok process
        while True:
            time.sleep(1)
            # Check if ngrok died
            if ngrok_proc.poll() is not None:
                print("[!] ngrok process terminated unexpectedly.")
                break
    except KeyboardInterrupt:
        print("\n[*] Shutting down proxy and ngrok tunnel...")
    finally:
        if ngrok_proc:
            ngrok_proc.terminate()
            ngrok_proc.wait()
        print("[+] Terminated.")

if __name__ == '__main__':
    main()
