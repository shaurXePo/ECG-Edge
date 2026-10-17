/* system_stm32f4.c - clock and FPU setup. */
#include "stm32f4xx.h"

/* CMSIS global: current core clock.  The HSI RC oscillator (16 MHz, +/-1 % factory trim) is
 * the reset default and is what we use unless ECG_USE_PLL=1. */
uint32_t SystemCoreClock = 16000000u;

#if defined(ECG_USE_PLL) && ECG_USE_PLL && defined(ECG_BOARD_NUCLEO_F411RE)
/* HSI 16 MHz / M=16 -> 1 MHz VCO input; x N=192 -> 192 MHz VCO; / P=2 -> 96 MHz SYSCLK;
 * / Q=4 -> 48 MHz (USB, unused).  F411 limit is 100 MHz; at 96 MHz and 2.7-3.6 V flash needs
 * 3 wait states.  APB1 limit is 50 MHz -> divide by 2 (48 MHz).  APB2 = 96 MHz. */
static void clock_96mhz(void)
{
    RCC->CR |= RCC_CR_HSION;           while (!(RCC->CR & RCC_CR_HSIRDY)) { }
    RCC->APB1ENR |= RCC_APB1ENR_PWREN;
    PWR->CR |= PWR_CR_VOS;             /* voltage scale 1: required above 84 MHz */
    FLASH->ACR = FLASH_ACR_ICEN | FLASH_ACR_DCEN | FLASH_ACR_PRFTEN | FLASH_ACR_LATENCY_3WS;
    RCC->PLLCFGR = (16u << RCC_PLLCFGR_PLLM_Pos) | (192u << RCC_PLLCFGR_PLLN_Pos) |
                   (0u << RCC_PLLCFGR_PLLP_Pos) /* P=2 */ | (4u << RCC_PLLCFGR_PLLQ_Pos);  /* PLLSRC=0 -> HSI */
    RCC->CFGR = RCC_CFGR_HPRE_DIV1 | RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV1;
    RCC->CR |= RCC_CR_PLLON;           while (!(RCC->CR & RCC_CR_PLLRDY)) { }
    RCC->CFGR |= RCC_CFGR_SW_PLL;      while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) { }
    SystemCoreClock = 96000000u;
}
#endif

void SystemInit(void)
{
    /* Give coprocessors CP10 and CP11 (the FPU) full access.  WITHOUT this the first float
     * instruction raises a UsageFault - the classic "works in Debug, hard-faults in Release" bug. */
    SCB->CPACR |= (0xFu << 20);
    __DSB(); __ISB();
#if defined(ECG_USE_PLL) && ECG_USE_PLL && defined(ECG_BOARD_NUCLEO_F411RE)
    clock_96mhz();
#endif
}
