/* platform_stm32f4.c - implementation of ecg_platform.h for STM32F4 (real board, Renode, QEMU).
 *
 * Output path:
 *   Nucleo-F411RE : USART2 (PA2 = TX, AF7) -> ST-LINK virtual COM port -> /dev/ttyACM0
 *   Renode        : same registers, Renode's STM32_UART model
 *   QEMU          : ECG_OUTPUT_SEMIHOST -> semihosting SYS_WRITEC (needs QEMU -semihosting)
 *                   NEVER enable semihosting on real hardware without a debugger: BKPT faults.
 */
#include "stm32f4xx.h"
#include "ecg_platform.h"

extern uint32_t _ebss, _estack;          /* linker: end of .bss, top of RAM */
extern uint32_t SystemCoreClock;

#if defined(ECG_OUTPUT_SEMIHOST)
/* ARM semihosting: r0 = operation, r1 = parameter block, then BKPT 0xAB. */
static inline int sh_call(int op, uint32_t arg)
{
    register int      r0 __asm__("r0") = op;
    register uint32_t r1 __asm__("r1") = arg;
    __asm__ volatile("bkpt 0xAB" : "+r"(r0) : "r"(r1) : "memory");
    return r0;
}
#endif

void platform_init(void)
{
#if !defined(ECG_OUTPUT_SEMIHOST)
    /* --- USART2 on PA2 -------------------------------------------------------------- */
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;                      /* clock GPIOA */
    RCC->APB1ENR |= RCC_APB1ENR_USART2EN;                     /* clock USART2 (on APB1) */
    GPIOA->MODER   = (GPIOA->MODER & ~(3u << (2 * 2))) | (2u << (2 * 2));    /* PA2 = alternate function */
    GPIOA->OSPEEDR |= (3u << (2 * 2));                        /* PA2 very high speed */
    GPIOA->AFR[0]  = (GPIOA->AFR[0] & ~(0xFu << (4 * 2))) | (7u << (4 * 2)); /* AF7 = USART1..3 */
    /* APB1 clock = SystemCoreClock (no divider) unless the PLL config divides it by 2. */
    uint32_t pclk1 = SystemCoreClock;
#if defined(ECG_USE_PLL) && ECG_USE_PLL && defined(ECG_BOARD_NUCLEO_F411RE)
    pclk1 = SystemCoreClock / 2u;
#endif
    USART2->BRR = (pclk1 + ECG_UART_BAUD / 2u) / ECG_UART_BAUD;   /* oversampling by 16: BRR = fck/baud, rounded */
    USART2->CR1 = USART_CR1_UE | USART_CR1_TE;                /* UART enable, transmitter enable (8N1 default) */
#endif
    /* --- DWT cycle counter ---------------------------------------------------------- */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;           /* enable the trace block (DWT lives in it) */
    DWT->CYCCNT = 0u;
    DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;                     /* start counting core cycles */
}

void platform_putc(char c)
{
#if defined(ECG_OUTPUT_SEMIHOST)
    (void)sh_call(0x03 /* SYS_WRITEC */, (uint32_t)&c);
#else
    while (!(USART2->SR & USART_SR_TXE)) { }                  /* wait until the data register is empty */
    USART2->DR = (uint8_t)c;
#endif
}

void platform_flush(void)
{
#if !defined(ECG_OUTPUT_SEMIHOST)
    while (!(USART2->SR & USART_SR_TC)) { }                   /* transmission complete (shift register empty) */
#endif
}

uint32_t    platform_cpu_hz(void)  { return SystemCoreClock; }

const char *platform_name(void)
{
#if defined(ECG_BOARD_NUCLEO_F411RE)
    return "STM32F411RE (Nucleo)";
#elif defined(ECG_BOARD_RENODE_F407)
    return "Renode STM32F407 model (timing NOT meaningful)";
#else
    return "QEMU netduinoplus2/STM32F405 (timing NOT meaningful)";
#endif
}

/* DWT->CTRL bit 25 (NOCYCCNT) reads 1 if the implementation has no cycle counter.
 * Simulators often return 0 for everything, so also check that the counter really moves. */
int platform_has_cycle_counter(void)
{
    if (DWT->CTRL & DWT_CTRL_NOCYCCNT_Msk) return 0;
    uint32_t a = DWT->CYCCNT;
    for (volatile int i = 0; i < 16; i++) { }
    return DWT->CYCCNT != a;
}

/* ---- stack painting ------------------------------------------------------------------ */
#define STACK_FILL 0xA5A5A5A5u

void platform_stack_paint(void)
{
    uint32_t *p = &_ebss;                                           /* lowest address the stack may reach */
    uint32_t *limit = (uint32_t *)((__get_MSP() - 64u) & ~3u);      /* stay below the live frames */
    while (p < limit) *p++ = STACK_FILL;
}

uint32_t platform_stack_used(void)
{
    const uint32_t *p = &_ebss;
    while (p < &_estack && *p == STACK_FILL) p++;                   /* first word the stack has touched */
    return (uint32_t)((const uint8_t *)&_estack - (const uint8_t *)p);
}

uint32_t platform_stack_total(void) { return (uint32_t)((const uint8_t *)&_estack - (const uint8_t *)&_ebss); }

void platform_exit(int code)
{
    (void)code;                                   /* only used by the semihosting build */
#if defined(ECG_OUTPUT_SEMIHOST)
    (void)sh_call(0x18 /* SYS_EXIT */, code == 0 ? 0x20026u : 0x20023u);   /* ADP_Stopped_ApplicationExit / InternalError */
#endif
    for (;;) { __WFI(); }
}
