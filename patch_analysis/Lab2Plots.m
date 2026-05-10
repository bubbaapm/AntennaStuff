% EE 4170 Lab 2

close all; clear all; clc;

% Load file
data = readtable('EE4170 Lab 2 Data Sec 1_public.xlsx');
r = data{:, 1};       % Position in cm
S21 = data{:, 2};     % S21 in dB

% Maths

% Calculate Received Power (Pr)
Pt_dBm = 5; 
Pr_dBm = S21 + Pt_dBm;     % dBm + dB = dBm
Pr_mW = 10.^(Pr_dBm / 10); % Convert dBm to mW

% Calculate 1/sqrt(Pr)
inv_sqrt_Pr = 1 ./ sqrt(Pr_mW);

% Calculate Theoretical Far-Field Boundary
f = 10.3e9;                  % Frequency in Hz
c = 2.99792458e10;           % Speed of light in cm/s
lambda = c / f;              % Wavelength in cm
a_width = 7.849;             % Antenna aperture width in cm
a_height = 5.944;            % Antenna aperture height in cm
D = sqrt(a_width^2 + a_height^2); % Max diagonal dimension in cm
far_field_theoretical = (2 * D^2) / lambda;

fprintf('\nIdeal Calculations\n');
fprintf('Antenna Diagonal (D): %.3f cm\n', D);
fprintf('Wavelength (lambda): %.3f cm\n', lambda);
fprintf('Theoretical Far-Field Boundary: %.2f cm\n\n', far_field_theoretical);

% Far-Field Data for curve fitting
% Ideal boundary is ~66.6 cm
far_field_idx = r >= 30;
r_far = r(far_field_idx);
inv_sqrt_Pr_far = inv_sqrt_Pr(far_field_idx);

% Linear fit to find the x-intercept and epsilon
p = polyfit(r_far, inv_sqrt_Pr_far, 1);
m = p(1);
c_fit = p(2);

x_intercept = -c_fit / m;
epsilon = -x_intercept; 

fprintf('Measured Results\n');
fprintf('The x-intercept is: %.2f cm\n', x_intercept);
fprintf('The amplitude center offset (epsilon/2) is: %.2f cm\n\n', epsilon/2);

% Calculate corrected distance (r1)
r1 = r + epsilon;

% Plots

% Log-Log of Pr vs r
figure(1);
loglog(r, Pr_mW, '-o', 'LineWidth', 1.5);
grid on;
xlabel('Distance between apertures r (cm)');
ylabel('Received Power P_r (mW)');
title('Log-Log Plot of Received Power vs r');


% Log-Log of Pr vs r (w/ fit line and calculated far-field)
% Fit a line to the log10(data) in the far-field (r >= 70 cm)
log_r_far = log10(r(far_field_idx));
log_Pr_far = log10(Pr_mW(far_field_idx));

% polyfit(x, y, 1) finds the slope and intercept
p_log = polyfit(log_r_far, log_Pr_far, 1);
measured_slope = p_log(1);

% Generate the trendline over full distance range to see changes
Pr_trend = 10.^(polyval(p_log, log10(r)));

figure(2);
loglog(r, Pr_mW, 'b-o', 'LineWidth', 1.5);
hold on;
loglog(r, Pr_trend, 'r--', 'LineWidth', 1.5);
xline(far_field_theoretical, 'g--', 'LineWidth', 1.5);

grid on;
xlabel('Distance between antennas r (cm)');
ylabel('Received Power P_r (mW)');
title(sprintf('Log-Log Plot with Far-Field Fit (Slope = %.2f)', measured_slope));
legend('Measured Data', 'Far-Field Fit', 'Theoretical Boundary', 'Location', 'best')
% Calculate the trendline's Pr value at the theoretical boundary
Pr_at_boundary = 10^(polyval(p_log, log10(far_field_theoretical)));
% Plot a marker 
plot(far_field_theoretical, Pr_at_boundary, 'k*', 'MarkerSize', 8, 'LineWidth', 1.5);

% Label for marker
label_str = sprintf('  Boundary (%.1f cm, %.3f mW)', far_field_theoretical, Pr_at_boundary);
text(far_field_theoretical, Pr_at_boundary, label_str, 'VerticalAlignment', 'bottom', 'FontWeight', 'bold');;
hold off;


% 1/sqrt(Pr) vs r with Linear Fit
figure(3);
plot(r, inv_sqrt_Pr, '-o', 'LineWidth', 1.5);
hold on;
r_trend = linspace(x_intercept, max(r), 100);
plot(r_trend, polyval(p, r_trend), 'r--', 'LineWidth', 1.5);
xline(0, 'k-'); yline(0, 'k-'); 
grid on;
xlabel('Distance between antennas r (cm)');
ylabel('1 / sqrt(P_r) (mW^{-1/2})');
title('1 / sqrt(P_r) vs r');
legend('Measured Data', 'Far-Field Linear Fit', 'Location', 'best');
hold off;


% Log-Log of Pr vs r1
figure(4);
loglog(r1, Pr_mW, '-o', 'LineWidth', 1.5);
grid on;
xlabel('Distance between amplitude centers r_1 (cm)');
ylabel('Received Power P_r (mW)');
title('Log-Log Plot of Received Power vs r_1');


% 1/sqrt(Pr) vs r1 with Linear Fit
figure(5);
plot(r1, inv_sqrt_Pr, '-o', 'LineWidth', 1.5);
hold on;
p1 = polyfit(r1(far_field_idx), inv_sqrt_Pr(far_field_idx), 1);
r1_trend = linspace(0, max(r1), 100);
plot(r1_trend, polyval(p1, r1_trend), 'r--', 'LineWidth', 1.5);
xline(0, 'k-'); yline(0, 'k-');
grid on;
xlabel('Distance between amplitude centers r_1 (cm)');
ylabel('1 / sqrt(P_r) (mW^{-1/2})');
title('1 / sqrt(P_r) vs r_1');
legend('Measured Data', 'Far-Field Linear Fit', 'Location', 'best');
hold off;

