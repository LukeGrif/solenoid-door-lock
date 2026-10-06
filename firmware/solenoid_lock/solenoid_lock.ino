/*
 * Solenoid / motor-latch door lock controller for Teensy 4.1
 *
 * Lock: 12V DC motor-driven rotary latch with integrated status microswitch.
 *   Red    (+12V)  -> +12V supply
 *   Black  (GND)   -> MOSFET drain (MOSFET switches the low side)
 *   Yellow/White   -> status microswitch (dry contact, NOT a drive signal)
 *
 * The Teensy 4.1 runs at 3.3V and its pins are NOT 5V tolerant, so the
 * 12V lock must be switched through a logic-level MOSFET (or a relay module)
 * and the microswitch must only ever see the Teensy's own 3.3V pull-up.
 * See README.md for the full wiring diagram.
 *
 * Serial protocol (USB serial, newline-terminated, case-insensitive):
 *   UNLOCK          Pulse the lock for the configured pulse time
 *   UNLOCK <ms>     Pulse the lock for <ms> milliseconds (clamped to MAX_PULSE_MS)
 *   LOCK            Cut power to the lock immediately (abort a pulse)
 *   STATUS          Report the current state
 *   PULSE <ms>      Set the default unlock pulse time
 *   PING            Replies PONG
 *
 * Replies / events (one per line):
 *   STATE LOCKED | STATE UNLOCKED      (from the microswitch, sent on change)
 *   DRIVE ON | DRIVE OFF               (whether the lock is being powered)
 *   PULSE <ms>                         (current default pulse time)
 *   OK <message> | ERR <message>
 */

// ---------------- Configuration ----------------
const uint8_t LOCK_DRIVE_PIN = 2;   // -> MOSFET module PWM/signal input (or gate via ~100 ohm)
const uint8_t LOCK_SENSE_PIN = 3;   // -> one microswitch wire (other wire -> GND)
const uint8_t LED_PIN        = 13;  // on-board LED mirrors the drive output

// Set to false if the status reads backwards on your lock (the microswitch
// may be normally-open or normally-closed depending on the model).
const bool SWITCH_CLOSED_MEANS_LOCKED = true;

const uint32_t DEFAULT_PULSE_MS = 500;   // typical for motor latches: 300-1000 ms
const uint32_t MIN_PULSE_MS     = 50;
const uint32_t MAX_PULSE_MS     = 3000;  // safety cap: never stall the motor longer
const uint32_t DEBOUNCE_MS      = 30;
// ------------------------------------------------

uint32_t pulseMs = DEFAULT_PULSE_MS;

bool     driving       = false;
uint32_t driveStartMs  = 0;
uint32_t driveLengthMs = 0;

bool     lastRawSense    = false;
uint32_t lastSenseChange = 0;
bool     stableLocked    = false;

String inputLine;

bool readLockedRaw() {
  // INPUT_PULLUP: switch closed -> pin pulled LOW
  bool switchClosed = (digitalRead(LOCK_SENSE_PIN) == LOW);
  return SWITCH_CLOSED_MEANS_LOCKED ? switchClosed : !switchClosed;
}

void reportState() {
  Serial.println(stableLocked ? "STATE LOCKED" : "STATE UNLOCKED");
}

void reportDrive() {
  Serial.println(driving ? "DRIVE ON" : "DRIVE OFF");
}

void driveOff() {
  digitalWrite(LOCK_DRIVE_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
  if (driving) {
    driving = false;
    reportDrive();
  }
}

void startUnlock(uint32_t ms) {
  ms = constrain(ms, MIN_PULSE_MS, MAX_PULSE_MS);
  driveLengthMs = ms;
  driveStartMs  = millis();
  driving       = true;
  digitalWrite(LOCK_DRIVE_PIN, HIGH);
  digitalWrite(LED_PIN, HIGH);
  Serial.print("OK UNLOCK ");
  Serial.println(ms);
  reportDrive();
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  if (cmd.length() == 0) return;

  int space = cmd.indexOf(' ');
  String verb = (space < 0) ? cmd : cmd.substring(0, space);
  String arg  = (space < 0) ? ""  : cmd.substring(space + 1);
  arg.trim();

  if (verb == "UNLOCK" || verb == "OPEN") {
    startUnlock(arg.length() ? (uint32_t)arg.toInt() : pulseMs);
  } else if (verb == "LOCK" || verb == "CLOSE" || verb == "STOP") {
    driveOff();
    Serial.println("OK LOCK");
  } else if (verb == "STATUS") {
    reportState();
    reportDrive();
    Serial.print("PULSE ");
    Serial.println(pulseMs);
  } else if (verb == "PULSE") {
    long ms = arg.toInt();
    if (ms <= 0) {
      Serial.println("ERR PULSE needs a value in ms");
      return;
    }
    pulseMs = constrain((uint32_t)ms, MIN_PULSE_MS, MAX_PULSE_MS);
    Serial.print("PULSE ");
    Serial.println(pulseMs);
  } else if (verb == "PING") {
    Serial.println("PONG");
  } else {
    Serial.print("ERR unknown command: ");
    Serial.println(cmd);
  }
}

void setup() {
  pinMode(LOCK_DRIVE_PIN, OUTPUT);
  digitalWrite(LOCK_DRIVE_PIN, LOW);   // make sure the lock is off at boot
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  pinMode(LOCK_SENSE_PIN, INPUT_PULLUP);

  Serial.begin(115200);  // Teensy USB serial runs at full USB speed regardless

  lastRawSense    = readLockedRaw();
  stableLocked    = lastRawSense;
  lastSenseChange = millis();
  inputLine.reserve(64);
}

void loop() {
  uint32_t now = millis();

  // End the unlock pulse (non-blocking)
  if (driving && (now - driveStartMs >= driveLengthMs)) {
    driveOff();
  }

  // Debounce the status microswitch and report changes
  bool raw = readLockedRaw();
  if (raw != lastRawSense) {
    lastRawSense    = raw;
    lastSenseChange = now;
  } else if (raw != stableLocked && (now - lastSenseChange >= DEBOUNCE_MS)) {
    stableLocked = raw;
    reportState();
  }

  // Read serial commands
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      handleCommand(inputLine);
      inputLine = "";
    } else if (inputLine.length() < 60) {
      inputLine += c;
    }
  }
}
