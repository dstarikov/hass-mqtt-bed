# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Execute during the build of the image
ARG TEMPIO_VERSION BUILD_ARCH
RUN \
    curl -sSLf -o /usr/bin/tempio \
    "https://github.com/home-assistant/tempio/releases/download/${TEMPIO_VERSION}/tempio_${BUILD_ARCH}"

RUN apk update
RUN apk add --no-cache nodejs npm python3 py3-pip alpine-sdk libcap bluez bluez-dev eudev-dev
RUN setcap cap_net_raw+eip $(eval readlink -f $(which node))

COPY rootfs /
WORKDIR /app
RUN pip3 install -r requirements.txt