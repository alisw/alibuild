package: clobber-initdotsh
version: "1"
---
echo exit 1 > "$INSTALLROOT/etc/profile.d/init.sh"
