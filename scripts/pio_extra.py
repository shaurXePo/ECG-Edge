# PlatformIO pre-script: compile the handful of CMSIS-DSP kernels this project uses.
# (Run scripts/fetch_deps.sh first so third_party/CMSIS-DSP exists.)
import os
Import("env")  # noqa: F821  (provided by PlatformIO / SCons)

root = env.subst("$PROJECT_DIR")  # noqa: F821
dsp_src = os.path.join(root, "third_party", "CMSIS-DSP", "Source")
if not os.path.isdir(dsp_src):
    raise SystemExit("third_party/CMSIS-DSP missing: run ./scripts/fetch_deps.sh")
if not os.path.exists(os.path.join(root, "firmware", "inc", "generated", "ecg_params.h")):
    raise SystemExit("generated headers missing: run python scripts/export_headers.py")

kernels = [
    "FilteringFunctions/arm_fir_f32.c", "FilteringFunctions/arm_fir_init_f32.c",
    "FilteringFunctions/arm_fir_q15.c", "FilteringFunctions/arm_fir_init_q15.c",
    "FilteringFunctions/arm_biquad_cascade_df2T_f32.c", "FilteringFunctions/arm_biquad_cascade_df2T_init_f32.c",
    "FilteringFunctions/arm_biquad_cascade_df1_q15.c", "FilteringFunctions/arm_biquad_cascade_df1_init_q15.c",
    "FilteringFunctions/arm_biquad_cascade_df1_q31.c", "FilteringFunctions/arm_biquad_cascade_df1_init_q31.c",
    "SupportFunctions/arm_q15_to_float.c", "SupportFunctions/arm_q15_to_q31.c",
]
env.BuildSources(os.path.join("$BUILD_DIR", "cmsis_dsp"), dsp_src,  # noqa: F821
                 src_filter=["-<*>"] + [f"+<{k}>" for k in kernels])
