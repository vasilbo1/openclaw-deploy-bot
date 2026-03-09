def get_mac_instruction(server_ip: str, container_name: str) -> str:
    return f"""📱 *Connection Guide — Mac*

1. Open Terminal (Cmd+Space → Terminal)

2. Generate an SSH key:
`ssh-keygen -t ed25519 -C "my-key"`
Press Enter three times

3. Send your public key:
`cat ~/.ssh/id_ed25519.pub`

4. Wait for it to be added to the server

5. Configure SSH settings:
```
cat > ~/.ssh/config << EOF
Host {server_ip}
  User {container_name}
  IdentityFile ~/.ssh/id_ed25519
  UseKeychain yes
  AddKeysToAgent yes
EOF
```

6. Add the key permanently:
`ssh-add --apple-use-keychain ~/.ssh/id_ed25519`

7. Connect:
`ssh {container_name}@{server_ip}`

8. Run Claude Code inside:
`claude`

💡 To work via Claude Code on your Mac:
_"On server {server_ip} inside container {container_name}, do: [task]"_"""


def get_windows_instruction(server_ip: str, container_name: str) -> str:
    return f"""💻 *Connection Guide — Windows*

1. Install Git for Windows:
https://git-scm.com/download/win

2. Open Git Bash (right-click on the desktop)

3. Generate an SSH key:
`ssh-keygen -t ed25519 -C "my-key"`
Press Enter three times

4. Send your public key:
`cat ~/.ssh/id_ed25519.pub`

5. Wait for it to be added to the server

6. Configure SSH settings:
```
cat > ~/.ssh/config << EOF
Host {server_ip}
  User {container_name}
  IdentityFile ~/.ssh/id_ed25519
  AddKeysToAgent yes
EOF
```

7. Add the key:
```
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

8. To persist after reboot — run PowerShell as Administrator:
```
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
ssh-add $env:USERPROFILE\\.ssh\\id_ed25519
```

9. Connect:
`ssh {container_name}@{server_ip}`

💡 To work via Claude Code:
_"On server {server_ip} inside container {container_name}, do: [task]"_"""
