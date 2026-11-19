# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
project(g729)

# libbcg729 (Belledonne), estática: o CI a compila e passa -DBCG729_HINTS=<prefixo de instalação>.
find_path(BCG729_INCLUDE_DIR
  NAMES bcg729/encoder.h
  HINTS "${BCG729_HINTS}/include"
  PATHS /usr/local/include /usr/include
)

find_library(BCG729_LIBRARY
  NAMES bcg729 libbcg729
  HINTS "${BCG729_HINTS}/lib" "${BCG729_HINTS}/lib64"
  PATHS /usr/local/lib /usr/lib
)

if(NOT BCG729_INCLUDE_DIR OR NOT BCG729_LIBRARY)
  # Como o opus: não registra o módulo. Via APP_MODULES o CMake do baresip ainda lista
  # "g729" em MODULES_DETECTED e aborta o configure (set_target_properties sem alvo): falha alta, não silenciosa.
  message(WARNING "g729: libbcg729 não encontrada (passe -DBCG729_HINTS=<prefixo>); módulo g729 não será construído")
  return()
endif()

list(APPEND MODULES_DETECTED ${PROJECT_NAME})
set(MODULES_DETECTED ${MODULES_DETECTED} PARENT_SCOPE)

set(SRCS g729.c)

if(STATIC)
    add_library(${PROJECT_NAME} OBJECT ${SRCS})
else()
    add_library(${PROJECT_NAME} MODULE ${SRCS})
endif()

target_include_directories(${PROJECT_NAME} PRIVATE ${BCG729_INCLUDE_DIR})
target_link_libraries(${PROJECT_NAME} PRIVATE ${BCG729_LIBRARY})
# Linkagem estática: sem isto o header do bcg729 gera dllimport no Windows e o link quebra.
target_compile_definitions(${PROJECT_NAME} PRIVATE BCG729_STATIC)
