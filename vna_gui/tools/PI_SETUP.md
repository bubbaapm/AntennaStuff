# Raspberry Pi Overnight Characterization Setup

This guide is for running unattended LibreVNA characterization tests on a
Raspberry Pi 5 so the lab Windows PCs can sign out or reboot without killing
the run. It uses the official LibreVNA-GUI Raspberry Pi 5 release.

## Why LibreVNA-GUI Is Still Needed

The LibreVNA hardware does not expose a TCP SCPI server by itself. It is a USB
device. The LibreVNA-GUI application talks to the hardware over USB and provides
the SCPI server on TCP port `19542`.

The measurement chain is:

```text
LibreVNA hardware -> USB -> Raspberry Pi -> LibreVNA-GUI -> SCPI localhost:19542 -> characterization logger
```

So the Pi still needs LibreVNA-GUI running, even if you never use the GUI window
after setup.

## Recommended Hardware

- Raspberry Pi 5.
- Stable USB-C power supply for the Pi.
- Wired Ethernet if available.
- LibreVNA connected directly or through a reliable powered USB hub.
- Optional: small monitor/keyboard for first setup; VNC is fine afterward.

## Quick Setup

From `vna_gui` on the Pi, run:

```bash
bash tools/setup_pi.sh
```

The script performs the dependency install, installs the LibreVNA udev rule,
downloads the official Raspberry Pi 5 LibreVNA-GUI release into
`vna_gui/tools/librevna`, deletes the ZIP after extraction, makes
`LibreVNA-GUI` executable, creates `vna_gui/.venv`, and installs the Python
requirements.

After setup, stay in `vna_gui` for the characterization commands. For a guided
terminal workflow, run:

```bash
source .venv/bin/activate
python tools/characterization_prompt.py
```

The remaining sections show the same process manually and include extra
troubleshooting notes.

## Install OS And Dependencies

Use a 64-bit Raspberry Pi OS Desktop or Ubuntu Desktop image.

```bash
sudo apt update
sudo apt install qt6-base-dev libqt6svg6 python3 python3-venv python3-pip git tmux unzip wget
```

Install the LibreVNA udev rule so the Pi user can access the USB device:

```bash
wget https://raw.githubusercontent.com/jankae/LibreVNA/master/Software/PC_Application/51-vna.rules
sudo cp 51-vna.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If the VNA still cannot be opened, reboot the Pi.

## Install LibreVNA-GUI

Download the official Raspberry Pi 5 LibreVNA-GUI v1.6.5 release:

```bash
mkdir -p ~/librevna
cd ~/librevna
wget https://github.com/jankae/LibreVNA/releases/download/v1.6.5/LibreVNA-GUI-RPi5-v1.6.5.zip
unzip LibreVNA-GUI-RPi5-v1.6.5.zip
```

You do not need to remember the final path during normal use. The setup script
uses `vna_gui/tools/librevna`; the characterization logger searches that folder
plus common locations such as `~/librevna` and can start LibreVNA-GUI
automatically.

For a one-time manual test, find the unpacked GUI folder:

```bash
find ~/librevna -maxdepth 3 -type f -name LibreVNA-GUI -print
```

Start the GUI once from the folder containing `LibreVNA-GUI`:

```bash
cd /path/from/find/command
chmod +x ./LibreVNA-GUI
./LibreVNA-GUI
```

Confirm that LibreVNA-GUI sees the USB device and that its SCPI server is
enabled on port `19542`. After this first manual test, close LibreVNA-GUI; the
logger can start it automatically.

## Install The Characterization Tools

Navigate to the AntennaStuff repo folder (or wherever you placed it):

```bash
cd ~/AntennaStuff
```

From `vna_gui`:

```bash
cd ~/AntennaStuff/vna_gui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For command-line overnight runs, the logger only needs the Python package
dependencies. The PyQt GUI tool is optional on the Pi.

## First Smoke Test

The logger will start LibreVNA-GUI if the SCPI server is not already running:

```bash
cd ~/AntennaStuff/vna_gui
source .venv/bin/activate
python -m vna_tester.tools.characterize \
  --dut "Pi smoke test load" \
  --kind load \
  --start 2.3e9 \
  --stop 2.6e9 \
  --points 501 \
  --ifbw 1000 \
  --averaging 4 \
  --interval 60 \
  --count 3 \
  --out characterization_runs/pi_smoke_test
```

After it finishes, analyze it:

```bash
python -m vna_tester.tools.analyze_characterization characterization_runs/pi_smoke_test
```

## Overnight Run With tmux

Use `tmux` so the run survives SSH disconnects:

```bash
tmux new -s vna
cd ~/AntennaStuff/vna_gui
source .venv/bin/activate
python -m vna_tester.tools.characterize \
  --dut "Overnight antenna" \
  --kind antenna \
  --start 2.3e9 \
  --stop 2.6e9 \
  --points 501 \
  --ifbw 1000 \
  --averaging 4 \
  --interval 300 \
  --count 96 \
  --out characterization_runs/overnight_antenna
```

Detach from tmux with `Ctrl+B`, then `D`.

Reconnect later:

```bash
tmux attach -t vna
```

## Practical Overnight Checklist

- Disable sleep/suspend and screen blanking on the Pi.
- Use wired Ethernet if possible.
- Confirm the Pi clock is correct.
- Do a 3-sweep smoke test before leaving.
- Leave LibreVNA-GUI in `vna_gui/tools/librevna` or `~/librevna` so the logger
  can find and start it automatically. If you put it elsewhere, pass
  `--librevna-gui /path/to/LibreVNA-GUI`.
- Do not leave the normal custom VNA GUI connected at the same time. LibreVNA's
  SCPI server accepts only one connection.
- Make sure the sweep grid matches the calibration grid when possible.
- Record the calibration file/path in the characterization tool notes.

## Calibration Workflow

LibreVNA calibration state is held by LibreVNA-GUI, not permanently by the
hardware. If the VNA/Pi loses power, load a `.cal` file before the overnight
run.

Recommended workflow:

1. Calibrate on the Windows PC or Pi.
2. Save the calibration as a `.cal` file.
3. Copy the `.cal` file to:

```text
~/AntennaStuff/vna_gui/cals/
```

4. Run the characterization with:

```bash
--calibration latest --use-cal-sweep
```

`latest` loads the newest `.cal` file found in common calibration folders.
`--use-cal-sweep` uses the sweep grid stored in the loaded calibration/active
VNA state, so you do not have to retype start/stop/points.

Example overnight antenna run using the newest copied calibration:

```bash
tmux new -s vna
cd ~/AntennaStuff/vna_gui
source .venv/bin/activate
python -m vna_tester.tools.characterize \
  --calibration latest \
  --use-cal-sweep \
  --dut "Overnight antenna" \
  --kind antenna \
  --ifbw 1000 \
  --averaging 4 \
  --interval 300 \
  --count 96 \
  --out characterization_runs/overnight_antenna
```

Useful Pi setup checks:

```bash
timedatectl
sudo raspi-config
```

In `raspi-config`, enable VNC if you want remote desktop access. If using
Raspberry Pi OS Desktop, also disable screen blanking in the desktop power or
display settings.

## If LibreVNA-GUI Needs A Display

The simplest path is Pi OS Desktop or Ubuntu Desktop with VNC. Start
LibreVNA-GUI in that desktop session, then run the characterization logger from
SSH or a terminal.

More headless setups such as `xvfb-run` may work, but they are more fragile
with Qt/OpenGL. Use the desktop/VNC path first unless you have time to debug.
