#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
"""Smoke de G.729: dois baresip, contas só com audio_codecs=g729/8000, chamada de ~3 s com tom de 440 Hz.
Exige G729 no encoder e no decoder dos dois lados (texto do audio_debug do baresip),
nenhum erro de encode/decode no log, o tom decodificado de verdade no WAV recebido e os dois processos vivos.
Negociar G729 não prova nada sozinho: um decoder que devolve erro em todo pacote também passaria.
Uso: g729-smoke.py <baresip> [--modules <dir>] [--host <ip>]  (stdlib; roda em Windows e Linux)"""
import argparse, array, json, os, random, re, shutil, socket, subprocess, sys, tempfile, time

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


H, TMO, TONE = args.host or local_ip(), 15, 440
tmp = tempfile.mkdtemp(prefix="g729smoke")
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
        # Sem placa de som: ausine é a fonte (tom) e aufile grava o que chega num WAV, como Audio::Test do core.
        # Caminhos relativos ao cwd do processo (o baresip trunca valores do config no primeiro espaço).
        mods = ["g729", "ausine", "aufile", "auconv", "auresamp"]
        cfg = (f"module_path {args.modules}\n" if args.modules else "") + (
            f"sip_listen {H}:{s.sip}\nctrl_tcp_listen 127.0.0.1:{s.ctl}\n"
            f"audio_player aufile,rx.wav\naudio_source ausine,{TONE}\naudio_alert aufile,alert.wav\n"
            "ring_aufile none\nringback_disabled yes\nringback_aufile none\n"
            + "".join(f"module {m}.so\n" for m in mods) + "module_app menu.so\nmodule_app ctrl_tcp.so\n")
        open(os.path.join(s.dir, "config"), "w").write(cfg)
        s.log = os.path.join(tmp, name + ".log")
        s.wav = os.path.join(s.dir, "rx.wav")
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
                     + "; ".join(f"{m.get('type')}:{m.get('param')}" for m in s.ev[-12:]))
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


def tone(path):
    """(pico, amostras altas, Hz estimado) do WAV gravado pelo aufile. Cabeçalho de 44 bytes: tamanhos do 'data' não são confiáveis com o arquivo aberto."""
    raw = open(path, "rb").read()
    i = raw.find(b"data")
    if i < 0: return 0, 0, 0.0
    pcm = array.array("h"); pcm.frombytes(raw[i + 8:][: (len(raw) - i - 8) // 2 * 2])
    if sys.byteorder == "big": pcm.byteswap()
    loud = sum(1 for x in pcm if abs(x) > 500)
    # Frequência: cruzamentos de zero na janela de 0,5 s com mais energia (esconde o silêncio inicial do buffer de jitter).
    w, best, hz = 4000, -1, 0.0
    for a in range(0, max(len(pcm) - w, 0) + 1, 400):
        seg = pcm[a:a + w]
        if len(seg) < w: break
        e = sum(x * x for x in seg)
        if e > best:
            best, hz = e, sum(1 for p, q in zip(seg, seg[1:]) if (p < 0) != (q < 0)) / 2 / (w / 8000)
    return max((abs(x) for x in pcm), default=0), loud, hz


a, b = UA("A"), UA("B")
step(f"host SIP {H}; baresip A sip={a.sip} ctrl={a.ctl}; B sip={b.sip} ctrl={b.ctl}")
for u in (a, b): u.send("uanew", f"<sip:{u.name.lower()}@{H}:{u.sip}>;regint=0;audio_codecs=g729/8000")
for u in (a, b): u.wait("resposta do uanew", lambda m: m.get("response") and m.get("token") == "uanew")
step("1 uanew nos dois (só g729/8000)")
a.do("dial", f"sip:b@{H}:{b.sip}")
b.wait("CALL_INCOMING", ev("CALL_INCOMING")); b.do("accept")
for u in (a, b): u.wait("CALL_ESTABLISHED", ev("CALL_ESTABLISHED"))
step("2 chamada estabelecida")
for u in (a, b): u.wait("CALL_RTPESTAB audio", ev("CALL_RTPESTAB", param="audio"))
step("3 CALL_RTPESTAB audio nos dois lados; deixando o RTP correr 3 s")
t0 = time.time()
while time.time() - t0 < 3:
    for u in (a, b):
        if u.proc.poll() is not None: fail(f"{u.name}: processo saiu durante o RTP")
        u.pump(0.1)
# O decoder só aparece no audio_debug depois do 1º pacote recebido: repete até aparecer.
for u in (a, b):
    t1 = time.time()
    while True:
        out = str(u.ask("audio_debug").get("data"))
        # "<nome> 8000Hz/1ch": sem codec o baresip imprime só "ptime=..." / o formato, que não casa e o laço tenta de novo.
        enc = re.search(r"encode:\s*(\S+) \d+Hz", out); dec = re.search(r"decode:\s*(\S+) \d+Hz", out)
        if enc and dec: break
        if time.time() - t1 > TMO: fail(f"{u.name}: audio_debug sem encode/decode:\n{out.strip()}")
        time.sleep(0.5)
    step(f"4 audio_debug {u.name}:\n{out.strip()}")
    if enc[1].lower() != "g729" or dec[1].lower() != "g729":
        fail(f"{u.name}: esperava G729 no encode e no decode, veio encode={enc[1]} decode={dec[1]}")
a.do("hangup")
for u in (a, b): u.wait("CALL_CLOSED", ev("CALL_CLOSED"))
time.sleep(0.5)  # o aufile fecha (e acerta o cabeçalho) ao parar o stream
step("5 hangup ok nos dois lados")
for u in (a, b):
    if u.proc.poll() is not None: fail(f"{u.name}: processo morreu")
    # Erros de encode/decode/PLC do codec no log (warning do baresip: "audio: G729 encode error", "audio_recv: G729 codec decode ...").
    bad = [l for l in open(u.log, errors="replace") if re.search(r"G729 (encode error|codec decode|codec PLC)", l, re.I)]
    if bad: fail(f"{u.name}: erros do codec G729 no log: {bad[:3]}")
    pico, altas, hz = tone(u.wav)
    step(f"6 {u.name}: WAV recebido pico={pico} amostras_altas={altas} tom~{hz:.0f} Hz")
    # G.729 é com perdas, mas um tom puro de 440 Hz tem de sair como tom: energia real e a frequência certa.
    if pico < 3000 or altas < 4000: fail(f"{u.name}: áudio decodificado fraco/silencioso (pico={pico}, altas={altas})")
    if not 0.85 * TONE <= hz <= 1.15 * TONE: fail(f"{u.name}: tom decodificado em {hz:.0f} Hz, esperado ~{TONE} Hz")
cleanup()
print("G729 SMOKE OK")
