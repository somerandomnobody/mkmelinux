#!/usr/bin/env bash
# It is recommended to run AI using this.
podman run -d --name aicontainer -v ./:/code ubuntu:latest sleep infinity
podman exec aicontainer bash -c "apt update && apt install sudo nano -y && useradd aiuser"
podman exec -it aicontainer bash -c "sudo -u aiuser bash"