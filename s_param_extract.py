import os
import numpy as np
import skrf as rf

def extract_batch_s11(directory, target_freqs_hz):
    print(f"\n{'Antenna Trace File':<35} | {'2.4 GHz (dB)':<12} | {'5.1 GHz (dB)':<12} | {'5.8 GHz (dB)':<12}")
    print("-" * 80)

    # Loop through all files in the directory
    for filename in sorted(os.listdir(directory)):
        if filename.endswith(".s1p") or filename.endswith(".s2p"):
            filepath = os.path.join(directory, filename)
            
            try:
                # skrf does RI, MA, or DB touchstone formats
                ntwk = rf.Network(filepath)
                
                # Extract frequency array and S11 magnitude in dB
                freqs = ntwk.f
                s11_mag_linear = np.abs(ntwk.s[:, 0, 0]) # [:, 0, 0] is the S11 parameter
                s11_db = 20 * np.log10(s11_mag_linear)
                
                results = []
                for target in target_freqs_hz:
                    # Find index of the closest frequency point
                    closest_idx = np.argmin(np.abs(freqs - target))
                    results.append(s11_db[closest_idx])
                
                # Print the formatted row
                print(f"{filename:<35} | {results[0]:>10.2f} | {results[1]:>10.2f} | {results[2]:>10.2f}")
                
            except Exception as e:
                print(f"{filename:<35} | Error: {e}")

if __name__ == "__main__":
    # Name of new directory
    data_dir = r"vna_gui/s1p_s2p_files"
    
    # Target frequencies
    targets = [2.4e9, 5.1e9, 5.8e9]
    
    # Ensure the directory exists before running
    if os.path.exists(data_dir):
        extract_batch_s11(data_dir, targets)
    else:
        print(f"Error: Could not find directory '{data_dir}'. Make sure you run this from the repo root.")