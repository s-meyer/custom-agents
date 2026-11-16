FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      make gcc-arm-linux-gnueabihf libc6-dev-armhf-cross \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
