#ifndef UTIL_H
#define UTIL_H
#include <stddef.h>
int count_matches(const char *text, char needle);
int parse_count(const char *text);
unsigned int read_unaligned(const unsigned char *buf);
#endif
