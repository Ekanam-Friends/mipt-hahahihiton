#!/bin/sh
set -eu
name=mipt-review
id "$name" >/dev/null 2>&1 || useradd --create-home --user-group --shell /bin/sh "$name"
passwd -l "$name"
chown root:root /home/mipt-review
chmod 755 /home/mipt-review
install -d -m 755 /opt/mipt-regnav/admin /etc/ssh/authorized_keys
install -o root -g root -m 644 /opt/mipt-regnav/release/deploy/review_shell.py /opt/mipt-regnav/admin/review_shell.py
cat > /usr/local/sbin/mipt-review-launch <<'SH'
#!/bin/sh
set -eu
test "$#" -le 1
if test -t 0; then tty=-t; else tty=; fi
exec /usr/bin/docker run --rm -i $tty --network none --read-only --cap-drop ALL --security-opt no-new-privileges --memory 96m --cpus 0.25 --pids-limit 32 --user 65534:65534 --workdir /project --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONUNBUFFERED=1 --mount type=bind,src=/opt/mipt-regnav/release,dst=/project,readonly --mount type=bind,src=/opt/mipt-regnav/admin/review_shell.py,dst=/review_shell.py,readonly --entrypoint python mipt-regnav:release /review_shell.py "${1-}"
SH
cat > /usr/local/bin/mipt-review-dispatch <<'SH'
#!/bin/sh
exec /usr/bin/sudo -n /usr/local/sbin/mipt-review-launch "${SSH_ORIGINAL_COMMAND-}"
SH
chown root:root /usr/local/sbin/mipt-review-launch /usr/local/bin/mipt-review-dispatch
chmod 755 /usr/local/sbin/mipt-review-launch /usr/local/bin/mipt-review-dispatch
printf '%s\n' 'mipt-review ALL=(root) NOPASSWD: /usr/local/sbin/mipt-review-launch *' > /etc/sudoers.d/mipt-review
chmod 440 /etc/sudoers.d/mipt-review
visudo -cf /etc/sudoers.d/mipt-review
cat > /etc/ssh/sshd_config.d/72-mipt-review.conf <<'CONF'
Match User mipt-review
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthorizedKeysFile /etc/ssh/authorized_keys/mipt-review
    ForceCommand /usr/local/bin/mipt-review-dispatch
    DisableForwarding yes
    AllowTcpForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitUserRC no
    PermitTTY yes
Match all
CONF
sshd -t
systemctl reload ssh
sshd -T -C user=mipt-review,host=localhost,addr=127.0.0.1 | grep -E 'forcecommand|passwordauthentication|authorizedkeysfile|disableforwarding|permituser(rc|environment)'
