#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
"""Smoke do ctrl_tcp: segunda conexão recusada sem derrubar a primeira; quadro inválido fecha a conexão.
Uso: ctrl-tcp-smoke.py <porta>  (baresip já rodando com ctrl_tcp_listen 127.0.0.1:<porta>; stdlib)"""
import json
import socket
import sys
import time

if len(sys.argv) != 2:
    sys.exit(__doc__)
PORT = int(sys.argv[1])
fails = 0


def conn():
    return socket.create_connection(("127.0.0.1", PORT), timeout=3)


def frame(cmd, tok):
    b = json.dumps({"command": cmd, "token": tok}, separators=(",", ":")).encode()
    return b"%d:%s," % (len(b), b)


def recv_all(s, wait=1.5):
    """Lê até fechar ou esgotar `wait`; devolve (bytes, fechou)."""
    s.settimeout(wait)
    out = b""
    try:
        while True:
            d = s.recv(65536)
            if not d:
                return out, True
            out += d
    except socket.timeout:
        return out, False
    except ConnectionError:
        return out, True


def ask(s, tok):
    try:
        s.sendall(frame("help", tok))
    except OSError:
        return False
    end = time.time() + 3
    buf = b""
    while time.time() < end:
        d, closed = recv_all(s, 0.5)
        buf += d
        if b'"token":"%s"' % tok.encode() in buf:
            return True
        if closed:
            return False
    return False


def check(name, ok):
    global fails
    print("PASS" if ok else "FAIL", name)
    fails += not ok


a = conn()
check("a) A recebe resposta com o token", ask(a, "t1"))
b = conn()
bd, bclosed = recv_all(b)
check("b) B fechada pelo servidor sem dados (dados=%d, fechou=%s)" % (len(bd), bclosed), bclosed and not bd)
check("c) A ainda responde depois de B", ask(a, "t2"))
try:
    a.sendall(b"GET / HTTP/1.1\r\n\r\n")
except OSError:
    pass
_, aclosed = recv_all(a)
check("d) lixo fecha A (fechou=%s)" % aclosed, aclosed)
time.sleep(0.3)
c = conn()
check("e) C conecta e recebe resposta", ask(c, "t3"))
sys.exit(1 if fails else 0)
