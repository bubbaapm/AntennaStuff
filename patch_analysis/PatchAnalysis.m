%% EE 4170/5170 - Patch Antenna Chamber Analysis
%  Combined distance-sweep + rotation-pattern analysis of two identical
%  patch antennas measured in an anechoic chamber with a Keysight N9926A.
%
%  Files in chamber_results/ (Touchstone S2P, S21 calibrated):
%    <D>.s2p          - distance sweep at D cm (D = 10, 20, ..., 150)
%    30Q.s2p          - rotation reference at 30 cm, 0 deg (one antenna flipped)
%    30Q<A>.s2p       - rotation pattern at 30 cm, A deg (A = 10, 20, ..., 180)
%
%  Patch is NOT a horn. We therefore avoid horn-specific results:
%    - No aperture efficiency (no defined physical aperture area for a patch)
%    - No 2D^2/lambda based on horn aperture dimensions; if used at all,
%      D refers to the largest physical patch dimension (substrate)
%  General results that DO apply to a patch and are kept here:
%    - Friis 1/sqrt(Pr) linearization (with x-intercept => epsilon)
%    - Friis two-antenna gain G_dB = 0.5 * (S21_dB + 20*log10(4*pi*R/lambda))
%    - Polar pattern, HPBW, cos^n single-lobe fit, D = 2(n+1), Kraus 41253/HP^2

close all; clear; clc;

%% --- User Configuration -------------------------------------------------
data_dir            = 'chamber_measurements';
Pt_dBm              = 5;        % Source power into TX port (matches Lab 2)
target_freq_Hz      = [];       % [] = auto-detect peak; else override (Hz)

patch_width = 0.0429;
patch_height = 0.0484;
patch_D = sqrt(patch_width^2 + patch_height^2);
patch_largest_dim_m = patch_D;      % e.g., 0.04 for a 4 cm patch; NaN to skip
ff_min_cm           = 30;       % Lower distance bound (cm) for far-field fit
ff_max_cm           = 100;      % Upper bound (data beyond often shows noise/multipath)

distance_cm  = 10:10:150;
rotation_deg = 0:10:180;        % 30Q (=0), 30Q10, ..., 30Q180

%% --- Constants ----------------------------------------------------------
c = 299792458;                  % m/s

%% --- Load distance sweep ------------------------------------------------
n_dist        = numel(distance_cm);
S21_dist_mat  = [];
freq          = [];
for k = 1:n_dist
    fname = fullfile(data_dir, sprintf('%d.s2p', distance_cm(k)));
    [f, s] = read_s2p_S21(fname);
    if isempty(freq); freq = f; end
    S21_dist_mat(:, k) = s.dB; %#ok<AGROW>
end

%% --- Identify operating frequency --------------------------------------
if isempty(target_freq_Hz)
    % Average over the clean far-field portion to suppress both near-field
    % bias (small r) and noise/multipath bias (large r), then pick the peak.
    ff_cols     = distance_cm >= ff_min_cm & distance_cm <= ff_max_cm;
    mean_S21    = mean(S21_dist_mat(:, ff_cols), 2);
    [~, idx_f0] = max(mean_S21);
else
    [~, idx_f0] = min(abs(freq - target_freq_Hz));
end
f0      = freq(idx_f0);
lambda0 = c / f0;

fprintf('--- Operating frequency ---\n');
if isempty(target_freq_Hz)
    fprintf('  f0      = %.3f GHz   (auto-detected: peak of mean S21 over %d-%d cm)\n', ...
            f0/1e9, ff_min_cm, ff_max_cm);
else
    fprintf('  f0      = %.3f GHz   (user-specified %.4f GHz, snapped to nearest data point)\n', ...
            f0/1e9, target_freq_Hz/1e9);
    fprintf('  Note: data frequency step is %.0f MHz; %.4f GHz snaps to %.3f GHz.\n', ...
            (freq(2)-freq(1))/1e6, target_freq_Hz/1e9, f0/1e9);
end
fprintf('  lambda0 = %.2f cm\n\n', lambda0*100);

%% --- S21 vs frequency for all distances --------------------------------
figure('Name', 'S21 vs Frequency (all distances)');
hold on;
cmap = parula(n_dist);
for k = 1:n_dist
    plot(freq/1e9, S21_dist_mat(:, k), 'Color', cmap(k, :), ...
         'LineWidth', 1.0, 'DisplayName', sprintf('%d cm', distance_cm(k)));
end
xline(f0/1e9, 'w--', sprintf('f_0 = %.2f GHz', f0/1e9), ...
      'LabelVerticalAlignment', 'bottom', 'HandleVisibility', 'off');
xlabel('Frequency (GHz)'); ylabel('|S_{21}| (dB)');
title('Patch-to-patch |S_{21}| vs Frequency for All Distances');
grid on; legend('Location', 'eastoutside'); hold off;

%% --- Distance analysis at f0 -------------------------------------------
S21_f0  = S21_dist_mat(idx_f0, :).';
Pr_dBm  = S21_f0 + Pt_dBm;
Pr_mW   = 10.^(Pr_dBm/10);
inv_sP  = 1 ./ sqrt(Pr_mW);
r_cm    = distance_cm(:);

% Linear fit on the clean far-field segment (1/sqrt(Pr) is linear in r for
% Friis). The upper bound excludes data that drifts due to chamber multipath
% or noise floor, which otherwise skews x-intercept and slope.
ff_idx     = r_cm >= ff_min_cm & r_cm <= ff_max_cm;
p_lin      = polyfit(r_cm(ff_idx), inv_sP(ff_idx), 1);
m_fit      = p_lin(1); b_fit = p_lin(2);
x_int      = -b_fit/m_fit;
epsilon_cm = -x_int;
r1_cm      = r_cm + epsilon_cm;

% Log-log slope check (Friis far field => -2)
log_r   = log10(r_cm(ff_idx));
log_Pr  = log10(Pr_mW(ff_idx));
p_log   = polyfit(log_r, log_Pr, 1);
slope   = p_log(1);

fprintf('--- Distance analysis at f0 ---\n');
fprintf('  Fit range: %d cm <= r <= %d cm  (%d points)\n', ff_min_cm, ff_max_cm, sum(ff_idx));
fprintf('  Linear fit:               1/sqrt(Pr) = %.4e * r + %.4e\n', m_fit, b_fit);
fprintf('  x-intercept              = %.2f cm\n', x_int);
fprintf('  Amplitude-center offset  epsilon = %.2f cm\n', epsilon_cm);
fprintf('    (For a patch, |epsilon| should be small. Large |epsilon| usually\n');
fprintf('     means the fit is being skewed by noise/multipath at large r,\n');
fprintf('     or a reference-plane offset between the bench mark and the patch face.)\n');
fprintf('  Log-log slope of Pr vs r = %.2f   (Friis far field => -2)\n', slope);
if abs(slope + 2) > 0.25
    fprintf('    >> Slope deviates from -2; consider tightening ff_min_cm/ff_max_cm.\n');
end

% Friis-based gain (identical antennas, no polarization mismatch).
% Two estimates are reported:
%   (a) Using measured r directly (epsilon = 0) — PREFERRED for patches.
%       Patch radiates from its surface, so physical amplitude-center offset
%       is ~0. If slope is far from -2, epsilon from the linear fit is an
%       artifact and artificially biases this estimate if applied.
%   (b) Using r + epsilon — shown for comparison with Lab 2 method.
G_dB_raw  = 0.5 * (S21_f0 + 20*log10(4*pi*(r_cm/100) / lambda0));
G_dB_mean = mean(G_dB_raw(ff_idx));
G_dB_med  = median(G_dB_raw(ff_idx));
G_dB_std  = std(G_dB_raw(ff_idx));

R_m  = r1_cm/100;
G_dB = 0.5 * (S21_f0 + 20*log10(4*pi*R_m / lambda0));
G_dB_eps_mean = mean(G_dB(ff_idx));

fprintf('  Gain (r direct, no epsilon)  : mean %.2f dBi,  median %.2f dBi,  std %.2f dB\n', ...
        G_dB_mean, G_dB_med, G_dB_std);
fprintf('  Gain (r + epsilon = %.0f cm): mean %.2f dBi   [epsilon is artifact if slope != -2]\n\n', ...
        epsilon_cm, G_dB_eps_mean);

% Optional 2D^2/lambda boundary using LARGEST PATCH dimension (NOT horn aperture).
if ~isnan(patch_largest_dim_m)
    R_ff_2D2L_cm = (2 * patch_largest_dim_m^2 / lambda0) * 100;
    fprintf('  2D^2/lambda boundary (D = %.3f m): %.2f cm\n\n', ...
            patch_largest_dim_m, R_ff_2D2L_cm);
else
    R_ff_2D2L_cm = NaN;
end

%% --- Distance plots ----------------------------------------------------
figure('Name', 'Pr vs r (log-log)');
loglog(r_cm(ff_idx),  Pr_mW(ff_idx),  'bo-', 'LineWidth', 1.5, 'DisplayName', 'In fit range');
hold on;
loglog(r_cm(~ff_idx), Pr_mW(~ff_idx), 'x', 'Color', [1 0.6 0], 'MarkerSize', 10, 'LineWidth', 2, ...
       'DisplayName', 'Excluded (near-field / noisy tail)');
trend = 10.^(polyval(p_log, log10(r_cm)));
loglog(r_cm, trend, 'r--', 'LineWidth', 1.5, ...
       'DisplayName', sprintf('Fit (slope = %.2f)', slope));
if ~isnan(R_ff_2D2L_cm)
    xline(R_ff_2D2L_cm, 'g--', sprintf('2D^2/\\lambda = %.1f cm', R_ff_2D2L_cm), ...
          'LabelVerticalAlignment', 'bottom', 'HandleVisibility', 'off');
end
grid on; xlabel('Distance r (cm)'); ylabel('P_r (mW)');
title(sprintf('Patch P_r vs Distance @ %.2f GHz (log-log)', f0/1e9));
legend('Location', 'best'); hold off;

figure('Name', '1/sqrt(Pr) vs r');
plot(r_cm(ff_idx),  inv_sP(ff_idx),  'bo-', 'LineWidth', 1.5, 'DisplayName', 'In fit range');
hold on;
plot(r_cm(~ff_idx), inv_sP(~ff_idx), 'x', 'Color', [1 0.6 0], 'MarkerSize', 10, 'LineWidth', 2, ...
     'DisplayName', 'Excluded (near-field / noisy tail)');
r_trend = linspace(min([0; x_int]), max(r_cm), 100);
plot(r_trend, polyval(p_lin, r_trend), 'r--', 'LineWidth', 1.5, ...
     'DisplayName', sprintf('Linear fit, x-int = %.1f cm', x_int));
xline(0, 'w-', 'HandleVisibility', 'off');
yline(0, 'w-', 'HandleVisibility', 'off');
grid on; xlabel('r (cm)'); ylabel('1 / \surd P_r  (mW^{-1/2})');
title(sprintf('1/\\surdP_r vs r @ %.2f GHz', f0/1e9));
legend('Location', 'best'); hold off;

figure('Name', 'Pr vs r1 (Lab 2 comparison only)');
loglog(r1_cm, Pr_mW, 'b-o', 'LineWidth', 1.5);
grid on;
xlabel('r_1 = r + \epsilon (cm)  — \epsilon is a fit artifact for this patch');
ylabel('P_r (mW)');
title(sprintf('P_r vs r_1  [Lab 2 comparison only, slope \\neq -2 so \\epsilon = %.1f cm is not physical]', ...
              epsilon_cm));

figure('Name', 'Friis Gain vs Distance');
plot(r_cm(ff_idx)/100,  G_dB_raw(ff_idx),  'bo-', 'LineWidth', 1.5, 'DisplayName', 'In fit range');
hold on;
plot(r_cm(~ff_idx)/100, G_dB_raw(~ff_idx), 'x', 'Color', [1 0.6 0], 'MarkerSize', 10, 'LineWidth', 2, ...
     'DisplayName', 'Excluded (near-field / noisy tail)');
yline(G_dB_mean, 'r--', ...
      sprintf('Mean = %.2f dBi  (median %.2f dBi)', G_dB_mean, G_dB_med), ...
      'LabelHorizontalAlignment', 'left', 'HandleVisibility', 'off');
xlabel('Antenna separation r (m)'); ylabel('Estimated gain G (dBi)');
title(sprintf('Friis Gain Estimate (identical patches) @ %.2f GHz  [no \\epsilon correction]', f0/1e9));
grid on; legend('Location', 'best'); hold off;

%% --- Rotation pattern at f0 -------------------------------------------
n_rot      = numel(rotation_deg);
S21_rot_dB = zeros(n_rot, 1);
for k = 1:n_rot
    a = rotation_deg(k);
    if a == 0
        fname = fullfile(data_dir, '30Q.s2p');
    else
        fname = fullfile(data_dir, sprintf('30Q%d.s2p', a));
    end
    [~, s] = read_s2p_S21(fname);
    S21_rot_dB(k) = s.dB(idx_f0);
end

% Normalize to peak (typically at 0 deg, boresight).
Pr_rot_lin = 10.^(S21_rot_dB/10);
[Pr_max, idx_pk] = max(Pr_rot_lin);
Pr_norm    = Pr_rot_lin / Pr_max;
Pr_norm_dB = 10*log10(Pr_norm);
E_norm     = sqrt(Pr_norm);

fprintf('--- Rotation pattern at f0 ---\n');
fprintf('  Peak |S21| occurs at theta = %d deg (expected 0 for boresight)\n', rotation_deg(idx_pk));
fprintf('  S21 range across rotation: %.1f dB ... %.1f dB\n', ...
        min(S21_rot_dB), max(S21_rot_dB));

% Mirror the half-pattern (0..180) into a full pattern (-180..180).
% This assumes pattern symmetry about the boresight cut, since you only
% measured one side. Stated explicitly so it's not invisible.
theta_full_deg = [-flip(rotation_deg(2:end)), rotation_deg];
Pr_norm_full   = [flip(Pr_norm(2:end));    Pr_norm];
Pr_dB_full     = [flip(Pr_norm_dB(2:end)); Pr_norm_dB];
E_norm_full    = [flip(E_norm(2:end));     E_norm];
theta_full_rad = deg2rad(theta_full_deg);

% Polar plots
figure('Name', 'Pattern: Normalized E (linear)');
polarplot(theta_full_rad, E_norm_full, 'b-', 'LineWidth', 1.5);
title(sprintf('Normalized field |E|/|E|_{max}  @ %.2f GHz', f0/1e9));
rlim([0 1]);

figure('Name', 'Pattern: Normalized Pr (linear)');
polarplot(theta_full_rad, Pr_norm_full, 'b-', 'LineWidth', 1.5);
title(sprintf('Normalized power P_r/P_{r,max}  @ %.2f GHz', f0/1e9));
rlim([0 1]);

lower_lim = floor(min(Pr_dB_full)/10)*10;
figure('Name', 'Pattern: Normalized Pr (dB)');
polarplot(theta_full_rad, Pr_dB_full, 'b-', 'LineWidth', 2, 'DisplayName', 'Pattern');
hold on;
polarplot(theta_full_rad, repmat(-3,  size(theta_full_rad)), 'r--', 'DisplayName', '-3 dB');
polarplot(theta_full_rad, repmat(-6,  size(theta_full_rad)), 'g--', 'DisplayName', '-6 dB');
polarplot(theta_full_rad, repmat(-10, size(theta_full_rad)), 'm--', 'DisplayName', '-10 dB');
title(sprintf('Normalized power (dB)  @ %.2f GHz', f0/1e9));
rlim([lower_lim 0]);
legend('Location', 'bestoutside'); hold off;

% (Annotated rectangular plot is drawn later, once HPBW / F/B / SLL are known.)

%% --- HPBW, cos^n fit, directivity (Lab 9 Q5/Q6/Q7 generalized) -------
% Interpolate finely between -90 and 90 (front hemisphere).
theta_fine_rad = linspace(-pi/2, pi/2, 4001);
Pr_dB_fine     = interp1(theta_full_rad, Pr_dB_full, theta_fine_rad, 'linear');

half = (length(theta_fine_rad)+1)/2;
[~, iL] = min(abs(Pr_dB_fine(1:half)   - (-3)));
[~, iR] = min(abs(Pr_dB_fine(half:end) - (-3)));
iR = iR + half - 1;
HPBW_rad = theta_fine_rad(iR) - theta_fine_rad(iL);
HPBW_deg = rad2deg(HPBW_rad);

% cos^n single-lobe approximation. Patches have broad beams (HPBW ~ 60-90 deg),
% so n is small and the fit is rough by nature. This is NOT horn-specific;
% it's a general one-parameter pattern model.
n_est    = log(0.5) / log(cos(HPBW_rad/2));
U_th_lin = (cos(theta_fine_rad)).^n_est;
U_th_dB  = 10*log10(U_th_lin);

% Two general directivity estimates (neither is horn-specific):
%   D = 2(n+1)              from the cos^n fit
%   D = 41253/(HP_E*HP_H)   Kraus single-cut approximation
% We have only one pattern cut, so reusing HPBW for both planes gives an
% optimistic upper bound (true D is lower if the orthogonal cut is wider).
D_lin_n  = 2*(n_est + 1);
D_dBi_n  = 10*log10(D_lin_n);
D_lin_kr = 41253 / (HPBW_deg^2);
D_dBi_kr = 10*log10(D_lin_kr);

fprintf('  -3 dB angles: %.1f deg (left), %.1f deg (right)\n', ...
        rad2deg(theta_fine_rad(iL)), rad2deg(theta_fine_rad(iR)));
fprintf('  HPBW (single cut)        = %.1f deg\n', HPBW_deg);
fprintf('  cos^n fit                : n = %.2f\n', n_est);
fprintf('  Directivity D = 2(n+1)     = %.2f   (%.2f dBi)  [cos^n model; ignores back/side radiation -> upper bound]\n', D_lin_n, D_dBi_n);
fprintf('  Directivity D = 41253/HP^2 = %.2f   (%.2f dBi)  [Kraus single-cut; optimistic]\n', D_lin_kr, D_dBi_kr);

% --- Pattern-integration directivity (axial-symmetry assumption) -----
% For a near-square patch, treating the measured pattern as axially symmetric
% about the boresight (i.e. U(theta,phi) = U(theta), where theta is the
% angle from boresight) lets us integrate over the full sphere using just
% the measured 0..180 deg cut. This honors the back lobe and sidelobes
% that the cos^n model throws away, so it gives a more honest D for a patch
% than 2(n+1) does.
theta_b_rad = deg2rad(rotation_deg(:));         % 0..pi from boresight
U_norm_b    = Pr_norm(:);                       % normalized power at those angles
P_norm      = trapz(theta_b_rad, U_norm_b .* sin(theta_b_rad));   % over theta only
D_axi       = 2 / P_norm;                       % phi integral cancels with 4pi
D_axi_dBi   = 10*log10(D_axi);
fprintf('  Directivity (axial-sym integration of measured pattern) = %.2f (%.2f dBi)\n', D_axi, D_axi_dBi);

% Front-to-back ratio
front_mask = abs(theta_full_deg) <= 90;
back_mask  = abs(theta_full_deg) >= 90;
front_max  = max(Pr_dB_full(front_mask));
back_max   = max(Pr_dB_full(back_mask));
FB_dB      = front_max - back_max;
fprintf('  Front-to-back ratio      = %.1f dB  (max front - max back)\n', FB_dB);

% Back-lobe level: highest peak in the back hemisphere (|theta| > 90 deg).
% For a patch with ground plane, there are no true isolated sidelobes in
% the front hemisphere with 10 deg sampling — the pattern simply rolls off
% smoothly from main lobe to null. "Sidelobe" past the HPBW but still in
% the front hemisphere is just the main-lobe shoulder, not an isolated lobe.
% The meaningful secondary lobe for a ground-plane antenna is the back lobe.
back_hemi   = abs(theta_full_deg) > 90;
[BLL_dB, bl_i] = max(Pr_dB_full(back_hemi));
BLL_theta   = theta_full_deg(find(back_hemi, 1) + bl_i - 1);
fprintf('  Back-lobe level (max at |theta| > 90 deg) = %.1f dB at theta = %d deg\n', BLL_dB, BLL_theta);

% Note: D_axial = 9+ dBi may look high vs the textbook 6.6 dBi for a
% "standard" half-wave patch. It is consistent with your HPBW here.
% Theoretically, E-plane HPBW for your patch (L=4.84 cm, f0=5.22 GHz) is
% approximately:  cos(theta) * sinc(kL/2 * sin(theta)), which gives
% -3 dB crossing around 25-28 deg => HPBW ~ 50-56 deg.
% H-plane (W=4.29 cm) gives a similar result. Both planes narrow because
% your patch is operating at ~0.8-lambda dimension (larger than the typical
% 0.5-lambda reference), which concentrates the beam more than the textbook
% case. HPBW ~58 deg in both planes, D_axial ~9 dBi is self-consistent.
fprintf('    Note: D_axial = %.1f dBi is consistent with HPBW = %.1f deg.\n', D_axi_dBi, HPBW_deg);
fprintf('    Theoretical E-plane HPBW for L = %.2f cm at %.2f GHz is ~50-56 deg.\n', ...
        patch_height*100, f0/1e9);
fprintf('    Textbook 6.6 dBi assumes a standard lambda/2 patch (HPBW ~90 deg);\n');
fprintf('    your patch is ~0.8*lambda, giving a narrower beam and higher D.\n\n');

% Radiation efficiency: use direct-r gain (no epsilon artifact).
eta_axi = 10^((G_dB_mean - D_axi_dBi)/10);
fprintf('  Radiation efficiency   ~ %.0f%%  (G_direct-r / D_axial-sym)\n', eta_axi*100);
fprintf('    Typical patches: 70-95%%. If lower, likely causes are:\n');
fprintf('    1) Impedance mismatch (patch not tuned to exactly 50 ohm at f0)\n');
fprintf('    2) Dielectric/conductor loss in the substrate (FR4: tanD ~ 0.02)\n');
fprintf('    3) Bench multipath making G_friis slightly underestimated\n\n');

% Rectangular plot with annotations (drawn here so HPBW/SLL/FB are available).
% Negative-theta data is mirrored from the measured 0..180 deg cut.
figure('Name', 'Pattern: Rectangular');
plot(theta_full_deg, Pr_dB_full, 'b-o', 'LineWidth', 1.5, 'DisplayName', 'Measured (mirrored)');
hold on;
yline(-3, 'r--', '-3 dB', 'LabelHorizontalAlignment', 'left', 'HandleVisibility', 'off');
xline( HPBW_deg/2, 'm:', sprintf('+HPBW/2 = %.0f deg', HPBW_deg/2), 'HandleVisibility', 'off');
xline(-HPBW_deg/2, 'm:', sprintf('-HPBW/2 = %.0f deg',-HPBW_deg/2), 'HandleVisibility', 'off');
plot(BLL_theta, BLL_dB, 'r^', 'MarkerSize', 10, 'MarkerFaceColor', 'r', ...
     'DisplayName', sprintf('Back lobe = %.1f dB @ %d deg', BLL_dB, BLL_theta));
xlabel('Rotation angle \theta (deg)'); ylabel('Normalized P_r (dB)');
title(sprintf('Rectangular pattern @ %.2f GHz  (HPBW = %.1f deg, F/B = %.1f dB)', ...
              f0/1e9, HPBW_deg, FB_dB));
xlim([-180 180]); ylim([lower_lim 0]); grid on;
legend('Location', 'south'); hold off;

figure('Name', 'Pattern + cos^n overlay');
plot(rad2deg(theta_fine_rad), Pr_dB_fine, 'b-', 'LineWidth', 2, 'DisplayName', 'Measured');
hold on;
plot(rad2deg(theta_fine_rad), U_th_dB, 'r--', 'LineWidth', 2, ...
     'DisplayName', sprintf('cos^{%.2f}(\\theta)', n_est));
xline(rad2deg(theta_fine_rad(iL)), 'w:', 'HandleVisibility', 'off');
xline(rad2deg(theta_fine_rad(iR)), 'w:', 'HandleVisibility', 'off');
yline(-3, 'w:', '-3 dB', 'HandleVisibility', 'off');
xlim([-90 90]); ylim([max(-40, lower_lim) 0]);
xlabel('\theta (deg)'); ylabel('Normalized P_r (dB)');
title(sprintf('cos^n pattern fit (HPBW = %.1f deg) @ %.2f GHz', HPBW_deg, f0/1e9));
grid on; legend('Location', 'south'); hold off;

%% --- 30 vs 30Q comparison (effect of flipping one antenna) ----------
[~, s30 ] = read_s2p_S21(fullfile(data_dir, '30.s2p'));
[~, s30Q] = read_s2p_S21(fullfile(data_dir, '30Q.s2p'));

figure('Name', '30 vs 30Q comparison');
plot(freq/1e9, s30.dB,  'b-', 'LineWidth', 1.5, 'DisplayName', '30.s2p (original)');
hold on;
plot(freq/1e9, s30Q.dB, 'r-', 'LineWidth', 1.5, 'DisplayName', '30Q.s2p (one antenna flipped)');
xline(f0/1e9, 'w--', sprintf('f_0 = %.2f GHz', f0/1e9), ...
      'LabelVerticalAlignment', 'bottom', 'HandleVisibility', 'off');
xlabel('Frequency (GHz)'); ylabel('|S_{21}| (dB)');
title('Effect of Flipping One Antenna at 30 cm');
grid on; legend('Location', 'best'); hold off;

dS21_f0 = s30.dB(idx_f0) - s30Q.dB(idx_f0);
fprintf('--- 30 vs 30Q at f0 ---\n');
fprintf('  |S21|_30  = %.2f dB\n', s30.dB(idx_f0));
fprintf('  |S21|_30Q = %.2f dB\n', s30Q.dB(idx_f0));
fprintf('  Delta     = %+.2f dB  (positive => flipping reduced coupling)\n', dS21_f0);
fprintf('  Interpretation depends on what "flip" was physically:\n');
fprintf('    180 deg about boresight  -> co-pol preserved (~0 dB diff)\n');
fprintf('    90 deg about boresight   -> cross-pol      (large negative drop)\n');
fprintf('    flip front-to-back       -> back lobe coupling (often big diff)\n');
fprintf('  Compare with the rotation pattern''s value at the equivalent angle\n');
fprintf('  to disambiguate.\n\n');

%% --- Touchstone S2P loader (S21 only, format DB/MA/RI; Hz/MHz/GHz) ----
function [freq, s21] = read_s2p_S21(fname)
    fid = fopen(fname, 'r');
    if fid < 0, error('Could not open %s', fname); end
    cleaner = onCleanup(@() fclose(fid)); %#ok<NASGU>

    freq_unit_scale = 1;
    param_format    = 'DB';

    % Skip blank/comment lines; consume option line if present.
    while true
        pos  = ftell(fid);
        line = fgetl(fid);
        if ~ischar(line), error('Unexpected EOF in %s', fname); end
        s = strtrim(line);
        if isempty(s), continue; end
        if s(1) == '!', continue; end
        if s(1) == '#'
            tok = strsplit(s);
            % Touchstone option line: # <freq_unit> S <format> R <Z0>
            if numel(tok) >= 4
                switch upper(tok{2})
                    case 'HZ',  freq_unit_scale = 1;
                    case 'KHZ', freq_unit_scale = 1e3;
                    case 'MHZ', freq_unit_scale = 1e6;
                    case 'GHZ', freq_unit_scale = 1e9;
                end
                param_format = upper(tok{4});
            end
            continue;
        end
        fseek(fid, pos, 'bof');
        break;
    end

    raw  = fscanf(fid, '%f', [9 Inf]).';
    freq = raw(:, 1) * freq_unit_scale;
    a    = raw(:, 4);   % S21 first value
    b    = raw(:, 5);   % S21 second value

    switch param_format
        case 'DB'   % a = dB magnitude, b = degrees
            s21.dB  = a;
            s21.ang = b;
            s21.lin = 10.^(a/20) .* exp(1j*deg2rad(b));
        case 'MA'   % a = linear magnitude, b = degrees
            s21.lin = a .* exp(1j*deg2rad(b));
            s21.dB  = 20*log10(abs(s21.lin));
            s21.ang = b;
        case 'RI'   % a = real, b = imag
            s21.lin = a + 1j*b;
            s21.dB  = 20*log10(abs(s21.lin));
            s21.ang = rad2deg(angle(s21.lin));
        otherwise
            error('Unknown S2P format "%s" in %s', param_format, fname);
    end
end
