%% EE 4170/5170 - Patch antenna chamber data analysis
%
%  .s2p files in chamber_results/ folder
%    <D>.s2p          - distance sweep at D cm (D = 10, 20, ..., 150)
%    30Q.s2p          - rotation reference at 30 cm, 0 deg (antenna flipped
%    over from 30.s2p)
%    30Q#.s2p       - rotation pattern at 30 cm, # deg (# = 10, 20, ..., 180)

close all; clear; clc;

%% Setup
data_dir            = 'chamber_measurements';
c = 299792458; % Speed of light (m/s)
Pt_dBm              = 5; % Source power into TX port (matches Lab 2)
target_freq_Hz      = 5.23e9; % [] = auto-detect peak; else override (Hz)

patch_width = 0.0429; % Ground plane width (m)
patch_height = 0.0484; % Ground plane height (m) 
patch_D = sqrt(patch_width^2 + patch_height^2); % Calculate diagonal dimension
patch_largest_dim_m = patch_D; % patch_D, or NaN to skip
ff_min_cm           = 20; % Lower bound 
ff_max_cm           = 150; % Upper bound - where noise starts to dominate

distance_cm  = 10:10:150; % 10.s2p, ... , 150.s2p
rotation_deg = 0:10:180; % 30Q.s2p (=0), 30Q10.s2p, ..., 30Q180.s2p



%% Load distance sweep
n_dist        = numel(distance_cm);
S21_dist_mat  = [];
freq          = [];
for k = 1:n_dist
    fname = fullfile(data_dir, sprintf('%d.s2p', distance_cm(k)));
    [f, s] = read_s2p_S21(fname);
    if isempty(freq); freq = f; end
    S21_dist_mat(:, k) = s.dB; %#ok<AGROW>
end

% Identify operating frequency
if isempty(target_freq_Hz)
    % Average over the lower and upper bound, then find peak
    ff_cols     = distance_cm >= ff_min_cm & distance_cm <= ff_max_cm;
    mean_S21    = mean(S21_dist_mat(:, ff_cols), 2);
    [~, idx_f0] = max(mean_S21);
else
    [~, idx_f0] = min(abs(freq - target_freq_Hz));
end
f0      = freq(idx_f0);
lambda0 = c / f0;

fprintf('Operating frequency:\n');
if isempty(target_freq_Hz)
    fprintf('  f0      = %.3f GHz   (Peak of mean S21 over %d-%d cm)\n', ...
            f0/1e9, ff_min_cm, ff_max_cm);
else
    fprintf('  f0      = %.3f GHz \n', f0/1e9);
    fprintf('  Data frequency step is %.0f MHz; %.4f GHz snaps to %.3f GHz.\n', ...
            (freq(2)-freq(1))/1e6, target_freq_Hz/1e9, f0/1e9);
end
fprintf('  lambda0 = %.2f cm\n\n', lambda0*100);

%% S21 vs frequency
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

%% Distance analysis at f0
S21_f0  = S21_dist_mat(idx_f0, :).';
Pr_dBm  = S21_f0 + Pt_dBm;
Pr_mW   = 10.^(Pr_dBm/10);
inv_sP  = 1 ./ sqrt(Pr_mW);
r_cm    = distance_cm(:);

% Linear fit on far-field
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

fprintf('Distance analysis at f0:\n');
fprintf('  Fit range: %d cm <= r <= %d cm  (%d points)\n', ff_min_cm, ff_max_cm, sum(ff_idx));
fprintf('  Linear fit:               1/sqrt(Pr) = %.4e * r + %.4e\n', m_fit, b_fit);
fprintf('  x-intercept              = %.2f cm\n', x_int);
fprintf('  Amplitude-center offset  epsilon = %.2f cm\n', epsilon_cm);
fprintf('  Log-log slope of Pr vs r = %.2f   (Friis far field => -2)\n', slope);
if abs(slope + 2) > 0.25
    fprintf('    Slope off from -2; maybe change ff_min_cm/ff_max_cm?\n');
end

% Friis-based gain
% Two different versions
% 1. Using measured r directly (epsilon = 0)
% 2. Using r + epsilon — shown for comparison with Lab 2 method.
G_dB_raw  = 0.5 * (S21_f0 + 20*log10(4*pi*(r_cm/100) / lambda0));
G_dB_mean = mean(G_dB_raw(ff_idx));
G_dB_med  = median(G_dB_raw(ff_idx));
G_dB_std  = std(G_dB_raw(ff_idx));

R_m  = r1_cm/100;
G_dB = 0.5 * (S21_f0 + 20*log10(4*pi*R_m / lambda0));
G_dB_eps_mean = mean(G_dB(ff_idx));

fprintf('  Gain (r direct, no epsilon)  : mean %.2f dBi,  median %.2f dBi,  std %.2f dB\n', ...
        G_dB_mean, G_dB_med, G_dB_std);
fprintf('  Gain (r + epsilon = %.0f cm): mean %.2f dBi\n\n', ...
        epsilon_cm, G_dB_eps_mean);

% Farfield boundary 
if ~isnan(patch_largest_dim_m)
    R_ff_2D2L_cm = (2 * patch_largest_dim_m^2 / lambda0) * 100;
    fprintf(' Farfield boundary (D = %.3f m): %.2f cm\n\n', ...
            patch_largest_dim_m, R_ff_2D2L_cm);
else
    R_ff_2D2L_cm = NaN;
end

%% Distance plots
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

figure('Name', 'Pr vs r1');
loglog(r1_cm, Pr_mW, 'b-o', 'LineWidth', 1.5, 'DisplayName', 'Measured (shifted by \epsilon)');
hold on;

% Create ideal -2 slope line passing through the first far-field point
idx_ref = find(ff_idx, 1, 'first'); % Find index of the first valid far-field point
r1_ref = r1_cm(idx_ref);
Pr_ref = Pr_mW(idx_ref);
Pr_ideal = Pr_ref .* (r1_ref ./ r1_cm).^2; % Calculate ideal 1/r^2 drop-off

loglog(r1_cm, Pr_ideal, 'r--', 'LineWidth', 1.5, 'DisplayName', 'Ideal -2 Slope (1/r^2)');

grid on;
xlabel('r_1 = r + \epsilon (cm)');
ylabel('P_r (mW)');
title('P_r vs r_1 (Amplitude Center Corrected)');
legend('Location', 'best');
hold off;

figure('Name', 'Friis Gain vs Distance');
plot(r_cm(ff_idx)/100,  G_dB_raw(ff_idx),  'bo-', 'LineWidth', 1.5, 'DisplayName', 'In fit range');
hold on;
plot(r_cm(~ff_idx)/100, G_dB_raw(~ff_idx), 'x', 'Color', [1 0.6 0], 'MarkerSize', 10, 'LineWidth', 2, ...
     'DisplayName', 'Excluded (near-field / noisy tail)');
yline(G_dB_mean, 'r--', ...
      sprintf('Mean = %.2f dBi  (median %.2f dBi)', G_dB_mean, G_dB_med), ...
      'LabelHorizontalAlignment', 'left', 'HandleVisibility', 'off');
xlabel('Antenna separation r (m)'); ylabel('Estimated gain G (dBi)');
title(sprintf('Friis Gain Estimate (identical patches) @ %.2f GHz', f0/1e9));
grid on; legend('Location', 'best'); hold off;

%% Rotation pattern at f0
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

% Normalize to peak
Pr_rot_lin = 10.^(S21_rot_dB/10);
[Pr_max, idx_pk] = max(Pr_rot_lin);
Pr_norm    = Pr_rot_lin / Pr_max;
Pr_norm_dB = 10*log10(Pr_norm);
E_norm     = sqrt(Pr_norm);

fprintf('Rotation pattern at f0:\n');
fprintf('  Peak |S21| occurs at theta = %d deg\n', rotation_deg(idx_pk));
fprintf('  S21 range: %.1f dB ... %.1f dB\n', ...
        min(S21_rot_dB), max(S21_rot_dB));

% Mirror half-pattern (0..180) into a full pattern (-180..180)
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
% Annotated rectangular plot done after HPB, F/B, SLL are calculated

%% HPBW, cos^n fit, directivity (Lab 9 stuff) 
% Interpolate between -90 and 90 (front hemisphere)
theta_fine_rad = linspace(-pi/2, pi/2, 4001);
Pr_dB_fine     = interp1(theta_full_rad, Pr_dB_full, theta_fine_rad, 'linear');

half = (length(theta_fine_rad)+1)/2;
[~, iL] = min(abs(Pr_dB_fine(1:half)   - (-3)));
[~, iR] = min(abs(Pr_dB_fine(half:end) - (-3)));
iR = iR + half - 1;
HPBW_rad = theta_fine_rad(iR) - theta_fine_rad(iL);
HPBW_deg = rad2deg(HPBW_rad);

% cos^n single-lobe approximation
n_est    = log(0.5) / log(cos(HPBW_rad/2));
U_th_lin = (cos(theta_fine_rad)).^n_est;
U_th_dB  = 10*log10(U_th_lin);

% Two general directivity estimates:
%   D = 2(n+1) from the cos^n fit
%   D = 41253/(HP_E*HP_H) Kraus single-cut approx
D_lin_n  = 2*(n_est + 1);
D_dBi_n  = 10*log10(D_lin_n);
D_lin_kr = 41253 / (HPBW_deg^2);
D_dBi_kr = 10*log10(D_lin_kr);

fprintf('  -3 dB angles: %.1f deg (left), %.1f deg (right)\n', ...
        rad2deg(theta_fine_rad(iL)), rad2deg(theta_fine_rad(iR)));
fprintf('  HPBW (single cut)        = %.1f deg\n', HPBW_deg);
fprintf('  cos^n fit                : n = %.2f\n', n_est);
fprintf('  Directivity D = 2(n+1)     = %.2f   (%.2f dBi)  - cos^n model - ignores back/side radiation\n', D_lin_n, D_dBi_n);
fprintf('  Directivity D = 41253/HP^2 = %.2f   (%.2f dBi)  - Kraus\n', D_lin_kr, D_dBi_kr);

% Pattern-integration directivity (axial-symmetry assumption)
theta_b_rad = deg2rad(rotation_deg(:));         % 0..pi from face
U_norm_b    = Pr_norm(:);                       % normalized power
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
fprintf('  Front-to-back ratio = %.1f dB  (max front - max back)\n', FB_dB);

% Back-lobe level
back_hemi   = abs(theta_full_deg) > 90;
[BLL_dB, bl_i] = max(Pr_dB_full(back_hemi));
BLL_theta   = theta_full_deg(find(back_hemi, 1) + bl_i - 1);
fprintf('  Back-lobe level = %.1f dB at theta = %d deg\n', BLL_dB, BLL_theta);

% Radiation efficiency using direct-r gain (no epsilon).
eta_axi = 10^((G_dB_mean - D_axi_dBi)/10);
fprintf('  Radiation efficiency   ~ %.0f%%  (G_direct-r / D_axial-sym)\n', eta_axi*100);

% Rectangular plot with annotations
% Negative-theta data is mirrored
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

%% 30/50 vs 30Q/50Q comparison (flipping antenna over)
[~, s30 ] = read_s2p_S21(fullfile(data_dir, '30.s2p'));
[~, s30Q] = read_s2p_S21(fullfile(data_dir, '30Q.s2p'));
[~, s50 ] = read_s2p_S21(fullfile(data_dir, '50.s2p'));
[~, s50Q] = read_s2p_S21(fullfile(data_dir, '50Q.s2p'));

figure('Name', '30/50 vs 30Q/50Q comparison');
plot(freq/1e9, s30.dB,  'b-', 'LineWidth', 1.5, 'DisplayName', '30.s2p (30 original)');
hold on;
plot(freq/1e9, s30Q.dB, 'r-', 'LineWidth', 1.5, 'DisplayName', '30Q.s2p (30 one antenna flipped)');
hold on;
plot(freq/1e9, s50.dB,  'cyan-', 'LineWidth', 1.5, 'DisplayName', '50.s2p (50 original)');
hold on;
plot(freq/1e9, s50Q.dB, 'm-', 'LineWidth', 1.5, 'DisplayName', '50Q.s2p (50 one antenna flipped)');
hold on;
xline(f0/1e9, 'w--', sprintf('f_0 = %.2f GHz', f0/1e9), ...
      'LabelVerticalAlignment', 'bottom', 'HandleVisibility', 'off');
xlabel('Frequency (GHz)'); ylabel('|S_{21}| (dB)');
title('Effect of Flipping at 30 and 50 cm');
grid on; legend('Location', 'best'); hold off;

dS21_f0_30 = s30.dB(idx_f0) - s30Q.dB(idx_f0);
fprintf('\n30/50 vs 30Q/50Q at f0:n');
fprintf('  |S21|_30  = %.2f dB\n', s30.dB(idx_f0));
fprintf('  |S21|_30Q = %.2f dB\n', s30Q.dB(idx_f0));
fprintf('  Delta     = %+.2f dB\n', dS21_f0_30);
dS21_f0_50 = s50.dB(idx_f0) - s50Q.dB(idx_f0);
fprintf('  |S21|_50  = %.2f dB\n', s50.dB(idx_f0));
fprintf('  |S21|_50Q = %.2f dB\n', s50Q.dB(idx_f0));
fprintf('  Delta     = %+.2f dB\n', dS21_f0_50);

%% Touchstone S2P loading (S21 only, format DB/MA/RI; Hz/MHz/GHz)
function [freq, s21] = read_s2p_S21(fname)
    fid = fopen(fname, 'r');
    if fid < 0, error('Could not open %s', fname); end
    cleaner = onCleanup(@() fclose(fid)); %#ok<NASGU>

    freq_unit_scale = 1;
    param_format    = 'DB';

    % Skip blank/comment lines, read option line if present.
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

%% Export plot images
fprintf('\nExporting plots:\n');

% Find or create new directoy
export_dir = 'chamber_plots';
if ~exist(export_dir, 'dir')
    mkdir(export_dir);
end

% Get all open figures
figs = findobj('Type', 'figure');
for i = 1:length(figs)
    fig = figs(i);

    % Make figure name valid file name (no spaces/slashes)
    safe_name = matlab.lang.makeValidName(fig.Name);
    if isempty(safe_name)
        safe_name = sprintf('Figure_%d', fig.Number);
    end

    filename = fullfile(export_dir, sprintf('%s.png', safe_name));

    % Export at 300 DPI
    exportgraphics(fig, filename, 'Resolution', 300);
    fprintf('Saved: %s\n', filename);
end
fprintf('Plots exported, should find them in /%s/ folder.\n', export_dir);