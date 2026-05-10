import os
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d

# =============================================================================
# Configuration
# =============================================================================
data_dir = '.'  # Current directory
export_dir = 'chamber_plots'
os.makedirs(export_dir, exist_ok=True)

target_freq_Hz = 5.23e9
Pt_dBm = 5
c = 299792458
ff_min_cm = 20
ff_max_cm = 150
patch_width = 0.0429
patch_height = 0.0484
patch_D = np.sqrt(patch_width**2 + patch_height**2)

distance_cm = np.arange(10, 160, 10)
rotation_deg = np.arange(0, 190, 10)

# =============================================================================
# Custom Touchstone Parser (S21 Only)
# =============================================================================
def read_s2p_S21(fname):
    freq_unit_scale = 1.0
    param_format = 'DB'
    freqs, s21_db = [], []
    try:
        with open(fname, 'r') as fid:
            for line in fid:
                line = line.strip()
                if not line or line.startswith('!'): continue
                if line.startswith('#'):
                    parts = line[1:].strip().split()
                    for p in parts:
                        p_upper = p.upper()
                        if p_upper in ['HZ', 'KHZ', 'MHZ', 'GHZ']:
                            if p_upper == 'HZ': freq_unit_scale = 1.0
                            elif p_upper == 'KHZ': freq_unit_scale = 1e3
                            elif p_upper == 'MHZ': freq_unit_scale = 1e6
                            elif p_upper == 'GHZ': freq_unit_scale = 1e9
                        elif p_upper in ['DB', 'MA', 'RI']:
                            param_format = p_upper
                    continue
                parts = [float(x) for x in line.split()]
                if len(parts) >= 9:
                    freqs.append(parts[0] * freq_unit_scale)
                    a, b = parts[3], parts[4]
                    if param_format == 'DB':
                        s21_db.append(a)
                    elif param_format == 'MA':
                        s21_db.append(20*np.log10(a) if a > 0 else -100)
                    elif param_format == 'RI':
                        s21_db.append(20*np.log10(np.sqrt(a**2 + b**2)) if (a!=0 or b!=0) else -100)
        return np.array(freqs), np.array(s21_db)
    except Exception as e:
        return None, None

# =============================================================================
# Load Data & Identify Frequency
# =============================================================================
freq = None
S21_dist_mat = []
valid_dists = []

for d in distance_cm:
    fname = os.path.join(data_dir, f"{d}.s2p")
    if os.path.exists(fname):
        f, s = read_s2p_S21(fname)
        if f is not None:
            if freq is None: freq = f
            S21_dist_mat.append(s)
            valid_dists.append(d)

S21_dist_mat = np.column_stack(S21_dist_mat)
valid_dists = np.array(valid_dists)

ff_mask = (valid_dists >= ff_min_cm) & (valid_dists <= ff_max_cm)
idx_f0 = np.argmin(np.abs(freq - target_freq_Hz))
f0 = freq[idx_f0]
lambda0 = c / f0

# =============================================================================
# Distance Analysis (Friis)
# =============================================================================
S21_f0 = S21_dist_mat[idx_f0, :]
Pr_dBm = S21_f0 + Pt_dBm
Pr_mW = 10**(Pr_dBm / 10)
inv_sP = 1 / np.sqrt(Pr_mW)

r_cm = valid_dists
r_ff = r_cm[ff_mask]
inv_sP_ff = inv_sP[ff_mask]

# Linear fit
p_lin = np.polyfit(r_ff, inv_sP_ff, 1)
m_fit, b_fit = p_lin[0], p_lin[1]
x_int = -b_fit / m_fit
epsilon_cm = -x_int
r1_cm = r_cm + epsilon_cm

# Log-Log fit
p_log = np.polyfit(np.log10(r_ff), np.log10(Pr_mW[ff_mask]), 1)
slope = p_log[0]

# Gain Calculation
G_dB_raw = 0.5 * (S21_f0 + 20*np.log10(4*np.pi*(r_cm/100)/lambda0))
G_dB_mean = np.mean(G_dB_raw[ff_mask])

# =============================================================================
# Rotation Pattern Analysis
# =============================================================================
S21_rot_dB = []
valid_rot = []
for a in rotation_deg:
    fname = os.path.join(data_dir, "30Q.s2p" if a == 0 else f"30Q{a}.s2p")
    if os.path.exists(fname):
        _, s = read_s2p_S21(fname)
        if s is not None:
            S21_rot_dB.append(s[idx_f0])
            valid_rot.append(a)

S21_rot_dB = np.array(S21_rot_dB)
valid_rot = np.array(valid_rot)

Pr_rot_lin = 10**(S21_rot_dB / 10)
Pr_norm = Pr_rot_lin / np.max(Pr_rot_lin)
Pr_norm_dB = 10*np.log10(Pr_norm)

# Mirror Pattern
theta_full_deg = np.concatenate([-np.flip(valid_rot[1:]), valid_rot])
Pr_dB_full = np.concatenate([np.flip(Pr_norm_dB[1:]), Pr_norm_dB])
Pr_norm_full = np.concatenate([np.flip(Pr_norm[1:]), Pr_norm])
theta_full_rad = np.deg2rad(theta_full_deg)

# Interpolate for exact HPBW
theta_fine_rad = np.linspace(-np.pi/2, np.pi/2, 4001)
f_interp = interp1d(theta_full_rad, Pr_dB_full, kind='linear')
Pr_dB_fine = f_interp(theta_fine_rad)

half = len(theta_fine_rad)//2
iL = np.argmin(np.abs(Pr_dB_fine[:half] - (-3)))
iR = np.argmin(np.abs(Pr_dB_fine[half:] - (-3))) + half
HPBW_rad = theta_fine_rad[iR] - theta_fine_rad[iL]
HPBW_deg = np.rad2deg(HPBW_rad)

# Directivity Metrics
n_est = np.log(0.5) / np.log(np.cos(HPBW_rad/2))
D_dBi_n = 10*np.log10(2*(n_est + 1))

theta_b_rad = np.deg2rad(valid_rot)
P_norm = np.trapz(Pr_norm * np.sin(theta_b_rad), theta_b_rad)
D_axi_dBi = 10*np.log10(2 / P_norm)

front_mask = np.abs(theta_full_deg) <= 90
back_mask = np.abs(theta_full_deg) >= 90
FB_dB = np.max(Pr_dB_full[front_mask]) - np.max(Pr_dB_full[back_mask])

back_hemi = np.abs(theta_full_deg) > 90
BLL_dB = np.max(Pr_dB_full[back_hemi])
BLL_theta = theta_full_deg[back_hemi][np.argmax(Pr_dB_full[back_hemi])]

eta_axi = 10**((G_dB_mean - D_axi_dBi)/10)

# Flip Delta
_, s30 = read_s2p_S21(os.path.join(data_dir, "30.s2p"))
_, s30Q = read_s2p_S21(os.path.join(data_dir, "30Q.s2p"))
dS21_f0 = s30[idx_f0] - s30Q[idx_f0]

# =============================================================================
# Print Condensed Summary
# =============================================================================
print("\n========================================================")
print("               CONDENSED RESULTS SUMMARY")
print("========================================================")
print(f"Target Freq (f0)         : {f0/1e9:.3f} GHz")
print(f"Dist Fit Range           : {ff_min_cm} to {ff_max_cm} cm")
print(f"Amp. Center (epsilon)    : {epsilon_cm:.2f} cm")
print(f"Dist. Log-Log Slope      : {slope:.2f}")
print(f"Mean Raw Gain            : {G_dB_mean:.2f} dBi")
print("--------------------------------------------------------")
print(f"HPBW (Measured cut)      : {HPBW_deg:.1f} deg")
print(f"Directivity (Integration): {D_axi_dBi:.2f} dBi")
print(f"Directivity (cos^n fit)  : {D_dBi_n:.2f} dBi")
print(f"Front-to-Back Ratio      : {FB_dB:.1f} dB")
print(f"Back-Lobe Level          : {BLL_dB:.1f} dB (at {BLL_theta} deg)")
print(f"Estimated Efficiency     : {eta_axi*100:.1f} %")
print(f"Flip Delta (30 vs 30Q)   : {dS21_f0:+.2f} dB")
print("========================================================\n")

# =============================================================================
# Export High-Quality Plots
# =============================================================================
print("Generating and saving plots...")

# 1. Pr vs r1 (Amplitude Center Corrected with Ideal Slope)
plt.figure(figsize=(8, 6))
plt.loglog(r1_cm, Pr_mW, 'bo-', linewidth=1.5, label='Measured (shifted)')
idx_ref = np.where(ff_mask)[0][0]
Pr_ideal = Pr_mW[idx_ref] * (r1_cm[idx_ref] / r1_cm)**2
plt.loglog(r1_cm, Pr_ideal, 'k--', linewidth=1.5, label='Ideal -2 Slope (1/r^2)')
plt.grid(True, which="both", ls="--")
plt.xlabel('r_1 = r + epsilon (cm)')
plt.ylabel('P_r (mW)')
plt.title('P_r vs r_1 (Amplitude Center Corrected)')
plt.legend()
plt.savefig(os.path.join(export_dir, 'Pr_vs_r1_Amplitude_Center.png'), dpi=300, bbox_inches='tight')

# 2. Rectangular Pattern
plt.figure(figsize=(8, 6))
plt.plot(theta_full_deg, Pr_dB_full, 'b-o', linewidth=1.5, label='Measured (mirrored)')
plt.axhline(-3, color='r', linestyle='--', label='-3 dB')
plt.axvline(HPBW_deg/2, color='m', linestyle=':', label=f'+HPBW/2 = {HPBW_deg/2:.0f} deg')
plt.axvline(-HPBW_deg/2, color='m', linestyle=':', label=f'-HPBW/2 = {-HPBW_deg/2:.0f} deg')
plt.plot(BLL_theta, BLL_dB, 'r^', markersize=10, label=f'Back lobe = {BLL_dB:.1f} dB @ {BLL_theta} deg')
plt.xlim([-180, 180])
plt.ylim([np.floor(np.min(Pr_dB_full)/10)*10, 0])
plt.grid(True)
plt.xlabel(r'Rotation angle $\theta$ (deg)')
plt.ylabel('Normalized $P_r$ (dB)')
plt.title(f'Rectangular pattern @ {f0/1e9:.2f} GHz')
plt.legend(loc='lower center', bbox_to_anchor=(0.5, -0.25), ncol=2)
plt.savefig(os.path.join(export_dir, 'Pattern_Rectangular.png'), dpi=300, bbox_inches='tight')

# 3. Polar Pattern
fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={'projection': 'polar'})
ax.plot(theta_full_rad, Pr_dB_full, 'b-', linewidth=2, label='Pattern')
ax.plot(theta_full_rad, np.full_like(theta_full_rad, -3), 'r--', label='-3 dB')
ax.plot(theta_full_rad, np.full_like(theta_full_rad, -10), 'm--', label='-10 dB')
ax.set_ylim([np.floor(np.min(Pr_dB_full)/10)*10, 0])
ax.set_title(f'Normalized power (dB) @ {f0/1e9:.2f} GHz\n', va='bottom')
ax.legend(loc='lower left', bbox_to_anchor=(1.05, 0))
plt.savefig(os.path.join(export_dir, 'Pattern_Polar.png'), dpi=300, bbox_inches='tight')

print(f"All plots successfully saved to the '{export_dir}' folder!")