# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
"""Patch no re (rem/vid/fmt.c): vidfmt_name() recusa formato negativo.

vtx->fmt e vrx->fmt do baresip começam em (enum vidfmt)-1. O re só testa fmt >= VID_FMT_N: no GCC o enum
é sem sinal e -1 cai em "???"; no MSVC o enum é int com sinal, -1 passa no teste e lê vidfmt_descv[-1]
(0xC0000005 no video_debug antes do 1º quadro). O cast para unsigned cobre os dois compiladores.
Idempotente; falha alto se o trecho esperado não existir.

Uso: python patch-re-vidfmt-name.py <caminho do re>
"""
import pathlib
import sys

p = pathlib.Path(sys.argv[1]) / "rem/vid/fmt.c"
s = p.read_text(encoding="utf-8")

new = "\tif ((unsigned)fmt >= VID_FMT_N)\n\t\treturn \"???\";\n"
if new in s:
    print("re: patch do vidfmt_name ja aplicado")
    sys.exit(0)
old = "\tif (fmt >= VID_FMT_N)\n\t\treturn \"???\";\n"
assert s.count(old) == 1, "ponto do patch (vidfmt_name) mudou"
p.write_text(s.replace(old, new), encoding="utf-8")
print("re: patch do vidfmt_name aplicado")
