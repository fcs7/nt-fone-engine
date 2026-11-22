# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
"""Patches no baresip v4.12.0 aplicados pelo build do motor (main.c, sdl.c, ctrl_tcp, ícone e CMake).

Uso: python patches/apply-baresip-patches.py <dir do baresip> <caminho do ntfone.ico>

Cada patch confere com assert que o trecho original existe uma única vez: se o baresip mudar, o build falha em vez de seguir sem o patch.
O patch do re (patches/patch-re-codec-prio.py) é separado.
"""
import pathlib
import shutil
import sys

if len(sys.argv) != 3:
    sys.exit(__doc__)
root = pathlib.Path(sys.argv[1])
ico = sys.argv[2]

# MSVC não tem getopt.h: sem HAVE_GETOPT o main.c ignora todos os argumentos e o
# baresip lê %APPDATA%\.baresip (ctrl_tcp do nosso config nunca abria). Aceita "-f <dir>".
p = root / "src/main.c"; s = p.read_text()
a = "\ttmr_init(&tmr_quit);\n"
assert s.count(a) == 1, "ponto do patch mudou"
p.write_text(s.replace(a, a + "#ifndef HAVE_GETOPT\n\tif (argc == 3 && 0 == str_cmp(argv[1], \"-f\"))\n\t\tconf_path_set(argv[2]);\n#endif\n"))
# Tecla q na janela de vídeo (sdl) empurra 'q' para a UI, que roda o comando quit e derrubava o motor no meio da chamada.
p = root / "modules/sdl/sdl.c"; s = p.read_text()
a = "\t\t\tcase SDLK_q:\n\t\t\t\tmqueue_push(st->mq, 'q', NULL);\n\t\t\t\tbreak;\n\n"
assert s.count(a) == 1, "ponto do patch do sdl mudou"
p.write_text(s.replace(a, ""))
# ctrl_tcp: qualquer conexão nova derrubava a atual (uma página web no loopback derrubava o app); agora a segunda é recusada.
p = root / "modules/ctrl_tcp/ctrl_tcp.c"; s = p.read_text()
a = "\t/* only one connection allowed */\n\tst->tc = mem_deref(st->tc);\n\tst->ns = mem_deref(st->ns);\n"
assert s.count(a) == 1, "ponto do patch do ctrl_tcp mudou"
p.write_text(s.replace(a, "\t/* only one connection allowed: recusa a nova em vez de derrubar a atual */\n\tif (st->tc) {\n\t\ttcp_reject(st->ts);\n\t\treturn;\n\t}\n\n\tst->ns = mem_deref(st->ns);\n"))
# ctrl_tcp: quadro netstring inválido só descartava o buffer e deixava a conexão aberta; agora fecha.
p = root / "modules/ctrl_tcp/tcp_netstring.c"; s = p.read_text()
a = "\t\t\t\tnetstring->mb = mem_deref(netstring->mb);\n\t\t\t}\n\n\t\t\treturn false;\n"
assert s.count(a) == 1, "ponto do patch do netstring mudou"
p.write_text(s.replace(a, "\t\t\t\tnetstring->mb = mem_deref(netstring->mb);\n\t\t\t\t*errp = EBADMSG;\n\t\t\t\treturn true;\n\t\t\t}\n\n\t\t\treturn false;\n"))
# Ícone do NT-Fone no baresip.exe: o SDL usa o ícone do executável na janela de vídeo e na barra de tarefas.
shutil.copyfile(ico, root / "src/ntfone.ico")
(root / "src/ntfone.rc").write_text('1 ICON "ntfone.ico"\n')
p = root / "CMakeLists.txt"; s = p.read_text()
a = "add_executable(baresip_exe src/main.c)\n"
assert s.count(a) == 1, "ponto do patch do CMake mudou"
p.write_text(s.replace(a, "enable_language(RC)\nadd_executable(baresip_exe src/main.c src/ntfone.rc)\n"))
