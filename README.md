# Solenoid Door Lock Controller (Teensy 4.1)

Open a 12V motor-driven rotary latch lock from a desktop GUI.

```
 [ Python GUI ] --USB serial--> [ Teensy 4.1 ] --MOSFET--> [ 12V lock ]
                <-- lock status ---------------- microswitch <--
```

- `firmware/solenoid_lock/solenoid_lock.ino`: the Arduino sketch for the Teensy 4.1
- `gui/lock_gui.py`: the desktop GUI (Python + Tkinter + pyserial)

## How this kind of lock works

This is a **motor-driven rotary latch**, not a simple solenoid that holds open
while powered:

- **Red / black** are the 12V motor power. A short pulse of 12V (about
  0.3–1 s) makes the motor release the latch.
- **Yellow / white** are the **status microswitch**. It's a plain switch
  contact that tells you if the latch is locked or open. It is *not* an
  input for driving the lock.
- **Locking happens mechanically.** Pushing the door shut re-engages the
  latch. That's why the GUI has **UNLOCK / OPEN** to fire the pulse, and
  **LOCK / STOP** only cuts motor power at once (as an abort).
- **Don't hold 12V on it continuously.** The firmware caps every pulse at
  3 s to protect the motor.

> Check your wire colours with a multimeter before connecting. With no power
> on the lock, measure continuity across yellow/white and move the latch by
> hand. The reading should switch between open and closed.

## Wiring

**The Teensy 4.1 is a 3.3V board and its pins are NOT 5V tolerant.** Never
connect 12V to any Teensy pin. The lock must be switched through a
logic-level MOSFET or a relay module that works with 3.3V.

### Option A: NOYITO isolated MOSFET module (LR7843 + optocoupler)

This is the easiest option. The module has its own optocoupler, gate
resistor and pull-down, so you don't need the separate resistors listed in
Option B. The input marked **PWM** is just the control input. The firmware
sets it fully on for the unlock pulse, so no PWM signal is needed.

```
Teensy pin 2 ─────────── module PWM   (signal +)
Teensy GND   ─────────── module GND   (signal −)

12V PSU (+)  ─────────── module DC+   (power in)
12V PSU (−)  ─────────── module DC−   (power in)

module OUT+  ─────────── Lock RED     (+12V)
module OUT−  ─────────── Lock BLACK   (GND)

Teensy pin 3 ─────────── Lock YELLOW  (microswitch)
Teensy GND   ─────────── Lock WHITE   (microswitch)
```

- Because the module is isolated, the 12V supply's ground and the Teensy's
  ground don't need to be connected.
- Add a **1N5819** or **1N4007** diode across OUT+ and OUT−, with the stripe
  to OUT+. It protects the MOSFET from the motor's voltage spike when power
  cuts off.
- Check the module's listing to confirm that its signal input accepts
  3.3V.
- The microswitch wires go straight to the Teensy, not through the module.

### Option B: discrete MOSFET

#### Parts

- A 12V DC power supply that can deliver at least 2A
- A logic-level N-channel MOSFET that fully turns on at 3.3V, such as an
  **IRLB8721** or **IRLZ34N**, or a "3.3V compatible MOSFET/relay module".
  A plain IRF520 module will **not** turn on properly at 3.3V.
- A flyback diode such as a **1N5819** or **1N4007**
- A 100 Ω resistor for the gate and a 10 kΩ resistor for the gate pull-down

#### Connections

```
12V PSU (+) ──────────────┬──────────── Lock RED (+12V)
                          │
                       [Diode]  cathode (stripe) to +12V
                          │
                          ├──────────── Lock BLACK (GND)
                          │
                       MOSFET Drain
Teensy pin 2 ──[100Ω]── MOSFET Gate
                  │
               [10kΩ]
                  │
GND ─────────────┴────── MOSFET Source ── 12V PSU (−) ── Teensy GND
                                          (grounds MUST be shared)

Teensy pin 3 ─────────── Lock YELLOW  (microswitch)
Teensy GND   ─────────── Lock WHITE   (microswitch)
```

- The microswitch uses the Teensy's internal pull-up. Nothing else is
  needed, and the switch only ever sees 3.3V.
- The yellow/white order doesn't matter, because it's just a switch.
- If the GUI shows LOCKED when the door is open, set
  `SWITCH_CLOSED_MEANS_LOCKED = false` in the sketch.

## Uploading the firmware to the Teensy 4.1

1. Install the [Arduino IDE](https://www.arduino.cc/en/software) (2.x).
2. Add Teensy support. Go to **File → Preferences → Additional boards manager
   URLs** and add
   `https://www.pjrc.com/teensy/package_teensy_index.json`. Then open
   **Boards Manager**, search for **Teensy** and install it.
3. Open `firmware/solenoid_lock/solenoid_lock.ino`.
4. Pick **Tools → Board → Teensy 4.1** and **Tools → USB Type → Serial**.
5. Click **Upload**. Press the button on the Teensy if the loader asks you to.

To test without the GUI, open the Serial Monitor (newline line ending) and
type `STATUS`, `UNLOCK`, `UNLOCK 800` or `LOCK`.

## Running the GUI

```bash
cd gui
pip install -r requirements.txt
python lock_gui.py
```

1. Pick the Teensy's port. It's selected automatically when it's detected
   (`COMx` on Windows, `/dev/ttyACM0` on Linux, `/dev/cu.usbmodem…` on macOS).
2. Click **Connect**.
3. Set the unlock pulse time (500 ms is a good starting point) and press
   **UNLOCK / OPEN**.
4. The big indicator follows the microswitch live: **LOCKED** is red and
   **UNLOCKED** is green.

Close the Arduino Serial Monitor first, because only one program can use
the port at a time. On Linux, Tkinter may need `sudo apt install python3-tk`,
and you may need the
[Teensy udev rules](https://www.pjrc.com/teensy/00-teensy.rules).

## Serial protocol

| Command       | Effect                                               |
|---------------|------------------------------------------------------|
| `UNLOCK`      | Pulse the lock for the default pulse time            |
| `UNLOCK <ms>` | Pulse for `<ms>` milliseconds (50–3000)               |
| `LOCK`        | Cut lock power immediately                           |
| `PULSE <ms>`  | Set the default pulse time                           |
| `STATUS`      | Reply with `STATE …`, `DRIVE …`, `PULSE …`            |
| `PING`        | Reply with `PONG`                                    |

The Teensy also sends `STATE LOCKED` / `STATE UNLOCKED` on its own whenever
the microswitch changes.

## Troubleshooting

**"Connection lost" right after Connect (Linux):** another program is using
the port. The usual culprits are:

- **The Arduino IDE.** Close its Serial Monitor, or quit the IDE.
- **ModemManager.** It probes new `/dev/ttyACM*` devices. Installing the
  [Teensy udev rules](https://www.pjrc.com/teensy/00-teensy.rules) tells it
  to leave the Teensy alone. As a quick test, you can stop it with
  `sudo systemctl stop ModemManager`.

The log shows the actual error after "Connection lost:".
