CC = arm-linux-gnueabihf-gcc
CFLAGS = -std=c11 -O2 -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wformat=2 -Wcast-align=strict -Iinclude
TARGET = out/app
SOURCES = src/main.c src/util.c

.PHONY: all clean
all: $(TARGET)
$(TARGET): $(SOURCES) include/util.h
	mkdir -p out
	$(CC) $(CFLAGS) $(SOURCES) -o $(TARGET)
clean:
	rm -rf out
