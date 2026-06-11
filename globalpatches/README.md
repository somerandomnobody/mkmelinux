# Global Patches - patch CVEs in distros quickly

The global patches directory is for patches to distros (scripts) that will be executed across all distros.

This can be useful for patching CVEs (eg. copyfail in Debian) in mkmelinux without relying on distros to patch it, and you can ensure that all distros you make are secure. This is sometimes faster than Distro maintainers!

You can use this directory for other patches that you may want to use over multiple distros.

This executes after your extra chroot steps script.