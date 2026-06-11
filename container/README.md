Everything you put here will be copied into the container's working directory. Useful for in between scripts.

Files you can put in here:
runbefore.sh - runs before the mkmelinux.sh script will run.
runafter.sh - runs after the mkmelinux.sh script.

You can put all other files inside here to be able to work with them inside a container. Note that this will not automatically run if not using containers. 
Files in all containers will be mounted in /env. Your working directory is /env, so other files will be accessible with "./container/...".