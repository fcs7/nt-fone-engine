# Componentes de terceiros

Este arquivo lista o que entra no `baresip.exe` e no `SDL2.dll` produzidos pelo workflow `.github/workflows/windows.yml`.
Versões, tags e hashes vêm do próprio workflow; o commit de cada componente foi conferido nos repositórios oficiais em 2026-11-19.
O que não pôde ser confirmado está marcado "a confirmar". Cada release traz um `build-manifest.txt` com as versões e os hashes
realmente usados naquele build, e o código-fonte de todos os componentes abaixo está em `nt-fone-engine-source.tar.gz`.

Os textos de licença estão em [`licenses/`](licenses/); de onde cada um veio (URL, commit e SHA-256) está em
[`licenses/ORIGENS.txt`](licenses/ORIGENS.txt).

## Componentes distribuídos

| Componente | Versão / tag | Commit | Licença | Upstream | Como entra | Licença em `licenses/` |
|---|---|---|---|---|---|---|
| baresip | v4.12.0 | `9cfab81550acc4bd38d6580d79b45cc6eea65cd6` | BSD-3-Clause | https://github.com/baresip/baresip | É o `baresip.exe` (com os módulos próprios e os patches deste repositório) | `licenses/baresip/LICENSE` |
| re (libre) | v4.12.0 | `65555dad439de9d6a81b3ee6092b9c096585249b` | BSD-3-Clause | https://github.com/baresip/re | Ligado estaticamente ao `baresip.exe`, com o patch `patches/patch-re-codec-prio.py` | `licenses/re/LICENSE` |
| Opus | v1.5.2 | `ddbe48383984d56acd9e1ab6a090c54ca6b735a6` | BSD-3-Clause, mais concessões de patente (ver `COPYING`) | https://github.com/xiph/opus | Ligado estaticamente ao `baresip.exe` | `licenses/opus/COPYING` |
| bcg729 | 1.1.1 | `faaa895862165acde6df8add722ba4f85a25007d` | GPL-3.0-or-later (cabeçalho de `src/encoder.c` conferido); a Belledonne também a vende sob licença comercial, que não é a usada aqui | https://github.com/BelledonneCommunications/bcg729 | Ligado estaticamente ao `baresip.exe` pelo módulo `g729`. É o motivo de o `baresip.exe` ser distribuído sob a GPLv3 | `licenses/bcg729/LICENSE.txt` e `licenses/bcg729/README.md` (trecho "Licensing") |
| OpenSSL | 4.0.3 | `af1775b60dfa141a4ad762585052cabeb9f37e9e` (tag `openssl-4.0.3`) | Apache-2.0 | https://github.com/openssl/openssl | `libssl`/`libcrypto` estáticas, vindas do `openssl-windows-x64.zip` pré-compilado (ver abaixo), ligadas ao `baresip.exe` | `licenses/openssl/LICENSE.txt` |
| SDL2 | 2.32.10 | `5d249570393f7a37e037abf22cd6012a4cc56a71` (tag `release-2.32.10`) | zlib | https://github.com/libsdl-org/SDL | **Ao lado do executável**: `SDL2.dll` (ligação dinâmica), copiada do `SDL2-devel-2.32.10-VC.zip` oficial (SHA-256 `AF347939395A58B365846AAEA27391E69F9EC9D4DD650D6AC40802159B418A6E`, conferido no workflow) | `licenses/SDL2/LICENSE.txt` |
| libvpx | Não fixada: é a versão da porta do vcpkg no runner `windows-2022` no momento do build. Em 2026-11-19 a porta do vcpkg estava em 1.16.0 (port-version 3). A confirmar no `build-manifest.txt` de cada release | Não fixado (a confirmar) | BSD-3-Clause (`LICENSE`) com concessão de patentes (`PATENTS`). A porta do vcpkg declara "BSD-3-Clause AND ISC" | https://github.com/webmproject/libvpx | Ligado estaticamente ao `baresip.exe` (triplet `x64-windows-static-md`). O vcpkg aplica patches da própria porta, que vão no pacote de fontes em `vcpkg-port-libvpx-<versão>.tar.gz` | `licenses/libvpx/LICENSE` e `licenses/libvpx/PATENTS` (da tag v1.16.0; o tarball do libvpx no pacote de fontes traz os da versão exata) |

## Origem do binário do OpenSSL

O workflow não compila o OpenSSL: baixa o `openssl-windows-x64.zip` do release `v2026.10.0` de
https://github.com/baresip/tools (commit do tag `7c8f609b1381f9b3342af86b61b27e35fd3f70bf`) e confere o SHA-256
(`35dcf7d7dc47c7557f89c58202de031be0bbdd3854ed4f13270ebc9342adab07`) e a versão lida em `opensslv.h` (4.0.3). O arquivo é a saída do workflow
`.github/workflows/build.yml` daquele tag, que compila o OpenSSL a partir do tarball oficial com
`perl Configure VC-WIN64A no-shared no-deprecated no-tests no-makedepend` seguido de `nmake build_libs` e `nmake install_dev` (MSVC 2022, NASM).
Essa receita foi lida no repositório em 2026-11-19; que o zip do release tenha sido produzido exatamente por ela é **a confirmar**.
O repositório `baresip/tools` não declara licença, por isso o conteúdo dele **não** é redistribuído aqui nem no pacote de fontes.
O código-fonte do OpenSSL 4.0.3 (tarball oficial, conferido com o `.sha256` publicado pelo projeto) vai em `nt-fone-engine-source.tar.gz`.

## Código deste repositório

`baresip-modules/ntaudio`, `baresip-modules/g729`, `patches/`, `scripts/` e o workflow: GPL-3.0-or-later, Copyright (C) 2026 NTWeb
(identificador SPDX no topo de cada arquivo). O texto da licença está em [`LICENSE`](LICENSE).
`assets/ntfone.ico` (ícone da marca) não é licenciado por este repositório além do necessário para recompilar o `baresip.exe`: ver "Marca" no [README](README.md).

## Outros itens

- **Sons** (`sounds.zip`): são os `share/*.wav` do baresip v4.12.0 (commit `9cfab81550acc4bd38d6580d79b45cc6eea65cd6`). O repositório do baresip está sob BSD-3-Clause; a licença individual de cada arquivo de áudio é **a confirmar**.
- **Bibliotecas de sistema e runtime**: o `baresip.exe` importa DLLs do Windows e o runtime do Visual C++ (`vcruntime140*.dll`, `api-ms-win-crt-*`), conforme o gate de dependências do workflow. Elas não fazem parte deste repositório nem das releases.
- **Ferramentas de build** (não distribuídas): MSVC 2022, CMake, Ninja, Git, Python, 7-Zip, PowerShell e o vcpkg (que usa NASM e MSYS2 para compilar o libvpx).
