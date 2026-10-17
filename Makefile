# Convenience wrapper. Every target just calls the commands documented in README.md.
TC      := -DCMAKE_TOOLCHAIN_FILE=$(CURDIR)/firmware/cmake/arm-none-eabi.cmake
PY      ?= python3
BAUD    ?= 115200
SOURCE  ?= wfdb          # wfdb = real MIT-BIH record 100 | synthetic = offline smoke test

.PHONY: deps export host host-run qemu qemu-run nucleo nucleo-pll renode renode-run footprint flash validate clean

deps:           ; ./scripts/fetch_deps.sh
export:         ; $(PY) scripts/export_headers.py --source $(SOURCE)

host:           ; cmake -S firmware -B build/host -DECG_TARGET=host -DCMAKE_BUILD_TYPE=Release && cmake --build build/host -j
host-run: host  ; ./build/host/ecg_edge.elf > results/host_run.log && $(PY) scripts/validate.py --log results/host_run.log --label host
	ctest --test-dir build/host --output-on-failure

qemu:           ; cmake -S firmware -B build/qemu -DECG_TARGET=qemu $(TC) -DCMAKE_BUILD_TYPE=Release && cmake --build build/qemu -j
qemu-run: qemu  ; ./firmware/sim/run_qemu.sh

nucleo:         ; cmake -S firmware -B build/nucleo -DECG_TARGET=stm32f4 -DECG_USE_PLL=0 -DECG_UART_BAUD=$(BAUD) $(TC) -DCMAKE_BUILD_TYPE=Release && cmake --build build/nucleo -j
nucleo-pll:     ; cmake -S firmware -B build/nucleo -DECG_TARGET=stm32f4 -DECG_USE_PLL=1 -DECG_UART_BAUD=460800 $(TC) -DCMAKE_BUILD_TYPE=Release && cmake --build build/nucleo -j

renode:         ; cmake -S firmware -B build/renode -DECG_TARGET=renode $(TC) -DCMAKE_BUILD_TYPE=Release && cmake --build build/renode -j
renode-run: renode ; ./firmware/renode/run_renode.sh

footprint:      ; $(PY) scripts/footprint.py

# flash with ST-LINK: either of these works (install stlink-tools or openocd)
flash:          ; st-flash --reset write build/nucleo/ecg_edge.bin 0x08000000

validate:       ; $(PY) scripts/validate.py --log results/mcu_run.log --label mcu --cross results/host_run.log

clean:          ; rm -rf build
