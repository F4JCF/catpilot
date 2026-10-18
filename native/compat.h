/* Compatibilité MinGW (Windows) : fonctions POSIX absentes utilisées par ft8_lib. */
#ifndef CATPILOT_COMPAT_H
#define CATPILOT_COMPAT_H
#ifdef _WIN32
#include <string.h>
static inline char* catpilot_stpcpy(char* dst, const char* src)
{
    size_t n = strlen(src);
    memcpy(dst, src, n + 1);
    return dst + n;
}
#define stpcpy catpilot_stpcpy
#endif
#endif
