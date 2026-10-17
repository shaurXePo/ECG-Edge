/* STM32F407VG (Renode stm32f4_discovery model, QEMU STM32F405): 1 MiB flash, 128 KiB SRAM.
 * The 64 KiB CCM RAM at 0x10000000 is deliberately NOT used: the DMA cannot reach it and it
 * would make the Renode/QEMU result differ from the F411 board. */
MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 1024K
  RAM   (xrw) : ORIGIN = 0x20000000, LENGTH = 128K
}
INCLUDE stm32f4_sections.ld
