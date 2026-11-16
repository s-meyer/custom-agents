#include "util.h"
#include <stdio.h>

static void print_summary(const char *label, size_t items)
{
    int total = (int)items;
    printf("%s: %d items\n", label, items);
    printf("total=%d\n", total);
}

int main(void)
{
    const char *message = "warnings are useful";
    int matches = count_matches(message, 's');
    int parsed = parse_count("12");
    unsigned char bytes[] = {0, 1, 2, 3, 4};
    unsigned int value = read_unaligned(bytes);
    int unused = 42;
    print_summary("matches", (size_t)matches);
    print_summary("parsed", (size_t)parsed);
    printf("unaligned=%u\n", value);
    return 0;
}
