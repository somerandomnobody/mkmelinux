# A rewrite of mkmelinux in Python.
import argparse
import tomllib
import subprocess
import tempfile
import atexit
import shlex
import time
import sys
import os

# Python buffers prints when stdout is a pipe (like under podman exec), so our
# messages would all appear at the end, after the subprocess output. Flush every line instead.
sys.stdout.reconfigure(line_buffering=True)

# Colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

def info(msg):
    print(GREEN + "[INFO]" + RESET + " " + msg)

def warn(msg):
    print(YELLOW + "[WARN]" + RESET + " " + msg)

def error(msg):
    print(RED + "[ ERR ]" + RESET + " " + msg)

# Initial argument parsing
parser = argparse.ArgumentParser(
                    prog='mkmelinux',
                    description='A Linux builder',
                    epilog='Need help? Check the documentation at https://github.com/somerandomnobody/mkmelinux.')
parser.add_argument('-dt', '--distro-template', required=True, help='Distro Template file you want to use. Required.')
parser.add_argument('-hn', '--hostname', required=True, help='Hostname of the built system. Required.')
parser.add_argument('-t', '--type', required=True, choices=['ISO', 'HARDDISK', 'V86'], help='Type of build you want to make. Required.')
parser.add_argument('-c', '--configdir', default='distro', help='Path to the distro config folder. Default is "distro".')
parser.add_argument('-vs', '--vhd-size', type=int, help='Size of the harddisk image in gigabytes (integer). Required when type is HARDDISK.')
parser.add_argument('-newfs', '--generate-new-rootfs',
                    action='store_true', help='Generate a new rootfs and delete the old one.')
parser.add_argument('-v', '--var', action='append', default=[], metavar='NAME=VALUE',
                    help='Pass a variable to the distro template, available as $NAME in all template commands. Can be used multiple times.')
parser.add_argument('-sbm', '--skip-boot-marker',
                    action='store_true', help='Skip the V86 ready marker (for custom markers in extrachrootsteps).')
args = parser.parse_args()

if args.type == "HARDDISK" and args.vhd_size is None:
    error("Argument --vhd-size is required when using --type HARDDISK.")
    sys.exit(2)

# Template variables (the old DT.NAME=VALUE arguments)
dtvars = {}
for var in args.var:
    if "=" not in var:
        error("Bad --var '" + var + "', must be NAME=VALUE.")
        sys.exit(2)
    name, value = var.split("=", 1)
    dtvars[name] = value

print("Checking for distro templates...")
files = [f for f in os.listdir('./distro-templates') if os.path.isfile(os.path.join('./distro-templates', f))]
dtfiles = [file for file in files if file.endswith("dt")]
print(dtfiles)
print("Found " + str(len(dtfiles)) + " distro templates.")

# Load the requested distro template
dtpath = os.path.join('./distro-templates', args.distro_template + '.dt')
if not os.path.isfile(dtpath):
    error("Distro template '" + args.distro_template + "' not found (looked for " + dtpath + ")")
    sys.exit(1)
with open(dtpath, "rb") as f:
    template = tomllib.load(f)

# Validate the template
for section, key in [("DistroInfo", "DistroName"), ("DistroInfo", "Supporting"), ("DistroConfig", "Download-Rootfs-Cmd")]:
    if key not in template.get(section, {}):
        error("Distro template '" + args.distro_template + "' is missing required key '" + section + "." + key + "'")
        sys.exit(1)
if args.type not in template["DistroInfo"]["Supporting"]:
    error("Build type '" + args.type + "' is not supported by distro template '" + args.distro_template + "'.")
    error("Supported: " + str(template["DistroInfo"]["Supporting"]))
    sys.exit(1)

def dt(key):
    # Get a key from the DistroConfig section, or "" if the template doesn't set it.
    return template.get("DistroConfig", {}).get(key, "")

info("Working Directory: " + os.getcwd())
info("Distro template: " + args.distro_template + " (" + template["DistroInfo"]["DistroName"] + ")")

# Privilege setup
if os.geteuid() == 0:
    SUDO = []
else:
    SUDO = ["sudo"]
    warn("We will now prompt for a sudo password...")
    subprocess.run(["sudo", "echo", "Sudo access granted"])

def run(cmd, **kwargs):
    # Run a command and return its exit code.
    return subprocess.run(cmd, **kwargs).returncode

def runordie(cmd, **kwargs):
    # Run a command and quit the build if it fails.
    code = run(cmd, **kwargs)
    if code != 0:
        error("Command failed with exit code " + str(code) + ": " + " ".join(cmd))
        sys.exit(1)

def runoutput(cmd):
    # Run a command and return its stdout (quits the build on failure).
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        error("Command failed with exit code " + str(result.returncode) + ": " + " ".join(cmd))
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()

def shell(script):
    # Run a string of shell commands and return the exit code.
    return run(SUDO + ["bash", "-c", script])

def exports():
    # Export statements prepended to every template step, so templates can
    # read --var variables plus TYPE and SKIP_BOOT_MARKER.
    out = ""
    for name in dtvars:
        out += "export " + name + "=" + shlex.quote(dtvars[name]) + "\n"
    out += "export TYPE=" + args.type + "\n"
    if args.skip_boot_marker:
        out += "export SKIP_BOOT_MARKER=YES\n"
    return out

def writestepfile(content):
    # Write a template step to a temp file and return its path.
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".sh", prefix="mkmelinux-", delete=False)
    tmp.write(exports() + content + "\n")
    tmp.close()
    return tmp.name

def runstep(name, content):
    # Run a named template step outside the chroot. Quits the build on failure.
    info("step " + name + " starting")
    tmp = writestepfile(content)
    code = run(SUDO + ["bash", tmp])
    os.remove(tmp)
    if code != 0:
        error("step " + name + " failed! Command was:")
        print("---")
        print(content)
        print("---")
        sys.exit(1)
    info("step " + name + " succeeded")

def runchrootstep(name, content, fatal=True):
    # Run a named template step inside the chroot.
    info("step " + name + " starting")
    tmp = writestepfile(content)
    runordie(SUDO + ["cp", tmp, "./rootfs/_step.sh"])
    os.remove(tmp)
    code = run(SUDO + ["chroot", "./rootfs", "bash", "-c", "PATH=$PATH:/usr/sbin bash /_step.sh"])
    run(SUDO + ["rm", "-f", "./rootfs/_step.sh"])
    if code != 0:
        if not fatal:
            warn("step " + name + " exited non-zero (may be normal in a chroot)")
            return
        error("step " + name + " failed! Command was:")
        print("---")
        print(content)
        print("---")
        sys.exit(1)
    info("step " + name + " succeeded")

# If Setup-Chroot-Cmd ran, Exit-Chroot-Cmd must run when we quit — even on error.
exitchroot = {"pending": ""}
def exitchrootcleanup():
    if exitchroot["pending"] != "":
        content = exitchroot["pending"]
        exitchroot["pending"] = ""
        warn("Running Exit-Chroot-Cmd...")
        tmp = writestepfile(content)
        run(SUDO + ["bash", tmp])
        os.remove(tmp)
atexit.register(exitchrootcleanup)

# Clean old artifacts
info("Cleaning old build artifacts...")
if args.type == "ISO":
    shell("rm -f ./output/linux.iso ./rootfs.squashfs")
elif args.type == "HARDDISK":
    shell("rm -f ./output/harddisk.img")
elif args.type == "V86":
    shell("rm -f ./rootfs-v86.tar")

if args.generate_new_rootfs:
    info("Removing old rootfs...")
    # An aborted build can leave chroot bind mounts (/proc, /sys, /dev) behind
    # inside ./rootfs - rm -rf must never recurse into those.
    if os.path.isdir("./rootfs"):
        shell("umount -R ./rootfs 2>/dev/null || true")
        mounts = subprocess.run(["mount"], capture_output=True, text=True).stdout
        rootfsdir = os.path.join(os.getcwd(), "rootfs")
        mountpoints = [line.split()[2] for line in mounts.splitlines() if len(line.split()) > 2 and line.split()[2].startswith(rootfsdir)]
        for mountpoint in sorted(mountpoints, reverse=True):
            shell("umount " + shlex.quote(mountpoint) + " 2>/dev/null || true")
    shell("rm -rf ./rootfs ./iso")
else:
    info("Will use old rootfs if one already exists.")

# Rootfs identity check
# Reusing a ./rootfs left over from a different distro template fails in
# confusing ways. Record what created the rootfs and refuse a mismatch up front.
rootfsid = "template:" + args.distro_template
if args.type == "V86":
    rootfsid = rootfsid + ":i386"
idfile = "./.mkmelinux-rootfs-id"

if os.path.isdir("./rootfs") and not args.generate_new_rootfs:
    if os.path.isfile(idfile):
        with open(idfile) as f:
            existingid = f.read().strip()
        if existingid != rootfsid:
            error("The existing ./rootfs was created for '" + existingid + "', but this build needs '" + rootfsid + "'.")
            error("Reusing it would fail in confusing ways. Use -newfs to rebuild it.")
            sys.exit(1)
    else:
        warn("Existing ./rootfs has no identity marker (made by an older mkmelinux?).")
        warn("Make sure it really is a '" + rootfsid + "' rootfs, or use -newfs.")

# Download / bootstrap rootfs
if args.generate_new_rootfs or not os.path.isdir("./rootfs"):
    runstep("Download-Rootfs-Cmd", dt("Download-Rootfs-Cmd"))
    with open(idfile, "w") as f:
        f.write(rootfsid + "\n")

# Set hostname
info("Setting hostname to '" + args.hostname + "'...")
shell("chroot ./rootfs bash -c 'rm /etc/hostname && echo " + args.hostname + " >> /etc/hostname' || true") # Some distros come with no default hosts file

# Setup chroot environment
# Mounts /proc, resolv.conf, and makes the rootfs a mountpoint so that the
# distro's package manager works correctly inside the chroot.
if dt("Setup-Chroot-Cmd") != "":
    runstep("Setup-Chroot-Cmd", dt("Setup-Chroot-Cmd"))
    exitchroot["pending"] = dt("Exit-Chroot-Cmd")

# Install base packages
info("Installing base packages...")
if dt(args.type + "-Install-Base-Packages-Cmd") != "":
    runchrootstep(args.type + "-Install-Base-Packages-Cmd", dt(args.type + "-Install-Base-Packages-Cmd"))
else:
    warn("Template has no " + args.type + "-Install-Base-Packages-Cmd - skipping base package install.")
info("Done with initial package installation.")

# Extra customization directory
info("Checking for extra customization directory...")
if os.path.isdir(os.path.join(args.configdir, "extracustomization")):
    info("Found extra customization directory, patching rootfs...")
    shell("cp -r " + shlex.quote(os.path.join(args.configdir, "extracustomization")) + "/* ./rootfs")
else:
    info("No extra customization directory found. Your build will be plain.")

# Extra chroot steps
if os.path.isfile(os.path.join(args.configdir, "extrachrootsteps.sh")):
    info("Found extrachrootsteps.sh, executing inside chroot...")
    with open(os.path.join(args.configdir, "extrachrootsteps.sh")) as f:
        runchrootstep("extrachrootsteps.sh", f.read())
else:
    warn("No extrachrootsteps.sh found. Your build will be plain.")
    # No user script - set up tty1 root autologin and unlock the root account so
    # the system is usable. Works on any systemd distro; non-fatal because not
    # every rootfs can run this (NixOS configures autologin in its template).
    warn("Adding default root autologin so you can log in without a password...")
    runchrootstep("default-autologin", '''
mkdir -p /etc/systemd/system/getty@tty1.service.d/
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
EOF
passwd -d root
''', fatal=False)

# Global patches
if os.path.isdir("./globalpatches"):
    for root, dirs, patchfiles in os.walk("./globalpatches"):
        for patchfile in patchfiles:
            if patchfile.endswith(".sh"):
                script = os.path.join(root, patchfile)
                print(GREEN + "+ Running: " + RESET + script)
                with open(script) as f:
                    runchrootstep(script, f.read(), fatal=False)
                print(GREEN + "+ Done running: " + RESET + script)
else:
    warn("globalpatches directory not found!")

# Post-ExtraChrootSteps-Cmd
# Runs inside the chroot after extrachrootsteps.sh and globalpatches, so
# templates can act on user-supplied content (e.g. pre-placed APKs).
if dt("Post-ExtraChrootSteps-Cmd") != "":
    runchrootstep("Post-ExtraChrootSteps-Cmd", dt("Post-ExtraChrootSteps-Cmd"))

# Pre-initramfs template step (type-specific)
# Lets templates configure the initramfs environment (e.g. install live boot
# hooks) before the initramfs is regenerated.
if dt(args.type + "-Pre-Initramfs-Cmd") != "":
    runchrootstep(args.type + "-Pre-Initramfs-Cmd", dt(args.type + "-Pre-Initramfs-Cmd"))

# Regenerate initramfs
# Errors are warnings here - initramfs tools often exit non-zero in a chroot
# due to missing /dev/console, kernel modules not matching the host, etc.
info("Regenerating initramfs...")
if dt("Regenerate-Initramfs-Cmd") != "":
    runchrootstep("Regenerate-Initramfs-Cmd", dt("Regenerate-Initramfs-Cmd"), fatal=False)
else:
    runchrootstep("update-initramfs", "update-initramfs -u", fatal=False)

if args.type == "V86":
    info("Renaming kernel and initrd for v86...")
    shell("chroot ./rootfs bash -c 'mv /boot/vmlinuz-* /boot/vmlinuz-linux && mv /boot/initrd.img-* /boot/initramfs-linux.img'")

# Exit-Chroot-Cmd - must run before packaging so the rootfs is decoupled
# from the host before we squash / copy it.
exitchrootcleanup()

# Package output
if args.type == "ISO":
    info("Packaging rootfs to SQUASHFS...")
    runordie(SUDO + ["mksquashfs", "rootfs/", "rootfs.squashfs", "-comp", "xz", "-e", "boot"])
    info("Generating ISO directories...")
    os.makedirs("./iso/boot/grub", exist_ok=True)
    os.makedirs("./iso/live", exist_ok=True)
    info("Copying necessary files...")
    if dt("Vmlinuz-Name") != "":
        vmlinuz = dt("Vmlinuz-Name")
    else:
        vmlinuz = sorted([f for f in os.listdir("./rootfs/boot") if f.startswith("vmlinuz")])[-1]
    if dt("Initramfs-Name") != "":
        initramfs = dt("Initramfs-Name")
    else:
        initramfs = sorted([f for f in os.listdir("./rootfs/boot") if f.startswith("initrd.img")])[-1]
    runordie(SUDO + ["cp", "./rootfs/boot/" + vmlinuz, "./iso/boot/vmlinuz"])
    runordie(SUDO + ["cp", "./rootfs/boot/" + initramfs, "./iso/boot/initrd.img"])
    runordie(SUDO + ["mv", "./rootfs.squashfs", "./iso/live"])
    info("Writing GRUB config...")
    extracmdline = ""
    if dt("Grub-Extra-Cmdline") != "":
        extracmdline = " " + dt("Grub-Extra-Cmdline")
    with open("./iso/boot/grub/grub.cfg", "w") as f:
        f.write('''set timeout=5
set default=0

menuentry "Linux ''' + args.hostname + '''" {
    linux /boot/vmlinuz boot=live mklive.label=MKLIVE''' + extracmdline + '''
    initrd /boot/initrd.img
}
''')
    info("Assembling ISO...")
    os.makedirs("./output", exist_ok=True)
    runordie(SUDO + ["grub-mkrescue", "-o", "./output/linux.iso", "./iso"])
    # Patch the ISO 9660 Primary Volume Descriptor to set volume label MKLIVE.
    # The PVD sits at sector 16 (byte 32768); Volume Identifier is at PVD offset 40.
    # This lets udev create /dev/disk/by-label/MKLIVE so the initramfs hook can find
    # the boot medium - the same mechanism the real archiso mkinitcpio hook uses.
    shell("printf '%-32.32s' 'MKLIVE' | dd of=./output/linux.iso bs=1 seek=32808 conv=notrunc 2>/dev/null")
    info("Finished! ISO is ready at output/linux.iso.")

elif args.type == "HARDDISK":
    info("Generating harddisk .img image of " + str(args.vhd_size) + " Gigabytes...")
    os.makedirs("./output", exist_ok=True)
    runordie(SUDO + ["truncate", "-s", str(args.vhd_size) + "G", "./output/harddisk.img"])
    info("Setting up loop device...")
    loopdev = runoutput(SUDO + ["losetup", "-f", "--show", "./output/harddisk.img"])
    info("Partition edit: Making 512MB EFI partition and filling the rest with ext4...")
    run(SUDO + ["fdisk", loopdev], input="g\nn\n1\n\n+512M\nt\n1\nn\n2\n\n\nw\n", text=True)
    info("Attempting to refresh partitions...")
    runordie(SUDO + ["partx", "--update", loopdev])
    time.sleep(0.5)
    info("Formatting partitions...")
    runordie(SUDO + ["mkfs.vfat", "-F", "32", loopdev + "p1"])
    runordie(SUDO + ["mkfs.ext4", loopdev + "p2"])
    info("Mounting partitions...")
    runordie(SUDO + ["mkdir", "-p", "/fat32part", "/ext4part"])
    runordie(SUDO + ["mount", loopdev + "p1", "/fat32part"])
    runordie(SUDO + ["mount", loopdev + "p2", "/ext4part"])
    info("Writing boot files...")
    for d in ["proc", "sys", "dev", "run"]:
        runordie(SUDO + ["mount", "--bind", "/" + d, "./rootfs/" + d])
    runordie(SUDO + ["mkdir", "-p", "/tmpboot"])
    shell("mv ./rootfs/boot/* /tmpboot/")
    runordie(SUDO + ["mount", "--bind", "/fat32part/", "./rootfs/boot/"])
    shell("mv /tmpboot/* ./rootfs/boot/")
    fsuuid = runoutput(SUDO + ["findmnt", "-no", "UUID", "/ext4part"])
    runordie(SUDO + ["chroot", "./rootfs", "bash", "-c", "grub-mkconfig -o /boot/grub/grub.cfg"])
    runordie(SUDO + ["chroot", "./rootfs", "bash", "-c", "sed -i 's/root=UUID=[^ ]*/root=UUID=" + fsuuid + "/g' /boot/grub/grub.cfg"])
    runordie(SUDO + ["chroot", "./rootfs", "bash", "-c", "grub-install --target=x86_64-efi --efi-directory=/boot/ --boot-directory=/boot --removable --recheck --bootloader-id=GRUB"])
    info("Writing fstab...")
    shell("chroot ./rootfs bash -c 'rm -f /etc/fstab && echo \"UUID=" + fsuuid + " / ext4 defaults 0 1\" >> /etc/fstab'")
    info("Writing rootfs to disk...")
    for d in ["proc", "sys", "dev", "run"]:
        runordie(SUDO + ["umount", "./rootfs/" + d])
    shell("cp -r ./rootfs/* /ext4part")
    info("Unmounting partitions...")
    runordie(SUDO + ["sync"])
    runordie(SUDO + ["umount", "/fat32part"])
    runordie(SUDO + ["umount", "/ext4part"])
    info("Detaching loop device...")
    runordie(SUDO + ["losetup", "-d", loopdev])
    info("Finished! Disk image is ready at output/harddisk.img.")
    info("Flash to a drive with: dd if=output/harddisk.img of=/dev/sdX bs=4M status=progress")

elif args.type == "V86":
    info("Exporting 32-bit rootfs as tar...")
    runordie(SUDO + ["tar", "-cf", "./rootfs-v86.tar", "-C", "./rootfs", "."])
    info("Running mkv86.sh...")
    runordie(["bash", "./mkv86.sh"])
