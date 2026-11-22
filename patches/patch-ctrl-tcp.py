# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
"""Patches no módulo ctrl_tcp do baresip (modules/ctrl_tcp/ctrl_tcp.c e tcp_netstring.c).

  1. com um cliente conectado, a conexão nova é recusada em vez de substituir a atual;
  2. quadro netstring inválido fecha a conexão.

Cada patch confere com assert que o trecho original existe uma única vez: se o baresip mudar,
o build falha em vez de seguir sem o patch.

Uso: python patch-ctrl-tcp.py <caminho do baresip>
"""
import pathlib
import sys

if len(sys.argv) != 2:
    sys.exit(__doc__)
root = pathlib.Path(sys.argv[1])

# ctrl_tcp: com um cliente conectado, a conexão nova é recusada em vez de substituir a atual.
p = root / "modules/ctrl_tcp/ctrl_tcp.c"; s = p.read_text()
a = "\t/* only one connection allowed */\n\tst->tc = mem_deref(st->tc);\n\tst->ns = mem_deref(st->ns);\n"
assert s.count(a) == 1, "ponto do patch do ctrl_tcp mudou"
p.write_text(s.replace(a, "\t/* only one connection allowed: recusa a nova em vez de substituir a atual */\n\tif (st->tc) {\n\t\ttcp_reject(st->ts);\n\t\treturn;\n\t}\n\n\tst->ns = mem_deref(st->ns);\n"))
# ctrl_tcp: quadro netstring inválido fecha a conexão.
p = root / "modules/ctrl_tcp/tcp_netstring.c"; s = p.read_text()
a = "\t\t\t\tnetstring->mb = mem_deref(netstring->mb);\n\t\t\t}\n\n\t\t\treturn false;\n"
assert s.count(a) == 1, "ponto do patch do netstring mudou"
p.write_text(s.replace(a, "\t\t\t\tnetstring->mb = mem_deref(netstring->mb);\n\t\t\t\t*errp = EBADMSG;\n\t\t\t\treturn true;\n\t\t\t}\n\n\t\t\treturn false;\n"))
