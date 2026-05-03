% Open circuit stub tuner calc
close all; clear; clc;

% Basic Variables
ZA = 475.22516 + 1j*8.7361845;  % Antenna input impedance
Z0 = 50;          % Overallharacteristic impedance
Z1 = 50;          % Characteristic impedance of stub
Z2 = 50;          % Characteristic impedance from stub to patch

eps_r = 3.66;      % Dielectric constant of substrate
h_mils = 64;      %  Substrate thickness in mils
W_mils = 140;     % Width 50-ohm trace in mils

freq = 2.4e9;     % Operating frequency in Hz
c = 299792458;    % Speed of light in m/s

% e_reff calc
% W/h >= 1
if (W_mils / h_mils) >= 1
    eps_reff = ((eps_r + 1) / 2) + (((eps_r - 1) / 2) * (1 + 12 * (h_mils / W_mils))^-0.5);
else
    % W/h < 1
    eps_reff = ((eps_r + 1) / 2) + (((eps_r - 1) / 2) * ((1 + 12 * (h_mils / W_mils))^-0.5 + 0.04 * (1 - (W_mils / h_mils))^2));
end

% Optimizing stuff
initial_guess = [pi/4, pi/4]; 
options = optimoptions('fsolve', 'Display', 'off', 'FunctionTolerance', 1e-6);

% Solve with equations
[solutions, ~, exitflag] = fsolve(@(x) impedance_equations(x, ZA, Z0, Z1, Z2), initial_guess, options);

if exitflag > 0
    beta_l1 = mod(solutions(1), pi); 
    beta_l2 = mod(solutions(2), pi);
    
    % Physica length calc
    lambda_0 = c / freq;                             % Free space wavelength (m)
    lambda_g = lambda_0 / sqrt(eps_reff);            % Guided wavelength (m)
    beta = (2 * pi) / lambda_g;                      % Phase constant (rad/m)
    
    L1_meters = beta_l1 / beta;                      % Physical length of stub (m)
    L2_meters = beta_l2 / beta;                      % Physical length to patch (m)
    
    % Meters to mils
    m_to_mils = 39370.0787;
    L1_mils = L1_meters * m_to_mils;
    L2_mils = L2_meters * m_to_mils;

    % Print calculations
    fprintf('eps_reff: %.4f\n', eps_reff);
    
    fprintf('\n Stub Lengths:\n');
    fprintf('Electrical length of stub (beta*l1):  %.2f degrees\n', rad2deg(beta_l1));
    fprintf('Electrical length to patch (beta*l2): %.2f degrees\n', rad2deg(beta_l2));
    fprintf('--------------------------------------------------\n');
    fprintf('Physical Length of Stub (L1):         %.2f mils\n', L1_mils);
    fprintf('Physical Length to Patch (L2):        %.2f mils\n', L2_mils);
    fprintf('--------------------------------------------------\n');
    
else
    fprintf('\nSolver issue, change some numbers\n');
end

function F = impedance_equations(x, ZA, Z0, Z1, Z2)
    Z1_in = -1j * Z1 / tan(x(1));
    Z2_in = Z2 * (ZA + 1j * Z2 * tan(x(2))) / (Z2 + 1j * ZA * tan(x(2)));
    Z_in = (Z1_in * Z2_in) / (Z1_in + Z2_in);
    
    F(1) = real(Z_in) - Z0; 
    F(2) = imag(Z_in) - 0;  
end