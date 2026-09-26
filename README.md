# Libre Potato

A small Python file server for your Debian machine. Sign in from a browser and browse, preview, download, and upload files in one folder you choose.

It is meant to run on the Libre Potato computer (Debian with GNOME) and be opened from your other devices. The process only serves that one folder, and only after a password check.

## What you can do

- Sign in with one username and password
- Browse folders, including on a phone
- Preview text, images, PDF, audio, and video
- Download files
- Upload a file or create a folder

Dotfiles such as `.ssh` and `.env` are skipped. Names that try to climb out of the folder with `..` are rejected. The server also refuses to use `/` or its own application folder as the file root.

There is no delete yet. Remove files on the Debian machine itself.

## Security choices

The app listens on `127.0.0.1` by default, so it is not reachable from the internet just by starting it. The practical way to open it from anywhere is [Tailscale](https://tailscale.com/): the Debian machine and your phone join the same tailnet, and Tailscale provides the encrypted path. You do not open a port on your router.

The password is stored as a scrypt hash. The session cookie is marked `HttpOnly`. Login slows down after repeated failures. HTML and SVG files are downloaded, not shown in the browser, so a saved web page cannot run as this site.

Use a dedicated folder such as `/home/dylan/Potato`. Do not point it at your whole home directory.

## Install it on the Debian machine

The repo is private, so sign in to GitHub on that machine first. Download the ZIP from the Code button on the repo page, or clone it:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
git clone https://github.com/dylanwells120-png/libre-potato.git ~/libre-potato
cd ~/libre-potato
./packaging/install.sh
```

The installer asks for the folder you want to reach (it suggests `~/Potato`), a username, and a password. It stores a hash of the password, installs the dependencies, and starts a background service for your user. Run it as yourself, not with sudo, so the service can read your files.

Open `http://127.0.0.1:8787` on the Debian machine and sign in.

Logs:

```bash
journalctl --user -u libre-potato -f
```

So it keeps running after you log out of GNOME:

```bash
sudo loginctl enable-linger "$USER"
```

## Reach it from another device

The server listens only on that machine. Tailscale is the path from your phone or another computer: install it on both devices, sign in to the same account, and leave the server on localhost.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8787
```

`tailscale serve` prints an HTTPS address. Use that address in a browser, or paste it into the desktop client. Set `LIBRE_POTATO_HTTPS_ONLY=1` in `~/.config/libre-potato/env` and restart the service (`systemctl --user restart libre-potato`) so the browser sign-in cookie is only sent over HTTPS.

A phone uses the browser at that address. Another computer can use the browser or the desktop client below.

## Desktop client

`client/` is a separate app for a Mac or another Linux computer. Download this same repo there, then:

```bash
cd libre-potato/client
./setup.sh
./run.sh
```

On Debian, install `python3-tk` first if setup says Tk is missing. Sign in with the Tailscale address, the username, and the password from the installer. The app saves the address and a sign-in token, not the password.

From the window you can open folders, download a file, upload files, and create a folder.

## Develop

Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Copy `.env.example` to `.env` before `python -m app`.
