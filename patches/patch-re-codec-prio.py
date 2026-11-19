# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
"""Patch no re (src/sdp/media.c): escolha de codec pela prioridade local, não pela ordem da oferta.

Sem isto, quem atende repete a ordem do outro lado: o PBX NT-Fone oferece PCMU primeiro nas
chamadas recebidas e o baresip fechava em G.711 mesmo com Opus na oferta. Com o patch, a
prioridade é a ordem dos módulos no config (opus antes de g711, no config de quem usa este motor):
  1. a resposta lista os codecs na nossa ordem (não reordena para a da oferta);
  2. sdp_media_rformat(m, NULL), que o baresip usa para escolher o codificador, devolve o
     primeiro codec nosso que a outra ponta também ofereceu;
  3. a resposta leva só esse codec (+ telephone-event), para as duas pontas usarem o mesmo.
G.711 continua aceito quando é o único em comum.

shortcut: o re joga para o fim da lista local os codecs que a oferta não trouxe; se o primeiro
INVITE vier sem Opus e um re-INVITE da mesma chamada o trouxer, PCMU segue ganhando nessa
chamada. Corrigir só se aparecer na prática (reordenar lfmtl pela ordem de registro).

Uso: python patch-re-codec-prio.py <caminho do re>
"""
import pathlib
import sys

p = pathlib.Path(sys.argv[1]) / "src/sdp/media.c"
s = p.read_text(encoding="utf-8")

prepend = "\t\t\tlist_unlink(&lfmt->le);\n\t\t\tlist_prepend(&m->lfmtl, &lfmt->le, lfmt);\n"
assert s.count(prepend) == 1, "ponto do patch (align_formats) mudou"
s = s.replace(prepend, "")

head = (
    "\tif (!m || !sa_port(&m->raddr))\n"
    "\t\treturn NULL;\n"
    "\n"
    "\tfor (le=m->rfmtl.head; le; le=le->next) {\n"
)
assert s.count(head) == 1, "ponto do patch (rformat) mudou"
local_first = (
    "\tif (!m || !sa_port(&m->raddr))\n"
    "\t\treturn NULL;\n"
    "\n"
    "\t/* nt-fone: prioridade local (ordem dos modulos), nao a ordem da oferta */\n"
    "\tif (!name) {\n"
    "\t\tfor (le=m->lfmtl.head; le; le=le->next) {\n"
    "\t\t\tconst struct sdp_format *lf = le->data;\n"
    "\t\t\tstruct le *rl;\n"
    "\n"
    "\t\t\tif (!lf->sup)\n"
    "\t\t\t\tcontinue;\n"
    "\n"
    "\t\t\tfor (rl=m->rfmtl.head; rl; rl=rl->next) {\n"
    "\t\t\t\tconst struct sdp_format *rf = rl->data;\n"
    "\n"
    "\t\t\t\tif (rf->sup && sdp_format_cmp(lf, rf))\n"
    "\t\t\t\t\treturn rf;\n"
    "\t\t\t}\n"
    "\t\t}\n"
    "\n"
    "\t\treturn NULL;\n"
    "\t}\n"
    "\n"
    "\tfor (le=m->rfmtl.head; le; le=le->next) {\n"
)
s = s.replace(head, local_first)

# 3. Ao responder, um codec só (o de maior prioridade local) + telephone-event. Sem isto quem
#    ofereceu escolhe pela própria ordem e manda PCMU enquanto nós mandamos Opus; e o baresip
#    descarta esse PCMU se ele chegar antes do audio_update (rx->pt já visto, decoder forçado
#    para opus): áudio de mão única, medido com dois baresip 4.12.0.
tail = "\t\t\t\tlist_append(&m->lfmtl, &lfmt->le, lfmt);\n\t\t\t}\n\t\t}\n\t}\n}\n"
assert s.count(tail) == 1, "ponto do patch (align_formats, fim) mudou"
single = (
    "\t\t\t\tlist_append(&m->lfmtl, &lfmt->le, lfmt);\n\t\t\t}\n\t\t}\n\t}\n"
    "\n"
    "\t/* nt-fone: na resposta, so o codec de maior prioridade local + telephone-event */\n"
    "\tif (offer) {\n"
    "\t\tbool chosen = false;\n"
    "\n"
    "\t\tfor (lle = m->lfmtl.head; lle; lle = lle->next) {\n"
    "\t\t\tlfmt = lle->data;\n"
    "\t\t\tif (!lfmt->sup || !str_casecmp(lfmt->name, \"telephone-event\"))\n"
    "\t\t\t\tcontinue;\n"
    "\t\t\tif (chosen)\n"
    "\t\t\t\tlfmt->sup = false;\n"
    "\t\t\tchosen = true;\n"
    "\t\t}\n"
    "\n"
    "\t\tfor (rle = m->rfmtl.head; rle; rle = rle->next) {\n"
    "\t\t\tbool keep = false;\n"
    "\n"
    "\t\t\trfmt = rle->data;\n"
    "\t\t\tif (!rfmt->sup)\n"
    "\t\t\t\tcontinue;\n"
    "\t\t\tfor (lle = m->lfmtl.head; lle; lle = lle->next) {\n"
    "\t\t\t\tlfmt = lle->data;\n"
    "\t\t\t\tif (lfmt->sup && sdp_format_cmp(lfmt, rfmt)) {\n"
    "\t\t\t\t\tkeep = true;\n"
    "\t\t\t\t\tbreak;\n"
    "\t\t\t\t}\n"
    "\t\t\t}\n"
    "\t\t\trfmt->sup = keep;\n"
    "\t\t}\n"
    "\t}\n"
    "}\n"
)
s = s.replace(tail, single)
p.write_text(s, encoding="utf-8")
print("re: patch de prioridade de codec aplicado")
