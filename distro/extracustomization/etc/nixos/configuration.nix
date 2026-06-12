{ config, pkgs, lib, ... }:

{
  # ── Basics ──────────────────────────────────────────────────────────────
  networking.hostName = "my-nixos";

  # System-wide packages.
  environment.systemPackages = with pkgs; [
    vim
    fastfetch
  ];

  nixpkgs.config.allowUnfree = true;

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

  # No display manager (see nixos.dt: udev can't autoload DRM modules, so a
  # failing DM can hang the boot). Instead, autologin the nixos user on tty1
  # and start Plasma straight from the bash login shell. Other ttys and ssh
  # logins still get a normal shell.
  services = {
    desktopManager.plasma6.enable = true;
    getty.autologinUser = "nixos";
  };
  programs.bash.loginShellInit = ''
    if [ "$(tty)" = "/dev/tty1" ] && [ -z "$WAYLAND_DISPLAY" ]; then
      exec dbus-run-session startplasma-wayland
    fi
  '';
  environment.plasma6.excludePackages = with pkgs.kdePackages; [
    plasma-browser-integration
    elisa
    gwenview
    okular
    khelpcenter
    print-manager
    krdp
  ]; # make ISO lighter

  # https://nixos.wiki/wiki/FAQ/When_do_I_update_stateVersion
  system.stateVersion = lib.trivial.release;
}
