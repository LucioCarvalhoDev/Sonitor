#!/bin/sh
set -e
U=@@USER@@
if id -u "$U" >/dev/null 2>&1; then
    userdel -r "$U" 2>/dev/null || userdel "$U" || true
fi
echo "sonitor: teardown complete"
