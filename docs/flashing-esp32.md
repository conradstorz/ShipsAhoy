# Flashing the ESP32 Ticker Firmware

This guide walks you through everything needed to load the `esp32_ticker` firmware onto an ESP32-S3-WROOM-1 development board on a Windows PC.
No prior Arduino or ESP32 experience is assumed.

---

## What You Need

### Hardware
- **ESP32-S3-WROOM-1 development board** (any devkit with that module)
- **USB cable** — must be a data cable, not a charge-only cable. If the cable that came with your board does not work, try a different one.
- **Windows 11 PC**

### Software (installed in this guide)
- **arduino-cli** — the command-line tool that compiles and uploads Arduino sketches
- **ESP32 board support package** — tells arduino-cli how to build for ESP32-S3
- **FastLED library** — drives the WS2812B LED panels

---

## Part 1 — Install arduino-cli

`arduino-cli` is a single executable. You do not need to install the Arduino IDE.

### Step 1.1 — Download arduino-cli

1. Open your browser and go to: https://arduino.github.io/arduino-cli/latest/installation/
2. Under **"Download"**, click the link for **Windows 64-bit** (the file will be named something like `arduino-cli_1.x.x_Windows_64bit.zip`).
3. Save the ZIP file somewhere easy to find, for example your Downloads folder.

### Step 1.2 — Extract and place the executable

1. Right-click the ZIP file and choose **Extract All**.
2. Inside the extracted folder you will find `arduino-cli.exe`.
3. Create a folder for it, for example: `C:\tools\arduino-cli\`
4. Move `arduino-cli.exe` into that folder.

### Step 1.3 — Add arduino-cli to your PATH

Adding it to PATH means you can type `arduino-cli` in any terminal without typing the full path every time.

1. Press **Windows key**, type `environment variables`, and click **"Edit the system environment variables"**.
2. Click the **Environment Variables** button near the bottom.
3. In the **User variables** section, find the row named **Path** and double-click it.
4. Click **New** and type: `C:\tools\arduino-cli`
5. Click **OK** on all three windows.

### Step 1.4 — Verify the installation

1. Press **Windows key + R**, type `cmd`, press Enter. A black command window opens.
2. Type the following and press Enter:
   ```
   arduino-cli version
   ```
3. You should see output like: `arduino-cli Version: 1.x.x ...`

If you see `'arduino-cli' is not recognized`, go back to Step 1.3 and make sure the path is correct, then close and reopen the command window.

---

## Part 2 — Install the ESP32 Board Package

This tells arduino-cli how to compile code for ESP32 microcontrollers.

### Step 2.1 — Update the board index

In the command window, type:
```
arduino-cli core update-index
```
This downloads a list of available board packages. Wait for it to finish.

### Step 2.2 — Install the ESP32 core

```
arduino-cli core install esp32:esp32
```

This downloads several hundred megabytes of compilers and tools. It can take a few minutes. Wait for it to finish completely.

### Step 2.3 — Verify the install

```
arduino-cli core list
```

You should see a line containing `esp32:esp32` in the output.

---

## Part 3 — Install the FastLED Library

FastLED is the library that controls the WS2812B LED panels.

```
arduino-cli lib install "FastLED"
```

Wait for it to finish. You should see output ending in `FastLED@x.x.x installed`.

---

## Part 4 — Connect the ESP32 Board

### Step 4.1 — Plug in the board

Connect the ESP32 development board to your PC using the USB cable.

Windows should automatically install a driver. You may see a notification in the system tray saying "Device driver installed successfully." If nothing happens after 30 seconds, continue to the next step.

### Step 4.2 — Find the COM port

The board shows up as a COM port on Windows. You need to know which number it got.

1. Press **Windows key + X** and click **Device Manager**.
2. Expand the section called **Ports (COM & LPT)**.
3. Look for an entry that says something like:
   - `USB Serial Device (COM3)`
   - `Silicon Labs CP210x USB to UART Bridge (COM4)`
   - `USB-SERIAL CH340 (COM5)`
   The exact name depends on the chip your devkit uses. The important part is the **COM number**.
4. Note your COM number — you will need it in Part 5.

**If no entry appears:** Your USB cable may be charge-only. Try a different cable. If it still does not appear, you may need to install a driver manually — see the Troubleshooting section at the end.

---

## Part 5 — Navigate to the Project Folder

The firmware sketch is inside the ShipsAhoy repository. In the command window, navigate there:

```
cd D:\Users\Conrad\Documents\programming\ShipsAhoy\ShipsAhoy
```

Confirm you are in the right place:
```
dir esp32_ticker
```

You should see a list of files including `esp32_ticker.ino`, `config.h`, `protocol.cpp`, etc.

---

## Part 6 — Compile the Firmware

This step converts the C++ source code into a binary file the ESP32 can run. No hardware is needed for this step — it only uses your PC.

```
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

**What `--fqbn esp32:esp32:esp32s3` means:** "Fully Qualified Board Name" — it tells the compiler exactly which ESP32 variant to target. The `esp32s3` part matches the ESP32-S3-WROOM-1 module used in this project.

**Expected output:** Several lines of compilation output ending with something like:
```
Sketch uses 123456 bytes (9%) of program storage space.
Global variables use 12345 bytes (3%) of dynamic memory.
```

The exact numbers will differ. What matters is that there are **no lines containing the word `Error`**.

**If you see errors:** See the Troubleshooting section at the end.

---

## Part 7 — Upload (Flash) the Firmware

This step sends the compiled binary to the ESP32 board over USB.

Replace `COM3` with the COM port number you found in Step 4.2:

```
arduino-cli upload -p COM3 --fqbn esp32:esp32:esp32s3 esp32_ticker
```

**What to expect:**
- The upload tool connects to the board (the board's LED may flash briefly).
- You will see progress output like `Writing at 0x00001000... (5 %)`
- It ends with: `Leaving... Hard resetting via RTS pin...`

That last line means the board has been reset and the new firmware is now running.

**If the upload fails:** See the Troubleshooting section at the end.

---

## Part 8 — Verify the Board is Running

Open the serial monitor to see boot messages from the board:

```
arduino-cli monitor -p COM3 -c baudrate=115200
```

Again, replace `COM3` with your COM port number.

**Expected output within a few seconds:**
```
[esp32_ticker] booting
  Display: 320 x 8 (2560 LEDs) on GPIO 38
  UART: 921600 baud on RX=18 TX=17
[display] display_task started on Core 1
[protocol] uart_task started on Core 0
[esp32_ticker] ready
```

If you see this output, the firmware is running correctly.

To exit the serial monitor, press **Ctrl + C**.

---

## Part 9 — LED Data Pin

The firmware is configured to use **GPIO 38** as the data line to the first LED panel.

If your physical wiring uses a different GPIO pin, open `esp32_ticker/config.h` in any text editor and change this line:

```cpp
#define DATA_PIN    38
```

to the correct pin number, then repeat the compile and upload steps (Parts 6 and 7).

> **Note on GPIO 48:** Many ESP32-S3 development boards have their onboard RGB LED connected to GPIO 48. Do **not** use GPIO 48 for the external LED panels — it will cause interference. Use any other free GPIO pin.

---

## Troubleshooting

### "arduino-cli is not recognized"
The PATH was not set correctly. Close the command window, reopen it, and try again. If it still fails, double-check that `arduino-cli.exe` is in the folder you added to PATH.

### Compile error: "No such file or directory: FastLED.h"
The FastLED library was not installed. Run:
```
arduino-cli lib install "FastLED"
```

### Compile error: "esp32:esp32:esp32s3: Unknown board"
The ESP32 core was not installed. Run:
```
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

### Upload error: "No device found on COM3" or "Cannot open port"
- Make sure the board is plugged in.
- Make sure no other program (such as a serial monitor) is using the COM port.
- Confirm the COM port number in Device Manager — it may have changed since you last checked.

### Upload error: "Failed to connect to ESP32: Timed out waiting for packet header"
The board may need to be put into bootloader mode manually:
1. While the board is plugged in, hold the **BOOT** button (sometimes labeled **IO0**).
2. While holding BOOT, press and release the **RESET** button (labeled **RST** or **EN**).
3. Release the BOOT button.
4. Immediately run the upload command again.

### No COM port appears in Device Manager
Your board requires a driver that Windows did not install automatically. Check the board's documentation for the USB-to-serial chip it uses (common ones are CP2102, CH340, or FTDI) and download the driver from the manufacturer's website.

### Serial monitor shows garbage characters
The baud rate is wrong. Make sure you used `-c baudrate=115200` in the monitor command. The firmware sends at 115200 baud (the monitor port), not 921600 (that speed is only used for communication with the Raspberry Pi).

### Board boots but LEDs do not light up when connected to the Pi
This is expected — the firmware waits for commands from the Pi over UART. The LEDs will only light up once the Raspberry Pi sends a `CMD_SCROLL`, `CMD_STATIC`, or `CMD_FRAME` command. See the main ShipsAhoy documentation for running the Pi-side software.

---

## Quick Reference

| Task | Command |
|------|---------|
| Compile only | `arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker` |
| Upload to board | `arduino-cli upload -p COM3 --fqbn esp32:esp32:esp32s3 esp32_ticker` |
| Open serial monitor | `arduino-cli monitor -p COM3 -c baudrate=115200` |
| Compile + upload in one step | `arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker && arduino-cli upload -p COM3 --fqbn esp32:esp32:esp32s3 esp32_ticker` |

Replace `COM3` with your actual COM port number every time.
