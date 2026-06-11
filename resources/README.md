# Resources

Ready-to-copy starting points for customizing distro template builds.

- `nixos-configuration-template.nix` — base `/etc/nixos/configuration.nix` for
  NixOS builds. Copy it to `distro/extracustomization/etc/nixos/configuration.nix`
  and edit. Read its header comments before pasting in a config from elsewhere:
  flake-based starter configs need small changes to build here.
