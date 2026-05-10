% EE 4170/5170 Lab 4: Linear Polarization
clear; clc; close all;

%% Load Data
disp('Loading data...');
filename = 'EE4170 Lab 4 Data Sec 1_Public.xlsx';

% Read data from the Excel file
opts = detectImportOptions(filename);
lab4_data = readtable(filename, opts);

% Extract Variables (Column 1 is Angle, Column 2 is S21)
gamma_deg = lab4_data{:, 1}; % Angle in degrees
S21_dB = lab4_data{:, 2};    % S21 in dB

%% Question 1: Normalized |S21| 
% Convert S21 from dB to linear magnitude
% S21 is a voltage ratio, so linear magnitude is 10^(S21_dB / 20)
S21_mag = 10 .^ (S21_dB / 20);

% Find the maximum value of |S21| over all angles to be S0
S0 = max(S21_mag);

% Calculate the normalized |S21|
S21_norm = S21_mag / S0;

% Plot Question 1
figure('Name', 'Question 1: Measured Data');
scatter(gamma_deg, S21_norm, 60, 'b', 'filled');
hold on;
plot(gamma_deg, S21_norm, 'b--', 'LineWidth', 1); % Light line connecting dots
hold off;
title('Normalized |S_{21}| vs. Polarization Angle (\gamma)');
xlabel('Polarization Angle \gamma (degrees)');
ylabel('Normalized Magnitude |S_{21}| / S_0');
grid on;

%% Question 2 & 3: Theoretical Function f(gamma) and Overlay

% Generate smooth data for theoretical curve
gamma_smooth = linspace(min(gamma_deg), max(gamma_deg), 200);
f_gamma = cosd(gamma_smooth); % Using cosd for degrees

% Create the overlay plot
figure('Name', 'Lab 4: Linear Polarization');
hold on;

% Plot measured data points
scatter(gamma_deg, S21_norm, 60, 'b', 'filled', 'DisplayName', 'Measured |S_{21}| / S_0');
plot(gamma_deg, S21_norm, 'b--', 'LineWidth', 1, 'HandleVisibility', 'off'); % Light line connecting dots

% Plot theoretical function
plot(gamma_smooth, f_gamma, 'r-', 'LineWidth', 2, 'DisplayName', 'Theoretical f(\gamma) = \cos(\gamma)');

hold off;
title('Normalized |S_{21}| vs. Polarization Angle (\gamma)');
xlabel('Polarization Angle \gamma (degrees)');
ylabel('Normalized Magnitude |S_{21}| / S_0');
legend('Location', 'southwest');
grid on;



%% Print Written Answers (Questions 4 & 5)
fprintf('\n--- Lab 4 Analysis Answers ---\n');
fprintf('Question 1 & 3: Overlay plot generated successfully.\n\n');

fprintf('Question 2: According to Eqn (1), the PLF is |rho_t dot rho_r|^2 = cos^2(gamma).\n');
fprintf('            Since |S21| represents a voltage parameter (proportional to sqrt(Power)),\n');
fprintf('            the correct mapping function for the magnitude is f(gamma) = cos(gamma).\n\n');

fprintf('Question 4: At gamma = 90 deg, the antennas are fully cross-polarized (PLF = 0).\n');
fprintf('            Rotating the receiver in the xz-plane by theta keeps its polarization\n');
fprintf('            vector strictly within the xz-plane. Because the transmitter is polarized\n');
fprintf('            along the y-axis, no y-component is introduced to the receiver.\n');
fprintf('            Thus, the dot product remains zero and |S21| is unchanged.\n\n');

fprintf('Question 5: At gamma=90, theta=10, the receiver has both x and z components.\n');
fprintf('            Subsequently rotating the platform in the yz-plane by delta=10 tilts\n');
fprintf('            that new z-component into the y-direction. This introduces a slight\n');
fprintf('            co-polarized y-component to the receiving antenna, causing the PLF\n');
fprintf('            to become non-zero, which slightly increases the measured |S21|.\n\n');