/* stm32f4_sections.ld - section placement shared by all STM32F4 variants.
 * The including file defines MEMORY { FLASH, RAM }.
 *
 *   FLASH: .isr_vector  .text  .rodata  (+ LOAD image of .data)
 *   RAM  : .data  .bss  ... free space ...  stack (grows DOWN from _estack)
 *
 * No heap: nothing in this firmware calls malloc, which is also what makes the stack
 * high-water measurement meaningful (everything between _ebss and _estack is stack headroom).
 */
ENTRY(Reset_Handler)

_estack         = ORIGIN(RAM) + LENGTH(RAM);   /* initial SP = top of RAM */
_Min_Stack_Size = 0x1000;                      /* link fails if less than 4 KiB would remain for the stack */

SECTIONS
{
  .isr_vector : { . = ALIGN(4); KEEP(*(.isr_vector)) . = ALIGN(4); } > FLASH

  .text : {
    . = ALIGN(4);
    *(.text) *(.text*) *(.glue_7) *(.glue_7t) *(.eh_frame)
    KEEP(*(.init)) KEEP(*(.fini))
    . = ALIGN(4);
  } > FLASH

  .rodata : { . = ALIGN(4); *(.rodata) *(.rodata*) . = ALIGN(4); } > FLASH

  .ARM.extab : { *(.ARM.extab* .gnu.linkonce.armextab.*) } > FLASH
  .ARM : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } > FLASH

  _sidata = LOADADDR(.data);                   /* flash address of the initial values of .data */
  .data : { . = ALIGN(4); _sdata = .; *(.data) *(.data*) . = ALIGN(4); _edata = .; } > RAM AT > FLASH

  .bss : { . = ALIGN(4); _sbss = .; *(.bss) *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM

  /* Reserve the minimum stack so the linker errors out instead of letting the stack
   * silently collide with .bss at run time. */
  ._stack_check : { . = ALIGN(8); . = . + _Min_Stack_Size; . = ALIGN(8); } > RAM

  /DISCARD/ : { *(.note.GNU-stack) }
  .ARM.attributes 0 : { *(.ARM.attributes) }
}
