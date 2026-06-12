# A rewrite of runinpodman in Python.
# Why an Incus VM on top of a container?
# It allows us to use loop devices regardless of host configuration. Also works on CI since CI most likely has KVM. Also provides a well known build environment.
import argparse
import tomllib
import subprocess
import shlex
import time
import sys
import os

# Python buffers prints when stdout is a pipe (like in CI), so our messages
# would all appear at the end, after the podman output. Flush every line instead.
sys.stdout.reconfigure(line_buffering=True)

parser = argparse.ArgumentParser(
                    prog='runinpodman',
                    description='Runs the mkmelinux build inside a Podman container.',
                    epilog='Need help? Check the documentation at https://github.com/somerandomnobody/mkmelinux.')
parser.add_argument('-pv86', '--package-v86-only',
                    action='store_true', help='Only run the v86 packaging step (fs2json, copy-to-sha256, state generation).')
args = parser.parse_args()

def run(cmd, **kwargs):
    # Run a command and return its exit code.
    return subprocess.run(cmd, **kwargs).returncode

def runordie(cmd, **kwargs):
    # Run a command and quit if it fails.
    code = run(cmd, **kwargs)
    if code != 0:
        print("Command failed with exit code " + str(code) + ": " + " ".join(cmd))
        sys.exit(1)

def incontainer(cmd):
    # Run a bash command inside the build container.
    runordie(["podman", "exec", "debian-build", "bash", "-c", cmd])

def deletecontainer():
    print("Script exited, deleting container... (press ^C to abort...)")
    time.sleep(5)
    run(["podman", "stop", "debian-build"])
    run(["podman", "rm", "debian-build"])

if args.package_v86_only:
    print("Packaging v86 build...")
    run(["podman", "rm", "-f", "debian-build"], capture_output=True)
    runordie(["podman", "run", "--name", "debian-build", "-v", "./:/env", "debian:latest", "bash", "-c",
              "apt update && apt install nodejs python3 python3-pip -y && pip3 install zstandard --break-system-packages && bash /env/mkv86.sh"])
    run(["podman", "rm", "debian-build"])
    sys.exit(0)

with open("./distro/arguments.txt") as f:
    arguments = f.read().strip()
argparts = shlex.split(arguments)

def argvalue(flags):
    # Get the value following one of the given flags in the arguments string.
    for i, part in enumerate(argparts):
        if part in flags and i + 1 < len(argparts):
            return argparts[i + 1]
        for flag in flags:
            if part.startswith(flag + "="):
                return part.split("=", 1)[1]
    return ""

buildtype = argvalue(["-t", "--type"])

# If a distro template is specified, extract its ContainerConfig.Packages so
# the build container has the tools the template needs (e.g. curl, zstd for Arch).
templatepackages = ""
templatename = argvalue(["-dt", "--distro-template"])
if templatename != "":
    dtpath = "./distro-templates/" + templatename + ".dt"
    if os.path.isfile(dtpath):
        with open(dtpath, "rb") as f:
            template = tomllib.load(f)
        templatepackages = " ".join(template.get("ContainerConfig", {}).get("Packages", []))
        print("Distro template '" + templatename + "' - extra container packages: " + (templatepackages if templatepackages else "none"))
    else:
        print("Warning: distro template '" + templatename + "' not found at " + dtpath)

# Before/after hooks
runbefore = ""
runafter = ""
if os.path.isfile("./container/runbefore.sh"):
    print("Found runbefore script.")
    runbefore = "./container/runbefore.sh"
if os.path.isfile("./container/runafter.sh"):
    print("Found runafter script.")
    runafter = "./container/runafter.sh"

if run(["podman", "stats", "--no-stream", "debian-build"], capture_output=True) == 0:
    print("Detected Podman container is still running, quitting it...")
    run(["podman", "stop", "debian-build"])
    run(["podman", "rm", "debian-build"])

print("Checking build type...")
if buildtype == "V86":
    print("Detected a V86 build...")
    print("Starting Podman container and mounting dirs...")
    runordie(["podman", "run", "-d", "--privileged", "--name", "debian-build", "-v", "./:/env", "debian:latest", "sleep", "infinity"])
    print("Updating and installing required packages (debootstrap, python3, nodejs)...")
    incontainer("apt update && apt install debootstrap python3 python3-pip nodejs " + templatepackages + " -y")
    incontainer("pip3 install zstandard --break-system-packages")
    if runbefore != "":
        incontainer("cd /env && bash " + runbefore)
    print("Starting script")
    print("########################################################################################################")
    incontainer("cd /env && python3 mkmelinux.py " + arguments)
    if runafter != "":
        incontainer("cd /env && bash " + runafter)
    print("Running v86 packaging (fs2json, copy-to-sha256, state generation)...")
    incontainer("cd /env && bash mkv86.sh")
    deletecontainer()
elif buildtype == "HARDDISK":
    print("Detected a harddisk build, proceeding with harddisk setup...")
    print("Note; harddisk images produced will be UEFI bootable only.")
    if not os.path.isfile("./.dismissvhostwarning"):
        print("###########################################################")
        print("#               WARNING! Please read this!                #")
        print("# We have detected that you are running a HARDDISK build. #")
        print("# HARDDISK builds require loop devices. To ensure that we #")
        print("# have enough loop devices, we'll launch an Incus VM to   #")
        print("# build it for you.                                       #")
        print("# This *REQUIRES* that kernel module vhost_vsock is added #")
        print("# and currently running on your host.                     #")
        print("# If unsure, execute 'sudo modprobe vhost_vsock' to fix.  #")
        print("###########################################################")
        print("(to dismiss, create the file .dismissvhostwarning in the same directory that the script is ran from.)")
        print("Waiting 10 seconds before continuing...")
        time.sleep(10)
    print("Starting Podman container and mounting dirs...")
    runordie(["podman", "run", "-d", "--privileged", "--name", "debian-build", "-v", "./:/env", "debian:latest", "sleep", "infinity"])
    print("Updating and installing all required bash packages...")
    incontainer("apt update && apt install sshfs incus tmux -y")
    incontainer("service incus start && incus admin init --auto && incus launch images:debian/12 build-vm --vm")
    print("Waiting for Incus VM to become ready...")
    incontainer("until incus exec build-vm -- true 2>/dev/null; do sleep 2; done")
    incontainer("incus exec build-vm -- apt install python3 parted dosfstools debootstrap squashfs-tools grub-pc-bin grub-efi-amd64-bin xorriso systemd-container mtools qemu-utils fdisk " + templatepackages + " -y")
    incontainer("mkdir /env2")
    incontainer("incus exec build-vm -- mkdir /env")
    incontainer("tmux new-session -d -s incusfiles incus file mount build-vm/env /env2/")
    time.sleep(1)
    incontainer("cp /env/mkmelinux.py /env2")
    incontainer("cp -r /env/container /env2")
    incontainer("cp -r /env/distro /env2/distro")
    incontainer("cp -r /env/globalpatches /env2/globalpatches")
    incontainer("cp -r /env/distro-templates /env2/distro-templates")
    if runbefore != "":
        incontainer("incus exec build-vm --cwd /env -- bash " + runbefore)
    print("Starting script")
    print("########################################################################################################")
    incontainer("incus exec build-vm --cwd /env -- python3 mkmelinux.py " + arguments)
    if runafter != "":
        incontainer("incus exec build-vm --cwd /env -- bash " + runafter)
    incontainer("mkdir -p /env/output && cp /env2/output/harddisk* /env/output/ 2>/dev/null || cp /env2/harddisk* /env/ 2>/dev/null || true")
    deletecontainer()
else:
    print("Detected a non harddisk build, executing normally...")
    print("Starting Podman container and mounting dirs...")
    runordie(["podman", "run", "-d", "--privileged", "--name", "debian-build", "-v", "./:/env", "debian:latest", "sleep", "infinity"])
    print("Updating and installing all required bash packages...")
    incontainer("apt update && apt install python3 parted dosfstools debootstrap squashfs-tools grub-pc-bin grub-efi-amd64-bin xorriso systemd-container mtools qemu-utils fdisk " + templatepackages + " -y")
    if runbefore != "":
        incontainer("cd /env && bash " + runbefore)
    print("Starting script")
    print("########################################################################################################")
    incontainer("cd /env && python3 mkmelinux.py " + arguments)
    if runafter != "":
        incontainer("cd /env && bash " + runafter)
    deletecontainer()
