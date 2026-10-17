/* startup_stm32f4.c - reset handler and vector table for STM32F40x/F41x (Cortex-M4F).
 *
 * Written in C (no assembly startup) so every step is visible:
 *   1. the CPU loads SP from vector[0] and PC from vector[1] (= Reset_Handler)
 *   2. copy .data initial values from flash to RAM       (initialised globals)
 *   3. zero .bss                                          (uninitialised globals)
 *   4. SystemInit(): enable the FPU, optionally set up the PLL
 *   5. call main()
 * Symbols _sidata/_sdata/_edata/_sbss/_ebss/_estack come from the linker script.
 */
#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
extern void SystemInit(void);
extern int  main(void);

void Reset_Handler(void);
void Default_Handler(void);

/* Core exceptions + the three interrupts the ADC/UART hook would use. All others -> Default_Handler. */
#define WEAK_DEFAULT __attribute__((weak, alias("Default_Handler")))
void NMI_Handler(void)          WEAK_DEFAULT;
void HardFault_Handler(void)    WEAK_DEFAULT;
void MemManage_Handler(void)    WEAK_DEFAULT;
void BusFault_Handler(void)     WEAK_DEFAULT;
void UsageFault_Handler(void)   WEAK_DEFAULT;
void SVC_Handler(void)          WEAK_DEFAULT;
void DebugMon_Handler(void)     WEAK_DEFAULT;
void PendSV_Handler(void)       WEAK_DEFAULT;
void SysTick_Handler(void)      WEAK_DEFAULT;
void ADC_IRQHandler(void)       WEAK_DEFAULT;   /* IRQ 18: ADC1/2/3 end of conversion   */
void TIM2_IRQHandler(void)      WEAK_DEFAULT;   /* IRQ 28: sampling-rate timer          */
void USART2_IRQHandler(void)    WEAK_DEFAULT;   /* IRQ 38: UART RX hook                 */

typedef void (*isr_t)(void);

#pragma GCC diagnostic ignored "-Woverride-init"   /* range initialiser is deliberately overridden below */
__attribute__((section(".isr_vector"), used))
const isr_t g_vectors[16 + 82] = {
    (isr_t)&_estack,            /*  0 initial stack pointer */
    Reset_Handler,              /*  1 */
    NMI_Handler,                /*  2 */
    HardFault_Handler,          /*  3 */
    MemManage_Handler,          /*  4 */
    BusFault_Handler,           /*  5 */
    UsageFault_Handler,         /*  6 */
    0, 0, 0, 0,                 /*  7-10 reserved */
    SVC_Handler,                /* 11 */
    DebugMon_Handler,           /* 12 */
    0,                          /* 13 reserved */
    PendSV_Handler,             /* 14 */
    SysTick_Handler,            /* 15 */
    [16 ... 16 + 81] = Default_Handler,        /* all 82 device interrupts default ... */
    [16 + 18] = ADC_IRQHandler,                /* ... except the ones we may use */
    [16 + 28] = TIM2_IRQHandler,
    [16 + 38] = USART2_IRQHandler,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;      /* .data: flash -> RAM */
    for (dst = &_sbss; dst < &_ebss; ) *dst++ = 0u;   /* .bss: zero */
    SystemInit();
    (void)main();
    for (;;) { }
}

void Default_Handler(void) { for (;;) { } }     /* trap unexpected interrupts / faults (attach a debugger here) */
