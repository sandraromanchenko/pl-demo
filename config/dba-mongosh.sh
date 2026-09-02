#!/bin/bash
# Operator shell for the demo: authenticates as `dba` using the password file
# so the password never appears on the command line.
set -euo pipefail
pwd=$(tr -d '\n' < /etc/mongodb/dba-password)
exec mongosh -u dba -p "$pwd" --authenticationDatabase admin --quiet "$@"
