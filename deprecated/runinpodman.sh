#!/bin/bash
set -euo pipefail

# Why an Incus VM on top of a container?
# It allows us to use loop devices regardless of host configuration. Also works on CI since CI most likely has KVM. Also provides a well known build environment.


for arg in "$@"; do
    if [[ "$arg" == *"="* ]]; then
        key="${arg%%=*}"
        value="${arg#*=}"
        declare "$key=$value"
    fi
done

if [[ "$@" == *"PACKAGEV86ONLY"* ]]; then
echo "Packaging v86 build..."
podman rm -f debian-build 2>/dev/null || true
podman run --name debian-build -v ./:/env debian:latest bash -c "apt update && apt install nodejs python3 python3-pip -y && pip3 install zstandard --break-system-packages && bash /env/mkv86.sh"
podman rm debian-build
exit
fi

runbefore=""
runafter=""

arguments=$(cat ./distro/arguments.txt)

# If a distro template is specified, extract its ContainerConfig.Packages so
# the build container has the tools the template needs (e.g. curl, zstd for Arch).
TEMPLATE_PACKAGES=""
if [[ "$arguments" == *"OSTEMPLATE="* ]]; then
    ostemplate=$(echo "$arguments" | grep -oP 'OSTEMPLATE=\K\S+')
    dt_file="./distro-templates/${ostemplate}.dt"
    if [[ -f "$dt_file" ]]; then
        in_container_section=0
        while IFS= read -r dtline; do
            dtline="${dtline%%#*}"  # strip inline comments
            dtline="${dtline%"${dtline##*[![:space:]]}"}"  # strip trailing whitespace
            [[ -z "$dtline" ]] && continue
            if [[ "$dtline" =~ ^\[([A-Za-z0-9_-]+)\]$ ]]; then
                in_container_section=0
                [[ "${BASH_REMATCH[1]}" == "ContainerConfig" ]] && in_container_section=1
                continue
            fi
            if (( in_container_section )) && [[ "$dtline" =~ ^Packages ]]; then
                TEMPLATE_PACKAGES=$(echo "$dtline" | grep -oP '"[^"]*"' | tr -d '"' | tr '\n' ' ')
                break
            fi
        done < "$dt_file"
        echo "Distro template '${ostemplate}' — extra container packages: ${TEMPLATE_PACKAGES:-none}"
    else
        echo "Warning: distro template '${ostemplate}' not found at ${dt_file}" >&2
    fi
fi

# Before/after hooks
if [[ -f "./container/runbefore.sh" ]]; then
    echo "Found runbefore script."
    runbefore="./container/runbefore.sh"
fi
if [[ -f "./container/runafter.sh" ]]; then
    echo "Found runafter script."
    runafter="./container/runafter.sh"
fi


if podman stats debian-build >> /dev/null; then 
echo "Detected Podman container is still running, quitting it..."
podman stop debian-build
podman rm debian-build
fi


echo "Checking build type..."
if [[ "$arguments" == *"TYPE=V86"* ]]; then
echo "Detected a V86 build..."
echo "Starting Podman container and mounting dirs..."
podman run -d --privileged --name debian-build -v ./:/env debian:latest sleep infinity
echo "Updating and installing required packages (debootstrap, python3, nodejs)..."
podman exec debian-build bash -c "apt update && apt install debootstrap python3 python3-pip nodejs ${TEMPLATE_PACKAGES} -y"
podman exec debian-build bash -c "pip3 install zstandard --break-system-packages"
[[ -z "${runbefore}" ]] || podman exec debian-build bash -c "cd /env && bash ${runbefore}"
echo "Starting script"
echo "########################################################################################################"
podman exec debian-build bash -c "cd /env && bash mkmelinux.sh ${arguments}"
[[ -z "${runafter}" ]] || podman exec debian-build bash -c "cd /env && bash ${runafter}"
echo "Running v86 packaging (fs2json, copy-to-sha256, state generation)..."
podman exec debian-build bash -c "cd /env && bash mkv86.sh"
echo "Script exited, deleting container... (press ^C to abort...)"
sleep 5
podman stop debian-build
podman rm debian-build
elif [[ "$arguments" == *"TYPE=HARDDISK"* ]]; then
echo "Detected a harddisk build, proceeding with harddisk setup..."
echo "Note; harddisk images produced will be UEFI bootable only."
if ! [[ -f ./.dismissvhostwarning ]]; then
    echo "###########################################################"
    echo "#               WARNING! Please read this!                #"
    echo "# We have detected that you are running a HARDDISK build. #"
    echo "# HARDDISK builds require loop devices. To ensure that we #"
    echo "# have enough loop devices, we'll launch an Incus VM to   #"
    echo "# build it for you.                                       #"
    echo "# This *REQUIRES* that kernel module vhost_vsock is added #"
    echo "# and currently running on your host.                     #"
    echo "# If unsure, execute 'sudo modprobe vhost_vsock' to fix.  #"
    echo "###########################################################"
    echo "(to dismiss, create the file .dismissvhostwarning in the same directory that the script is ran from.)"
    echo "Waiting 10 seconds before continuing..."
    sleep 10
fi
echo "Starting Podman container and mounting dirs..."
podman run -d --privileged --name debian-build -v ./:/env debian:latest sleep infinity
echo "Updating and installing all required bash packages..."
podman exec debian-build bash -c "apt update && apt install sshfs incus tmux -y"
# podman exec debian-build bash -c "apt update && apt install debootstrap squashfs-tools grub-pc-bin grub-efi-amd64-bin xorriso systemd-container mtools qemu-utils incus fdisk -y"
podman exec debian-build bash -c "service incus start && incus admin init --auto && incus launch images:debian/12 build-vm --vm"
echo "Waiting for Incus VM to become ready..."
podman exec debian-build bash -c "until incus exec build-vm -- true 2>/dev/null; do sleep 2; done"
podman exec debian-build bash -c "incus exec build-vm -- apt install parted dosfstools debootstrap squashfs-tools grub-pc-bin grub-efi-amd64-bin xorriso systemd-container mtools qemu-utils fdisk ${TEMPLATE_PACKAGES} -y" # Add busybox if chroot doesn't exist.
podman exec debian-build bash -c "mkdir /env2"
podman exec debian-build bash -c "incus exec build-vm -- mkdir /env"
podman exec debian-build bash -c "tmux new-session -d -s incusfiles incus file mount build-vm/env /env2/"
sleep 1
podman exec debian-build bash -c "cp /env/mkmelinux.sh /env2"
podman exec debian-build bash -c "cp -r /env/container /env2"
podman exec debian-build bash -c "cp -r /env/distro /env2/distro"
podman exec debian-build bash -c "cp -r /env/globalpatches /env2/globalpatches"
podman exec debian-build bash -c "cp -r /env/distro-templates /env2/distro-templates"
#podman exec debian-build bash -c "cp /env/extrachrootsteps.sh /env2/"
[[ -z "${runbefore}" ]] || podman exec debian-build bash -c "incus exec build-vm --cwd /env -- bash ${runbefore}"
echo "Starting script"
echo "########################################################################################################" # add a bunch of characters to know when the script starts.
podman exec debian-build bash -c "incus exec build-vm --cwd /env -- bash mkmelinux.sh ${arguments}"
[[ -z "${runafter}" ]] || podman exec debian-build bash -c "incus exec build-vm --cwd /env -- bash ${runafter}"
podman exec debian-build bash -c "cp /env2/harddisk* /env"
podman exec debian-build bash -c "cp /env2/linux.iso /env"
echo "Script exited, deleting container... (press ^C to abort...)"
sleep 5
podman stop debian-build
podman rm debian-build
else
echo "Detected a non harddisk build, executing normally..."
echo "Starting Podman container and mounting dirs..."
podman run -d --privileged --name debian-build -v ./:/env debian:latest sleep infinity
echo "Updating and installing all required bash packages..."
podman exec debian-build bash -c "apt update && apt install parted dosfstools debootstrap squashfs-tools grub-pc-bin grub-efi-amd64-bin xorriso systemd-container mtools qemu-utils fdisk ${TEMPLATE_PACKAGES} -y"
[[ -z "${runbefore}" ]] || podman exec debian-build bash -c "cd /env && bash ${runbefore}"
echo "Starting script"
echo "########################################################################################################" # add a bunch of characters to know when the script starts.
podman exec debian-build bash -c "cd /env && bash mkmelinux.sh ${arguments}"
[[ -z "${runafter}" ]] || podman exec debian-build bash -c "cd /env && bash ${runafter}"
echo "Script exited, deleting container... (press ^C to abort...)"
sleep 5
podman stop debian-build
podman rm debian-build
fi

