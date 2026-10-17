# ECG-Edge firmware build.
#
#   Host (numerics, no hardware):   cmake -S firmware -B build/host    -DECG_TARGET=host
#   Nucleo-F411RE (real board):     cmake -S firmware -B build/nucleo  -DECG_TARGET=stm32f4 \
#                                         -DCMAKE_TOOLCHAIN_FILE=firmware/cmake/arm-none-eabi.cmake
#   Renode (STM32F407 model):       ... -DECG_TARGET=renode   (same toolchain file)
#   QEMU  (netduinoplus2/F405):     ... -DECG_TARGET=qemu     (same toolchain file)
#
# Directory layout:
#   src/ inc/        hardware-independent code (depends only on ecg_platform.h + CMSIS-DSP)
#   board/host       PC implementation of ecg_platform.h
#   board/stm32f4    Cortex-M4 implementation (startup, clock, UART, DWT, linker scripts)
cmake_minimum_required(VERSION 3.16)
project(ecg_edge C ASM)

set(ECG_TARGET "host" CACHE STRING "host | stm32f4 | renode | qemu")
set_property(CACHE ECG_TARGET PROPERTY STRINGS host stm32f4 renode qemu)
set(ECG_ROOT      ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(ECG_GEN_DIR   ${CMAKE_CURRENT_SOURCE_DIR}/inc/generated CACHE PATH "directory with generated ecg_*.h")
set(ECG_BLOCK_SIZE 36 CACHE STRING "default block size [samples]")
set(ECG_UART_BAUD 115200 CACHE STRING "UART baud rate")
set(ECG_USE_PLL 0 CACHE STRING "1 = run the Nucleo-F411RE at 96 MHz from the PLL (hardware only)")
set(ECG_OPT "-O2" CACHE STRING "optimisation level for the application and CMSIS-DSP")
foreach(g FIR_F32 FIR_Q15 FIR_Q15M IIR_F32 IIR_Q15 IIR_Q31 IIRH_F32 IIRH_Q15 IIRH_Q15R IIRH_Q31 PT)
  set(ECG_ENABLE_${g} 1 CACHE STRING "build implementation group ${g} (0/1)")
endforeach()

set(DSP  ${ECG_ROOT}/third_party/CMSIS-DSP)
set(CORE ${ECG_ROOT}/third_party/CMSIS_5/CMSIS/Core/Include)
set(DEVF4 ${ECG_ROOT}/third_party/cmsis_device_f4/Include)
foreach(d ${DSP}/Source ${CORE} ${DEVF4})
  if(NOT EXISTS ${d})
    message(FATAL_ERROR "Missing ${d}. Run scripts/fetch_deps.sh first.")
  endif()
endforeach()
foreach(f ecg_params.h ecg_coeffs.h ecg_testvec.h)
  if(NOT EXISTS ${ECG_GEN_DIR}/${f})
    message(FATAL_ERROR "Missing ${ECG_GEN_DIR}/${f}. Run: python scripts/export_headers.py")
  endif()
endforeach()

# ---- only the CMSIS-DSP kernels we actually use (keeps compile time and flash small) ----
set(DSPF ${DSP}/Source/FilteringFunctions)
set(DSPS ${DSP}/Source/SupportFunctions)
set(DSP_SRCS
  ${DSPF}/arm_fir_f32.c ${DSPF}/arm_fir_init_f32.c
  ${DSPF}/arm_fir_q15.c ${DSPF}/arm_fir_init_q15.c
  ${DSPF}/arm_biquad_cascade_df2T_f32.c ${DSPF}/arm_biquad_cascade_df2T_init_f32.c
  ${DSPF}/arm_biquad_cascade_df1_q15.c  ${DSPF}/arm_biquad_cascade_df1_init_q15.c
  ${DSPF}/arm_biquad_cascade_df1_q31.c  ${DSPF}/arm_biquad_cascade_df1_init_q31.c
  ${DSPS}/arm_q15_to_float.c ${DSPS}/arm_q15_to_q31.c)

set(APP_SRCS
  src/ecg_app.c src/ecg_pipeline.c src/ecg_out.c src/ecg_registry.c
  src/ecg_source_vector.c src/ecg_source_ring.c
  src/ecg_filters_f32.c src/ecg_filters_q15.c src/ecg_filters_q31.c
  src/ecg_fir_q15_manual.c src/ecg_pan_tompkins.c)

if(ECG_TARGET STREQUAL "host")
  set(BOARD_SRCS board/host/platform_host.c board/host/main_host.c)
  set(BOARD_INC  board/host)
  set(ECG_PT_PEAKS 16384)           # host can afford to detect on very long records
else()
  set(BOARD_SRCS board/stm32f4/startup_stm32f4.c board/stm32f4/system_stm32f4.c
                 board/stm32f4/platform_stm32f4.c board/stm32f4/main_stm32f4.c)
  set(BOARD_INC  board/stm32f4)
  set(ECG_PT_PEAKS 128)
endif()

add_executable(ecg_edge ${APP_SRCS} ${DSP_SRCS} ${BOARD_SRCS})
set_target_properties(ecg_edge PROPERTIES SUFFIX ".elf" OUTPUT_NAME ecg_edge)

target_include_directories(ecg_edge PRIVATE
  inc ${ECG_GEN_DIR} ${BOARD_INC}
  ${DSP}/Include ${DSP}/PrivateInclude ${CORE} ${DEVF4})

target_compile_definitions(ecg_edge PRIVATE
  ECG_BLOCK_SIZE=${ECG_BLOCK_SIZE} ECG_UART_BAUD=${ECG_UART_BAUD} ECG_PT_MAX_PEAKS=${ECG_PT_PEAKS}
  ECG_ENABLE_FIR_F32=${ECG_ENABLE_FIR_F32} ECG_ENABLE_FIR_Q15=${ECG_ENABLE_FIR_Q15}
  ECG_ENABLE_FIR_Q15M=${ECG_ENABLE_FIR_Q15M} ECG_ENABLE_IIR_F32=${ECG_ENABLE_IIR_F32}
  ECG_ENABLE_IIR_Q15=${ECG_ENABLE_IIR_Q15} ECG_ENABLE_IIR_Q31=${ECG_ENABLE_IIR_Q31}
  ECG_ENABLE_IIRH_F32=${ECG_ENABLE_IIRH_F32} ECG_ENABLE_IIRH_Q15=${ECG_ENABLE_IIRH_Q15}
  ECG_ENABLE_IIRH_Q15R=${ECG_ENABLE_IIRH_Q15R} ECG_ENABLE_IIRH_Q31=${ECG_ENABLE_IIRH_Q31}
  ECG_ENABLE_PT=${ECG_ENABLE_PT})

target_compile_options(ecg_edge PRIVATE ${ECG_OPT} -g3 -Wall -Wextra -ffunction-sections -fdata-sections)

if(ECG_TARGET STREQUAL "host")
  target_compile_definitions(ecg_edge PRIVATE ECG_TARGET_HOST=1)
  target_link_libraries(ecg_edge PRIVATE m)
  # CMSIS-DSP's own sources trigger a few harmless pedantic warnings; keep ours clean.
  set_source_files_properties(${DSP_SRCS} PROPERTIES COMPILE_OPTIONS "-w")
else()
  # ---------------- Cortex-M4F ----------------
  set(CPU_FLAGS -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16)
  target_compile_options(ecg_edge PRIVATE ${CPU_FLAGS})
  target_compile_definitions(ecg_edge PRIVATE ECG_USE_PLL=${ECG_USE_PLL})
  set_source_files_properties(${DSP_SRCS} PROPERTIES COMPILE_OPTIONS "-w")

  if(ECG_TARGET STREQUAL "stm32f4")
    target_compile_definitions(ecg_edge PRIVATE STM32F411xE ECG_BOARD_NUCLEO_F411RE=1)
    set(LD stm32f411re.ld)
  elseif(ECG_TARGET STREQUAL "renode")
    target_compile_definitions(ecg_edge PRIVATE STM32F407xx ECG_BOARD_RENODE_F407=1)
    set(LD stm32f407vg.ld)
  elseif(ECG_TARGET STREQUAL "qemu")
    # QEMU 'netduinoplus2' = STM32F405: same memory map as F407; output via semihosting.
    target_compile_definitions(ecg_edge PRIVATE STM32F405xx ECG_BOARD_QEMU_F405=1 ECG_OUTPUT_SEMIHOST=1)
    set(LD stm32f407vg.ld)
  else()
    message(FATAL_ERROR "unknown ECG_TARGET ${ECG_TARGET}")
  endif()

  target_link_options(ecg_edge PRIVATE ${CPU_FLAGS}
    -T${CMAKE_CURRENT_SOURCE_DIR}/board/stm32f4/ld/${LD}
    -L${CMAKE_CURRENT_SOURCE_DIR}/board/stm32f4/ld
    -nostartfiles --specs=nano.specs --specs=nosys.specs
    -Wl,--gc-sections -Wl,-Map=${CMAKE_BINARY_DIR}/ecg_edge.map
    -Wl,--print-memory-usage)
  target_link_libraries(ecg_edge PRIVATE m)

  add_custom_command(TARGET ecg_edge POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:ecg_edge> ${CMAKE_BINARY_DIR}/ecg_edge.bin
    COMMAND ${CMAKE_SIZE} --format=berkeley $<TARGET_FILE:ecg_edge>
    COMMENT "Creating .bin and printing section sizes")
endif()

# ---- host unit test for the ring-buffer input hook ----------------------------------------
if(ECG_TARGET STREQUAL "host")
  enable_testing()
  add_executable(test_ring tests/test_ring.c src/ecg_source_ring.c)
  target_include_directories(test_ring PRIVATE inc ${ECG_GEN_DIR} board/host ${DSP}/Include ${CORE})
  add_test(NAME ring_source COMMAND test_ring)
endif()
