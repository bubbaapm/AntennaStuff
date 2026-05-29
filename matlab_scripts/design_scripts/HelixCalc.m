close all; clear; clc;

% Constants and Inputs
c = 2.99792458e8;       % speed of light in m/s
N = 5;                 % number of turns in helix
fr = 5.2e9;            % frequency in Hz
lambda_0 = c/fr;

% Helix Design Calculations
C = lambda_0;           % optimal circumference of helix
D = C / pi;             % diameter of helix
alpha_d = 13;           % optimal alpha in degrees
alpha_r = deg2rad(alpha_d); % optimal alpha in rads
S = C * tan(alpha_r);   % space between turns
L_0 = sqrt(C^2 + S^2);  % length of one turn
L_n = N * L_0;          % length of helix wire
L = S * N;              % axial length of helix
d = 2.54;                  % wire diameter

% Unit Conversions (mm)
C_mm = C*1e3;
D_mm = D*1e3;
S_mm = S*1e3;
L_0_mm = L_0*1e3;
L_n_mm = L_n*1e3;
L_mm = L*1e3;

% Results Output
fprintf('Calculation Results:\n');
fprintf('Frequency:          %.2f GHz\n', fr/1e9);
fprintf('Wavelength (λ):     %.4f m\n', lambda_0);
fprintf('Number of Turns:    %d\n', N);
fprintf('Pitch Angle:        %.2f degrees\n', alpha_d);
fprintf('Circumference:      %.4f mm\n', C_mm);
fprintf('Diameter (D):       %.4f mm\n', D_mm);
fprintf('Spacing (S):        %.4f mm\n', S_mm);
fprintf('Length of One Turn: %.4f mm\n', L_0_mm);
fprintf('Total Wire Length:  %.4f mm\n', L_n_mm);
fprintf('Axial Length (L):   %.4f mm\n', L_mm);
