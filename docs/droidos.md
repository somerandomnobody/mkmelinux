# DroidOS explanation

**TLDR: DroidOS is essentially Arch Linux that runs Waydroid full screen.**

Why this instead of building raw Android x86? It would require either building Android from scratch, which requires hundreds of gigabytes of space, or downloading an Android x86 ISO and extracting the rootfs from it, which is kind of pointless because then you're just repackaging an ISO.

DroidOS with Arch Linux also comes with some advantages, namely being able to support any drivers that Linux does, and with Linux supporting a wide range of wifi card drivers, we can more or less guarantee that most PCs will be able to run it.

---
## How it works

DroidOS is built from the `droidos.dt` distro template (see `distro-templates/`). The base is the official Arch Linux bootstrap rootfs with the `linux-zen` kernel, plus Weston (Wayland compositor in kiosk mode) and Waydroid (Android in an LXC container) from the archlinuxcn repository.

The boot chain looks like this:

1. **GRUB** boots the kernel with a quiet command line (`quiet loglevel=3 ...`) so no kernel text is shown.
2. **Initramfs** — a custom mkinitcpio hook (`droidos-splash`) draws the DroidOS boot screen on tty1 within the first moments of boot. On the live ISO, a second hook (`mklive`) finds the boot medium by volume label, mounts the squashfs and sets up an overlayfs writable layer before switching root.
3. **systemd** boots in the background while the boot screen keeps the display clean. `systemd-firstboot` is masked so it never prompts for timezone/locale (defaults: UTC, en_US.UTF-8).
4. **Autologin** — root is logged in automatically on tty1, and `.bash_profile` stops the boot screen and launches Weston.
5. **Weston** runs in kiosk mode with the pixman (CPU) renderer and starts `runwaydroid.sh`, which handles networking, audio, GPU detection, and finally runs `waydroid show-full-ui` — full-screen Android.

If Android shuts down or Waydroid exits, a menu appears offering to restart Android, reboot, shut down, drop to a shell, or (on the live ISO) install to disk. If the Android UI crashes three times in a row, the system reboots itself.

---
## Building DroidOS

The easiest way is the TUI: run `bash host-setup.sh`, pick ISO or Virtual Machine as the build type, then pick DroidOS on the template screen. The TUI also has a DroidOS configuration page where you choose between the standard and Android TV variants and can pre-load APKs.

To build without the TUI, use a `distro/arguments.txt` like this and run mkmelinux through `runinpodman.sh`:

```
GENERATE_HOSTNAME=droidos TYPE=ISO CONFIGDIR=/env/distro OSTEMPLATE=droidos
```

Supported build types (`TYPE`):
- `ISO` — a live ISO, bootable on both BIOS and UEFI. Includes the disk installer. Recommended.
- `HARDDISK` — a raw UEFI-only virtual machine disk image (requires `VHD_SIZE`).

v86 builds are not supported (Android needs far more than v86 can offer).

### Template arguments

Template variables are passed with the `DT.` prefix (see `distro-templates/README.md`):

`DT.DROIDOS_TYPE` — can be either `MOBILE` or `ANDROIDTV`. If unset, `MOBILE` is the default. `MOBILE` initializes a vanilla LineageOS-based Android image; `ANDROIDTV` downloads an Android TV image with GApps instead (Android TV image by supechicken666.dev).

The chosen type is baked into the image at `/etc/droidos/config` so runtime scripts know which variant they are running.

### Pre-installing APKs

Any `.apk` files placed in `distro/extracustomization/var/lib/droidos/apks/` before building are installed automatically on first boot, once Android finishes booting. Already-installed APKs are tracked in a `.installed` directory so they are not installed twice. The TUI's DroidOS page points at the same folder.

---
## The live ISO experience

On first boot of the live ISO:

1. If no network connection comes up within ~10 seconds, a dialog offers `nmtui` to connect to wifi (NetworkManager handles networking).
2. A boot menu appears: Run DroidOS Live, Install DroidOS to Disk, Shut Down, Restart, or Exit to Shell.
3. "Run DroidOS Live" starts Android directly from the ISO (changes are kept in RAM via overlayfs and lost on reboot).

### The installer

"Install DroidOS to Disk" runs a dialog-based installer that:

- Lets you pick a target disk (everything on it is erased).
- Detects BIOS vs UEFI firmware automatically and partitions accordingly (GPT in both cases; an EFI system partition on UEFI, a BIOS boot partition for GRUB on legacy systems).
- Copies the live system to disk with rsync, regenerates the initramfs for disk boot, installs GRUB, and writes an fstab.
- Offers a "safe mode" GRUB entry that boots the fallback initramfs without the quiet flags.

An installed system boots the same way as the live one, minus the live boot menu.

---
## GPU handling

Android normally requires GPU acceleration, but DroidOS adapts at startup:

- **Intel / AMD GPU present** — hardware rendering is used as-is.
- **Nvidia GPU with an Intel iGPU** — Waydroid is routed through the Intel iGPU (Nvidia's driver does not work with Waydroid's gralloc).
- **Nvidia only, or no GPU at all** — software rendering via SwiftShader is enabled automatically. Slower, but it boots.

Android TV is the exception: it requires hardware rendering (Intel or AMD), and refuses to start with an explanatory message otherwise. Android TV also forces a 1920×1080 render resolution to avoid a stride-alignment display artifact on Intel hardware.

Weston itself uses the pixman CPU renderer, which avoids a DMA-BUF fence race that causes diagonal tearing during animations on Intel.

---
## Other details

- **Audio** runs as PipeWire + WirePlumber + pipewire-pulse, started by `droidos-audio` before Android launches, with the default sink set to 100%.
- **Binder** devices (`binder`, `hwbinder`, `vndbinder`) are created via binderfs by `droidos-binder` on every Android session start. The `linux-zen` kernel ships the binder module.
- **Fake wifi**: `persist.waydroid.fake_wifi=*` makes all Android apps see a WiFi connection; actual traffic flows through the `waydroid0` bridge. NetworkManager is told to leave the bridge and veth interfaces alone.
- **Device identity**: Android reports manufacturer/brand `mkmelinux`, model `DroidOS`.
- **ARM app support**: libhoudini is installed via [waydroid_script](https://github.com/casualsnek/waydroid_script) so ARM-only APKs run on x86. GApps are installed the same way.
- **Boot screen**: drawn from the initramfs by the `droidos-splash` mkinitcpio hook on tty1, and kept on screen until Weston takes over the display. The hook is included in the live ISO initramfs, the HARDDISK image initramfs, and any initramfs regenerated by the disk installer.

---
## Hardware requirements

Note that Android by default requires SSE3 support, so CPUs without SSE3 will never be able to boot Android.

Additionally, Android typically requires GPU acceleration to run, however in this case we automatically switch to software rendering if we cannot find a GPU. This works on the normal Android image, but Android TV requires a GPU for acceleration, otherwise it doesn't seem to boot at all.

A working internet connection is needed during the build (Android images, GApps, and libhoudini are downloaded at build time). The OS itself boots fine offline — if no connection is found at startup, you are offered `nmtui` to set one up, and you can skip it.
