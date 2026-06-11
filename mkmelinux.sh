#!/usr/bin/env bash

# Main build script for mkmelinux.
# We recommend that you run this in Podman / Docker for maximum compatibility.

# Extra params (can declare with arguments):
# GENERATE_HOSTNAME  - hostname of the built system (required)
# TYPE               - "ISO", "HARDDISK", or "V86" (required)
# CONFIGDIR          - path to the distro config folder, e.g. "distro" (required)
# OSTYPE             - "MINBASE" or "NORMAL" — Debian variant (required unless OSTEMPLATE is set)
# OSTEMPLATE         - name of a .dt file in distro-templates/, e.g. "arch-linux" (optional)
# VHD_SIZE           - integer gigabytes, required when TYPE=HARDDISK
# GENERATE_NEW_ROOTFS - if "YES", delete and rebuild the rootfs from scratch
# DEBLOAT            - reserved for future use
# SKIP_BOOT_MARKER   - if "YES", skip the V86 ready marker (for custom markers in extrachrootsteps)
# EMERG_CHROOT       - path to a rootfs to chroot into (skips the normal build entirely)
# EMERG_CHROOT_CMD   - command to run inside the chroot (default: /bin/sh)
# DT.<VAR>=<VALUE>   - pass a variable to the distro template; available as $VAR in all
#                      template commands (both build container and chroot). Use underscores,
#                      not hyphens, in variable names. Example: DT.DROIDOS_TYPE=ANDROIDTV

# ── Argument parsing ──────────────────────────────────────────────────────────

declare -A _DT_VARS=()

for arg in "$@"; do
    if [[ "$arg" == *"="* ]]; then
        key="${arg%%=*}"
        value="${arg#*=}"
        if [[ "$key" == DT.* ]]; then
            dtkey="${key#DT.}"
            _DT_VARS["$dtkey"]="$value"
        else
            declare "$key=$value"
        fi
    fi
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTDIR="$SCRIPT_DIR/output"

# ── Emergency chroot ──────────────────────────────────────────────────────────
# EMERG_CHROOT bypasses the normal build and drops straight into a shell (or a
# specified command) inside an existing rootfs. Useful for debugging a broken
# build without re-running the whole pipeline.

if [[ -n "${EMERG_CHROOT:-}" ]]; then
    if [[ ! -d "${EMERG_CHROOT}" ]]; then
        echo "Error: EMERG_CHROOT path '${EMERG_CHROOT}' does not exist or is not a directory." >&2
        exit 1
    fi
    _cmd="${EMERG_CHROOT_CMD:-/bin/sh}"
    echo "Emergency chroot into '${EMERG_CHROOT}', running: ${_cmd}"
    mount --bind /proc  "${EMERG_CHROOT}/proc"  2>/dev/null || true
    mount --bind /sys   "${EMERG_CHROOT}/sys"   2>/dev/null || true
    mount --bind /dev   "${EMERG_CHROOT}/dev"   2>/dev/null || true
    mount --bind /dev/pts "${EMERG_CHROOT}/dev/pts" 2>/dev/null || true
    chroot "${EMERG_CHROOT}" ${_cmd} || true
    umount "${EMERG_CHROOT}/dev/pts" 2>/dev/null || true
    umount "${EMERG_CHROOT}/dev"     2>/dev/null || true
    umount "${EMERG_CHROOT}/sys"     2>/dev/null || true
    umount "${EMERG_CHROOT}/proc"    2>/dev/null || true
    exit 0
fi

# ── Distro template support ───────────────────────────────────────────────────
# When OSTEMPLATE is set, a .dt TOML file is parsed and its commands override
# the Debian defaults for each build step that it defines.

declare -A _toml
USING_TEMPLATE=0

_toml_parse() {
    local file="$1" section="" key="" val="" in_ml=0 ml_key="" rest=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Strip trailing whitespace
        line="${line%"${line##*[![:space:]]}"}"

        if (( in_ml )); then
            if [[ "$line" == "'''" ]]; then
                in_ml=0
                _toml["${section}.${ml_key}"]="${val%$'\n'}"
                val=""
            else
                val+="${line}"$'\n'
            fi
            continue
        fi

        [[ -z "$line" || "$line" == \#* ]] && continue

        # Section header [Name]
        if [[ "$line" =~ ^\[([A-Za-z0-9_-]+)\]$ ]]; then
            section="${BASH_REMATCH[1]}"
            continue
        fi

        # Key = value
        if [[ "$line" =~ ^([A-Za-z0-9_-]+)[[:space:]]*=[[:space:]]*(.*) ]]; then
            key="${BASH_REMATCH[1]}"
            rest="${BASH_REMATCH[2]}"

            if [[ "$rest" == "'''" ]]; then
                in_ml=1; ml_key="$key"; val=""; continue
            fi

            # Strip surrounding double or single quotes
            if [[ "$rest" =~ ^\"(.*)\"$ ]] || [[ "$rest" =~ ^\'(.*)\'$ ]]; then
                rest="${BASH_REMATCH[1]}"
            fi
            _toml["${section}.${key}"]="$rest"
        fi
    done < "$file"

    if (( in_ml )); then
        echo "Error: TOML parse error in '${file}': unclosed multiline string for key '${ml_key}'" >&2
        exit 1
    fi
}

_toml_validate() {
    local missing=0
    for k in "DistroInfo.DistroName" "DistroInfo.Supporting" "DistroConfig.Download-Rootfs-Cmd"; do
        if [[ -z "${_toml[$k]:-}" ]]; then
            echo "Error: distro template '${OSTEMPLATE}' is missing required key '${k}'" >&2
            missing=1
        fi
    done
    (( missing )) && exit 1

    if [[ "${_toml[DistroInfo.Supporting]:-}" != *"\"${TYPE}\""* ]]; then
        echo "Error: build TYPE='${TYPE}' is not supported by distro template '${OSTEMPLATE}'." >&2
        echo "       Supported: ${_toml[DistroInfo.Supporting]:-}" >&2
        exit 1
    fi
}

# Returns the value for a template key, or empty string if not set.
dt() { echo "${_toml[$1]:-}"; }
dt_has() { [[ -n "${_toml[$1]:-}" ]]; }

# Emit export statements for all DT. variables so they can be prepended to
# any bash -c string or script file that runs inside or outside the chroot.
_dt_exports() {
    local out=""
    for v in "${!_DT_VARS[@]}"; do
        out+="export $(printf '%s=%q' "$v" "${_DT_VARS[$v]}"); "
    done
    printf '%s' "$out"
}

# Run a block of shell commands from a template key as root from the current directory.
# DT. variables are prepended as exports so templates can read them.
# Returns the exit code of the script.
_run_template_cmd() {
    local content="$1" rc
    local tmp
    tmp=$(mktemp /tmp/mkmelinux-XXXXXX.sh)
    {
        for v in "${!_DT_VARS[@]}"; do
            printf 'export %s=%q\n' "$v" "${_DT_VARS[$v]}"
        done
        printf '%s\n' "$content"
    } > "$tmp"
    $SUDO bash "$tmp" && rc=0 || rc=$?
    rm -f "$tmp"
    return $rc
}

# Run a named template step outside the chroot.
# Prints step start/success/failure and exits the build on failure.
_run_step() {
    local name="$1" content="$2"
    echo "${GREEN}[INFO]${RESET} step ${name} starting"
    if _run_template_cmd "$content"; then
        echo "${GREEN}[INFO]${RESET} step ${name} succeeded"
    else
        echo "${RED}[ ERR ]${RESET} step ${name} failed! Command was:"
        echo "---"
        printf '%s\n' "$content"
        echo "---"
        exit 1
    fi
}

# Run a named template step inside the chroot.
# Copies the script into the rootfs, chrootexecutes it, then removes it.
# Exits the build on failure.
_run_chroot_step() {
    local name="$1" content="$2"
    echo "${GREEN}[INFO]${RESET} step ${name} starting"
    local tmp
    tmp=$(mktemp /tmp/mkmelinux-XXXXXX.sh)
    {
        for v in "${!_DT_VARS[@]}"; do
            printf 'export %s=%q\n' "$v" "${_DT_VARS[$v]}"
        done
        printf '%s\n' "$content"
    } > "$tmp"
    $SUDO cp "$tmp" ./rootfs/_step.sh
    rm -f "$tmp"
    if $SUDO chroot ./rootfs bash -c "PATH=$PATH:/usr/sbin bash /_step.sh"; then
        echo "${GREEN}[INFO]${RESET} step ${name} succeeded"
    else
        echo "${RED}[ ERR ]${RESET} step ${name} failed! Command was:"
        echo "---"
        printf '%s\n' "$content"
        echo "---"
        $SUDO rm -f ./rootfs/_step.sh
        exit 1
    fi
    $SUDO rm -f ./rootfs/_step.sh
}

if [[ -n "${OSTEMPLATE:-}" ]]; then
    DT_FILE="${SCRIPT_DIR}/distro-templates/${OSTEMPLATE}.dt"
    if [[ ! -f "$DT_FILE" ]]; then
        echo "Error: distro template '${OSTEMPLATE}' not found (looked for ${DT_FILE})" >&2
        exit 1
    fi
    _toml_parse "$DT_FILE"
    USING_TEMPLATE=1
fi

# ── Mandatory argument checks ─────────────────────────────────────────────────

if [[ -z "${GENERATE_HOSTNAME:-}" ]] || [[ -z "${TYPE:-}" ]] || [[ -z "${CONFIGDIR:-}" ]]; then
    echo "Error: GENERATE_HOSTNAME, CONFIGDIR, and TYPE are required arguments!" >&2
    exit 2
fi
if (( ! USING_TEMPLATE )) && [[ -z "${OSTYPE:-}" ]]; then
    echo "Error: OSTYPE is required when not using a distro template." >&2
    echo "       Set OSTEMPLATE=<name> to use a distro template instead." >&2
    exit 2
fi
if [[ $TYPE == "HARDDISK" ]] && [[ -z "${VHD_SIZE:-}" ]]; then
    echo "Error: Argument VHD_SIZE is required when using TYPE=HARDDISK." >&2
    exit 2
fi
if [[ $TYPE != "HARDDISK" ]] && [[ $TYPE != "ISO" ]] && [[ $TYPE != "V86" ]]; then
    echo "Error: TYPE is invalid (must be HARDDISK, ISO, or V86)." >&2
    exit 2
fi
if [[ -n "${VHD_SIZE:-}" ]] && ! [[ $VHD_SIZE =~ ^[0-9]+$ ]]; then
    echo "Error: VHD_SIZE is not an integer (do not add a G after your value)." >&2
    exit 2
fi
if (( ! USING_TEMPLATE )) && [[ $OSTYPE != "MINBASE" ]] && [[ $OSTYPE != "NORMAL" ]]; then
    echo "Error: OSTYPE is invalid (must be MINBASE or NORMAL, or set OSTEMPLATE to use a distro template)." >&2
    exit 2
fi

# Validate template now that TYPE is confirmed
if (( USING_TEMPLATE )); then
    _toml_validate
fi

# ── Colors ────────────────────────────────────────────────────────────────────

RED=$(tput setaf 1)
GREEN=$(tput setaf 2)
YELLOW=$(tput setaf 3)
BLUE=$(tput setaf 4)
RESET=$(tput sgr0)

# Set after tput so that a tput failure in Podman does not abort the script.
set -euo pipefail

# ── Build log ─────────────────────────────────────────────────────────────────

mkdir -p "$SCRIPT_DIR/logs"
_LOGFILE="$SCRIPT_DIR/logs/build-$(date -u +%Y%m%d-%H%M%S).log"
exec > >(tee "$_LOGFILE") 2>&1
_BUILD_START=$(date -u +%s)
echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Build started — TYPE=${TYPE} HOSTNAME=${GENERATE_HOSTNAME}"

# ── Privilege setup ───────────────────────────────────────────────────────────

echo "${GREEN}[INFO]${RESET} Working Directory: ${PWD}"
if (( USING_TEMPLATE )); then
    echo "${GREEN}[INFO]${RESET} Distro template: ${OSTEMPLATE} (${_toml[DistroInfo.DistroName]:-})"
fi

if [[ $EUID -eq 0 ]]; then
    SUDO=""
else
    SUDO="sudo"
    echo "${YELLOW}[WARN]${RESET} We will now prompt for a sudo password..."
    $SUDO echo "Sudo access granted"
fi

# ── Exit-Chroot-Cmd trap ──────────────────────────────────────────────────────
# If Setup-Chroot-Cmd ran, Exit-Chroot-Cmd must run on exit — even on error.

_EXIT_CONTENT=""
_exit_done=0
_on_exit_cleanup() {
    local _exit_code=$?
    if [[ -n "$_EXIT_CONTENT" ]] && (( ! _exit_done )); then
        _exit_done=1
        echo "${YELLOW}[WARN]${RESET} Running Exit-Chroot-Cmd on exit..."
        local tmp
        tmp=$(mktemp /tmp/mkmelinux-exit-XXXXXX.sh)
        printf '%s\n' "$_EXIT_CONTENT" > "$tmp"
        $SUDO bash "$tmp" || true
        rm -f "$tmp"
    fi
    local _elapsed=$(( $(date -u +%s) - _BUILD_START ))
    if (( _exit_code == 0 )); then
        echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Build finished successfully in ${_elapsed}s."
    else
        echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Build failed (exit ${_exit_code}) after ${_elapsed}s."
    fi
}
trap '_on_exit_cleanup' EXIT

# ── Clean old artifacts ───────────────────────────────────────────────────────

echo "${GREEN}[INFO]${RESET} Cleaning old build artifacts..."
if [[ $TYPE == "ISO" ]]; then
    $SUDO rm -f "$OUTDIR/linux.iso" ./rootfs.squashfs
elif [[ $TYPE == "HARDDISK" ]]; then
    $SUDO rm -f "$OUTDIR/harddisk.img"
elif [[ $TYPE == "V86" ]]; then
    $SUDO rm -f ./rootfs-v86.tar
fi

if [[ "${GENERATE_NEW_ROOTFS:-}" == "YES" ]]; then
    echo "${GREEN}[INFO]${RESET} Removing old rootfs..."
    # A previously aborted build can leave chroot bind mounts (/proc, /sys,
    # /dev) behind inside ./rootfs — rm -rf must never recurse into those.
    if [[ -d ./rootfs ]]; then
        $SUDO umount -R ./rootfs 2>/dev/null || true
        mount | awk -v d="$(pwd)/rootfs" '$3 ~ d {print $3}' | sort -r | while read -r m; do
            $SUDO umount "$m" 2>/dev/null || true
        done
    fi
    $SUDO rm -rf ./rootfs
    $SUDO rm -rf ./iso
else
    echo "${GREEN}[INFO]${RESET} Will use old rootfs if one already exists."
fi

# ── Rootfs identity check ─────────────────────────────────────────────────────
# Reusing a ./rootfs left over from a different distro template (or Debian
# variant) fails in confusing ways — e.g. Alpine's Setup-Chroot-Cmd reporting
# that /sbin/apk does not exist inside what is actually a NixOS rootfs. Record
# what created the rootfs and refuse an obvious mismatch up front.

if (( USING_TEMPLATE )); then
    _ROOTFS_ID="template:${OSTEMPLATE}"
else
    _ROOTFS_ID="debian:${OSTYPE}"
    [[ $TYPE == "V86" ]] && _ROOTFS_ID="${_ROOTFS_ID}:i386"
fi
_ROOTFS_ID_FILE="./.mkmelinux-rootfs-id"

if [[ -d ./rootfs ]] && [[ "${GENERATE_NEW_ROOTFS:-}" != "YES" ]]; then
    if [[ -f "$_ROOTFS_ID_FILE" ]]; then
        _existing_id=$(<"$_ROOTFS_ID_FILE")
        if [[ "$_existing_id" != "$_ROOTFS_ID" ]]; then
            echo "${RED}[ ERR ]${RESET} The existing ./rootfs was created for '${_existing_id}', but this build needs '${_ROOTFS_ID}'."
            echo "${RED}[ ERR ]${RESET} Reusing it would fail in confusing ways. Set GENERATE_NEW_ROOTFS=YES to rebuild it"
            echo "${RED}[ ERR ]${RESET} (in the TUI: answer 'Make a new one' when asked about the existing rootfs)."
            exit 1
        fi
    else
        echo "${YELLOW}[WARN]${RESET} Existing ./rootfs has no identity marker (made by an older mkmelinux?)."
        echo "${YELLOW}[WARN]${RESET} Make sure it really is a '${_ROOTFS_ID}' rootfs, or set GENERATE_NEW_ROOTFS=YES."
    fi
fi

# ── Download / bootstrap rootfs ───────────────────────────────────────────────

if [[ "${GENERATE_NEW_ROOTFS:-}" == "YES" ]] || ! [[ -d ./rootfs ]]; then
    if (( USING_TEMPLATE )); then
        _run_step "Download-Rootfs-Cmd" "$(dt "DistroConfig.Download-Rootfs-Cmd")"
    else
        echo "${GREEN}[INFO]${RESET} Getting Debian rootfs, please wait..."
        ARCH_FLAG=""
        if [[ $TYPE == "V86" ]]; then
            ARCH_FLAG="--arch=i386"
            echo "${GREEN}[INFO]${RESET} V86 build — using 32-bit (i386) rootfs."
        fi
        if [[ $OSTYPE == "MINBASE" ]]; then
            echo "${GREEN}[INFO]${RESET} Getting Minbase variant..."
            $SUDO debootstrap $ARCH_FLAG --variant=minbase stable rootfs http://deb.debian.org/debian/
        else
            echo "${GREEN}[INFO]${RESET} Getting normal variant..."
            $SUDO debootstrap $ARCH_FLAG stable rootfs http://deb.debian.org/debian/
        fi
    fi
    echo "$_ROOTFS_ID" > "$_ROOTFS_ID_FILE"
fi

# ── Set hostname ──────────────────────────────────────────────────────────────

echo "${GREEN}[INFO]${RESET} Setting hostname to '${GENERATE_HOSTNAME}'..."
$SUDO chroot ./rootfs bash -c "rm /etc/hostname && echo ${GENERATE_HOSTNAME} >> /etc/hostname" || true # Some distros come with no default hosts file

# ── Setup chroot environment (template only) ──────────────────────────────────
# Mounts /proc, resolv.conf, and makes the rootfs a mountpoint so that the
# distro's package manager works correctly inside the chroot.

if (( USING_TEMPLATE )) && dt_has "DistroConfig.Setup-Chroot-Cmd"; then
    _run_step "Setup-Chroot-Cmd" "$(dt "DistroConfig.Setup-Chroot-Cmd")"
    if dt_has "DistroConfig.Exit-Chroot-Cmd"; then
        _EXIT_CONTENT="$(dt "DistroConfig.Exit-Chroot-Cmd")"
    fi
fi

# ── Install base packages ─────────────────────────────────────────────────────

echo "${GREEN}[INFO]${RESET} Installing base packages..."
if (( USING_TEMPLATE )); then
    _pkg_key="DistroConfig.${TYPE}-Install-Base-Packages-Cmd"
    if dt_has "$_pkg_key"; then
        _run_chroot_step "${TYPE}-Install-Base-Packages-Cmd" "$(dt "$_pkg_key")"
    else
        echo "${YELLOW}[WARN]${RESET} Template has no ${TYPE}-Install-Base-Packages-Cmd — skipping base package install."
    fi
else
    if [[ $TYPE == "ISO" ]]; then
        echo "${GREEN}[INFO]${RESET} Detected ISO build, installing ISO specific packages..."
        $SUDO chroot ./rootfs bash -c "apt update && apt install busybox linux-image-amd64 grub-pc initramfs-tools live-boot live-tools squashfs-tools systemd-sysv -y"
    elif [[ $TYPE == "HARDDISK" ]]; then
        echo "${GREEN}[INFO]${RESET} Detected HARDDISK build, installing packages..."
        $SUDO chroot ./rootfs bash -c "apt update && apt install busybox linux-image-amd64 grub-efi systemd-sysv -y"
    elif [[ $TYPE == "V86" ]]; then
        echo "${GREEN}[INFO]${RESET} Detected V86 build, installing 32-bit kernel and minimal system..."
        $SUDO bash -c "cat > rootfs/etc/apt/sources.list << 'EOF'
deb http://deb.debian.org/debian bookworm main
deb http://security.debian.org/debian-security bookworm-security main
deb http://deb.debian.org/debian bookworm-updates main
EOF"
        $SUDO chroot ./rootfs bash -c "apt update && apt install linux-image-686 systemd-sysv busybox -y" || true
        echo "${GREEN}[INFO]${RESET} Adding 9p/virtio modules to initramfs for v86 filesystem support..."
        $SUDO chroot ./rootfs bash -c "printf 'virtio_pci\n9pnet\n9pnet_virtio\n9p\n' >> /etc/initramfs-tools/modules"
        echo "${GREEN}[INFO]${RESET} Configuring serial console autologin for state generation..."
        $SUDO chroot ./rootfs bash -c "
mkdir -p /etc/systemd/system/serial-getty@ttyS0.service.d
cat > /etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf << 'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I 115200 xterm
EOF
systemctl enable serial-getty@ttyS0
"
        if [[ -z "${SKIP_BOOT_MARKER:-}" ]]; then
            echo "${GREEN}[INFO]${RESET} Adding boot ready marker..."
            $SUDO chroot ./rootfs bash -c "
cat >> /root/.profile << 'EOF'
if [ -z \"\$V86_READY_SENT\" ]; then
    export V86_READY_SENT=1
    sync
    echo 'V86_SYSTEM_READY'
fi
EOF
"
        else
            echo "${GREEN}[INFO]${RESET} Skipping automatic boot marker (SKIP_BOOT_MARKER=YES)."
        fi
    fi
fi

echo "${GREEN}[INFO]${RESET} Done with initial package installation."

# ── Extra customization directory ─────────────────────────────────────────────

echo "${GREEN}[INFO]${RESET} Checking for extra customization directory..."
if [[ -d "${CONFIGDIR}/extracustomization" ]]; then
    echo "${GREEN}[ OK ]${RESET} Found extra customization directory, patching rootfs..."
    $SUDO cp -r "${CONFIGDIR}/extracustomization/"* ./rootfs
else
    echo "${YELLOW}[INFO]${RESET} No extra customization directory found. Your build will be plain."
fi

# ── Extra chroot steps ────────────────────────────────────────────────────────

if [[ -f "${CONFIGDIR}/extrachrootsteps.sh" ]]; then
    echo "${GREEN}[ OK ]${RESET} Found extrachrootsteps.sh, executing inside chroot..."
    cp "${CONFIGDIR}/extrachrootsteps.sh" ./rootfs/steps.sh
    $SUDO chroot ./rootfs bash -c "PATH=$PATH:/usr/sbin bash /steps.sh"
    echo "${GREEN}[ OK ]${RESET} Script done, cleaning rootfs..."
    $SUDO rm ./rootfs/steps.sh
else
    echo "${YELLOW}[WARN]${RESET} No extrachrootsteps.sh found. Your build will be plain."
    # No user script — set up tty1 root autologin and unlock the root account so
    # the system is usable. Works on any systemd distro; the busybox install is
    # only needed on minimal Debian rootfses, harmless to skip on Arch.
    echo "${YELLOW}[WARN]${RESET} Adding default root autologin so you can log in without a password..."
    if (( ! USING_TEMPLATE )); then
        $SUDO chroot ./rootfs bash -c "apt install busybox -y" || true
    fi
    # Non-fatal: not every rootfs can run this (NixOS has no /usr/bin and
    # manages /etc declaratively — its template configures autologin itself).
    $SUDO chroot ./rootfs bash -c '
mkdir -p /etc/systemd/system/getty@tty1.service.d/
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
EOF
' || true
    # Unlock the root account (Arch ships it locked by default; Debian leaves
    # it without a password but locked). With "passwd -d", root can log in
    # with an empty password — matching the autologin behavior.
    $SUDO chroot ./rootfs bash -c "passwd -d root" || true
    echo "${GREEN}[ OK ]${RESET} Done."
fi

# ── Global patches ────────────────────────────────────────────────────────────

if [[ -d "./globalpatches" ]]; then
    find ./globalpatches -type f -name "*.sh" | while read -r script; do
        echo "${GREEN}+ Running: ${RESET} ${script}"
        cp "$script" ./rootfs/patch.sh
        $SUDO chroot ./rootfs bash -c "PATH=$PATH:/usr/sbin bash /patch.sh" || true
        # Delete from outside the chroot — minimal rootfses may lack rm in PATH.
        $SUDO rm -f ./rootfs/patch.sh
        echo "${GREEN}+ Done running: ${RESET} ${script}"
    done
else
    echo "${YELLOW}[WARN]${RESET} globalpatches directory not found!"
fi

# ── Post-ExtraChrootSteps-Cmd (template only) ─────────────────────────────────
# Runs inside the chroot after extrachrootsteps.sh and globalpatches have been
# applied. At this point extracustomization files are already in the rootfs, so
# templates can inspect or act on user-supplied content (e.g. pre-placed APKs).

if (( USING_TEMPLATE )) && dt_has "DistroConfig.Post-ExtraChrootSteps-Cmd"; then
    _run_chroot_step "Post-ExtraChrootSteps-Cmd" "$(dt "DistroConfig.Post-ExtraChrootSteps-Cmd")"
fi

# ── Pre-initramfs template step (type-specific) ───────────────────────────────
# Lets templates configure the initramfs environment (e.g. install live boot
# hooks) before mkinitcpio / update-initramfs runs.

_pre_initramfs_key="DistroConfig.${TYPE}-Pre-Initramfs-Cmd"
if (( USING_TEMPLATE )) && dt_has "$_pre_initramfs_key"; then
    _run_chroot_step "${TYPE}-Pre-Initramfs-Cmd" "$(dt "$_pre_initramfs_key")"
fi

# ── Regenerate initramfs ──────────────────────────────────────────────────────

echo "${GREEN}[INFO]${RESET} Regenerating initramfs..."
if (( USING_TEMPLATE )) && dt_has "DistroConfig.Regenerate-Initramfs-Cmd"; then
    echo "${GREEN}[INFO]${RESET} step Regenerate-Initramfs-Cmd starting"
    # Errors are warnings here — initramfs tools often exit non-zero in a chroot
    # due to missing /dev/console, kernel modules not matching the host, etc.
    if $SUDO chroot ./rootfs bash -c "PATH=$PATH:/usr/sbin $(_dt_exports)$(dt "DistroConfig.Regenerate-Initramfs-Cmd")"; then
        echo "${GREEN}[INFO]${RESET} step Regenerate-Initramfs-Cmd succeeded"
    else
        echo "${YELLOW}[WARN]${RESET} step Regenerate-Initramfs-Cmd exited non-zero (may be normal in a chroot)"
    fi
else
    $SUDO chroot ./rootfs bash -c "PATH=$PATH:/usr/sbin update-initramfs -u"
fi

if [[ $TYPE == "V86" ]]; then
    echo "${GREEN}[INFO]${RESET} Renaming kernel and initrd for v86..."
    $SUDO chroot ./rootfs bash -c "mv /boot/vmlinuz-* /boot/vmlinuz-linux && mv /boot/initrd.img-* /boot/initramfs-linux.img"
fi

# ── Exit-Chroot-Cmd (template only) ──────────────────────────────────────────

if [[ -n "$_EXIT_CONTENT" ]]; then
    echo "${GREEN}[INFO]${RESET} step Exit-Chroot-Cmd starting"
    _run_template_cmd "$_EXIT_CONTENT" && \
        echo "${GREEN}[INFO]${RESET} step Exit-Chroot-Cmd succeeded" || \
        echo "${YELLOW}[WARN]${RESET} step Exit-Chroot-Cmd exited non-zero"
    _exit_done=1
fi

# ── Package output ────────────────────────────────────────────────────────────

if [[ $TYPE == "ISO" ]]; then
    echo "${GREEN}[INFO]${RESET} Packaging rootfs to SQUASHFS..."
    mksquashfs rootfs/ rootfs.squashfs -comp xz -e boot
    echo "${GREEN}[INFO]${RESET} Generating ISO directories..."
    mkdir -p ./iso/boot/grub
    mkdir -p ./iso/live
    echo "${GREEN}[INFO]${RESET} Copying necessary files..."
    if (( USING_TEMPLATE )) && dt_has "DistroConfig.Vmlinuz-Name"; then
        $SUDO cp "./rootfs/boot/$(dt "DistroConfig.Vmlinuz-Name")" ./iso/boot/vmlinuz
    else
        $SUDO cp ./rootfs/boot/vmlinuz* ./iso/boot/vmlinuz
    fi
    if (( USING_TEMPLATE )) && dt_has "DistroConfig.Initramfs-Name"; then
        $SUDO cp "./rootfs/boot/$(dt "DistroConfig.Initramfs-Name")" ./iso/boot/initrd.img
    else
        $SUDO cp ./rootfs/boot/initrd.img* ./iso/boot/initrd.img
    fi
    $SUDO mv ./rootfs.squashfs ./iso/live
    echo "${GREEN}[INFO]${RESET} Writing GRUB config..."
    _EXTRA_CMDLINE=""
    if (( USING_TEMPLATE )) && dt_has "DistroConfig.Grub-Extra-Cmdline"; then
        _EXTRA_CMDLINE=" $(dt "DistroConfig.Grub-Extra-Cmdline")"
    fi
    cat > ./iso/boot/grub/grub.cfg << EOF
set timeout=5
set default=0

menuentry "Linux ${GENERATE_HOSTNAME}" {
    linux /boot/vmlinuz boot=live mklive.label=MKLIVE${_EXTRA_CMDLINE}
    initrd /boot/initrd.img
}
EOF
    echo "${GREEN}[INFO]${RESET} Assembling ISO..."
    mkdir -p "$OUTDIR"
    $SUDO grub-mkrescue -o "$OUTDIR/linux.iso" ./iso
    # Patch the ISO 9660 Primary Volume Descriptor to set volume label MKLIVE.
    # The PVD sits at sector 16 (byte 32768); Volume Identifier is at PVD offset 40.
    # This lets udev create /dev/disk/by-label/MKLIVE so the initramfs hook can find
    # the boot medium — the same mechanism the real archiso mkinitcpio hook uses.
    printf '%-32.32s' 'MKLIVE' | $SUDO dd of="$OUTDIR/linux.iso" bs=1 seek=32808 conv=notrunc 2>/dev/null
    echo "${GREEN}[INFO]${RESET} Finished! ISO is ready at output/linux.iso."

elif [[ $TYPE == "HARDDISK" ]]; then
    echo "${GREEN}[INFO]${RESET} Generating harddisk .img image of ${VHD_SIZE} Gigabytes..."
    mkdir -p "$OUTDIR"
    $SUDO truncate -s ${VHD_SIZE}G "$OUTDIR/harddisk.img"
    echo "${GREEN}[INFO]${RESET} Setting up loop device..."
    LOOP_DEV=$($SUDO losetup -f --show "$OUTDIR/harddisk.img")
    echo "${GREEN}[INFO]${RESET} Partition edit: Making 512MB EFI partition and filling the rest with ext4..."
    (echo g; echo n; echo 1; echo; echo +512M; echo t; echo 1; echo n; echo 2; echo; echo; echo w) | $SUDO fdisk ${LOOP_DEV}
    echo "${GREEN}[INFO]${RESET} Attempting to refresh partitions..."
    $SUDO partx --update ${LOOP_DEV}
    sleep 0.5
    echo "${GREEN}[INFO]${RESET} Formatting partitions..."
    $SUDO mkfs.vfat -F 32 ${LOOP_DEV}p1
    $SUDO mkfs.ext4 ${LOOP_DEV}p2
    echo "${GREEN}[INFO]${RESET} Mounting partitions..."
    $SUDO mkdir /fat32part
    $SUDO mkdir /ext4part
    $SUDO mount ${LOOP_DEV}p1 /fat32part
    $SUDO mount ${LOOP_DEV}p2 /ext4part
    echo "${GREEN}[INFO]${RESET} Writing boot files..."
    for d in proc sys dev run; do $SUDO mount --bind /$d ./rootfs/$d; done
    $SUDO mkdir /tmpboot
    $SUDO mv ./rootfs/boot/* /tmpboot/
    $SUDO mount --bind /fat32part/ ./rootfs/boot/
    $SUDO mv /tmpboot/* ./rootfs/boot/
    FSUUID=$($SUDO findmnt -no UUID /ext4part)
    $SUDO chroot ./rootfs bash -c "grub-mkconfig -o /boot/grub/grub.cfg"
    $SUDO chroot ./rootfs bash -c "sed -i 's/root=UUID=[^ ]*/root=UUID=${FSUUID}/g' /boot/grub/grub.cfg"
    $SUDO chroot ./rootfs bash -c "grub-install --target=x86_64-efi --efi-directory=/boot/ --boot-directory=/boot --removable --recheck --bootloader-id=GRUB"
    echo "${GREEN}[INFO]${RESET} Writing fstab..."
    $SUDO chroot ./rootfs bash -c "rm /etc/fstab"
    $SUDO chroot ./rootfs bash -c "echo 'UUID=${FSUUID} / ext4 defaults 0 1' >> /etc/fstab"
    echo "${GREEN}[INFO]${RESET} Writing rootfs to disk..."
    for d in proc sys dev run; do $SUDO umount ./rootfs/$d; done
    $SUDO cp -r ./rootfs/* /ext4part
    echo "${GREEN}[INFO]${RESET} Unmounting partitions..."
    $SUDO sync
    $SUDO umount /fat32part
    $SUDO umount /ext4part
    echo "${GREEN}[INFO]${RESET} Detaching loop device..."
    $SUDO losetup -d ${LOOP_DEV}
    echo "${GREEN}[INFO]${RESET} Finished! Disk image is ready at output/harddisk.img."
    echo "${GREEN}[INFO]${RESET} Flash to a drive with: dd if=output/harddisk.img of=/dev/sdX bs=4M status=progress"

elif [[ $TYPE == "V86" ]]; then
    echo "${GREEN}[INFO]${RESET} Exporting 32-bit rootfs as tar..."
    $SUDO tar -cf ./rootfs-v86.tar -C ./rootfs .
    echo "${GREEN}[INFO]${RESET} Running mkv86.sh..."
    bash "$(dirname "$0")/mkv86.sh"

else
    echo "${RED}[ ERR ]${RESET} Error: Invalid TYPE '${TYPE}'. This should have been caught earlier."
    exit 1
fi
