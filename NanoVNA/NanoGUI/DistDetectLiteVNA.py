import serial
import struct
import numpy as np
import matplotlib.pyplot as plt
from scipy.fft import ifft
import time

# --- CONFIGURATION ---
COM_PORT = 'COM6'         
FREQ_START = 5.0e9        # 5.0 GHz
FREQ_STOP = 5.4e9         # 5.4 GHz
POINTS = 501              # Number of sweep points
NUM_CAL_SWEEPS = 10       
# ---------------------

def setup_vna(ser, start_hz, stop_hz, points):
    """Initializes the VNA parameters and enters USB Calibrated Mode"""
    # Send 8 null bytes to reset protocol parser
    ser.write(b'\x00' * 8)
    time.sleep(0.05)
    
    # Enter calibrated mode (REG_V2_RAW_SAMPLES_MODE = 0x03)
    ser.write(b'\x20\x26\x03')
    
    step_hz = int((stop_hz - start_hz) / (points - 1))
    start_hz = int(start_hz)
    
    # CMD_V2_WRITE_8 (0x23) - Push Start and Step Hz
    ser.write(struct.pack('<BBQ', 0x23, 0x00, start_hz))
    ser.write(struct.pack('<BBQ', 0x23, 0x10, step_hz))
    
    # CMD_V2_WRITE_2 (0x21) - Push Points and Values per freq
    ser.write(struct.pack('<BBH', 0x21, 0x20, points))
    ser.write(struct.pack('<BBH', 0x21, 0x22, 1))
    
    # Clear FIFO (CMD_V2_WRITE_1, REG_V2_VALUES_FIFO, 0x00)
    ser.write(b'\x20\x30\x00')
    time.sleep(0.1)

def get_calibrated_sweep(ser, points):
    """Requests and unpacks exactly one full sweep from the VNA."""
    # Request all points from FIFO
    ser.write(b'\x18\x30\x00')
    
    expected_bytes = points * 32
    data = b''
    
    # Bounded read to prevent infinite hanging
    start_time = time.time()
    while len(data) < expected_bytes:
        chunk = ser.read(expected_bytes - len(data))
        data += chunk
        if time.time() - start_time > 1.5:
            # Drop out if VNA stops responding
            return None
            
    # Unpack exact number of bytes into a complex array
    s21_array = np.zeros(points, dtype=complex)
    for i in range(points):
        chunk = data[i*32 : (i+1)*32]
        unpacked = struct.unpack('<iiiiiiH5sB', chunk)
        
        fwd_real, fwd_imag = unpacked[0], unpacked[1]
        rev_real, rev_imag = unpacked[4], unpacked[5]
        freq_index = unpacked[6]
        
        fwd = complex(fwd_real, fwd_imag)
        # Prevent division by zero and index out of bounds
        if fwd == 0 or freq_index >= points:
            continue
            
        rev = complex(rev_real, rev_imag)
        s21_array[freq_index] = rev / fwd
        
    return s21_array

# Main Stuff
print(f"Connecting to LiteVNA on {COM_PORT}...")
try:
    ser = serial.Serial(COM_PORT, 115200, timeout=0.1)
except Exception as e:
    print(f"Failed to connect: {e}")
    exit()

# Setup USB side of the VNA to match variables
setup_vna(ser, FREQ_START, FREQ_STOP, POINTS)

# Background Subtraction
print("\n[!] STAND CLEAR OF ANTENNAS [!]")
print("Acquiring background clutter profile in 3 seconds...")
time.sleep(3)

baseline_sweeps = []
print(f"Grabbing {NUM_CAL_SWEEPS} baseline sweeps...")

while len(baseline_sweeps) < NUM_CAL_SWEEPS:
    sweep = get_calibrated_sweep(ser, POINTS)
    if sweep is not None:
        baseline_sweeps.append(sweep)
    time.sleep(0.02)

# Average sweeps to create a stable complex array of the room + cross-talk
s21_baseline = np.mean(baseline_sweeps, axis=0)
print("Background acquired! Starting live radar.\n")

# Live Plot Setup
plt.ion()
fig, ax = plt.subplots(figsize=(10, 6))
line, = ax.plot([], [], color='red', linewidth=2)

ax.set_title('Live 5.2GHz Radar (EMA Smoothed + Clutter Removed)')
ax.set_xlabel('Distance (Meters)')
ax.set_ylabel('Target Reflection Magnitude')
ax.set_xlim(0, 10)
ax.set_ylim(0, 0.01)
ax.grid(True)

# Live Radar Loop
try:
    bandwidth = FREQ_STOP - FREQ_START
    time_step = 1.0 / bandwidth
    times = np.arange(POINTS) * time_step
    distances = (times * 3e8) / 2.0
    window = np.hanning(POINTS)
    
    # EMA filtering
    s21_smoothed = np.zeros(POINTS, dtype=complex)
    alpha = 0.25 # Smoothing factor: 1.0 no smoothing, 0.1 heavy smoothing

    while True:
        s21_live = get_calibrated_sweep(ser, POINTS)
        
        if s21_live is not None:
            # Subtract static room/cross-talk from the live feed
            s21_target_only = s21_live - s21_baseline
            
            # Blend new sweep with the previous sweeps to lower noise floor
            s21_smoothed = (alpha * s21_target_only) + ((1 - alpha) * s21_smoothed)
            
            # DSP: Window and IFFT on smoothed data
            time_domain = ifft(s21_smoothed * window)
            magnitude = np.abs(time_domain)
            
            # Update Live Plot
            line.set_data(distances, magnitude)
            
            # Dynamically autoscale the Y-axis
            max_mag = np.max(magnitude)
            if max_mag > ax.get_ylim()[1]:
                ax.set_ylim(0, max_mag * 1.2)
            elif max_mag < ax.get_ylim()[1] * 0.5 and ax.get_ylim()[1] > 0.01:
                ax.set_ylim(0, ax.get_ylim()[1] * 0.95)
                
            fig.canvas.draw()
            fig.canvas.flush_events()
            
        time.sleep(0.02)

except KeyboardInterrupt:
    print("\nStopping radar stream.")
finally:
    print("Restoring VNA to normal mode...")
    try:
        # CMD_V2_WRITE_1 (0x20), REG_V2_RAW_SAMPLES_MODE (0x26), Value (0x02 to Leave)
        ser.write(b'\x00' * 8) # Send nulls to clear any pending protocol states
        ser.write(b'\x20\x26\x02')
        time.sleep(0.1)
        ser.close()
    except Exception as e:
        print(f"Could not close port cleanly: {e}")
    plt.close()