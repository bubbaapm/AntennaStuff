% EE 4170/5170 Lab 9: Pattern Measurement of Horn Antenna
clear; clc; close all;

% Setup Data
filenames = {
   'EE4170 Lab 9 Data Sec 1_Public.xlsx', ...
   'EE4170 Lab 9 Data Sec 2_Public.xlsx', ...
   'EE4170 Lab 9 Data Sec 3_Public.xlsx'
};

sec_names = {'Section 1', 'Section 2', 'Section 3'};
colors = {'c', 'm', 'y'};
num_files = length(filenames);
theta_all = cell(num_files, 1);
E_norm_all = cell(num_files, 1);
Pr_norm_all = cell(num_files, 1);
Pr_dB_all = cell(num_files, 1);
global_min_dB = 0;

for k = 1:num_files
   % Load Data
   opts = detectImportOptions(filenames{k});
   data = readtable(filenames{k}, opts);

   % Extract Variables
   theta_half_deg = data{:, 1};
   S21_half_dB = data{:, 2};

   % Create vectors for data (mirrored and beyond +-90)
   % Mirror 0-90 over axis
   theta_front_deg = [-flip(theta_half_deg(2:end)); theta_half_deg];
   S21_front_dB = [flip(S21_half_dB(2:end)); S21_half_dB];

   % Create back side (-180 to -100 and 100 to 180)
   % Use noise floor value for anything beyond +- 90 (~50 dB)
   min_S21 = min(S21_half_dB);
   theta_back_neg = (-180:10:-100)';
   S21_back_neg = repmat(min_S21, length(theta_back_neg), 1);
   theta_back_pos = (100:10:180)';
   S21_back_pos = repmat(min_S21, length(theta_back_pos), 1);

   % Make 360 degree array
   theta_full_deg = [theta_back_neg; theta_front_deg; theta_back_pos];
   S21_full_dB = [S21_back_neg; S21_front_dB; S21_back_pos];

   % Convert array to radians for polar plots
   theta_rad = deg2rad(theta_full_deg);

   % Maths
   Pr_linear = 10.^(S21_full_dB / 10);
   Pr_norm = Pr_linear / max(Pr_linear);
   E_norm = sqrt(Pr_norm);
   Pr_norm_dB = 10 * log10(Pr_norm);

   % Store for overlays
   theta_all{k} = theta_rad;
   E_norm_all{k} = E_norm;
   Pr_norm_all{k} = Pr_norm;
   Pr_dB_all{k} = Pr_norm_dB;
   global_min_dB = min(global_min_dB, min(Pr_norm_dB));

   % Plots
   fig_base = (k-1)*3;

   % Q1 - Normalized Amplitude Pattern
   figure(fig_base + 1);
   polarplot(theta_rad, E_norm, colors{k}, 'LineWidth', 1.5);
   title(['Q1: Normalized Amplitude (Field) Pattern - ', sec_names{k}]);
   rlim([0 1]);
   
   % Q2 - Normalized Power Pattern
   figure(fig_base + 2);
   polarplot(theta_rad, Pr_norm, colors{k}, 'LineWidth', 1.5);
   title(['Q2: Normalized Power Pattern - ', sec_names{k}]);
   rlim([0 1]);

   % Q3 - Normalized Power Pattern in dB
   figure(fig_base + 3);
   polarplot(theta_rad, Pr_norm_dB, colors{k}, 'LineWidth', 1.5);
   title(['Q3: Normalized Power Pattern (dB) - ', sec_names{k}]);
   % Set the lower limit based on lowest measured value
   lower_limit = floor(min(Pr_norm_dB) / 10) * 10;
   rlim([lower_limit 0]);
   % Mark -3dB, -6dB, and -10dB concentric circles (White for dark mode)
   hold on;
   polarplot(theta_rad, repmat(-3, size(theta_rad)), 'r--', 'DisplayName', '-3dB');
   polarplot(theta_rad, repmat(-6, size(theta_rad)), 'g--', 'DisplayName', '-6dB');
   polarplot(theta_rad, repmat(-10, size(theta_rad)), 'b--', 'DisplayName', '-10dB');
   legend('Power Pattern', '-3dB', '-6dB', '-10dB', 'Location', 'bestoutside');
   hold off;
end

% Load 2025 Data
opts_2025 = detectImportOptions('EE4170 Lab 9 Data 2025_Public.xlsx');
data_2025 = readtable('EE4170 Lab 9 Data 2025_Public.xlsx', opts_2025);
theta_2025_deg = data_2025{:, 1};
S21_2025_dB = data_2025{:, 2};

% Maths for 2025
theta_2025_rad = deg2rad(theta_2025_deg);
Pr_linear_2025 = 10.^(S21_2025_dB / 10);
Pr_norm_2025 = Pr_linear_2025 / max(Pr_linear_2025);
E_norm_2025 = sqrt(Pr_norm_2025);
Pr_dB_2025 = 10 * log10(Pr_norm_2025);
global_min_dB = min([global_min_dB; min(Pr_dB_2025)]);

% Overlay Plots

% Q1 - Overlay Normalized Amplitude Pattern
figure(10);
for k = 1:num_files
   polarplot(theta_all{k}, E_norm_all{k}, colors{k}, 'LineWidth', 1.5, 'DisplayName', sec_names{k});
   hold on;
end
polarplot(theta_2025_rad, E_norm_2025, 'w-.', 'LineWidth', 2, 'DisplayName', '2025');
title('Overlay Q1: Normalized Amplitude');
rlim([0 1]);
legend('Location', 'bestoutside');
hold off;

% Q2 - Overlay Normalized Power Pattern
figure(11);
for k = 1:num_files
   polarplot(theta_all{k}, Pr_norm_all{k}, colors{k}, 'LineWidth', 1.5, 'DisplayName', sec_names{k});
   hold on;
end
polarplot(theta_2025_rad, Pr_norm_2025, 'w-.', 'LineWidth', 2, 'DisplayName', '2025');
title('Overlay Q2: Normalized Power');
rlim([0 1]);
legend('Location', 'bestoutside');
hold off;

% Q3 - Overlay Normalized Power Pattern in dB
figure(12);
for k = 1:num_files
   polarplot(theta_all{k}, Pr_dB_all{k}, colors{k}, 'LineWidth', 1.5, 'DisplayName', sec_names{k});
   hold on;
end
polarplot(theta_2025_rad, Pr_dB_2025, 'w-.', 'LineWidth', 2, 'DisplayName', '2025');
title('Overlay Q3: Normalized Power (dB)');

% Set the lower limit based on lowest measured value
overlay_limit = floor(global_min_dB / 10) * 10;
rlim([overlay_limit 0]);

% Mark -3dB, -6dB, and -10dB concentric circles
polarplot(theta_2025_rad, repmat(-3, size(theta_2025_rad)), 'r--', 'HandleVisibility', 'off');
polarplot(theta_2025_rad, repmat(-6, size(theta_2025_rad)), 'g--', 'HandleVisibility', 'off');
polarplot(theta_2025_rad, repmat(-10, size(theta_2025_rad)), 'b--', 'HandleVisibility', 'off');
legend('Location', 'bestoutside');
hold off;

% Analysis Q3 Rectangular Plot
figure(13);
for k = 1:num_files
   plot(rad2deg(theta_all{k}), Pr_dB_all{k}, colors{k}, 'LineWidth', 1.5, 'DisplayName', sec_names{k});
   hold on;
end
plot(theta_2025_deg, Pr_dB_2025, 'w-.', 'LineWidth', 2, 'DisplayName', '2025');
% Line at -3dB to better show HPBW
yline(-3, 'w--', '-3dB HPBW Line', 'HandleVisibility', 'off', 'LabelHorizontalAlignment', 'left');
title('Rectangular Plot: Normalized Power (dB) vs Azimuth');
xlabel('Azimuth Angle \theta (Degrees)');
ylabel('Normalized Power (dB)');
xlim([-180 180]);
ylim([overlay_limit 0]);
grid on;
legend('Location', 'southoutside', 'Orientation', 'horizontal');
hold off;

%% Q5 HPBW and n-value
theta_meas_rad = theta_all{1}; 
Pr_dB_meas = Pr_dB_all{1};

theta_meas = theta_all{1};
Pr_dB_meas = Pr_dB_all{1};

% Interpolate the data good estimate
% Generate very fine theta array between -pi/2 and pi/2 (-90 to 90)
theta_fine_rad = linspace(-pi/2, pi/2, 2000);
Pr_dB_fine = interp1(theta_meas, Pr_dB_meas, theta_fine_rad, 'linear');

% Find left and right -3dB crossing points
% Split the array in half to find the crossing on the left (-90 to 0) and right (0 to 90)
half_idx = length(theta_fine_rad) / 2;
[~, idx_left] = min(abs(Pr_dB_fine(1:half_idx) - (-3)));
[~, idx_right_offset] = min(abs(Pr_dB_fine(half_idx+1:end) - (-3)));
idx_right = half_idx + idx_right_offset;
theta_3dB_left_rad = theta_fine_rad(idx_left);
theta_3dB_right_rad = theta_fine_rad(idx_right);

% 3. Calculate HPBW and n
HPBW_rad = theta_3dB_right_rad - theta_3dB_left_rad;
HPBW_deg = rad2deg(HPBW_rad);

% The equation for n: n = ln(0.5) / ln(cos(HPBW_rad / 2))
n_exact = log(0.5) / log(cos(HPBW_rad / 2));
fprintf('Section 1 Data Results\n');
fprintf('Left -3dB Angle: %.2f°\n', rad2deg(theta_3dB_left_rad));
fprintf('Right -3dB Angle: %.2f°\n', rad2deg(theta_3dB_right_rad));
fprintf('Total HPBW: %.2f°\n', HPBW_deg);
fprintf('Calculated n: %.3f\n\n', n_exact);

% Generate the Theoretical Curve U(theta) = cos^n(theta) [-pi/2, pi/2].
% If theta > 90, cos(theta) is negative
U_theory_linear = (cos(theta_fine_rad)).^n_exact;
U_theory_dB = 10 * log10(U_theory_linear);

% Q5 Rectangular Plot with Vertical Markers
figure(13);
% Plot
plot(rad2deg(theta_fine_rad), Pr_dB_fine, 'c-', 'LineWidth', 2, 'DisplayName', 'Measured Data'); hold on;
% Plot theoretical overlay
plot(rad2deg(theta_fine_rad), U_theory_dB, 'w-.', 'LineWidth', 2, 'DisplayName', sprintf('Theory: cos^{%.2f}(\\theta)', n_exact));
% Vertical and horizontal lines at 3dB crossings
xline(rad2deg(theta_3dB_left_rad), 'y--', 'HandleVisibility', 'off');
xline(rad2deg(theta_3dB_right_rad), 'y--', 'HandleVisibility', 'off');
yline(-3, 'y--', '-3dB Level', 'HandleVisibility', 'off', 'LabelHorizontalAlignment', 'center');

% Plot
xlim([-90 90]);
ylim([-30 0]);
xlabel('Azimuth Angle \theta (Degrees)');
ylabel('Normalized Power (dB)');
title('Question 5: Precise HPBW and Theoretical Overlay');
legend('Location', 'southoutside');
grid on;
hold off;

figure(14);
pax = polaraxes;

% Plot section 1 
polarplot(theta_meas_rad, Pr_dB_meas, 'c-', 'LineWidth', 2, 'DisplayName', 'Measured (Section 1)');
hold on;

% Plot theoretical curve
polarplot(theta_fine_rad, U_theory_dB, 'w--', 'LineWidth', 2, 'DisplayName', sprintf('Theory: cos^{%.2f}(\\theta)', n_exact));
title('Figure 14: Question 5 Theoretical Approximation');
rlim([-40 0]);
pax.ThetaLim = [-90 90];
legend('Location', 'bestoutside');
hold off;

% Q6 - Directivity from D = 2(n + 1)
D_theory_linear = 2 * (n_exact + 1);
D_theory_dBi = 10 * log10(D_theory_linear);

fprintf('Q6 - Directivity from n\n');
fprintf('Directivity (dimensionless): %.2f\n', D_theory_linear);
fprintf('Directivity (dBi): %.2f dBi\n\n', D_theory_dBi);

% Q7 - Directivity from D = 41,253 / (HP_E * HP_H)
D_design_linear = 41253 / (HPBW_deg * HPBW_deg);
D_design_dBi = 10 * log10(D_design_linear);

fprintf('Q7 - Other directivity equation\n');
fprintf('Directivity (dimensionless): %.2f\n', D_design_linear);
fprintf('Directivity (dBi): %.2f dBi\n\n', D_design_dBi);