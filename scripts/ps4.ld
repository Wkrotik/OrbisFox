# SPDX-License-Identifier: GPL-3.0-only
# Adapted from OpenOrbis v0.5.3 link.x (GPL v3).
# Capture section-suffixed data/TLS emitted by current LLVM and SDK libraries:
# create-fself sizes the writable segment from the named .data/.bss sections.
# Keep one writable LOAD: the converter splits its RELRO prefix from the
# writable data. Automatic LLD segments can produce duplicate writable LOADs
# after conversion when the SWGL vtables grow beyond one page.
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
	# Combine text, rodata, and eh_frame stuff
	# In case you'll ever need to get the base address of eboot.bin, you can use the &__text_start symbol.
	# No need to go through libkernel for that.
	.text : ALIGN(0x4000) {
		__text_start = .;
		# "/libexec/ld-elf.so.1"
		QUAD(0x6365786562696C2F);
		QUAD(0x2E666C652D646C2F);
		QUAD(0x00000000312E6F73);
		QUAD(0x0000000000000000);

		# original .text
		*(.text .text.*)
	} :text

	.rodata : ALIGN(0x10) {
		*(.rodata .rodata.*)
	} :text

    # Since we lack a proper POSIX dladdr() on a PS4, we define these global symbols
    # For libunwind's bare metal compilation mode.
    # That's way better than going through libkernel... ;-;
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

	# Reset PHDR inheritance so orphan dynamic tables are not included in EH_FRAME.
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
	
	.dynamic : {
		*(.dynamic);
	} :data :relro :dynamic

	.tls : ALIGN(0x20) {
		*(.tdata .tdata.*);
		*(.tbss .tbss.*);
	} :data :relro :tls

	# Align .got to 0x4000 if .data.rel.ro doesn't exist
	.got : ALIGN(SIZEOF(.data.rel.ro) > 0 ? 8 : 0x4000) {
		*(.got)
	} :data :relro

	# Align .got.plt to 0x4000 if .got doesn't exist
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
		. = ALIGN(0x20);
	} :data

	.bss : {
		*(.bss .bss.*)
	} :data

	# Force .got.plt to appear, because SPRX requires a valid .got.plt.
	/DISCARD/ : {
		QUAD(_GLOBAL_OFFSET_TABLE_)
	}
}
