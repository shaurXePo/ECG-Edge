# CMake toolchain file for arm-none-eabi-gcc (bare metal, no OS).
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(TC arm-none-eabi-)
find_program(CMAKE_C_COMPILER   ${TC}gcc REQUIRED)
find_program(CMAKE_ASM_COMPILER ${TC}gcc REQUIRED)
find_program(CMAKE_OBJCOPY      ${TC}objcopy REQUIRED)
find_program(CMAKE_SIZE         ${TC}size REQUIRED)
# A bare-metal link needs our linker script, so do not try to link a test executable.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
