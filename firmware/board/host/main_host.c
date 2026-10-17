/* main_host.c - command-line front end for the host build.
 *   ecg_edge_host [--block N] [--no-dump] [--no-sweep] [--pt-only] [--only NAME]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ecg_app.h"
#include "ecg_platform.h"

int main(int argc, char **argv)
{
    ecg_app_opts_t o;
    ecg_app_default_opts(&o);
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--block") && i + 1 < argc)      o.block = (uint32_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--no-dump"))               o.dump = 0;
        else if (!strcmp(argv[i], "--no-sweep"))              o.sweep = 0;
        else if (!strcmp(argv[i], "--pt-only"))               { o.pt_only = 1; o.sweep = 0; }
        else if (!strcmp(argv[i], "--only") && i + 1 < argc)  o.only = argv[++i];
        else { fprintf(stderr, "usage: %s [--block N] [--no-dump] [--no-sweep] [--pt-only] [--only NAME]\n", argv[0]); return 2; }
    }
    if (o.block == 0 || o.block > ECG_MAX_BLOCK_SIZE) { fprintf(stderr, "block must be 1..%u\n", (unsigned)ECG_MAX_BLOCK_SIZE); return 2; }
    int rc = ecg_app_run(&o);
    platform_exit(rc);
}
