"""Desktop window for browsing a Libre Potato server."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, simpledialog, ttk
import tkinter as tk

from potato_client.config import load_config, save_config
from potato_client.remote import PotatoClient, PotatoError


def format_size(size: int | None) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Libre Potato")
        self.geometry("860x580")
        self.minsize(680, 440)
        self.client: PotatoClient | None = None
        self.directory = ""
        self.parent = ""
        self.server_var = tk.StringVar()
        self.user_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Enter the server address from Tailscale, then sign in.")
        self._build()
        saved = load_config()
        self.server_var.set(str(saved.get("server") or ""))
        self.user_var.set(str(saved.get("username") or ""))
        token = saved.get("token")
        server = self.server_var.get().strip()
        if server and isinstance(token, str) and token:
            try:
                self.client = PotatoClient(server, token)
            except PotatoError as exc:
                self._status(str(exc))
            else:
                self.after(100, self.refresh)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        form = ttk.Frame(self, padding=12)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="Server").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(form, textvariable=self.server_var).grid(row=0, column=1, columnspan=3, sticky="ew")
        ttk.Label(form, text="Username").grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 8))
        ttk.Entry(form, textvariable=self.user_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(form, text="Password").grid(row=1, column=2, sticky="w", pady=(8, 0), padx=(12, 8))
        ttk.Entry(form, textvariable=self.password_var, show="*").grid(row=1, column=3, sticky="ew", pady=(8, 0))
        ttk.Button(form, text="Sign in", command=self.sign_in).grid(row=1, column=4, padx=(12, 0), pady=(8, 0))

        bar = ttk.Frame(self, padding=(12, 0, 12, 8))
        bar.grid(row=1, column=0, sticky="ew")
        ttk.Button(bar, text="Up", command=self.go_up).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Download", command=self.download_selected).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Upload", command=self.upload_files).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="New folder", command=self.make_folder).pack(side="left", padx=(8, 0))
        self.path_label = ttk.Label(bar, text="Files")
        self.path_label.pack(side="right")

        table = ttk.Frame(self, padding=(12, 0, 12, 0))
        table.grid(row=2, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("kind", "size", "modified"), show="tree headings")
        self.tree.heading("#0", text="Name")
        self.tree.heading("kind", text="Kind")
        self.tree.heading("size", text="Size")
        self.tree.heading("modified", text="Modified")
        self.tree.column("#0", width=320, stretch=True)
        self.tree.column("kind", width=90, stretch=False)
        self.tree.column("size", width=90, stretch=False)
        self.tree.column("modified", width=160, stretch=False)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self.open_selected)

        ttk.Label(self, textvariable=self.status_var, padding=12).grid(row=3, column=0, sticky="ew")

    def sign_in(self) -> None:
        server = self.server_var.get().strip()
        username = self.user_var.get().strip()
        password = self.password_var.get()

        def work() -> PotatoClient:
            client = PotatoClient(server)
            client.login(username, password)
            return client

        def done(client: PotatoClient) -> None:
            self.client = client
            self.password_var.set("")
            self.directory = ""
            save_config({"server": client.base_url, "username": username, "token": client.token})
            self._status("Signed in.")
            self.refresh()

        self._run(work, done)

    def refresh(self) -> None:
        client = self._require_client()
        if client is None:
            return
        directory = self.directory

        def work() -> dict:
            return client.list_files(directory)

        def done(payload: dict) -> None:
            self.parent = str(payload.get("parent") or "")
            path = str(payload.get("path") or "")
            self.path_label.configure(text=path or "Files")
            self.tree.delete(*self.tree.get_children())
            for entry in payload["entries"]:
                name = str(entry.get("name") or "")
                kind = str(entry.get("kind") or "")
                size = entry.get("size")
                self.tree.insert(
                    "",
                    "end",
                    iid=name,
                    text=name,
                    values=(kind, format_size(size if isinstance(size, int) else None), entry.get("modified") or ""),
                )
            self._status(f"{len(payload['entries'])} items")

        self._run(work, done)

    def go_up(self) -> None:
        if not self.directory:
            return
        self.directory = self.parent
        self.refresh()

    def open_selected(self, _event: object = None) -> None:
        name, kind = self._selected()
        if not name:
            return
        if kind == "folder":
            self.directory = f"{self.directory}/{name}" if self.directory else name
            self.refresh()
            return
        self.download_selected()

    def download_selected(self) -> None:
        client = self._require_client()
        name, kind = self._selected()
        if client is None or not name:
            return
        if kind == "folder":
            self._status("Open the folder, then download a file.")
            return
        dest = filedialog.askdirectory(title="Save into")
        if not dest:
            return
        remote = f"{self.directory}/{name}" if self.directory else name

        def work() -> Path:
            return client.download(remote, Path(dest))

        self._run(work, lambda path: self._status(f"Saved {path}"))

    def upload_files(self) -> None:
        client = self._require_client()
        if client is None:
            return
        paths = filedialog.askopenfilenames(title="Upload files")
        if not paths:
            return
        directory = self.directory

        def work() -> int:
            for raw in paths:
                client.upload(directory, Path(raw))
            return len(paths)

        def done(count: int) -> None:
            self._status(f"Uploaded {count} file{'s' if count != 1 else ''}.")
            self.refresh()

        self._run(work, done)

    def make_folder(self) -> None:
        client = self._require_client()
        if client is None:
            return
        name = simpledialog.askstring("New folder", "Folder name", parent=self)
        if not name:
            return
        directory = self.directory

        def work() -> str:
            client.mkdir(directory, name)
            return name

        def done(created: str) -> None:
            self._status(f"Created {created}.")
            self.refresh()

        self._run(work, done)

    def _selected(self) -> tuple[str, str]:
        selection = self.tree.selection()
        if not selection:
            self._status("Select a file or folder first.")
            return "", ""
        name = selection[0]
        return name, self.tree.set(name, "kind")

    def _require_client(self) -> PotatoClient | None:
        if self.client is None:
            self._status("Sign in first.")
            return None
        return self.client

    def _status(self, message: str) -> None:
        self.status_var.set(message)

    def _run(self, work, done) -> None:
        def target() -> None:
            try:
                result = work()
            except PotatoError as exc:
                self.after(0, lambda message=str(exc): self._status(message))
                if exc.status == 401:
                    self.after(0, self._clear_session)
                return
            except OSError as exc:
                self.after(0, lambda message=str(exc): self._status(message))
                return
            self.after(0, lambda value=result: done(value))

        threading.Thread(target=target, daemon=True).start()

    def _clear_session(self) -> None:
        self.client = None
        saved = load_config()
        saved.pop("token", None)
        save_config(saved)
