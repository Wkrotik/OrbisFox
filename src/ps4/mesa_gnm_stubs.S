// SPDX-License-Identifier: MIT
// Static PLT only: r11 is SysV caller-saved; tail jumps preserve integer/vector/
// stack arguments and genuine returns. No generated CPU code or JIT arena.
// Bind every executable target before any Mesa call. Missing targets trap;
// they never fabricate success or jump to null.
.section .text.orbis_mesa_gnm,"ax",@progbits
#define ORBIS_MESA_GNM(index, name) \
 .p2align 4; .globl name; .hidden name; .type name,@function; \
 name: mov orbis_mesa_gnm_targets+index*8(%rip),%r11; test %r11,%r11; \
 jz 1f; jmp *%r11; 1: ud2; .size name,.-name;
#include "orbisfox/mesa_gnm_symbols.inc"
#undef ORBIS_MESA_GNM
.section .note.GNU-stack,"",@progbits
