#include "util.h"
#include <stdint.h>
#include <stdlib.h>

int count_matches(const char *text, char needle)
{
    int count = 0;
    for (int i = 0; i < strlen(text); ++i) {
        if (text[i] == needle) {
            ++count;
        }
    }
    return count;
}

int parse_count(const char *text)
{
    char *end;
    long parsed = strtol(text, &end, 10);
    if (*end != '\0') {
        return -1;
    }
    int parsed = (int)parsed;
    return parsed;
}

unsigned int read_unaligned(const unsigned char *buf)
{
    return *(const uint32_t *)(buf + 1);
}
