#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
"""Smoke de vídeo: dois baresip, chamada só áudio, depois videodir nos dois lados; exige RTP de vídeo VP8.
Uso: video-smoke.py <baresip> [--modules <dir>] [--host <ip>]  (stdlib; roda em Windows e Linux)"""
import argparse, json, os, random, re, shutil, socket, subprocess, sys, tempfile, time

ap = argparse.ArgumentParser()
ap.add_argument("bin")
ap.add_argument("--modules")
ap.add_argument("--host")
args = ap.parse_args()
def local_ip():
    # baresip ignora loopback como endereço local no Windows e no WSL ("no laddr for 127.0.0.1"); connect UDP não envia nada.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as x:
            x.connect(("192.0.2.1", 9)); return x.getsockname()[0]
    except OSError:
        return "127.0.0.1"


H, TMO = args.host or local_ip(), 15
tmp = tempfile.mkdtemp(prefix="vsmoke")
procs, side = [], {}


def free_port(udp=False):
    # Abaixo das faixas efêmeras (Windows 49152+, Linux 32768+), como o app.
    while True:
        p = random.randint(20000, 31999)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
        try:
            s.bind((H if udp else "127.0.0.1", p)); return p
        except OSError:
            pass
        finally:
            s.close()


class UA:
    def __init__(s, name):
        s.name, s.sip, s.ctl, s.ev, s.buf = name, free_port(True), free_port(), [], b""
        s.dir = os.path.join(tmp, name); os.makedirs(s.dir)
        open(os.path.join(s.dir, "accounts"), "w").close()
        mods = ["g711", "vp8", "fakevideo"]
        cfg = (f"module_path {args.modules}\n" if args.modules else "") + (
            f"sip_listen {H}:{s.sip}\nctrl_tcp_listen 127.0.0.1:{s.ctl}\n"
            "video_source fakevideo,nil\nvideo_display fakevideo,nil\n"
            + "".join(f"module {m}.so\n" for m in mods) + "module_app menu.so\nmodule_app ctrl_tcp.so\n")
        open(os.path.join(s.dir, "config"), "w").write(cfg)
        s.log = os.path.join(tmp, name + ".log")
        side[name] = s  # fail() já mostra o log se o startup falhar
        # Windows: o baresip.exe patchado só lê "-f <dir>" com argv exato; log em arquivo (pipe sem dreno trava).
        s.proc = subprocess.Popen([os.path.abspath(args.bin), "-f", "."], cwd=s.dir, stdin=subprocess.DEVNULL,
                                  stdout=open(s.log, "w"), stderr=subprocess.STDOUT)
        procs.append(s.proc)
        end = time.time() + TMO
        while True:
            try:
                s.sock = socket.create_connection(("127.0.0.1", s.ctl), 2); break
            except OSError:
                if time.time() > end: fail(f"{name}: ctrl_tcp não abriu")
                time.sleep(0.3)

    def send(s, cmd, params="", token=None):
        b = json.dumps({"command": cmd, "params": params, "token": token or cmd}).encode()
        try: s.sock.sendall(str(len(b)).encode() + b":" + b + b",")
        except OSError as e: fail(f"{s.name}: ctrl_tcp erro ao enviar {cmd}: {e!r}")

    def pump(s, t):
        s.sock.settimeout(t)
        try:
            d = s.sock.recv(65536)
        except socket.timeout:
            return
        except OSError as e:
            fail(f"{s.name}: ctrl_tcp erro ao ler: {e!r}")
        if not d: fail(f"{s.name}: ctrl_tcp fechou")
        s.buf += d
        while b":" in s.buf:
            n, rest = s.buf.split(b":", 1); n = int(n)
            if len(rest) < n + 1: break
            m = json.loads(rest[:n]); s.buf = rest[n + 1:]
            s.ev.append(m)

    def wait(s, what, pred):
        """Procura em todo o histórico (ordem entre eventos não importa)."""
        end = time.time() + TMO
        while True:
            for m in s.ev:
                if pred(m): return m
            if time.time() > end:
                fail(f"timeout esperando {what} em {s.name}; últimos eventos: "
                     + "; ".join(f"{m.get('type')}:{m.get('param')}:{m.get('localvideodir')}/{m.get('remotevideodir')}" for m in s.ev[-12:]))
            s.pump(0.2)

    def do(s, cmd, params=""):
        """Comando que precisa dar ok: se o baresip recusar, falha na hora com a resposta dele."""
        r = s.ask(cmd, params)
        if not r.get("ok"): fail(f"{s.name}: {cmd} {params!r} recusado: {r.get('data')}")

    def ask(s, cmd, params=""):
        s.n = getattr(s, "n", 0) + 1; tok = f"{cmd}#{s.n}"  # token único: wait() varre o histórico e devolveria a 1ª resposta
        s.send(cmd, params, tok)
        return s.wait(f"resposta de {cmd}", lambda m: m.get("response") and m.get("token") == tok)


def fail(msg):
    print(f"FALHOU: {msg}")
    for u in side.values():
        try: u.proc.wait(timeout=2)  # queda em andamento vira código de saída, não "rodando"
        except subprocess.TimeoutExpired: pass
        rc = u.proc.poll()
        # Windows: crash aparece como 0xC0000005 etc.
        print(f"processo {u.name}: " + ("ainda rodando" if rc is None else f"saiu com código {rc} (0x{rc & 0xFFFFFFFF:08X})"))
    for u in side.values():
        print(f"--- log {u.name} (fim) ---")
        try: print("".join(open(u.log, errors="replace").readlines()[-120:]))
        except OSError: pass
    cleanup(); sys.exit(1)


def cleanup():
    for p in procs:
        p.kill(); p.wait()
    shutil.rmtree(tmp, ignore_errors=True)


def ev(type_, **kw):
    return lambda m: m.get("event") and m.get("type") == type_ and all(m.get(k) == v for k, v in kw.items())


def step(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


a, b = UA("A"), UA("B")
step(f"host SIP {H}; baresip A sip={a.sip} ctrl={a.ctl}; B sip={b.sip} ctrl={b.ctl}")
for u in (a, b): u.send("uanew", f"<sip:{u.name.lower()}@{H}:{u.sip}>;regint=0")
for u in (a, b): u.wait("resposta do uanew", lambda m: m.get("response") and m.get("token") == "uanew")
step("1 uanew nos dois ok")
a.do("dialdir", f"sip:b@{H}:{b.sip} audio=sendrecv video=inactive")
b.wait("CALL_INCOMING", ev("CALL_INCOMING")); b.do("acceptdir", "audio=sendrecv video=inactive")
a.wait("CALL_ESTABLISHED", ev("CALL_ESTABLISHED"))
step("2-3 chamada só áudio estabelecida")
a.do("videodir", "sendrecv")
b.wait("call com local=inactive remote=sendrecv", lambda m: m.get("class") == "call" and m.get("localvideodir") == "inactive" and m.get("remotevideodir") == "sendrecv")
step("4 A ligou vídeo; câmera de B segue desligada (inactive/sendrecv)")
b.do("videodir", "sendrecv")
for u in (a, b): u.wait("CALL_RTPESTAB video", ev("CALL_RTPESTAB", param="video"))
step("5 CALL_RTPESTAB video nos dois lados")
def vdisp(out):
    """(largura, altura, frames, n_keyframes) do rx: 'vidisp: fakevideo W x H frames=N' e 'n_keyframes=K'."""
    m = re.search(r"vidisp: \S+ (\d+) x (\d+) frames=(\d+)", out)
    k = re.search(r"n_keyframes=(\d+)", out)
    return (int(m[1]), int(m[2]), int(m[3]), int(k[1]) if k else None) if m else (0, 0, 0, None)


# video_debug antes do 1º quadro derruba o baresip no MSVC (0xC0000005): vrx/vtx->fmt começam em -1, o enum do MSVC é
# signed e vidfmt_name(-1) indexa fora da tabela (bug do re; o app nunca envia video_debug). Espera o 1º quadro decodificado nos dois lados.
MARK = "video: receiving with resolution"
t0 = time.time()
while any(MARK not in open(u.log, errors="replace").read() for u in (a, b)):
    for u in (a, b):
        if u.proc.poll() is not None: fail(f"{u.name}: processo saiu antes do 1º quadro de vídeo")
    if time.time() - t0 > TMO:
        fail("sem 1º quadro decodificado em " + ", ".join(u.name for u in (a, b) if MARK not in open(u.log, errors="replace").read()))
    time.sleep(0.2)
step(f"6 1º quadro decodificado nos dois lados (após {time.time() - t0:.1f}s)")
t0 = time.time()
for u in (a, b):
    tent = 0
    while True:
        tent += 1
        step(f"6 pedindo video_debug a {u.name} (tentativa {tent})")
        out = str(u.ask("video_debug").get("data"))
        w, h, n, k = vdisp(out)
        if w and h and n > 0: break
        if time.time() - t0 > TMO: fail(f"{u.name} nunca recebeu quadros decodificados; último video_debug:\n{out.strip()}")
        time.sleep(0.5)
    u.dbg = (out, w, h, n, k)
    if "encode: VP8" not in out or "decode: VP8" not in out: fail(f"video_debug de {u.name} não mostra VP8 no encode e no decode")
for u in (a, b):
    step(f"6 video_debug {u.name}:\n{u.dbg[0].strip()}")
for u in (a, b):
    step(f"6 {u.name}: encode/decode VP8, tela {u.dbg[1]}x{u.dbg[2]}, quadros={u.dbg[3]}, n_keyframes={u.dbg[4]} (após {time.time() - t0:.1f}s)")
a.do("hangup")
a.wait("CALL_CLOSED", ev("CALL_CLOSED"))
step("7 hangup ok")
cleanup()
print("VIDEO SMOKE OK")
