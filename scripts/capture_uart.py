#!/usr/bin/env python3
"""capture_uart.py - record the firmware's CSV stream from the ST-LINK virtual COM port.

    pip install pyserial
    python scripts/capture_uart.py --port /dev/ttyACM0 --out results/mcu_run.log      # Linux
    python scripts/capture_uart.py --port COM5          --out results/mcu_run.log      # Windows
    python scripts/capture_uart.py --list

Start this BEFORE pressing the black RESET button on the Nucleo (the firmware runs once after
reset and then idles), or it will have finished before you listen.  Capture ends at '#DONE'.
"""
import argparse
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port"); ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default="results/mcu_run.log")
    ap.add_argument("--timeout", type=float, default=300.0, help="give up after N seconds")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        sys.exit("pip install pyserial")
    if a.list or not a.port:
        for p in list_ports.comports():
            print(p.device, "-", p.description)
        return
    t0, n = time.time(), 0
    with serial.Serial(a.port, a.baud, timeout=1) as s, open(a.out, "wb") as f:
        print(f"listening on {a.port} @ {a.baud} baud ... press RESET on the board")
        buf = b""
        while time.time() - t0 < a.timeout:
            chunk = s.read(4096)
            if not chunk:
                continue
            f.write(chunk); buf = (buf + chunk)[-64:]; n += len(chunk)
            sys.stdout.write(f"\r{n} bytes"); sys.stdout.flush()
            if b"#DONE" in buf:
                print("\n#DONE received"); return
        sys.exit("\ntimeout before #DONE: wrong baud? board not reset? (see README troubleshooting)")


if __name__ == "__main__":
    main()
