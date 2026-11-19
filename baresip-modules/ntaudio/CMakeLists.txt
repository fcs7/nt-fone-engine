# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NTWeb
project(ntaudio)

list(APPEND MODULES_DETECTED ${PROJECT_NAME})
set(MODULES_DETECTED ${MODULES_DETECTED} PARENT_SCOPE)

set(SRCS ntaudio.c)

if(STATIC)
    add_library(${PROJECT_NAME} OBJECT ${SRCS})
else()
    add_library(${PROJECT_NAME} MODULE ${SRCS})
endif()
