# mkmelinux NixOS configuration template
#
# Copy this file to distro/extracustomization/etc/nixos/configuration.nix and
# edit it — it replaces /etc/nixos/configuration.nix in the built image, and
# any valid NixOS configuration works there.
#
# Notes for configs copied from elsewhere (starter templates, dotfiles repos):
#
#   * Use the classic module header below — NOT `{ inputs, ... }:`. Flake-only
#     arguments like `inputs` do not exist here (mkmelinux evaluates with
#     channels, not flakes) and fail the build.
#   * Do NOT import ./hardware-configuration.nix. The "hardware" layer
#     (kernel, initramfs, bootloader, root filesystem) is provided by
#     mkmelinux itself via /etc/nixos/mkmelinux-base.nix, which is merged in
#     automatically. A hardware-configuration.nix from a real machine defines
#     mounts for disks that do not exist in the live image and drops boot
#     into emergency mode.
#   * Avoid enabling a display manager (GDM, SDDM, ...). The kernel lives
#     outside the system profile, so udev cannot autoload DRM/input modules;
#     a display manager that fails to start takes over tty1 and leaves the
#     machine with no visible login prompt.
#
# Defaults provided by mkmelinux — override any of them freely here:
#   networking.hostName  = "mkmelinux-nixos"
#   networking.useDHCP   = true
#   networking.firewall.enable = false   (nf_tables cannot load at runtime)
#   services.getty.autologinUser = "root"
#   users.users.root.initialHashedPassword = ""
#   system.stateVersion  = (current release)

{ config, pkgs, lib, ... }:

{
  # ── Basics ──────────────────────────────────────────────────────────────
  networking.hostName = "my-nixos";

  # System-wide packages.
  environment.systemPackages = with pkgs; [
    vim
    htop
    # firefox
  ];

  # Allow unfree packages (uncomment if you need e.g. vscode, spotify):
  # nixpkgs.config.allowUnfree = true;

  # Enable flakes and the new nix CLI inside the built image:
  # nix.settings.experimental-features = "nix-command flakes";

  # ── Users ───────────────────────────────────────────────────────────────
  # A regular user with passwordless sudo. The root account stays usable on
  # tty1 via autologin unless you override services.getty.autologinUser.
  users.users.nixos = {
    isNormalUser = true;
    extraGroups = [ "wheel" "video" "audio" ];
    # Empty password — set a real one with `passwd` after boot, or put a
    # hash from `mkpasswd -m sha-512` here.
    initialHashedPassword = "";
    openssh.authorizedKeys.keys = [
      # "ssh-ed25519 AAAA... you@example.com"
    ];
  };
  security.sudo.wheelNeedsPassword = false;

  # ── Services ────────────────────────────────────────────────────────────
  # SSH server (handy for headless use):
  # services.openssh = {
  #   enable = true;
  #   settings.PermitRootLogin = "no";
  #   settings.PasswordAuthentication = false;
  # };

  # https://nixos.wiki/wiki/FAQ/When_do_I_update_stateVersion
  system.stateVersion = lib.trivial.release;
}
