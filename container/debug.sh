#!/bin/bash

# This script is supposed to be executed within an already running Podman container. It allows you to mount EFI partitions to debug why your harddisk images aren't working.
# Note: this is for HARDDISK builds only.

echo "Mounting loop device..."
LOOP_DEV=$($SUDO losetup -f --show ${PWD}/harddisk.img)
echo "Mounting partitions..."
$SUDO partx --update ${LOOP_DEV}
sleep 0.5
$SUDO mount ${LOOP_DEV}p1 /fat32part
$SUDO mount ${LOOP_DEV}p2 /ext4part
echo "Binding system folders necessary for bootloader installation inside chroot..."
for d in proc sys dev run; do $SUDO mount --bind /$d ./rootfs/$d; done
echo "Done"