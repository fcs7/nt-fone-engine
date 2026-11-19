# NT-Fone engine

Motor SIP do softphone NT-Fone: o [baresip](https://github.com/baresip/baresip) v4.12.0 compilado para Windows (MSVC, x64) com dois módulos próprios (`ntaudio` e `g729`), alguns patches e a configuração de build usada nos instaladores do NT-Fone.

Este repositório existe para dar a quem recebe o instalador do NT-Fone o **código-fonte correspondente** do `baresip.exe` que vai nele, como exige a GNU GPL v3.

## Relação com o app NT-Fone

O aplicativo NT-Fone é um programa separado. Ele inicia o `baresip.exe` deste repositório como processo próprio e conversa com ele por um socket TCP local (módulo `ctrl_tcp` do baresip). O app não faz parte deste repositório.

## Licença

O código deste repositório é distribuído sob a **GNU GPL v3 ou posterior** (ver [`LICENSE`](LICENSE)), Copyright (C) 2026 NTWeb.

O motivo: o `baresip.exe` liga estaticamente a biblioteca [bcg729](https://github.com/BelledonneCommunications/bcg729) (codec G.729), que é GPLv3 (a Belledonne também a vende sob licença comercial, que não usamos). O executável resultante é, portanto, uma obra combinada sob a GPLv3, e quem o recebe tem direito ao código-fonte completo, incluindo os scripts de build.

Os demais componentes (baresip, re, Opus, OpenSSL, SDL2, libvpx) têm licenças próprias e compatíveis. A lista completa, com versões, commits e textos de licença, está em [`THIRD_PARTY.md`](THIRD_PARTY.md) e em [`licenses/`](licenses/).

## Como obter o código-fonte correspondente de uma versão do instalador

Cada release deste repositório publica estes arquivos:

| Arquivo | O que é |
|---|---|
| `baresip.exe`, `SDL2.dll`, `sounds.zip` | O que o workflow compilou |
| `nt-fone-engine-source.tar.gz` | O código-fonte correspondente completo |
| `SHA256SUMS` | Somas SHA-256 de `baresip.exe`, `SDL2.dll`, `sounds.zip` e do tarball de fontes |
| `build-manifest.txt` | Versão e commit de cada componente, hashes dos arquivos baixados e do `baresip.exe` |

Para achar o código-fonte do `baresip.exe` de um instalador:

1. Calcule o SHA-256 do `baresip.exe` instalado (PowerShell: `Get-FileHash baresip.exe -Algorithm SHA256`; Linux: `sha256sum baresip.exe`).
2. Procure esse hash no `SHA256SUMS` (ou no `build-manifest.txt`) das releases deste repositório.
3. Baixe `nt-fone-engine-source.tar.gz` e `SHA256SUMS` dessa mesma release e confira: `sha256sum -c SHA256SUMS --ignore-missing`.
4. Dentro do tarball: `nt-fone-engine/` (este repositório no commit da release), `third-party/` (o código-fonte de re, baresip, Opus, bcg729, OpenSSL, SDL2 e libvpx nas versões usadas, mais a pasta da porta do vcpkg que compilou o libvpx) e `build-manifest.txt`.

Se o hash do seu `baresip.exe` não aparecer em nenhuma release, ou se algo faltar, use a oferta escrita abaixo.

## Como compilar

### Pelo workflow (recomendado)

No GitHub, aba **Actions**, workflow **windows**, **Run workflow**. O campo `release_tag` é opcional: vazio, o run só gera artefatos (`baresip-windows-x64` e `release-assets`); preenchido com uma tag que ainda não existe, o run também cria a release com todos os arquivos da tabela acima.

O workflow faz o build, roda os smokes (ctrl_tcp com `-f`, presença dos módulos opus, vp8, sdl, ntaudio e g729, chamada de vídeo VP8 e chamada G.729 entre dois `baresip.exe`) e um gate de dependências (só DLLs do sistema, runtime do VC++ e `SDL2.dll`). Se uma fonte de terceiros não puder ser obtida e conferida, o run falha em vez de gerar um pacote incompleto.

### Manualmente no Windows

Os comandos abaixo repetem o que o workflow faz; em caso de dúvida, o workflow ([`.github/workflows/windows.yml`](.github/workflows/windows.yml)) é a referência.

Requisitos: Windows x64, Visual Studio 2022 com o toolset MSVC x64, CMake, Ninja, Git, Python 3, 7-Zip, [vcpkg](https://github.com/microsoft/vcpkg) e `curl`. Escolha um diretório de trabalho vazio e deixe este repositório em `engine\` dentro dele (ou use a pasta `nt-fone-engine\` do tarball de fontes, renomeada para `engine`).

**1. Fontes do baresip, re, Opus e bcg729 e patches** (Git Bash ou PowerShell):

```sh
git clone --depth 1 -b v4.12.0 https://github.com/baresip/re re
git clone --depth 1 -b v4.12.0 https://github.com/baresip/baresip baresip
git clone --depth 1 -b v1.5.2 https://github.com/xiph/opus opus
git clone --depth 1 -b 1.1.1 https://github.com/BelledonneCommunications/bcg729 bcg729
git -C bcg729 rev-parse HEAD   # tem de ser faaa895862165acde6df8add722ba4f85a25007d
python engine/patches/patch-re-codec-prio.py re
python engine/patches/apply-baresip-patches.py baresip engine/assets/ntfone.ico
```

(Em vez de clonar, dá para extrair os tarballs de `third-party/` do pacote de fontes e renomear as pastas para `re`, `baresip`, `opus` e `bcg729`.)

**2. OpenSSL estático.** O workflow usa o `openssl-windows-x64.zip` do release `v2026.10.0` de [baresip/tools](https://github.com/baresip/tools/releases/tag/v2026.10.0) (OpenSSL 4.0.3, SHA-256 em `.github/workflows/windows.yml`). Você pode usá-lo ou compilar o OpenSSL 4.0.3 do tarball oficial (ver `THIRD_PARTY.md`) com `perl Configure VC-WIN64A no-shared no-deprecated no-tests no-makedepend`, e apontar `OPENSSL_ROOT_DIR` para o resultado:

```bat
curl -fsSL -o openssl.zip https://github.com/baresip/tools/releases/download/v2026.10.0/openssl-windows-x64.zip
7z x openssl.zip
set "OPENSSL_ROOT_DIR=%CD%\openssl-windows-x64"
```

**3. libvpx e SDL2.**

```bat
vcpkg install libvpx:x64-windows-static-md
set "VPX_INCLUDE_DIR=<raiz do vcpkg>/installed/x64-windows-static-md/include"
set "VPX_LIBRARY=<raiz do vcpkg>/installed/x64-windows-static-md/lib/vpx.lib"
```

O nome da biblioteca varia (`vpx.lib` ou `vpxmd.lib`): use o que existir em `lib\`. Do `SDL2-devel-2.32.10-VC.zip` da [release release-2.32.10 do SDL](https://github.com/libsdl-org/SDL/releases/tag/release-2.32.10), copie os `include\*.h` para `sdl2\include\SDL2\` e `lib\x64\SDL2.lib` e `lib\x64\SDL2.dll` para `sdl2\lib\`; depois `set "SDL_HINTS=%CD:\=/%/sdl2"`.

**4. Compilar** (Prompt de Comando; a primeira linha carrega o ambiente do MSVC):

```bat
call "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
cmake -S re -B re/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DOPENSSL_USE_STATIC_LIBS=TRUE
cmake --build re/build -j
set "OPUS_INST=%CD:\=/%/opus-inst"
cmake -S opus -B opus/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DOPUS_BUILD_PROGRAMS=OFF -DOPUS_BUILD_TESTING=OFF "-DCMAKE_INSTALL_PREFIX=%OPUS_INST%"
cmake --build opus/build -j
cmake --install opus/build
set "BCG729_INST=%CD:\=/%/bcg729-inst"
cmake -S bcg729 -B bcg729/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=NO -DENABLE_STATIC=YES -DENABLE_TESTS=NO -DCMAKE_POLICY_VERSION_MINIMUM=3.5 "-DCMAKE_INSTALL_PREFIX=%BCG729_INST%"
cmake --build bcg729/build -j
cmake --install bcg729/build
set "APP_MODS=%CD:\=/%/engine/baresip-modules"
cd baresip
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DSTATIC=ON -DOPENSSL_USE_STATIC_LIBS=TRUE "-DOPUS_HINTS=%OPUS_INST%" "-DBCG729_HINTS=%BCG729_INST%" "-DVPX_INCLUDE_DIR=%VPX_INCLUDE_DIR%" "-DVPX_LIBRARY=%VPX_LIBRARY%" "-DSDL_HINTS=%SDL_HINTS%" "-DAPP_MODULES_DIR=%APP_MODS%" "-DAPP_MODULES=ntaudio;g729" "-DMODULES=menu;ctrl_tcp;opus;g711;vp8;vp9;wasapi;dshow;sdl;selfview;srtp;auconv;auresamp;fakevideo;ausine;aufile"
cmake --build build -j --target baresip_exe
```

O resultado é `baresip\build\baresip.exe`; o `SDL2.dll` (em `sdl2\lib\`) precisa ficar ao lado dele, e os sons estão em `baresip\share\*.wav`. Os módulos `fakevideo`, `ausine` e `aufile` existem só para os smokes. Para rodá-los, com `baresip.exe` e `SDL2.dll` juntos numa pasta: `python engine\scripts\video-smoke.py <pasta>\baresip.exe` e `python engine\scripts\g729-smoke.py <pasta>\baresip.exe`.

Um build local não é byte a byte igual ao da release: o hash do `baresip.exe` só vale para o arquivo publicado.

## O que há neste repositório

| Caminho | Conteúdo |
|---|---|
| `baresip-modules/ntaudio/` | Módulo do baresip: ganho de microfone e de alto-falante, troca de dispositivo de áudio e de câmera durante a chamada, teste de áudio e toque de chamada recebida sintetizado |
| `baresip-modules/g729/` | Módulo do baresip: codec G.729 (RFC 3551, RFC 4856) sobre a libbcg729 |
| `patches/patch-re-codec-prio.py` | Patch no `re` (`src/sdp/media.c`): o codec é escolhido pela prioridade local, não pela ordem da oferta |
| `patches/apply-baresip-patches.py` | Patches no baresip: `-f <dir>` no `main.c` (MSVC não tem `getopt.h`), remoção da tecla `q` no módulo `sdl`, ícone no `baresip.exe` e `enable_language(RC)` no CMake |
| `scripts/` | Smokes usados pelo workflow (`video-smoke.py`, `g729-smoke.py`) |
| `assets/ntfone.ico` | Ícone embutido no `baresip.exe` |
| `.github/workflows/windows.yml` | Build, smokes, manifesto, pacote de fontes e release |
| `licenses/`, `THIRD_PARTY.md` | Licenças e lista de componentes de terceiros |

## Oferta escrita de código-fonte (GPLv3 §6)

O código-fonte correspondente completo de cada versão do `baresip.exe` que distribuímos com o instalador do NT-Fone fica disponível neste repositório e nos arquivos das releases (`nt-fone-engine-source.tar.gz`), pelo menos durante 3 anos depois da última vez que distribuirmos a versão correspondente e, se for mais longo, enquanto oferecermos suporte ao produto, como prevê a GPLv3 §6(b).

Quem recebeu um instalador pode pedir o código-fonte correspondente a qualquer momento abrindo uma **issue neste repositório** com a versão do instalador (ou o SHA-256 do `baresip.exe`). Esta oferta vale para qualquer terceiro que tenha recebido o instalador.

## Aviso

Este texto é informativo e não substitui orientação jurídica.

## Marca

Os nomes NT-Fone e NTWeb, os logotipos e o ícone `assets/ntfone.ico` não são licenciados por este repositório, além do necessário para recompilar o `baresip.exe`.
