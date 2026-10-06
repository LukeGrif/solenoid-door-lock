#!/usr/bin/env python3
"""Desktop GUI for the Teensy 4.1 door lock controller.

Requires Python 3 with tkinter and pyserial:
    pip install -r requirements.txt
    python lock_gui.py
"""

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import serial
import serial.tools.list_ports

TEENSY_VID = 0x16C0  # PJRC vendor ID
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "cris-logo.png")


class LockGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Door Lock Controller")
        self.root.minsize(420, 560)

        self.ser = None
        self.reader_thread = None
        self.stop_reader = threading.Event()
        self.rx_queue = queue.Queue()

        self._build_ui()
        self.refresh_ports()
        self.root.after(50, self._process_rx)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # Keep a reference to the image, or Tk will garbage-collect it
        self.logo = None
        try:
            self.logo = tk.PhotoImage(file=LOGO_PATH)
            tk.Label(self.root, image=self.logo).pack(pady=(8, 0))
        except tk.TclError:
            pass  # logo missing or unreadable; run without it

        conn = ttk.LabelFrame(self.root, text="Connection")
        conn.pack(fill="x", **pad)

        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(conn, textvariable=self.port_var, width=28, state="readonly")
        self.port_combo.grid(row=0, column=0, **pad)
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).grid(row=0, column=1, **pad)
        self.connect_btn = ttk.Button(conn, text="Connect", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=2, **pad)

        status = ttk.LabelFrame(self.root, text="Lock status")
        status.pack(fill="x", **pad)

        self.state_label = tk.Label(status, text="UNKNOWN", font=("Helvetica", 28, "bold"),
                                    bg="#888888", fg="white", width=14, pady=10)
        self.state_label.pack(**pad)
        self.drive_label = ttk.Label(status, text="Motor: off")
        self.drive_label.pack(**pad)

        ctrl = ttk.LabelFrame(self.root, text="Control")
        ctrl.pack(fill="x", **pad)

        ttk.Label(ctrl, text="Unlock pulse (ms):").grid(row=0, column=0, sticky="e", **pad)
        self.pulse_var = tk.IntVar(value=500)
        ttk.Spinbox(ctrl, from_=50, to=3000, increment=50, textvariable=self.pulse_var,
                    width=8).grid(row=0, column=1, sticky="w", **pad)

        self.unlock_btn = ttk.Button(ctrl, text="UNLOCK / OPEN", command=self.unlock)
        self.unlock_btn.grid(row=1, column=0, sticky="ew", **pad)
        self.lock_btn = ttk.Button(ctrl, text="LOCK / STOP", command=self.lock)
        self.lock_btn.grid(row=1, column=1, sticky="ew", **pad)
        ctrl.columnconfigure(0, weight=1)
        ctrl.columnconfigure(1, weight=1)

        logf = ttk.LabelFrame(self.root, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=8, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, **pad)

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.unlock_btn.config(state=state)
        self.lock_btn.config(state=state)

    def _log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S ") + text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    # ---------------- Serial ----------------
    def refresh_ports(self):
        ports = list(serial.tools.list_ports.comports())
        names = [p.device for p in ports]
        self.port_combo["values"] = names
        teensy = [p.device for p in ports if p.vid == TEENSY_VID]
        if teensy:
            self.port_var.set(teensy[0])
        elif names and self.port_var.get() not in names:
            self.port_var.set(names[0])

    def toggle_connection(self):
        if self.ser:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_var.get()
        if not port:
            self._log("No serial port selected")
            return
        try:
            # exclusive=True makes the open fail if another program has the port
            kwargs = {"exclusive": True} if os.name == "posix" else {}
            self.ser = serial.Serial(port, 115200, timeout=0.1, **kwargs)
        except serial.SerialException as e:
            self._log(f"Could not open {port}: {e}")
            self.ser = None
            return
        self.stop_reader.clear()
        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()
        self.connect_btn.config(text="Disconnect")
        self._set_controls_enabled(True)
        self._log(f"Connected to {port}")
        self.send("PULSE", self.pulse_var.get())
        self.send("STATUS")

    def disconnect(self):
        self.stop_reader.set()
        if self.ser:
            try:
                self.ser.close()
            except serial.SerialException:
                pass
        self.ser = None
        self.connect_btn.config(text="Connect")
        self._set_controls_enabled(False)
        self._set_state(None)
        self.drive_label.config(text="Motor: off")
        self._log("Disconnected")

    def _reader(self):
        buf = b""
        errors = 0
        while not self.stop_reader.is_set():
            try:
                data = self.ser.read(64)
                errors = 0
            except (serial.SerialException, OSError, TypeError) as e:
                # Linux sometimes reports a spurious "readiness to read but
                # returned no data" error; only give up if it keeps happening
                # or the device has really gone away.
                errors += 1
                if errors < 20 and self.ser and os.path.exists(self.ser.port):
                    time.sleep(0.05)
                    continue
                self.rx_queue.put(e)  # signal lost connection
                return
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.rx_queue.put(line.decode(errors="replace").strip())

    def send(self, *parts):
        if not self.ser:
            return
        cmd = " ".join(str(p) for p in parts)
        try:
            self.ser.write((cmd + "\n").encode())
            self._log(f"> {cmd}")
        except serial.SerialException as e:
            self._log(f"Write failed: {e}")
            self.disconnect()

    def _process_rx(self):
        try:
            while True:
                line = self.rx_queue.get_nowait()
                if isinstance(line, Exception):
                    self._log(f"Connection lost: {line}")
                    self.disconnect()
                    continue
                self._handle_line(line)
        except queue.Empty:
            pass
        self.root.after(50, self._process_rx)

    def _handle_line(self, line):
        if not line:
            return
        self._log(f"< {line}")
        if line == "STATE LOCKED":
            self._set_state(True)
        elif line == "STATE UNLOCKED":
            self._set_state(False)
        elif line == "DRIVE ON":
            self.drive_label.config(text="Motor: ON (unlocking)")
        elif line == "DRIVE OFF":
            self.drive_label.config(text="Motor: off")

    def _set_state(self, locked):
        if locked is None:
            self.state_label.config(text="UNKNOWN", bg="#888888")
        elif locked:
            self.state_label.config(text="LOCKED", bg="#c0392b")
        else:
            self.state_label.config(text="UNLOCKED", bg="#27ae60")

    # ---------------- Actions ----------------
    def unlock(self):
        try:
            ms = int(self.pulse_var.get())
        except (tk.TclError, ValueError):
            ms = 500
        self.send("UNLOCK", ms)

    def lock(self):
        self.send("LOCK")

    def on_close(self):
        if self.ser:
            self.send("LOCK")
            self.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    LockGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
