# Distro Templates
Distro Templates are **TOML** formatted files, that correspond to how mkmelinux should download and prepare the distro. 

## NOTE: This is **NOT** where you customize your distro. This is where you set up a base distribution for customization. For customizing a distro, use the distro/ folder.

For now, Arch Linux is supported. Future distros to be supported include:
- NixOS
- Alpine Linux
- Android x86 (Supported partially with droidos.dt.)
- Potentially Fedora Atomic

## Parameters

This is what a typical DistroInfo section of a distro template should look like, as an example:
```toml
[DistroInfo]
DistroName = "DroidOS"
Arch = "x64"
Description = "Android x86 via Waydroid on Weston — boots straight into Android"
Supporting = ["ISO", "HARDDISK"]
```
What is required: DistroName, Arch and Supporting.
DistroName: a string. Preferrably something short, as a name to your Distro Template.
Arch: one of the following: x64, x86. In future, more architectures may be added.
Description: a string. Again, a short description (one to two sentences) describing your Distro Template.
Supporting: one or multiple of the following: ISO, HARDDISK, V86. This is the build type that your Distro Template will support.

This is what a typical ContainerConfig section should look like:
```toml
[ContainerConfig]
Packages = ["curl", "zstd"]
```
This is completely optional - but it can be useful if building specific distros with specific system requirements.
What is required: nothing.
Packages: an array - enter in valid packages that can be installed using the debian APT system. These packages are installed in the build container, not the distro itself.

This is what a typical DistroConfig section should look like:
```toml
[DistroConfig]

Download-Rootfs-Cmd = ""
Setup-Chroot-Cmd = ""
Exit-Chroot-Cmd = ""
ISO-Install-Base-Packages-Cmd = ""
HARDDISK-Install-Base-Packages-Cmd = ""
ISO-Pre-Initramfs-Cmd = ""
Regenerate-Initramfs-Cmd = ""
Vmlinuz-Name = ""
Initramfs-Name = ""
```

Download-Rootfs-Cmd: runs in the build container. Should produce a usable rootfs/ directory. This is where you download and extract your base rootfs tarball.

Setup-Chroot-Cmd: runs in the build container, before entering the chroot. Use this to mount /proc, /dev, /sys, resolv.conf, and anything else the chroot needs to function — for example, initialising a package manager's keyring.

Exit-Chroot-Cmd: runs in the build container, after the chroot work is done. Should unmount everything that Setup-Chroot-Cmd mounted, decoupling the rootfs from the host system.

(ISO|HARDDISK)-Install-Base-Packages-Cmd: runs inside the chroot. The ISO and HARDDISK variants can differ — for example, ISO builds typically need squashfs-tools while HARDDISK builds need efibootmgr. Install only what is necessary to produce a bootable system; avoid bloating the final image with packages the user did not ask for.

Post-ExtraChrootSteps-Cmd: runs inside the chroot, after extrachrootsteps.sh and globalpatches have been applied. At this point any files the user placed in the extracustomization folder are already in the rootfs, so this step can inspect or act on them — for example, DroidOS uses it to inject APKs directly into the Waydroid system image so they are pre-installed as system apps on first Android boot.

(ISO|HARDDISK|V86)-Pre-Initramfs-Cmd: runs inside the chroot, after the install command but before the initramfs is generated. Each build type has its own variant — ISO-Pre-Initramfs-Cmd, HARDDISK-Pre-Initramfs-Cmd, and V86-Pre-Initramfs-Cmd — and only the one matching the current build type runs. Use this to install any custom mkinitcpio hooks or modules that the boot process requires — for example, the mklive hook that mounts the squashfs and sets up an overlayfs writable layer for ISO builds.

Regenerate-Initramfs-Cmd: runs inside the chroot. Should regenerate the initramfs or initrd image. For Arch-based distros this is mkinitcpio -P; for Debian-based distros this would be update-initramfs -u.

Vmlinuz-Name: the filename of the kernel image inside the rootfs, so mkmelinux knows where to find it when packaging the final build. For example, vmlinuz-linux-zen.

Initramfs-Name: the filename of the initramfs image inside the rootfs. For example, initramfs-linux-zen.img.

## Template Arguments (DT. variables)

You can pass custom variables into a distro template at build time by prefixing them with `DT.` on the command line:

```
DT.DROIDOS_TYPE=ANDROIDTV
```

Inside the template, the variable is available without the `DT.` prefix — so the above becomes `$DROIDOS_TYPE`. These variables are available in all template commands: Download-Rootfs-Cmd, Setup-Chroot-Cmd, Install-Base-Packages-Cmd, Pre-Initramfs-Cmd, Regenerate-Initramfs-Cmd, and Exit-Chroot-Cmd.

Use underscores in variable names, not hyphens. Hyphens are not valid in bash variable names.

Example use in a template — DroidOS uses `DROIDOS_TYPE` to switch between a standard Android build and an Android TV build:
```toml
ISO-Install-Base-Packages-Cmd = '''
if [ "${DROIDOS_TYPE:-MOBILE}" = "ANDROIDTV" ]; then
    waydroid init -c https://ota.supechicken666.dev/system \
                  -v https://ota.supechicken666.dev/vendor -s GAPPS
else
    waydroid init -s VANILLA
fi
'''
```
To build an Android TV image, pass `DT.DROIDOS_TYPE=ANDROIDTV` to mkmelinux. If the variable is not set, the default `MOBILE` build is used.
