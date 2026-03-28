def get_mac_instruction(server_ip: str, container_name: str) -> str:
    return f"""📱 *Connection Guide — Mac*

*1. Generate an SSH key* (skip if you already have one):
`ssh-keygen -t ed25519 -C "my-key"`
Press Enter three times

*2. Send your public key to the admin:*
`cat ~/.ssh/id_ed25519.pub`

*3.* Wait for confirmation that the key has been added

*4. Configure SSH:*
```
cat > ~/.ssh/config << EOF
Host {server_ip}
  User {container_name}
  IdentityFile ~/.ssh/id_ed25519
  UseKeychain yes
  AddKeysToAgent yes
EOF
```

*5. Add the key permanently:*
`ssh-add --apple-use-keychain ~/.ssh/id_ed25519`

*6. Connect:*
`ssh {server_ip}`
You will be placed *directly inside* the container `{container_name}`.

---

*📦 Transferring files into the container:*
```
scp myfile.tar.gz {container_name}@{server_ip}:/tmp/
ssh {server_ip} -t "docker cp /tmp/myfile.tar.gz {container_name}:/root/"
```

*🤖 Using Claude Code on your Mac:*
Tell Claude Code:
_"Connect to {server_ip} as user {container_name}. Run commands inside Docker container {container_name} using: docker exec {container_name} bash -c 'command'. To copy files into the container use: docker cp /tmp/file {container_name}:/root/"_"""


def get_windows_instruction(server_ip: str, container_name: str) -> str:
    return f"""💻 *Connection Guide — Windows*

*1. Install Git for Windows:*
https://git-scm.com/download/win

*2. Open Git Bash* (right-click on the desktop)

*3. Generate an SSH key* (skip if you already have one):
`ssh-keygen -t ed25519 -C "my-key"`
Press Enter three times

*4. Send your public key to the admin:*
`cat ~/.ssh/id_ed25519.pub`

*5.* Wait for confirmation that the key has been added

*6. Configure SSH:*
```
cat > ~/.ssh/config << EOF
Host {server_ip}
  User {container_name}
  IdentityFile ~/.ssh/id_ed25519
  AddKeysToAgent yes
EOF
```

*7. Add the key:*
```
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

*8. To persist after reboot — run PowerShell as Administrator:*
```
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
ssh-add $env:USERPROFILE\\.ssh\\id_ed25519
```

*9. Connect:*
`ssh {server_ip}`
You will be placed *directly inside* the container `{container_name}`.

---

*📦 Transferring files into the container:*
```
scp myfile.tar.gz {container_name}@{server_ip}:/tmp/
ssh {server_ip} -t "docker cp /tmp/myfile.tar.gz {container_name}:/root/"
```

*🤖 Using Claude Code:*
Tell Claude Code:
_"Connect to {server_ip} as user {container_name}. Run commands inside Docker container {container_name} using: docker exec {container_name} bash -c 'command'. To copy files into the container use: docker cp /tmp/file {container_name}:/root/"_"""
