% EE 4170/5170 Lab 3: Gain Measurement of Horn Antenna
clear; clc; close all;

%% Constants
c = 299792458; % Speed of light in m/s
f_lab2 = 10.3e9; % Frequency for Lab 2 data in Hz
lambda_lab2 = c / f_lab2;
epsilon = 0.02046; % Amplitude center offset in meters
R1_lab3 = 1.22046; % Measurement distance for Lab 3 in meters

% Horn Dimensions 
% Narda 640
N640_width_m = 3.09 * 0.0254; % Convert to meters
N640_height_m = 2.34 * 0.0254; 
D_N640 = sqrt(N640_width_m^2 + N640_height_m^2); % Max aperture dimension
A_phys_N640 = N640_width_m * N640_height_m; % Physical Area for Q6

% Waveline 699
W699_width_m = 3.48 * 0.0254; % Convert to meters
W699_height_m = 2.61 * 0.0254;
D_W699 = sqrt(W699_width_m^2 + W699_height_m^2); % Max aperture dimension

%% Load Data
disp('Loading data...');
opts2 = detectImportOptions('EE4170 Lab 2 Data Sec 1_public.xlsx');
lab2_data = readtable('EE4170 Lab 2 Data Sec 1_public.xlsx', opts2);

opts3 = detectImportOptions('Lab3 Antenna Data.xlsx', 'NumHeaderLines', 1);
lab3_data = readtable('Lab3 Antenna Data.xlsx', opts3);

% Extract Variables
R_aperture_cm = lab2_data{:, 1}; 
R_aperture = R_aperture_cm / 100; % Convert cm to meters
S21_lab2 = lab2_data{:, 2};

freq_640_GHz = lab3_data{:, 1};
S21_640 = lab3_data{:, 2};
freq_699_GHz = lab3_data{:, 5};
S21_699 = lab3_data{:, 6};

%% Question 1: Gain vs Separation (Aperture Distance)
% Formula: G_dB = 0.5 * (S21_dB + 20*log10(4*pi*R / lambda))
G_dB_q1 = 0.5 * (S21_lab2 + 20 * log10(4 * pi * R_aperture / lambda_lab2));
G_lin_q1 = 10 .^ (G_dB_q1 / 10);

figure('Name', 'Question 1');
subplot(1,2,1);
scatter(R_aperture, G_lin_q1, 'filled');
title('Numerical Gain vs Separation (Q1)');
xlabel('Aperture Separation R (m)'); ylabel('Numerical Gain'); grid on;

subplot(1,2,2);
scatter(R_aperture, G_dB_q1, 'filled');
title('Gain (dB) vs Separation (Q1)');
xlabel('Aperture Separation R (m)'); ylabel('Gain (dB)'); grid on;
% Create smooth trendlines
R_ap_smooth = linspace(min(R_aperture), max(R_aperture), 300);
G_dB_q1_smooth = spline(R_aperture, G_dB_q1, R_ap_smooth);

%% Question 2: Gain vs Separation (Amplitude Center Distance)
R_amp = R_aperture + epsilon; 

G_dB_q2 = 0.5 * (S21_lab2 + 20 * log10(4 * pi * R_amp / lambda_lab2));
G_lin_q2 = 10 .^ (G_dB_q2 / 10);

figure('Name', 'Question 2');
subplot(1,2,1);
scatter(R_amp, G_lin_q2, 'filled', 'MarkerFaceColor', 'r');
title('Numerical Gain vs Separation (Q2)');
xlabel('Amplitude Center Separation (m)'); ylabel('Numerical Gain'); grid on;

subplot(1,2,2);
scatter(R_amp, G_dB_q2, 'filled', 'MarkerFaceColor', 'r');
title('Gain (dB) vs Separation (Q2)');
xlabel('Amplitude Center Separation (m)'); ylabel('Gain (dB)'); grid on;

R_amp_smooth = linspace(min(R_amp), max(R_amp), 300);
G_dB_q2_smooth = spline(R_amp, G_dB_q2, R_amp_smooth);

% Combined Plot for Q1 and Q2
figure('Name', 'Q1 & Q2 Comparison');
hold on;
scatter(R_aperture, G_dB_q1, 50, 'b', 'filled', 'DisplayName', 'Q1: Aperture Data');
plot(R_ap_smooth, G_dB_q1_smooth, 'b--', 'LineWidth', 1.5, 'DisplayName', 'Q1 Trendline');

scatter(R_amp, G_dB_q2, 50, 'r', 'filled', 'DisplayName', 'Q2: Amplitude Center Data');
plot(R_amp_smooth, G_dB_q2_smooth, 'r--', 'LineWidth', 1.5, 'DisplayName', 'Q2 Trendline');
hold off;

title('Gain vs. Separation Distance (Q1 vs. Q2)');
xlabel('Separation Distance (m)');
ylabel('Calculated Gain (dB)');
legend('Location', 'southeast');
grid on;

%% Question 3: Verifying the Far-Field Condition
lambda_sweep = c ./ (freq_640_GHz .* 1e9);

% Calculate required far-field distance for all frequencies
R_ff_N640 = (2 * D_N640^2) ./ lambda_sweep;
R_ff_W699 = (2 * D_W699^2) ./ lambda_sweep;

% Worst-case scenario calculations (at 12 GHz)
f_max = 12e9; 
lambda_min = c / f_max;
R_ff_N640_max = (2 * D_N640^2) / lambda_min;
R_ff_W699_max = (2 * D_W699^2) / lambda_min;

fprintf('\n--- Question 3: Far-Field Condition ---\n');
fprintf('Narda 640 Max Dimension (D): %.4f m\n', D_N640);
fprintf('Waveline 699 Max Dimension (D): %.4f m\n', D_W699);
fprintf('Worst-case Wavelength (at 12 GHz): %.4f m\n', lambda_min);
fprintf('Max Far-field Distance (Narda 640): %.4f m\n', R_ff_N640_max);
fprintf('Max Far-field Distance (Waveline 699): %.4f m\n', R_ff_W699_max);
fprintf('Measurement distance is %.4f m (including amplitude center)\n', R1_lab3);

% Plot the far-field boundary across the frequency band
figure('Name', 'Question 3: Far-Field Boundary');
plot(freq_640_GHz, R_ff_N640, 'b', 'LineWidth', 2, 'DisplayName', 'Narda 640 Required R_{ff}');
hold on;
plot(freq_640_GHz, R_ff_W699, 'r', 'LineWidth', 2, 'DisplayName', 'Waveline 699 Required R_{ff}');
yline(R1_lab3, 'g', 'LineWidth', 2, 'DisplayName', 'Measurement Distance (1.22 m)');
hold off;
title('Required Far-Field Distance vs Frequency');
xlabel('Frequency (GHz)');
ylabel('Required Distance R_{ff} (m)');
legend('Location', 'best');
grid on;

%% Question 4: Narda 640 Gain vs. Frequency
G_dB_640 = 0.5 * (S21_640 + 20 * log10(4 * pi * R1_lab3 ./ lambda_sweep));

figure('Name', 'Question 4');
plot(freq_640_GHz, G_dB_640, 'LineWidth', 2);
title('Narda 640 Horn Antenna Gain vs Frequency');
xlabel('Frequency (GHz)'); ylabel('Gain (dB)'); grid on;

%% Questions 5 & 6: Effective Area and Aperture Efficiency at 10.3 GHz
[~, idx_10_3] = min(abs(freq_640_GHz - 10.3));
freq_target = freq_640_GHz(idx_10_3);

G_dB_10_3 = G_dB_640(idx_10_3);
G_lin_10_3 = 10^(G_dB_10_3 / 10);
lambda_10_3 = c / (freq_target * 1e9);

A_e = (G_lin_10_3 * lambda_10_3^2) / (4 * pi);
aperture_eff = A_e / A_phys_N640;

fprintf('\n--- Questions 5 & 6: at %.3f GHz ---\n', freq_target);
fprintf('Calculated Narda 640 Gain: %.2f dB (Linear: %.2f)\n', G_dB_10_3, G_lin_10_3);
fprintf('Effective Area (A_e): %.6f m^2\n', A_e);
fprintf('Physical Area (Narda 640): %.6f m^2\n', A_phys_N640);
fprintf('Aperture Efficiency: %.2f%%\n', aperture_eff * 100);

%% Question 7: Waveline 699 Gain at 10.3 GHz
S21_640_10_3 = S21_640(idx_10_3);
S21_699_10_3 = S21_699(idx_10_3);

G_699_10_3 = G_dB_10_3 + S21_699_10_3 - S21_640_10_3;

fprintf('\n--- Question 7: Waveline 699 Gain at %.3f GHz ---\n', freq_target);
fprintf('Narda 640 S21: %.2f dB\n', S21_640_10_3);
fprintf('Waveline 699 S21: %.2f dB\n', S21_699_10_3);
fprintf('Calculated Waveline 699 Gain: %.2f dB\n\n', G_699_10_3);