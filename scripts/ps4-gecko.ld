# SPDX-License-Identifier: GPL-3.0-only
# Full-Gecko variant of scripts/ps4.ld (OpenOrbis GPL v3).
# Keep the hardware-confirmed 0.11 linker lane unchanged. The converter sizes
# writable bytes from .data, so include protobuf defaults there with their real
# start/stop symbols. Explicit dynamic sections prevent EH_FRAME inheritance.
PHDRS
{
    text PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
    dynamic PT_DYNAMIC FLAGS(6);
    tls PT_TLS FLAGS(4);
    relro PT_GNU_RELRO FLAGS(4);
    eh_frame PT_GNU_EH_FRAME FLAGS(4);
}
SECTIONS
{
    .text : ALIGN(0x4000) {
        __text_start = .;
        QUAD(0x6365786562696C2F);
        QUAD(0x2E666C652D646C2F);
        QUAD(0x00000000312E6F73);
        QUAD(0x0000000000000000);
        *(.text .text.*)
    } :text

    .rodata : ALIGN(0x10) { *(.rodata .rodata.*) } :text
    .eh_frame : {
        __eh_frame_start = .;
        KEEP(*(.eh_frame))
        __eh_frame_end = .;
    } :text
    .eh_frame_hdr : {
        __eh_frame_hdr_start = .;
        KEEP(*(.eh_frame_hdr))
        __eh_frame_hdr_end = .;
    } :text :eh_frame

    .note.moz.toolkit-build-id : { KEEP(*(.note.moz.toolkit-build-id)) } :text
    .dynsym : { *(.dynsym) } :text
    .gnu.hash : { *(.gnu.hash) } :text
    .hash : { *(.hash) } :text
    .dynstr : { *(.dynstr) } :text
    .rela.dyn : { *(.rela.dyn) } :text
    .rela.plt : { *(.rela.plt) } :text
    .gcc_except_table : { *(.gcc_except_table .gcc_except_table.*) } :text

    .data.rel.ro : ALIGN(0x4000) {
        __data_relro_start = .;
        *(.data.rel.ro .data.rel.ro.*)
        . = ALIGN(8);
        __orbisfox_initializers_start = .;
        KEEP(*(SORT_BY_INIT_PRIORITY(.init_array.*)))
        KEEP(*(.init_array))
        __orbisfox_initializers_end = .;
        __data_relro_end = .;
    } :data :relro
    .init_array (TYPE = SHT_INIT_ARRAY) : {
        __init_array_start = .;
        KEEP(*(.orbisfox.startup_entry))
        __init_array_end = .;
    } :data :relro
    .fini_array : { KEEP(*(.fini_array .fini_array.*)) } :data :relro
    .dynamic : { *(.dynamic); } :data :relro :dynamic
    .tls : ALIGN(0x20) {
        *(.tdata .tdata.*);
        *(.tbss .tbss.*);
    } :data :relro :tls
    .got : ALIGN(SIZEOF(.data.rel.ro) > 0 ? 8 : 0x4000) {
        *(.got)
    } :data :relro
    .got.plt : ALIGN((SIZEOF(.got) > 0 || SIZEOF(.data.rel.ro) > 0) ? 8 : 0x4000) {
        *(.got.plt)
    } :data :relro
    .data.sce_process_param : ALIGN(0x4000) {
        KEEP(*(.data.sce_process_param))
    } :data
    .data.sce_module_param : ALIGN(0x4000) {
        KEEP(*(.data.sce_module_param))
    } :data
    .data : {
        *(.data .data.*)
        . = ALIGN(8);
        __start_pb_defaults = .;
        KEEP(*(pb_defaults))
        __stop_pb_defaults = .;
        . = ALIGN(0x20);
    } :data
    .bss : { *(.bss .bss.*) } :data
    /DISCARD/ : { QUAD(_GLOBAL_OFFSET_TABLE_) }
}
