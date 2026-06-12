#!/usr/bin/env python3
# mkmelinux TUI main file

import asyncio
import os
import pty
import random
import re
import select
import subprocess
import threading
from pathlib import Path

_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[mABCDEFGHJKSTfhnsu]|\x1b\(B|\r')

from textual.app import App, ComposeResult
from textual.containers import Center, Middle, Vertical, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Static,
    TextArea,
)

SCRIPT_DIR = Path(__file__).parent
DISTRO_DIR = SCRIPT_DIR / "distro"

BUILD_QUOTES = [
    "Making Linux happen...",
    "Arguing with the kernel...",
    "Downloading more RAM...",
    "Compiling feelings...",
    "Untangling dependencies...",
    "Bribing the package manager...",
    "Summoning the build daemon...",
    "Asking Stack Overflow...",
    "Blaming systemd...",
    "Counting inodes...",
    "Herding processes...",
    "Staring at dmesg output...",
    "Applying duct tape to the bootloader...",
    "Figuring out life...",
    "Asking AI for help...",
    "Using up some CPU cycles...",
    "The Linux Factory is baking...",
    "A freshly baked Linux build, coming (very) soon...",
    "Making cool-looking text appear...",
    "mkmelinux is making...",
    "Taking our sweet, sweet time...",
    "Waiting for the penguin to gather it's things...",
    "Hoping this build succeeds...",
    "mkmelinux is mkmelinux-ing...",
    "Thinking about life choices...",
    "Executing scripts...",
    "Your all-new penguin OS is being built...",
    "Making another Linux distro...",
    "Preparing the world for your creation...",
    "Waiting for the build to finish...",
    "Ruminating on packages...",
    "Making more loading quotes to show you...",
    "Nudging the Linux penguin to wake up...",
    "Writing bits and bytes to your drives...",
    "Executing in Podman...",
    "Making files...",
    "Building (almost) from scratch...",
    "The scripts are working...",
    "Using up your precious RAM...",
    "The Linux factory is hard at work...",
    "Penguins are running around, and gathering up into a file...",
    "Hot, and freshly-baked Linux builds coming your way...",
    "Sprucing up Linux...",
    "Making interesting things happen...",
    "Did you know? Press ^p to change theme and view a command palette.",
    "Does anyone read these...",
    "Doing the impossible...",
    "Figuring out the answer to life...",
    "Doing sorcery...",
    "Daydreaming...",
    "Yawning...",
    "Judging carefully...",
    "Scratching our heads...",
    "Manually blinking...",
    "Checking the time...",
    "Thinking about it...",
    "Waving a magic wand...",
    "Becoming a distro maintainer...",
    "Programming...",
    "Software engineering...",
    "Adding hacky fixes...",
    "Putting on a black hoodie...",
]
TEMPLATES_DIR = SCRIPT_DIR / "distro-templates"
ARGUMENTS_FILE = DISTRO_DIR / "arguments.txt"
EXTRACHROOTSTEPS_FILE = DISTRO_DIR / "extrachrootsteps.sh"


def _parse_dt_info(path: Path) -> dict:
    """Extract DistroInfo fields from a .dt file for display in the TUI."""
    info: dict = {"stem": path.stem, "display_name": path.stem, "description": "", "supporting": []}
    section = ""
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "DistroInfo" and "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == "DistroName":
                info["display_name"] = val
            elif key == "Description":
                info["description"] = val
            elif key == "Supporting":
                info["supporting"] = re.findall(r'"([^"]+)"', val)
    return info


def discover_templates(build_type: str) -> list:
    """Return template info dicts whose Supporting list includes build_type."""
    if not TEMPLATES_DIR.is_dir():
        return []
    results = []
    for dt_file in sorted(TEMPLATES_DIR.glob("*.dt")):
        info = _parse_dt_info(dt_file)
        if not info["supporting"] or build_type in info["supporting"]:
            results.append(info)
    return results


def all_templates(build_type: str) -> list:
    """Return all template info dicts, each with a 'supported' bool for build_type."""
    if not TEMPLATES_DIR.is_dir():
        return []
    results = []
    for dt_file in sorted(TEMPLATES_DIR.glob("*.dt")):
        info = _parse_dt_info(dt_file)
        info["supported"] = not info["supporting"] or build_type in info["supporting"]
        results.append(info)
    return results

XFCE4_STEPS = """\
# install and setup xfce4 desktop
apt install lightdm xfce4 -y
systemctl enable lightdm
echo "root" | passwd --stdin
cp /wallpapers/* /usr/share/backgrounds/xfce/
rm -rf /wallpapers/
# set default wallpaper — write to root's user config (higher priority than /etc/xdg/)
# cover all common connector names since the name varies by VM/hardware
WALLPAPER="/usr/share/backgrounds/xfce/mkmelinux.png"
mkdir -p /root/.config/xfce4/xfconf/xfce-perchannel-xml
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<channel name="xfce4-desktop" version="1.0">'
  echo '  <property name="backdrop" type="empty">'
  echo '    <property name="screen0" type="empty">'
  for mon in monitor0 monitorVirtual-1 monitorVGA-1 monitorHDMI-1 monitorHDMI-A-1 monitorDP-1 monitoreDP-1; do
    echo "      <property name=\\"$mon\\" type=\\"empty\\">"
    echo '        <property name="workspace0" type="empty">'
    echo "          <property name=\\"last-image\\" type=\\"string\\" value=\\"$WALLPAPER\\"/>"
    echo '          <property name="image-style" type="int" value="5"/>'
    echo '          <property name="color-style" type="int" value="0"/>'
    echo '        </property>'
    echo '      </property>'
  done
  echo '    </property>'
  echo '  </property>'
  echo '</channel>'
} > /root/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml
# add locale to prevent lightdm crashes
apt install locales -y
localectl set-locale LANG=en_US.UTF-8
# set auto login for root
cat > /etc/lightdm/lightdm.conf << EOF
[Seat:*]
autologin-user=root
autologin-user-timeout=0
autologin-session=xfce
EOF
# Debian's PAM config blocks root autologin by default — remove the restriction
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/lightdm-autologin
"""

# v86 variant: lightdm deps are unavailable on i386 bookworm — use xinit + tty1 autologin instead
XFCE4_V86_STEPS = """\
# install and setup xfce4 desktop — xinit instead of lightdm (lightdm deps unavailable on i386 bookworm)
apt install xfce4 xorg xinit -y
echo "root" | passwd --stdin
cp /wallpapers/* /usr/share/backgrounds/xfce/
rm -rf /wallpapers/
# set default wallpaper — write to root's user config (higher priority than /etc/xdg/)
# cover all common connector names since the name varies by VM/hardware
WALLPAPER="/usr/share/backgrounds/xfce/mkmelinux.png"
mkdir -p /root/.config/xfce4/xfconf/xfce-perchannel-xml
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<channel name="xfce4-desktop" version="1.0">'
  echo '  <property name="backdrop" type="empty">'
  echo '    <property name="screen0" type="empty">'
  for mon in monitor0 monitorVirtual-1 monitorVGA-1 monitorHDMI-1 monitorHDMI-A-1 monitorDP-1 monitoreDP-1; do
    echo "      <property name=\\"$mon\\" type=\\"empty\\">"
    echo '        <property name="workspace0" type="empty">'
    echo "          <property name=\\"last-image\\" type=\\"string\\" value=\\"$WALLPAPER\\"/>"
    echo '          <property name="image-style" type="int" value="5"/>'
    echo '          <property name="color-style" type="int" value="0"/>'
    echo '        </property>'
    echo '      </property>'
  done
  echo '    </property>'
  echo '  </property>'
  echo '</channel>'
} > /root/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml
# autologin root on tty1 (VGA console) so startx fires on boot
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'SYSD'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
SYSD
# start X automatically when root logs into tty1
cat >> /root/.profile << 'PROF'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
PROF
# launch xfce4 session from xinit
cat > /root/.xinitrc << 'XINIT'
exec xfce4-session
XINIT
chmod +x /root/.xinitrc
"""

KDE_STEPS = """\
# install and setup KDE Plasma desktop
apt install sddm kde-plasma-desktop -y
systemctl enable sddm
echo "root" | passwd --stdin
# add locale
apt install locales -y
localectl set-locale LANG=en_US.UTF-8
# set SDDM auto login for root
mkdir -p /etc/sddm.conf.d
cat > /etc/sddm.conf.d/autologin.conf << EOF
[Autologin]
User=root
Session=plasma
EOF
# Debian's PAM config blocks root autologin by default — remove the restriction
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/sddm-autologin
"""

GNOME_STEPS = """\
# install and setup GNOME desktop
apt install gdm3 gnome-core -y
systemctl enable gdm3
echo "root" | passwd --stdin
# add locale
apt install locales -y
localectl set-locale LANG=en_US.UTF-8
# set GDM auto login for root
mkdir -p /etc/gdm3
cat > /etc/gdm3/daemon.conf << EOF
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=root
EOF
# Debian's PAM config blocks root autologin by default — remove the restriction
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/gdm3-autologin
"""

OPENBOX_STEPS = """\
# install and setup Openbox window manager
apt install lightdm openbox -y
systemctl enable lightdm
echo "root" | passwd --stdin
# add locale
apt install locales -y
localectl set-locale LANG=en_US.UTF-8
# set LightDM auto login for root
cat > /etc/lightdm/lightdm.conf << EOF
[Seat:*]
autologin-user=root
autologin-user-timeout=0
autologin-session=openbox
EOF
# Debian's PAM config blocks root autologin by default — remove the restriction
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/lightdm-autologin
"""

# v86 variant: xinit-based, no lightdm
OPENBOX_V86_STEPS = """\
# install and setup Openbox window manager — xinit instead of lightdm (lightdm deps unavailable on i386 bookworm)
apt install openbox xorg xinit -y
echo "root" | passwd --stdin
# autologin root on tty1 (VGA console) so startx fires on boot
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'SYSD'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
SYSD
cat >> /root/.profile << 'PROF'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
PROF
cat > /root/.xinitrc << 'XINIT'
exec openbox-session
XINIT
chmod +x /root/.xinitrc
"""

DESKTOP_STEPS = {
    "xfce4": XFCE4_STEPS,
    "kde": KDE_STEPS,
    "gnome": GNOME_STEPS,
    "openbox": OPENBOX_STEPS,
}

DESKTOP_V86_STEPS = {
    "xfce4": XFCE4_V86_STEPS,
    "openbox": OPENBOX_V86_STEPS,
}

# ── Arch Linux desktop steps ──────────────────────────────────────────────────
# Arch uses pacman, has no passwd --stdin, locale setup differs, and GNOME's
# config lives at /etc/gdm/custom.conf (not /etc/gdm3/daemon.conf).

XFCE4_ARCH_STEPS = """\
# install and setup xfce4 desktop (Arch Linux)
pacman -Sy --noconfirm lightdm xfce4
systemctl enable lightdm
echo "root:root" | chpasswd
cp /wallpapers/* /usr/share/backgrounds/xfce/
rm -rf /wallpapers/
# set default wallpaper — write to root's user config (higher priority than /etc/xdg/)
# cover all common connector names since the name varies by VM/hardware
WALLPAPER="/usr/share/backgrounds/xfce/mkmelinux.png"
mkdir -p /root/.config/xfce4/xfconf/xfce-perchannel-xml
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<channel name="xfce4-desktop" version="1.0">'
  echo '  <property name="backdrop" type="empty">'
  echo '    <property name="screen0" type="empty">'
  for mon in monitor0 monitorVirtual-1 monitorVGA-1 monitorHDMI-1 monitorHDMI-A-1 monitorDP-1 monitoreDP-1; do
    echo "      <property name=\\"$mon\\" type=\\"empty\\">"
    echo '        <property name="workspace0" type="empty">'
    echo "          <property name=\\"last-image\\" type=\\"string\\" value=\\"$WALLPAPER\\"/>"
    echo '          <property name="image-style" type="int" value="5"/>'
    echo '          <property name="color-style" type="int" value="0"/>'
    echo '        </property>'
    echo '      </property>'
  done
  echo '    </property>'
  echo '  </property>'
  echo '</channel>'
} > /root/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml
# locale
sed -i 's/#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf
# set auto login for root
cat > /etc/lightdm/lightdm.conf << EOF
[Seat:*]
autologin-user=root
autologin-user-timeout=0
autologin-session=xfce
EOF
# remove PAM root restriction if present
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/lightdm-autologin
"""

KDE_ARCH_STEPS = """\
# install and setup KDE Plasma desktop (Arch Linux)
pacman -Sy --noconfirm sddm plasma-meta
systemctl enable sddm
echo "root:root" | chpasswd
# locale
sed -i 's/#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf
# set SDDM auto login for root
mkdir -p /etc/sddm.conf.d
cat > /etc/sddm.conf.d/autologin.conf << EOF
[Autologin]
User=root
Session=plasma
EOF
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/sddm-autologin
"""

GNOME_ARCH_STEPS = """\
# install and setup GNOME desktop (Arch Linux)
pacman -Sy --noconfirm gdm gnome
systemctl enable gdm
echo "root:root" | chpasswd
# locale
sed -i 's/#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf
# set GDM auto login for root
mkdir -p /etc/gdm
cat > /etc/gdm/custom.conf << EOF
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=root
EOF
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/gdm-autologin
"""

OPENBOX_ARCH_STEPS = """\
# install and setup Openbox window manager (Arch Linux)
pacman -Sy --noconfirm lightdm openbox
systemctl enable lightdm
echo "root:root" | chpasswd
# locale
sed -i 's/#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf
# set LightDM auto login for root
cat > /etc/lightdm/lightdm.conf << EOF
[Seat:*]
autologin-user=root
autologin-user-timeout=0
autologin-session=openbox
EOF
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/lightdm-autologin
"""

DESKTOP_ARCH_STEPS = {
    "xfce4":   XFCE4_ARCH_STEPS,
    "kde":     KDE_ARCH_STEPS,
    "gnome":   GNOME_ARCH_STEPS,
    "openbox": OPENBOX_ARCH_STEPS,
}

# Minimal Openbox rc.xml — no keyboard shortcuts, no mouse desktop bindings.
_LOCKDOWN_RC_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc"
                xmlns:xi="http://www.w3.org/2001/XInclude">
  <resistance><strength>10</strength><screen_edge_strength>20</screen_edge_strength></resistance>
  <focus><focusNew>yes</focusNew><followMouse>no</followMouse><focusLast>yes</focusLast>
    <underMouse>no</underMouse><focusDelay>200</focusDelay><raiseOnFocus>no</raiseOnFocus></focus>
  <placement><policy>Smart</policy><center>yes</center><monitor>Primary</monitor></placement>
  <theme><name>Clearlooks</name><titleLayout>NLIMC</titleLayout><keepBorder>yes</keepBorder>
    <animateIconify>no</animateIconify></theme>
  <desktops><number>1</number><firstdesk>1</firstdesk><popupTime>0</popupTime></desktops>
  <resize><drawContents>yes</drawContents></resize>
  <margins><top>0</top><bottom>0</bottom><left>0</left><right>0</right></margins>
  <dock><position>TopLeft</position><direction>Vertical</direction><autoHide>no</autoHide></dock>
  <keyboard></keyboard>
  <mouse><dragThreshold>8</dragThreshold><doubleClickTime>200</doubleClickTime></mouse>
  <menu><hideDelay>200</hideDelay><middle>no</middle><submenuShowDelay>100</submenuShowDelay>
    <applicationIcons>no</applicationIcons><manageDesktops>no</manageDesktops></menu>
  <applications></applications>
</openbox_config>
"""


def build_single_app_steps(command: str, lockdown: bool) -> str:
    lockdown_block = ""
    if lockdown:
        lockdown_block = """\
# lockdown: replace Openbox config with one that has no keyboard shortcuts
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/rc.xml << 'OBEOF'
""" + _LOCKDOWN_RC_XML + "OBEOF\n"

    return f"""\
# Single App Runner - Openbox kiosk mode
apt install lightdm openbox -y
systemctl enable lightdm
echo "root" | passwd --stdin
apt install locales -y
localectl set-locale LANG=en_US.UTF-8
# remove right-click desktop menu
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/menu.xml << 'OBEOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
</openbox_menu>
OBEOF
# autostart the app
cat > /etc/xdg/openbox/autostart << 'OBEOF'
{command} &
OBEOF
{lockdown_block}# LightDM auto login for root
cat > /etc/lightdm/lightdm.conf << 'OBEOF'
[Seat:*]
autologin-user=root
autologin-user-timeout=0
autologin-session=openbox
OBEOF
# Debian's PAM config blocks root autologin by default — remove the restriction
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/lightdm-autologin
"""


def build_single_app_v86_steps(command: str, lockdown: bool) -> str:
    """Kiosk mode for v86: xinit + openbox, no lightdm (unavailable on i386 bookworm)."""
    lockdown_block = ""
    if lockdown:
        lockdown_block = """\
# lockdown: replace Openbox config with one that has no keyboard shortcuts
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/rc.xml << 'OBEOF'
""" + _LOCKDOWN_RC_XML + "OBEOF\n"

    return f"""\
# Single App Runner (v86) - Openbox kiosk mode via xinit
apt install openbox xorg xinit -y
echo "root" | passwd --stdin
# remove right-click desktop menu
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/menu.xml << 'OBEOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
</openbox_menu>
OBEOF
# autostart the app
cat > /etc/xdg/openbox/autostart << 'OBEOF'
{command} &
OBEOF
{lockdown_block}# autologin root on tty1 so startx fires on boot
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'SYSD'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
SYSD
cat >> /root/.profile << 'PROF'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
PROF
cat > /root/.xinitrc << 'XINIT'
exec openbox-session
XINIT
chmod +x /root/.xinitrc
"""


def build_single_app_arch_steps(command: str, lockdown: bool) -> str:
    """Kiosk mode for Arch Linux: lightdm + openbox, pacman packages."""
    lockdown_block = ""
    if lockdown:
        lockdown_block = """\
# lockdown: replace Openbox config with one that has no keyboard shortcuts
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/rc.xml << 'OBEOF'
""" + _LOCKDOWN_RC_XML + "OBEOF\n"

    return f"""\
# Single App Runner - Openbox kiosk mode (Arch Linux)
pacman -Sy --noconfirm lightdm openbox
systemctl enable lightdm
echo "root:root" | chpasswd
# locale
sed -i 's/#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf
# remove right-click desktop menu
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/menu.xml << 'OBEOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
</openbox_menu>
OBEOF
# autostart the app
cat > /etc/xdg/openbox/autostart << 'OBEOF'
{command} &
OBEOF
{lockdown_block}# LightDM auto login for root
cat > /etc/lightdm/lightdm.conf << 'OBEOF'
[Seat:*]
autologin-user=root
autologin-user-timeout=0
autologin-session=openbox
OBEOF
sed -i '/pam_succeed_if.so user != root/d' /etc/pam.d/lightdm-autologin
"""


class BuildConfig:
    """Holds the user's choices across wizard screens."""
    def __init__(self) -> None:
        self.build_type = "ISO"
        self.hostname = "mylinux"
        self.ostype = "NORMAL"
        self.vhd_size = 20
        self.ostemplate = ""          # "" = Debian default; "arch-linux" = use arch-linux.dt
        self.desktop = "none"
        self.single_app_command = ""
        self.single_app_lockdown = False
        self.browser = "none"
        self.username = ""
        self.user_password = ""
        self.convert_to_qcow2 = False
        self.delete_original_img = False
        self.extra_packages = ""
        self.custom_script_content = ""
        self.generate_new_rootfs = False
        self.v86_custom_marker = False
        self.v86_marker_delay = 30
        self.install_calamares = False
        self.calamares_slides = [
            {"image": "", "title": "", "body": ""},
            {"image": "", "title": "", "body": ""},
            {"image": "", "title": "", "body": ""},
        ]
        self.droidos_type = "MOBILE"  # MOBILE or ANDROIDTV


config = BuildConfig()


class WizardPage(Widget):
    """Base class for wizard pages — emits navigation messages to WizardHost."""

    DEFAULT_CSS = """
    WizardPage {
        width: 100%;
        height: 100%;
        layout: vertical;
        opacity: 0;
        overflow: hidden;
    }
    WizardPage .content {
        height: 1fr;
        align: center middle;
        overflow: hidden;
    }
    WizardPage .box {
        width: 76;
        border: round $primary;
        padding: 1 2;
    }
    WizardPage .btn-bar {
        height: auto;
        align: center middle;
        padding: 1 0;
    }
    WizardPage .btn-bar Button {
        margin: 0 3;
    }
    WizardPage .tree {
        background: $surface;
        border: solid $panel;
        padding: 0 1;
        margin-bottom: 1;
        max-height: 12;
        overflow-y: auto;
    }
    """

    class GoNext(Message):
        def __init__(self, page: "WizardPage") -> None:
            self.page = page
            super().__init__()

    class GoBack(Message):
        pass

    def go_next(self, page: "WizardPage") -> None:
        self.post_message(self.GoNext(page))

    def go_back(self) -> None:
        self.post_message(self.GoBack())


class WizardHost(Widget):
    """Owns the wizard page stack and runs simultaneous slide transitions."""

    DEFAULT_CSS = """
    WizardHost {
        width: 100%;
        height: 1fr;
        overflow: hidden;
    }
    """

    _out_x:       reactive[float] = reactive(0.0)
    _in_x:        reactive[float] = reactive(0.0)
    _out_opacity: reactive[float] = reactive(1.0)
    _in_opacity:  reactive[float] = reactive(0.0)

    def __init__(self) -> None:
        super().__init__()
        self._stack: list[WizardPage] = []
        self._outgoing: WizardPage | None = None
        self._incoming: WizardPage | None = None
        self._transitioning: bool = False

    def compose(self) -> ComposeResult:
        first = BuildTypeScreen()
        self._stack.append(first)
        yield first

    def on_mount(self) -> None:
        first = self._stack[0]
        first.styles.opacity = 1.0
        first.styles.offset = (0, 0)

    def watch__out_x(self, value: float) -> None:
        if self._outgoing:
            self._outgoing.styles.offset = (round(value), 0)

    def watch__in_x(self, value: float) -> None:
        if self._incoming:
            self._incoming.styles.offset = (round(value), 0)

    def watch__out_opacity(self, value: float) -> None:
        if self._outgoing:
            self._outgoing.styles.opacity = value

    def watch__in_opacity(self, value: float) -> None:
        if self._incoming:
            self._incoming.styles.opacity = value

    async def _do_transition(
        self, incoming: WizardPage, out_to: int, in_from: int
    ) -> None:
        if self._transitioning:
            return
        self._transitioning = True

        outgoing = self._stack[-1]
        self._outgoing = outgoing
        self._incoming = incoming
        incoming.display = True

        outgoing.styles.offset = (0, 0)
        outgoing.styles.opacity = 1.0
        incoming.styles.offset = (in_from, 0)
        incoming.styles.opacity = 0.0

        self._out_x = 0.0
        self._out_opacity = 1.0
        self._in_x = float(in_from)
        self._in_opacity = 0.0

        self.animate("_out_x", float(out_to), duration=0.22, easing="in_cubic")
        self.animate("_out_opacity", 0.0, duration=0.18)
        self.animate("_in_x", 0.0, duration=0.22, easing="out_cubic")
        self.animate("_in_opacity", 1.0, duration=0.18)

        await asyncio.sleep(0.22)

        outgoing.display = False
        outgoing.styles.offset = (0, 0)
        self._outgoing = None
        self._incoming = None
        self._transitioning = False

    async def on_wizard_page_go_next(self, message: WizardPage.GoNext) -> None:
        message.stop()
        if self._transitioning:
            return
        page = message.page
        await self.mount(page)
        await self._do_transition(page, out_to=-40, in_from=40)
        self._stack.append(page)

    async def on_wizard_page_go_back(self, message: WizardPage.GoBack) -> None:
        message.stop()
        if len(self._stack) <= 1 or self._transitioning:
            return
        prev = self._stack[-2]
        await self._do_transition(prev, out_to=40, in_from=-40)
        current = self._stack.pop()
        current.remove()

    def trigger_go_back(self) -> None:
        if len(self._stack) > 1:
            self._stack[-1].go_back()


class MainScreen(Screen):
    def compose(self) -> ComposeResult:
        yield WizardHost()



# ---------------------------------------------------------------------------
# Screen 1 — Build type
# ---------------------------------------------------------------------------

class BuildTypeScreen(WizardPage):
    CSS = """
    .box { width: 70; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .subtitle { text-align: center; color: $text-muted; margin-bottom: 1; }
    RadioSet { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("mkmelinux distrobuilder", classes="title")
                yield Static("+=+ Welcome to the mkmelinux distro builder! +=+", classes="subtitle")
                yield Static("What kind of distro do you want to make?", classes="subtitle")
                with RadioSet(id="build_type"):
                    yield RadioButton("ISO  (Recommended for beginners)", value=True, id="ISO")
                    yield RadioButton("Virtual Machine  (Raw .img harddisk image)", id="HARDDISK")
                    yield RadioButton("v86  (32-bit browser VM via 9pfs + save state)", id="V86")
        with Horizontal(classes="btn-bar"):
            yield Button("Quit", variant="error", id="quit")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
            return
        if event.button.id == "next":
            rs: RadioSet = self.query_one("#build_type")
            if rs.pressed_button:
                config.build_type = rs.pressed_button.id
            self.go_next(OStemplateScreen())


# ---------------------------------------------------------------------------
# Screen 1b — OS template selector
# ---------------------------------------------------------------------------

class OStemplateScreen(WizardPage):
    CSS = """
    .box { width: 76; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .subtitle { color: $text-muted; margin-bottom: 1; }
    RadioSet { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        # debian.dt is represented by the hardcoded "Debian (default)" option below.
        templates = [t for t in all_templates(config.build_type) if t["stem"] != "debian"]
        # If the previously chosen template doesn't support this build type, fall back to Debian.
        debian_selected = config.ostemplate == "" or not any(
            t["stem"] == config.ostemplate and t["supported"] for t in templates
        )
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("What OS do you want to build?", classes="title")
                yield Static(
                    "Choose the base operating system for your distro. "
                    "Debian is the default and has the most features.",
                    classes="subtitle",
                )
                with RadioSet(id="ostemplate"):
                    yield RadioButton(
                        "Debian  (default — most features supported)",
                        value=debian_selected,
                        id="__debian__",
                    )
                    for tmpl in templates:
                        desc = f"  — {tmpl['description']}" if tmpl["description"] else ""
                        suffix = "" if tmpl["supported"] else "  (not available for this build type)"
                        yield RadioButton(
                            f"{tmpl['display_name']}{desc}{suffix}",
                            value=tmpl["supported"] and config.ostemplate == tmpl["stem"],
                            id=tmpl["stem"],
                            disabled=not tmpl["supported"],
                        )
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            rs: RadioSet = self.query_one("#ostemplate")
            if rs.pressed_button:
                chosen = rs.pressed_button.id
                config.ostemplate = "" if chosen == "__debian__" else chosen
            self.go_next(CommonConfigScreen())


# ---------------------------------------------------------------------------
# Screen 2 — Common config (hostname + ostype)
# ---------------------------------------------------------------------------

class CommonConfigScreen(WizardPage):
    CSS = """
    .box { width: 70; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    Label { margin-top: 1; }
    Input { margin-bottom: 1; }
    RadioSet { margin-bottom: 1; }
    .error { color: $error; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Let's name your distro!", classes="title")
                yield Static("Hostname — this becomes your distro's name and network identity.", classes="hint")
                yield Input(value=config.hostname, placeholder="e.g. mylinux", id="hostname")
                with Vertical(id="ostype_section"):
                    yield Static("OS base — how much of Debian should we start with?", classes="hint")
                    with RadioSet(id="ostype"):
                        yield RadioButton("NORMAL  (full Debian base — recommended)", value=True, id="NORMAL")
                        yield RadioButton("MINBASE  (minimal base — requires more configs)", id="MINBASE")
                yield Static("", id="error", classes="error")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")

    def on_mount(self) -> None:
        # OSTYPE is Debian-specific — hide it when a distro template is active.
        self.query_one("#ostype_section").display = config.ostemplate == ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            hostname = self.query_one("#hostname", Input).value.strip()
            if not hostname:
                self.query_one("#error", Static).update("Hostname cannot be empty.")
                return
            if " " in hostname:
                self.query_one("#error", Static).update("Hostname must not contain spaces.")
                return
            config.hostname = hostname
            if config.ostemplate == "":
                rs: RadioSet = self.query_one("#ostype")
                if rs.pressed_button:
                    config.ostype = rs.pressed_button.id
            if config.build_type == "HARDDISK":
                self.go_next(VMConfigScreen())
            elif config.ostemplate == "droidos":
                self.go_next(DroidOSConfigScreen())
            else:
                self.go_next(DesktopScreen())


# ---------------------------------------------------------------------------
# Screen 3 — VM-specific config (only for HARDDISK)
# ---------------------------------------------------------------------------

class VMConfigScreen(WizardPage):
    CSS = """
    .box { width: 70; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    Label { margin-top: 1; }
    Input { margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    .error { color: $error; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Virtual Machine configuration", classes="title")
                yield Label("How big should your virtual drive be? (in GB)")
                yield Input(value=str(config.vhd_size), placeholder="e.g. 20", id="vhd_size")
                yield Static("10 GB is the minimum. 20 GB is a comfortable size for most setups.", classes="hint")
                yield Static("", id="error", classes="error")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            raw = self.query_one("#vhd_size", Input).value.strip()
            if not raw.isdigit() or int(raw) < 1:
                self.query_one("#error", Static).update("Please enter a positive integer.")
                return
            config.vhd_size = int(raw)
            if config.ostemplate == "droidos":
                self.go_next(DroidOSConfigScreen())
            else:
                self.go_next(DesktopScreen())


# ---------------------------------------------------------------------------
# Screen 4 — Desktop environment
# ---------------------------------------------------------------------------

class DesktopScreen(WizardPage):
    CSS = """
    .box { width: 70; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .subtitle { color: $text-muted; margin-bottom: 1; }
    RadioSet { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        is_v86 = config.build_type == "V86"
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Pick a desktop environment!", classes="title")
                yield Static("This is what your users will see when they log in.", classes="subtitle")
                if is_v86:
                    yield Static("v86 runs a 32-bit CPU — only lightweight desktops are available.", classes="subtitle")
                else:
                    yield Static("Not sure? XFCE4 is a great starting point — fast and easy to use.", classes="subtitle")
                with RadioSet(id="desktop"):
                    yield RadioButton("None  (headless / plain)", value=True, id="none")
                    yield RadioButton("XFCE4  (lightweight, fast — recommended)", id="xfce4")
                    if not is_v86:
                        yield RadioButton("KDE Plasma  (modern, feature-rich)", id="kde")
                        yield RadioButton("GNOME  (clean, touch-friendly)", id="gnome")
                    yield RadioButton("Openbox  (ultra-minimal window manager)", id="openbox")
                    yield RadioButton("Single App Runner  (kiosk — launches one app only)", id="single_app")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            rs: RadioSet = self.query_one("#desktop")
            if rs.pressed_button:
                config.desktop = rs.pressed_button.id
            if config.build_type == "V86":
                self.go_next(V86OptionsScreen())
            elif config.desktop == "single_app":
                self.go_next(SingleAppConfigScreen())
            else:
                self.go_next(ExtraPackagesScreen())


# ---------------------------------------------------------------------------
# Screen 5a — Single App Runner config (only when single_app chosen)
# ---------------------------------------------------------------------------

class SingleAppConfigScreen(WizardPage):
    CSS = """
    .box { width: 74; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    Label { margin-top: 1; }
    Input { margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    RadioSet { margin-bottom: 1; }
    .error { color: $error; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Single App Runner — let's set it up!", classes="title")
                yield Label("What command should launch your app on startup?")
                yield Input(
                    value=config.single_app_command,
                    placeholder="e.g. /usr/bin/firefox  or  python3 /opt/myapp/app.py",
                    id="app_command",
                )
                yield Static("Your app will be the only thing visible — no taskbar, no right-click menu.", classes="hint")
                yield Static("Great for kiosks, digital signage, or dedicated appliances.", classes="hint")
                yield Label("Lockdown mode — disable keyboard shortcuts?")
                with RadioSet(id="lockdown"):
                    yield RadioButton(
                        "Enabled  — strip all keyboard shortcuts",
                        value=config.single_app_lockdown,
                        id="lockdown_yes",
                    )
                    yield RadioButton(
                        "Disabled  — keep default Openbox bindings",
                        value=not config.single_app_lockdown,
                        id="lockdown_no",
                    )
                yield Static("", id="error", classes="error")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            cmd = self.query_one("#app_command", Input).value.strip()
            if not cmd:
                self.query_one("#error", Static).update("App command cannot be empty.")
                return
            config.single_app_command = cmd
            rs: RadioSet = self.query_one("#lockdown")
            config.single_app_lockdown = rs.pressed_button is not None and rs.pressed_button.id == "lockdown_yes"
            self.go_next(ExtraPackagesScreen())


# ---------------------------------------------------------------------------
# Screen 5b — Extra packages
# ---------------------------------------------------------------------------

class ExtraPackagesScreen(WizardPage):
    CSS = """
    .box { width: 76; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    TextArea { height: 8; margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Any extra packages to install?", classes="title")
                yield Static("Enter package names separated by spaces or one per line.", classes="hint")
                yield Static("These are installed with apt before the desktop is set up.", classes="hint")
                yield TextArea(config.extra_packages, id="packages")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Skip", id="skip")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id in ("next", "skip"):
            if event.button.id == "skip":
                config.extra_packages = ""
            else:
                config.extra_packages = self.query_one("#packages", TextArea).text.strip()
            self.go_next(DistroCustomizationScreen())


# ---------------------------------------------------------------------------
# Screen 5c — Distro customization (browser, main user)
# ---------------------------------------------------------------------------

class DistroCustomizationScreen(WizardPage):
    CSS = """
    .box { width: 76; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .section { text-style: bold; margin-top: 1; }
    .hint { color: $text-muted; }
    Label { margin-top: 1; }
    Input { margin-bottom: 1; }
    RadioSet { margin-bottom: 1; }
    .error { color: $error; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Awesome! Let's add some finishing touches.", classes="title")

                yield Label("Would you like a browser pre-installed?", classes="section")
                with RadioSet(id="browser"):
                    yield RadioButton("No browser  (I'll install one myself)", value=True, id="none")
                    yield RadioButton("Firefox ESR  (popular and reliable)", id="firefox")
                    yield RadioButton("Chromium  (open-source Chrome)", id="chromium")
                    yield RadioButton("Falkon  (lightweight, Qt-based)", id="falkon")

                yield Label("Set up a user account (optional)", classes="section")
                yield Static("By default your distro logs in as root. You can create a named user here instead.", classes="hint")
                yield Static("If you set one up, you won't need a Calamares live installer to do it later.", classes="hint")
                yield Label("Username  (leave blank to stay as root)")
                yield Input(value=config.username, placeholder="e.g. alice", id="username")
                yield Label("Password")
                yield Input(
                    value=config.user_password,
                    placeholder="e.g. mypassword",
                    password=True,
                    id="user_password",
                )

                yield Static("", id="error", classes="error")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            rs: RadioSet = self.query_one("#browser")
            if rs.pressed_button:
                config.browser = rs.pressed_button.id

            username = self.query_one("#username", Input).value.strip()
            password = self.query_one("#user_password", Input).value

            if username and " " in username:
                self.query_one("#error", Static).update("Username must not contain spaces.")
                return
            if username and not password:
                self.query_one("#error", Static).update("Password cannot be empty when a username is set.")
                return

            config.username = username
            config.user_password = password

            if config.build_type == "HARDDISK":
                self.go_next(PostBuildScreen())
            elif config.build_type == "ISO" and not config.ostemplate:
                # Calamares uses an apt backend — only offer it for Debian builds.
                self.go_next(CalamaresScreen())
            else:
                self.go_next(ExtracustomizationScreen())


# ---------------------------------------------------------------------------
# Screen 5c — Calamares live installer (ISO only)
# ---------------------------------------------------------------------------

class CalamaresScreen(WizardPage):
    CSS = """
    .box { width: 80; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    .slides { margin-top: 1; }
    .slide-group { border: solid $panel; padding: 1 2; margin-bottom: 1; }
    .slide-label { text-style: bold; margin-bottom: 1; }
    Label { margin-top: 1; }
    Input { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        s = config.calamares_slides
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Want to include a live installer?", classes="title")
                yield Static("Calamares lets users install your distro to their hard drive from within the live session.", classes="hint")
                yield Static("Leave disabled for a pure live/kiosk system.", classes="hint")
                yield Checkbox("Enable Calamares installer", value=config.install_calamares, id="enable_calamares")

                with Vertical(id="slides_section", classes="slides"):
                    yield Static("Customise the installer slideshow — shown while files are being copied.", classes="hint")
                    yield Static("Leave slides blank to use the built-in defaults.", classes="hint")

                    for n in range(1, 4):
                        sl = s[n - 1]
                        with Vertical(classes="slide-group"):
                            yield Static(f"Slide {n}", classes="slide-label")
                            yield Label("Image filename  (from extracustomization/, e.g. wallpapers/mkmelinux.png)")
                            yield Input(value=sl["image"], placeholder="optional — leave blank for no image", id=f"slide{n}_image")
                            yield Label("Title")
                            yield Input(value=sl["title"], placeholder="e.g. Installing your system...", id=f"slide{n}_title")
                            yield Label("Body text")
                            yield Input(value=sl["body"], placeholder="e.g. Sit back while we set everything up.", id=f"slide{n}_body")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")


    def on_mount(self) -> None:
        self.query_one("#slides_section").display = config.install_calamares

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "enable_calamares":
            self.query_one("#slides_section").display = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            config.install_calamares = self.query_one("#enable_calamares", Checkbox).value
            for n in range(1, 4):
                config.calamares_slides[n - 1] = {
                    "image": self.query_one(f"#slide{n}_image", Input).value.strip(),
                    "title": self.query_one(f"#slide{n}_title", Input).value.strip(),
                    "body":  self.query_one(f"#slide{n}_body",  Input).value.strip(),
                }
            self.go_next(ExtracustomizationScreen())


# ---------------------------------------------------------------------------
# Screen 5d — Post-build options (HARDDISK only)
# ---------------------------------------------------------------------------

class PostBuildScreen(WizardPage):
    CSS = """
    .box { width: 76; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    Checkbox { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Almost there! Any post-build processing?", classes="title")
                yield Static(
                    "These steps run on your host machine after the build container finishes.",
                    classes="hint",
                )
                yield Checkbox(
                    "Convert harddisk.img to QCOW2 format  (requires qemu-img on your host)",
                    value=config.convert_to_qcow2,
                    id="convert_qcow2",
                )
                yield Checkbox(
                    "Delete the original harddisk.img once QCOW2 conversion is done",
                    value=config.delete_original_img,
                    id="delete_img",
                )
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            config.convert_to_qcow2 = self.query_one("#convert_qcow2", Checkbox).value
            config.delete_original_img = self.query_one("#delete_img", Checkbox).value
            self.go_next(ExtracustomizationScreen())


# ---------------------------------------------------------------------------
# Screen 5d — extracustomization directory browser
# ---------------------------------------------------------------------------

BROWSER_PACKAGES = {
    "firefox":  "firefox-esr",
    "chromium": "chromium",
    "falkon":   "falkon",
}

# Arch ships plain firefox (no ESR package); everything else is the same name.
BROWSER_PACKAGES_ARCH = {
    "firefox":  "firefox",
    "chromium": "chromium",
    "falkon":   "falkon",
}

BROWSER_LABELS = {
    "firefox":  "Firefox ESR",
    "chromium": "Chromium",
    "falkon":   "Falkon (lightweight, Qt-based)",
}


def build_browser_steps(browser: str, is_arch: bool = False) -> str:
    pkg = (BROWSER_PACKAGES_ARCH if is_arch else BROWSER_PACKAGES).get(browser, "")
    if not pkg:
        return ""
    if is_arch:
        return f"# install browser\npacman -Sy --noconfirm {pkg}\n"
    return f"# install browser\napt install {pkg} -y\n"


def build_user_steps(username: str, password: str, desktop: str, is_arch: bool = False) -> str:
    if not username:
        return ""
    steps = f"""\
# create main user
useradd -m -s /bin/bash {username}
echo "{username}:{password}" | chpasswd
"""
    if is_arch:
        # wheel is the sudoers group on Arch; sudo must be installed explicitly.
        steps += f"""\
pacman -Sy --noconfirm sudo
sed -i 's/# %wheel ALL=(ALL:ALL) ALL/%wheel ALL=(ALL:ALL) ALL/' /etc/sudoers
usermod -aG wheel {username}
"""
    else:
        steps += f"usermod -aG sudo {username}\n"

    if config.build_type == "V86":
        # v86 uses xinit + getty autologin — no display manager config to update
        if desktop in ("xfce4", "openbox", "single_app"):
            steps += f"""\
sed -i 's/--autologin root/--autologin {username}/' /etc/systemd/system/getty@tty1.service.d/autologin.conf
cp /root/.xinitrc /home/{username}/.xinitrc
chown {username}:{username} /home/{username}/.xinitrc
cat >> /home/{username}/.profile << 'PROF'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
PROF
"""
    else:
        # Update the display manager autologin to use the new user
        if desktop in ("xfce4", "openbox", "single_app"):
            steps += f"sed -i 's/autologin-user=root/autologin-user={username}/' /etc/lightdm/lightdm.conf\n"
        elif desktop == "kde":
            steps += f"sed -i 's/User=root/User={username}/' /etc/sddm.conf.d/autologin.conf\n"
        elif desktop == "gnome":
            # Arch uses /etc/gdm/custom.conf; Debian uses /etc/gdm3/daemon.conf
            gdm_conf = "/etc/gdm/custom.conf" if is_arch else "/etc/gdm3/daemon.conf"
            steps += f"sed -i 's/AutomaticLogin=root/AutomaticLogin={username}/' {gdm_conf}\n"
    return steps


def build_extra_packages_steps(packages: str, is_arch: bool = False) -> str:
    pkgs = " ".join(packages.split())  # normalise whitespace / newlines
    if not pkgs:
        return ""
    if is_arch:
        return f"# extra packages\npacman -Sy --noconfirm {pkgs}\n"
    return f"# extra packages\napt install {pkgs} -y\n"


def build_v86_marker_steps(desktop: str, delay: int) -> str:
    """Generate steps that install a boot-marker script which waits for the desktop before saving state."""
    if desktop == "xfce4":
        process_wait = "while ! pgrep -x xfce4-session > /dev/null 2>&1; do sleep 2; done\n"
    elif desktop in ("openbox", "single_app"):
        process_wait = "while ! pgrep -x openbox > /dev/null 2>&1; do sleep 2; done\n"
    else:
        process_wait = ""

    return f"""\
# install custom v86 boot marker — waits for the desktop before emitting V86_SYSTEM_READY
cat > /usr/local/bin/v86-ready-wait.sh << 'MKME_EOF'
#!/bin/bash
# wait for X display to appear on tty1
while ! [ -f /tmp/.X0-lock ]; do sleep 2; done
{process_wait}# allow the desktop to finish rendering before capturing state
sleep {delay}
sync
echo 'V86_SYSTEM_READY'
MKME_EOF
chmod +x /usr/local/bin/v86-ready-wait.sh
# hook the wait script into root's ttyS0 profile session
cat >> /root/.profile << 'PROF'
if [ -z "$V86_READY_SENT" ]; then
    export V86_READY_SENT=1
    /usr/local/bin/v86-ready-wait.sh
fi
PROF
"""


def assemble_chroot_script() -> str:
    """Build the full extrachrootsteps.sh content from the current config."""
    script = ""
    is_v86  = config.build_type == "V86"
    is_arch = config.ostemplate == "arch-linux"

    if config.desktop == "single_app":
        if is_v86:
            script += build_single_app_v86_steps(config.single_app_command, config.single_app_lockdown)
        elif is_arch:
            script += build_single_app_arch_steps(config.single_app_command, config.single_app_lockdown)
        else:
            script += build_single_app_steps(config.single_app_command, config.single_app_lockdown)
    elif config.desktop in DESKTOP_STEPS:
        if is_v86 and config.desktop in DESKTOP_V86_STEPS:
            script += DESKTOP_V86_STEPS[config.desktop]
        elif is_arch and config.desktop in DESKTOP_ARCH_STEPS:
            script += DESKTOP_ARCH_STEPS[config.desktop]
        else:
            script += DESKTOP_STEPS[config.desktop]

    script += build_extra_packages_steps(config.extra_packages, is_arch=is_arch)
    script += build_browser_steps(config.browser, is_arch=is_arch)
    script += build_user_steps(config.username, config.user_password, config.desktop, is_arch=is_arch)
    if is_v86 and config.v86_custom_marker and config.desktop != "none":
        script += build_v86_marker_steps(config.desktop, config.v86_marker_delay)
    # Calamares uses an apt backend and Debian-specific paths — skip for Arch.
    if config.install_calamares and not is_arch:
        script += build_calamares_steps(config.calamares_slides, config.desktop)
    return script


# ---------------------------------------------------------------------------
# Calamares config constants
# ---------------------------------------------------------------------------

_CALAMARES_SETTINGS = """\
---
modules-search: [ local, /usr/lib/calamares/modules ]

sequence:
  - show:
    - welcome
    - locale
    - keyboard
    - partition
    - users
    - summary
  - exec:
    - partition
    - mount
    - unpackfs
    - machineid
    - fstab
    - locale
    - keyboard
    - localecfg
    - initramfscfg
    - initramfs
    - grubcfg
    - bootloader
    - packages
    - users
    - displaymanager
    - networkcfg
    - hwclock
    - services-systemd
    - finished
  - show:
    - finished

branding: mkmelinux
prompt-install: true
dont-chroot: false"""

_CALAMARES_BRANDING_DESC = """\
---
componentName: mkmelinux

strings:
  productName:         mkmelinux
  shortProductName:    mkmelinux
  version:             "1.0"
  shortVersion:        "1.0"
  versionedName:       "mkmelinux 1.0"
  shortVersionedName:  "mkmelinux 1.0"
  bootloaderEntryName: mkmelinux
  productUrl:          "about:blank"
  supportUrl:          "about:blank"
  knownIssuesUrl:      "about:blank"
  releaseNotesUrl:     "about:blank"

images:
  productLogo:    "logo.png"
  productIcon:    "logo.png"
  productWelcome: "logo.png"

slideshow:    "show.qml"
slideshowAPI: 2

style:
  sidebarBackground: "#292F34"
  sidebarText:       "#FFFFFF"
  sidebarTextSelect: "#4D7CFF\""""

_CALAMARES_UNPACKFS_CONF = """\
---
unpack:
  - source: /run/live/medium/live/filesystem.squashfs
    sourcefs: squashfs
    destination: \"\""""

_CALAMARES_BOOTLOADER_CONF = """\
---
efiBootLoader:      "grub"
kernel:             "/vmlinuz"
img:                "/initrd.img"
fallback:           "/initrd.img"
timeout:            "10"
grubInstall:        "grub-install"
grubMkconfig:       "grub-mkconfig"
grubCfg:            "/boot/grub/grub.cfg"
grubProbeModule:    "grub-probe"
installEFIfallback: true"""

_CALAMARES_USERS_CONF = """\
---
defaultGroups:
  - users
  - lp
  - video
  - network
  - storage
  - wheel
  - audio
autologinGroup:  autologin
doAutologin:     false
sudoersGroup:    sudo
setRootPassword: false
doReusePassword: true
passwordRequirements:
  minLength: 6"""

_CALAMARES_PACKAGES_CONF = """\
---
backend: apt
operations:
  - remove:
    - calamares
    - live-boot
    - live-boot-initramfs-tools
    - live-config
    - live-config-systemd
    - squashfs-tools"""

_CALAMARES_DESKTOP = """\
[Desktop Entry]
Version=1.0
Type=Application
Name=Install System
Comment=Install this system to your hard drive
Exec=calamares
Icon=calamares
Terminal=false
Categories=System;"""


def _calamares_displaymanager_conf(desktop: str) -> str:
    dm_map = {
        "xfce4":      ("lightdm", "startxfce4",   "xfce4.desktop"),
        "kde":        ("sddm",    "startkde",      "plasma.desktop"),
        "gnome":      ("gdm",     "gnome-session", "gnome.desktop"),
        "openbox":    ("lightdm", "openbox",       "openbox.desktop"),
        "single_app": ("lightdm", "openbox",       "openbox.desktop"),
    }
    dm, executable, desktop_file = dm_map.get(desktop, ("lightdm", "startxfce4", "xfce4.desktop"))
    return (
        "---\n"
        "displaymanagers:\n"
        f"  - {dm}\n"
        "  - lightdm\n"
        "  - sddm\n"
        "  - gdm\n"
        "defaultDesktopEnvironment:\n"
        f'  executable: "{executable}"\n'
        f'  desktopFile: "{desktop_file}"'
    )


def generate_calamares_qml(slides: list) -> str:
    """Generate Calamares show.qml slideshow content from slide configs."""
    active = [s for s in slides if s.get("title") or s.get("image") or s.get("body")]
    if not active:
        active = [{"image": "", "title": "Installing your system...",
                   "body": "Please wait while everything is set up for you."}]

    slide_parts = []
    for slide in active:
        image = slide.get("image", "").strip()
        title = slide.get("title", "").strip()
        body  = slide.get("body",  "").strip()

        img_block = ""
        if image:
            img_block = (
                "        Image {\n"
                f'            source: "{image}"\n'
                "            width: 600; height: 280\n"
                "            fillMode: Image.PreserveAspectFit\n"
                "            anchors.horizontalCenter: parent.horizontalCenter\n"
                "        }\n"
            )

        slide_parts.append(
            "    Slide {\n"
            "        anchors.fill: parent\n"
            "        Rectangle {\n"
            '            color: "#1a1a2e"\n'
            "            anchors.fill: parent\n"
            "        }\n"
            "        Column {\n"
            "            anchors.centerIn: parent\n"
            "            spacing: 16\n"
            "            width: parent.width * 0.8\n"
            + img_block +
            "            Text {\n"
            f'                text: "{title}"\n'
            '                color: "white"\n'
            "                font.pixelSize: 22\n"
            "                font.bold: true\n"
            "                anchors.horizontalCenter: parent.horizontalCenter\n"
            "                wrapMode: Text.WordWrap\n"
            "                horizontalAlignment: Text.AlignHCenter\n"
            "                width: parent.width\n"
            '                visible: text !== ""\n'
            "            }\n"
            "            Text {\n"
            f'                text: "{body}"\n'
            '                color: "#aaaaaa"\n'
            "                font.pixelSize: 14\n"
            "                anchors.horizontalCenter: parent.horizontalCenter\n"
            "                wrapMode: Text.WordWrap\n"
            "                horizontalAlignment: Text.AlignHCenter\n"
            "                width: parent.width\n"
            '                visible: text !== ""\n'
            "            }\n"
            "        }\n"
            "    }\n"
        )

    qml = "import QtQuick 2.0;\n"
    qml += "import calamares.slideshow 1.0;\n\n"
    qml += "Presentation {\n"
    qml += "    id: presentation\n\n"
    qml += "    function nextSlide() { presentation.goToNextSlide(); }\n\n"
    qml += "    Timer {\n"
    qml += "        id: slideTimer\n"
    qml += "        interval: 5000\n"
    qml += "        running: presentation.visible\n"
    qml += "        repeat: true\n"
    qml += "        onTriggered: nextSlide();\n"
    qml += "    }\n\n"
    qml += "".join(slide_parts)
    qml += "}\n"
    return qml


def _heredoc(path: str, content: str) -> str:
    """Emit a bash heredoc that writes content to path."""
    return f"cat > {path} << 'MKMELINUX_EOF'\n{content.rstrip()}\nMKMELINUX_EOF"


def build_calamares_steps(slides: list, desktop: str) -> str:
    qml = generate_calamares_qml(slides)
    dm_conf = _calamares_displaymanager_conf(desktop)

    copy_logo = "[ -f /wallpapers/mkmelinux.png ] && cp /wallpapers/mkmelinux.png /etc/calamares/branding/mkmelinux/logo.png || true"
    copy_slides = ""
    for i, slide in enumerate(slides):
        img = slide.get("image", "").strip()
        if img:
            copy_slides += f"\n[ -f /extracustomization/{img} ] && cp /extracustomization/{img} /etc/calamares/branding/mkmelinux/slide{i+1}.png || true"

    parts = [
        "# install and configure Calamares live installer",
        "apt install calamares -y",
        "mkdir -p /etc/calamares/branding/mkmelinux /etc/calamares/modules",
        copy_logo + copy_slides,
        _heredoc("/etc/calamares/settings.conf",                              _CALAMARES_SETTINGS),
        _heredoc("/etc/calamares/branding/mkmelinux/branding.desc",           _CALAMARES_BRANDING_DESC),
        _heredoc("/etc/calamares/branding/mkmelinux/show.qml",                qml),
        _heredoc("/etc/calamares/modules/unpackfs.conf",                      _CALAMARES_UNPACKFS_CONF),
        _heredoc("/etc/calamares/modules/bootloader.conf",                    _CALAMARES_BOOTLOADER_CONF),
        _heredoc("/etc/calamares/modules/users.conf",                         _CALAMARES_USERS_CONF),
        _heredoc("/etc/calamares/modules/packages.conf",                      _CALAMARES_PACKAGES_CONF),
        _heredoc("/etc/calamares/modules/displaymanager.conf",                dm_conf),
        "mkdir -p /root/Desktop",
        _heredoc("/root/Desktop/install-system.desktop",                      _CALAMARES_DESKTOP),
        "chmod +x /root/Desktop/install-system.desktop",
    ]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Screen 5e — v86 state-capture options (V86 builds only)
# ---------------------------------------------------------------------------

class V86OptionsScreen(WizardPage):
    CSS = """
    .box { width: 76; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    .section { text-style: bold; margin-top: 1; }
    Label { margin-top: 1; }
    Input { margin-bottom: 1; }
    .error { color: $error; }
    #delay_row { height: auto; }
    #delay_row Label { margin-top: 0; width: auto; }
    #delay_row Input { width: 8; margin-bottom: 0; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("v86 state capture", classes="title")
                yield Static(
                    "v86 saves a snapshot of the VM so the browser loads it instantly. "
                    "By default the snapshot fires as soon as the kernel boots — before "
                    "the desktop has had time to start.",
                    classes="hint",
                )
                yield Checkbox(
                    "Wait for desktop before capturing state  (recommended for graphical builds)",
                    value=config.v86_custom_marker,
                    id="custom_marker",
                )
                with Vertical(id="delay_section"):
                    yield Static(
                        "After the desktop process appears, wait this many extra seconds "
                        "for it to finish rendering before the snapshot is taken.",
                        classes="hint",
                    )
                    with Horizontal(id="delay_row"):
                        yield Label("Settling delay (seconds): ")
                        yield Input(str(config.v86_marker_delay), id="marker_delay")
                yield Static("", id="error", classes="error")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")

    def on_mount(self) -> None:
        self.query_one("#delay_section").display = config.v86_custom_marker

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "custom_marker":
            self.query_one("#delay_section").display = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            config.v86_custom_marker = self.query_one("#custom_marker", Checkbox).value
            if config.v86_custom_marker:
                raw = self.query_one("#marker_delay", Input).value.strip()
                if not raw.isdigit() or int(raw) < 0:
                    self.query_one("#error", Static).update("Delay must be a non-negative integer.")
                    return
                config.v86_marker_delay = int(raw)
            if config.desktop == "single_app":
                self.go_next(SingleAppConfigScreen())
            else:
                self.go_next(ExtraPackagesScreen())


def _dir_tree_text(path: Path) -> str:
    """Return a simple text tree of the directory contents."""
    lines = []
    for root, dirs, files in os.walk(path):
        dirs.sort()
        rel = Path(root).relative_to(path)
        depth = len(rel.parts)
        indent = "  " * depth
        folder = rel.name if depth > 0 else str(path)
        if depth > 0:
            lines.append(f"{indent[:-2]}  {folder}/")
        for f in sorted(files):
            lines.append(f"{indent}  {f}")
    return "\n".join(lines) if lines else "  (empty)"


class ExtracustomizationScreen(WizardPage):
    CSS = """
    .box { width: 74; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        extra_dir = DISTRO_DIR / "extracustomization"
        tree_text = _dir_tree_text(extra_dir) if extra_dir.is_dir() else "  Directory not found."
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Add your own files to the distro!", classes="title")
                yield Static("Everything in the distro/extracustomization/ folder gets copied straight into your distro's root filesystem.", classes="hint")
                yield Static("Add wallpapers, scripts, configs, or anything else you need. Here's what's in there right now:", classes="hint")
                yield Static(tree_text, classes="tree")
                yield Static(
                    "Drop files in or remove them now, then hit Refresh and continue.",
                    classes="hint",
                )
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Refresh", id="refresh")
            yield Button("Next →", variant="primary", id="next")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "refresh":
            extra_dir = DISTRO_DIR / "extracustomization"
            tree_text = _dir_tree_text(extra_dir) if extra_dir.is_dir() else "  Directory not found."
            self.query_one(".tree", Static).update(tree_text)
            return
        if event.button.id == "next":
            self.go_next(ScriptEditorScreen())


# ---------------------------------------------------------------------------
# Screen — DroidOS configuration (only shown when droidos template is selected)
# ---------------------------------------------------------------------------

class DroidOSConfigScreen(WizardPage):
    CSS = """
    .box { width: 76; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    .section-label { text-style: bold; margin-top: 1; margin-bottom: 0; }
    """

    def compose(self) -> ComposeResult:
        apk_path = str(DISTRO_DIR / "extracustomization" / "var" / "lib" / "droidos" / "apks")
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("DroidOS configuration", classes="title")
                yield Label("Android variant", classes="section-label")
                with RadioSet(id="droidos_type"):
                    yield RadioButton(
                        "Mobile  — standard Android (default)",
                        id="MOBILE",
                        value=config.droidos_type == "MOBILE",
                    )
                    yield RadioButton(
                        "Android TV  — LineageOS 20 TV build with GApps (requires hardware GPU)",
                        id="ANDROIDTV",
                        value=config.droidos_type == "ANDROIDTV",
                    )
                yield Label("Pre-installing APKs", classes="section-label")
                yield Static(
                    f"Drop .apk files into:\n  {apk_path}\n"
                    "They will be injected into the Android system image at build time.",
                    classes="hint",
                )
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Next →", variant="primary", id="next")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "next":
            rs: RadioSet = self.query_one("#droidos_type")
            if rs.pressed_button:
                config.droidos_type = rs.pressed_button.id
            apk_dir = DISTRO_DIR / "extracustomization" / "var" / "lib" / "droidos" / "apks"
            apk_dir.mkdir(parents=True, exist_ok=True)
            self.go_next(ExtracustomizationScreen())


# ---------------------------------------------------------------------------
# Screen 6a — extrachrootsteps.sh editor
# ---------------------------------------------------------------------------

class ScriptEditorScreen(WizardPage):
    CSS = """
    .box { width: 90; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; margin-bottom: 1; }
    TextArea { height: 14; margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Fine-tune your setup script", classes="title")
                yield Static("This is the script that runs inside your new distro during the build.", classes="hint")
                yield Static("Feel free to add, remove, or change anything — it's just a shell script.", classes="hint")
                yield TextArea("", language="bash", id="script_editor")
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Reset to generated", id="reset")
            yield Button("Next →", variant="primary", id="next")


    def on_mount(self) -> None:
        content = config.custom_script_content if config.custom_script_content else assemble_chroot_script()
        self.query_one("#script_editor", TextArea).load_text(content)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            config.custom_script_content = ""
            self.go_back()
            return
        if event.button.id == "reset":
            self.query_one("#script_editor", TextArea).load_text(assemble_chroot_script())
            config.custom_script_content = ""
            return
        if event.button.id == "next":
            config.custom_script_content = self.query_one("#script_editor", TextArea).text
            self.go_next(ReviewScreen())


# ---------------------------------------------------------------------------
# Screen 6b — Review & build
# ---------------------------------------------------------------------------

class ReviewScreen(WizardPage):
    CSS = """
    .box { width: 70; }
    .title { text-align: center; text-style: bold; margin-bottom: 1; }
    .summary { margin-bottom: 1; }
    """

    def _summary(self) -> str:
        if config.ostemplate:
            templates = {t["stem"]: t["display_name"] for t in discover_templates(config.build_type)}
            os_line = f"  OS         : {templates.get(config.ostemplate, config.ostemplate)} (template)"
        else:
            os_line = f"  OS type    : {config.ostype} (Debian)"
        lines = [
            f"  Build type : {config.build_type}",
            f"  Hostname   : {config.hostname}",
            os_line,
        ]
        if config.ostemplate == "droidos":
            lines.append(f"  DroidOS    : {config.droidos_type}")
        if config.build_type == "HARDDISK":
            lines.append(f"  Drive size : {config.vhd_size} GB")
        lines.append(f"  Desktop    : {config.desktop}")
        if config.desktop == "single_app":
            lines.append(f"  App cmd    : {config.single_app_command}")
            lines.append(f"  Lockdown   : {'yes' if config.single_app_lockdown else 'no'}")
        lines.append(f"  Browser    : {config.browser}")
        if config.username:
            lines.append(f"  User       : {config.username}")
        if config.build_type == "HARDDISK":
            lines.append(f"  QCOW2      : {'yes' if config.convert_to_qcow2 else 'no'}")
            if config.convert_to_qcow2:
                lines.append(f"  Del .img   : {'yes' if config.delete_original_img else 'no'}")
        if config.build_type == "V86":
            if config.v86_custom_marker and config.desktop != "none":
                lines.append(f"  State save : wait for desktop + {config.v86_marker_delay}s settling")
            else:
                lines.append( "  State save : immediate (on kernel boot)")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with Vertical(classes="content"):
            with Vertical(classes="box"):
                yield Label("Looking good! Here's what we'll build.", classes="title")
                yield Static(self._summary(), classes="summary")
                yield Static(
                    "Hit Build to write your config and kick off the build with live output."
                )
        with Horizontal(classes="btn-bar"):
            yield Button("← Back", id="back")
            yield Button("Build", variant="success", id="build")
            yield Button("Save only", variant="primary", id="save")
            if config.build_type == "V86":
                yield Button("Package V86 →", variant="warning", id="package_v86")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.go_back()
            return
        if event.button.id == "save":
            config.generate_new_rootfs = False
            self._write_files()
            self.app.push_screen(BuildScreen(launch=False))
            return
        if event.button.id == "build":
            self._launch_build("runinpodman.py")
            return
        if event.button.id == "package_v86":
            self._launch_build("mkv86.sh")

    def _launch_build(self, script: str) -> None:
        rootfs_exists = (
            (SCRIPT_DIR / "rootfs").is_dir()
            and config.build_type != "HARDDISK"
        )
        if rootfs_exists:
            def _on_dialog(new_rootfs: bool) -> None:
                config.generate_new_rootfs = new_rootfs
                self._write_files()
                self.app.push_screen(BuildScreen(launch=True, script=script))
            self.app.push_screen(RootfsDialog(is_v86=script == "mkv86.sh"), _on_dialog)
        else:
            config.generate_new_rootfs = False
            self._write_files()
            self.app.push_screen(BuildScreen(launch=True, script=script))

    def _write_files(self) -> None:
        DISTRO_DIR.mkdir(exist_ok=True)
        args_parts = [
            f"-hn {config.hostname}",
            f"-t {config.build_type}",
            "-c /env/distro",
            f"-dt {config.ostemplate or 'debian'}",
        ]
        if not config.ostemplate:
            # Debian is a distro template now — the old OSTYPE became a template variable.
            args_parts.append(f"-v DEBIAN_VARIANT={config.ostype}")
        if config.build_type == "HARDDISK":
            args_parts.append(f"-vs {config.vhd_size}")
        if config.generate_new_rootfs:
            args_parts.append("-newfs")
        if config.build_type == "V86" and config.v86_custom_marker:
            args_parts.append("-sbm")
        if config.ostemplate == "droidos":
            args_parts.append(f"-v DROIDOS_TYPE={config.droidos_type}")
        ARGUMENTS_FILE.write_text(" ".join(args_parts) + "\n")

        chroot_script = config.custom_script_content if config.custom_script_content else assemble_chroot_script()
        if chroot_script.strip():
            EXTRACHROOTSTEPS_FILE.write_text(chroot_script)

        # Write after hook for post-build operations
        after_hook = DISTRO_DIR / ".after_hook.sh"
        if config.convert_to_qcow2:
            lines = ["#!/bin/bash", "qemu-img convert -f raw -O qcow2 harddisk.img harddisk.qcow2"]
            if config.delete_original_img:
                lines.append("rm harddisk.img")
            after_hook.write_text("\n".join(lines) + "\n")
        elif after_hook.exists():
            after_hook.unlink()


# ---------------------------------------------------------------------------
# Rootfs reuse dialog (modal)
# ---------------------------------------------------------------------------

class RootfsDialog(ModalScreen[bool]):
    """Returns True if the user wants a fresh rootfs, False to reuse."""

    CSS = """
    RootfsDialog {
        align: center middle;
    }
    RootfsDialog .dialog {
        width: 64;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    RootfsDialog .title { text-align: center; text-style: bold; margin-bottom: 1; }
    RootfsDialog .msg { color: $text-muted; margin-bottom: 1; }
    RootfsDialog .warn-v86 { color: red; text-style: bold; margin-bottom: 1; }
    RootfsDialog .btn-row { align: center middle; margin-top: 1; }
    RootfsDialog Button { margin: 0 2; }
    """

    def __init__(self, is_v86: bool = False) -> None:
        super().__init__()
        self.is_v86 = is_v86

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Existing rootfs detected", classes="title")
            yield Static(
                "A rootfs/ directory from a previous build already exists.",
                classes="msg",
            )
            yield Static(
                "Keeping it will skip debootstrap and save time. "
                "Making a new one ensures a completely clean build.",
                classes="msg",
            )
            yield Static(
                "If you switched to a different OS template, pick 'Make a new one' — "
                "the build refuses a rootfs made for a different distro.",
                classes="msg",
            )
            if self.is_v86:
                yield Static(
                    "WARNING: v86 requires a 32-bit rootfs. "
                    "If your existing rootfs is 64-bit, the build WILL fail.",
                    classes="warn-v86",
                )
            with Horizontal(classes="btn-row"):
                yield Button("Keep current rootfs", id="keep", variant="primary")
                yield Button("Make a new one", id="new", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "new")


# ---------------------------------------------------------------------------
# Screen 6 — Build output
# ---------------------------------------------------------------------------

class BuildScreen(Screen):
    CSS = """
    BuildScreen { layout: vertical; }
    #build-log { height: 1fr; border: round $primary; margin: 1 2; }
    #build-status { height: 1; padding: 0 2; text-align: center; content-align: center middle; }
    #btn-row { height: 3; align: center middle; }
    """

    _SPINNER_FRAMES = ["|", "/", "-", "\\"]

    def __init__(self, launch: bool, script: str = "runinpodman.py") -> None:
        super().__init__()
        self.launch = launch
        self.script = script

    def compose(self) -> ComposeResult:
        yield RichLog(id="build-log", highlight=False, markup=False, wrap=True)
        yield Static("" if self.launch else "Config saved. Run runinpodman.py whenever you're ready.", id="build-status")
        with Horizontal(id="btn-row"):
            yield Button("Quit", variant="primary", id="quit", disabled=self.launch)
        yield Footer()

    def on_mount(self) -> None:
        if self.launch:
            threading.Thread(target=self._stream_build, daemon=True).start()

    def _stream_build(self) -> None:
        log: RichLog = self.query_one("#build-log")
        status: Static = self.query_one("#build-status")

        status_text = [f"Running {self.script}..."]
        stop_spinner = threading.Event()
        stop_quotes = threading.Event()
        frame_idx = [0]

        def _spin() -> None:
            while not stop_spinner.wait(0.12):
                frame = self._SPINNER_FRAMES[frame_idx[0] % len(self._SPINNER_FRAMES)]
                frame_idx[0] += 1
                self.app.call_from_thread(status.update, f"{frame}  {status_text[0]}")

        def _cycle_quotes() -> None:
            while not stop_quotes.wait(5):
                status_text[0] = random.choice(BUILD_QUOTES)

        threading.Thread(target=_spin, daemon=True).start()
        threading.Thread(target=_cycle_quotes, daemon=True).start()

        master_fd, slave_fd = pty.openpty()
        runner = "python3" if self.script.endswith(".py") else "bash"
        proc = subprocess.Popen(
            [runner, str(SCRIPT_DIR / self.script)],
            cwd=str(SCRIPT_DIR),
            stdout=slave_fd,
            stderr=slave_fd,
            stdin=slave_fd,
        )
        os.close(slave_fd)

        buf = ""
        try:
            while True:
                try:
                    r, _, _ = select.select([master_fd], [], [], 0.1)
                except (ValueError, OSError):
                    break
                if r:
                    try:
                        chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                    except OSError:
                        break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        clean = _ANSI_ESCAPE.sub("", line)
                        if clean:
                            self.app.call_from_thread(log.write, clean)
                elif proc.poll() is not None:
                    break
        finally:
            os.close(master_fd)

        proc.wait()

        stop_spinner.set()
        stop_quotes.set()
        if proc.returncode == 0:
            self.app.call_from_thread(status.update, "Build complete! All done.")
        else:
            self.app.call_from_thread(
                status.update, f"Build failed (exit code {proc.returncode})."
            )

        quit_btn: Button = self.query_one("#quit")
        self.app.call_from_thread(setattr, quit_btn, "disabled", False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class DistroBuilderApp(App):
    TITLE = "mkmelinux distrobuilder"
    BINDINGS = [("q", "quit", "Quit"), ("escape", "go_back", "Back")]

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def action_go_back(self) -> None:
        try:
            self.screen.query_one(WizardHost).trigger_go_back()
        except Exception:
            if len(self.screen_stack) > 1:
                self.pop_screen()


if __name__ == "__main__":
    DistroBuilderApp().run()
