# Fedora Atomic explanation

**TLDR: an image-based Fedora live ISO, built from the official `fedora-bootc` base image — the same image the whole Fedora Atomic family (Silverblue, Kinoite, CoreOS, IoT) derives from.**

Why build from a container image instead of bootstrapping with dnf? Because that *is* how Fedora Atomic works: the OS ships as a bootable container image rather than being assembled from packages on the target machine. Unlike a normal distro container image, `quay.io/fedora/fedora-bootc` contains a complete bootable Fedora — kernel, systemd, NetworkManager, dnf, and dracut included. Customizing the rootfs with dnf inside the mkmelinux chroot mirrors exactly how Fedora Atomic images are customized in a Containerfile.

---
## How it works

Fedora Atomic is built from the `fedora-atomic.dt` distro template (see `distro-templates/`).

1. **Rootfs** — `skopeo` pulls the `fedora-bootc` OCI image from quay.io, and the template flattens its layers (65 of them — bootc images are chunked per-package-group) into `./rootfs` in manifest order, applying whiteouts and keeping the usr-merge directory symlinks intact. This is the same flattening a container runtime performs at `podman run` time.
2. **Customization** — the standard mkmelinux flow runs in the chroot: `extracustomization/` files are copied in, `extrachrootsteps.sh` runs (use **dnf**, not apt!), and global patches are applied. The only package the template itself adds is `dracut-live`.
3. **Initramfs** — Fedora's own **dracut `dmsquash-live`** module handles the live boot, the same mechanism real Fedora live ISOs use. The template builds a generic (non-hostonly) initramfs with `dmsquash-live` and `overlayfs` included. The kernel in bootc images lives at `/usr/lib/modules/<kver>/vmlinuz` (there is no populated `/boot`), so the template copies it out to `/boot/vmlinuz-fedora` for packaging.
4. **Boot** — GRUB passes `root=live:CDLABEL=MKLIVE rd.live.dir=live rd.live.squashimg=rootfs.squashfs rd.live.overlay.overlayfs=1` on the kernel command line. dmsquash-live finds the boot medium by the `MKLIVE` ISO label, detects mkmelinux's "flattened" squashfs (a plain root filesystem instead of Fedora's usual nested `LiveOS/rootfs.img`), and mounts it read-only under an overlayfs writable layer. Changes live in RAM and are lost on reboot.
5. **Login** — with no `extrachrootsteps.sh`, the standard mkmelinux default applies: root autologin on tty1 with an empty password. NetworkManager (included in the base image) brings up networking via DHCP.

### SELinux

SELinux is disabled (`selinux=0` on the kernel command line, and `SELINUX=disabled` in `/etc/selinux/config`). Tar extraction and mksquashfs do not preserve SELinux labels, and an unlabeled filesystem with SELinux enforcing will not boot. The policy packages remain installed, so a future disk-install path could relabel and re-enable it.

---
## Building Fedora Atomic

The easiest way is the TUI: run `bash host-setup.sh`, pick ISO as the build type, then pick Fedora Atomic on the template screen.

To build without the TUI, use a `distro/arguments.txt` like this and run mkmelinux through `runinpodman.sh`:

```
GENERATE_HOSTNAME=fedora TYPE=ISO CONFIGDIR=/env/distro OSTEMPLATE=fedora-atomic
```

Supported build types (`TYPE`):
- `ISO` — a live ISO (BIOS + UEFI via grub-mkrescue). The only supported type.

`HARDDISK` is not supported: mkmelinux's disk path runs `grub-install --target=x86_64-efi` inside the chroot, which Fedora's grub2 build refuses (Fedora installs prebuilt EFI binaries from `grub2-efi-x64` instead). `V86` is not supported either (no 32-bit Fedora).

A working internet connection is needed during the build (the base image is ~1 GiB compressed; expect a roughly 1.2 GiB ISO from a plain build). The built ISO boots fine offline.

### Template arguments

Template variables are passed with the `DT.` prefix (see `distro-templates/README.md`):

`DT.FEDORA_BOOTC_IMAGE` — the bootc image reference to build from. Defaults to `quay.io/fedora/fedora-bootc:latest`, which tracks the newest stable Fedora. Pin a release with e.g. `DT.FEDORA_BOOTC_IMAGE=quay.io/fedora/fedora-bootc:43`, or point it at any other bootc-compatible image (your own derived image included).

---
## Customizing

**Use dnf in `extrachrootsteps.sh`** — for example:

```bash
dnf -y install htop neovim
```

Things to know:

- The TUI's desktop / browser / extra-packages presets generate **apt** (or pacman) commands and will not work on Fedora — write the dnf equivalents yourself in the script editor. Desktops install the Fedora way (e.g. `dnf -y group install xfce-desktop-environment`), but keep an eye on ISO size.
- `/root` and `/home` are symlinks into `/var` (`var/roothome`, `var/home`) — this is normal for bootc images and already scaffolded by the template. `useradd -m` works as expected.
- Files in `distro/extracustomization/` are copied straight into the rootfs as usual.
- `rpm-ostree`/`bootc` are present in the image but the live system is not an ostree deployment, so `bootc upgrade`/`rpm-ostree status` will not function at runtime. Make changes at build time with dnf instead — the same model as a bootc Containerfile.

---
## Other details

- **Why not pull the Silverblue ostree ref instead?** The bootc base image is the direction Fedora Atomic is headed (bootable containers), it is a quarter the size of a desktop variant, and it is customizable with plain dnf in a chroot — no ostree repository plumbing needed at build time.
- The dracut config installed by the template lives at `/etc/dracut.conf.d/mklive.conf` (`hostonly=no`, plus the `dmsquash-live`/`overlayfs` modules), so any initramfs regenerated later (e.g. after a kernel update at build time) stays live-bootable.
- dmsquash-live mounts the medium at `/run/initramfs/live` and the read-only squashfs at `/run/initramfs/squashfs` in the booted system, rather than mkmelinux's usual `/run/mklive/*` paths used by the Arch/Alpine/NixOS templates.
