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

## Run it on Debian

Install Git and Python, then clone this private repo:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
git clone git@github.com:dylanwells120-png/libre-potato.git ~/libre-potato
cd ~/libre-potato
./scripts/setup.sh
```

Create the folder you want to reach, then edit `~/libre-potato/.env`:

```bash
mkdir -p ~/Potato
chmod 600 ~/libre-potato/.env
```

Set `LIBRE_POTATO_FILES_ROOT` to that folder (`/home/dylan/Potato`). Then, from the repo with the virtualenv active:

```bash
. .venv/bin/activate
python -m app.hash_password
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the hash in `LIBRE_POTATO_PASSWORD_HASH` and the random string in `LIBRE_POTATO_SECRET_KEY`.

Check that it serves pages:

```bash
python -m app
```

Open `http://127.0.0.1:8787` on the Debian machine and sign in. Stop it with Ctrl+C once that works.

### Start at boot

GNOME does not need to be logged in if lingering is enabled. This user service runs as you, so it can read your folder.

```bash
mkdir -p ~/.config/systemd/user
cp ~/libre-potato/deploy/libre-potato.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now libre-potato
sudo loginctl enable-linger "$USER"
```

Logs:

```bash
journalctl --user -u libre-potato -f
```

### Open it from your phone

Install Tailscale on the Debian machine and on the phone, and sign in to the same account.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Then either open `http://<the-machine-tailscale-ip>:8787` after changing `LIBRE_POTATO_HOST` to `0.0.0.0`, or keep the app on localhost and use Tailscale Serve so only your tailnet can reach it:

```bash
sudo tailscale serve --bg 8787
```

`tailscale serve` prints an HTTPS address. Use that from the phone. Leave `LIBRE_POTATO_HOST` at `127.0.0.1`. Set `LIBRE_POTATO_HTTPS_ONLY=1` in `.env` and restart the service so the sign-in cookie is only sent over HTTPS.

If you later put it on a public hostname, terminate HTTPS in Caddy or nginx and proxy to `127.0.0.1:8787`. Keep the app bound to localhost.

## Develop

Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Copy `.env.example` to `.env` before `python -m app`.
