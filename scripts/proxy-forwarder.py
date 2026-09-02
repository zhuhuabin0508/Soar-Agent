#!/usr/bin/env python3
"""容器代理转发器。

宿主机代理仅监听 127.0.0.1:8999，容器无法直接访问。
本脚本在 Docker 网桥网关（172.28.0.1）上监听 8998 端口，
将流量转发到 127.0.0.1:8999，供容器内 apt/pip/git/wget 走代理。

用法：nohup python3 proxy-forwarder.py >/dev/null 2>&1 &
"""
import socket
import threading
import select

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8998
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 8999


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            src.shutdown(socket.SHUT_RD)
        except OSError:
            pass
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client: socket.socket) -> None:
    try:
        upstream = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=15)
    except OSError:
        client.close()
        return
    t = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
    t.start()
    pipe(upstream, client)
    t.join(timeout=1)
    try:
        client.close()
    except OSError:
        pass
    try:
        upstream.close()
    except OSError:
        pass


def main() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(128)
    print(f"forwarder listening on {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
