% Rear-Fed Rectangular Patch Antenna Calculator
close all; clear; clc;

%% Input Parameters
% Target Specifications
fr = 5.5e9;        % Resonant Frequency (Hz) (2.4GHz = 2.4e9)
er = 4.1;           % Dielectric Constant of substrate (FR4 ~4.1-4.6)
Z0 = 50;            % Characteristic impedance (Ohms)

% Physical Dimensions (in mm or mils - all must match)
dielectric_t_input = 1.51;    % Substrate thickness
t_top_input = 0.035;            % Top copper thickness
t_bottom_input = 0.035;        % Bottom copper thickness

% Substrate extension past patch edges
Ls_input = 15;  % Length margin (X-axis)
Ws_input = 15;  % Width margin (Y-axis)

% Coax Feed Parameters
er_coax = 2.1;          % PTFE dielectric constant for SMA connector
pin_dia_input = 1.4859;   % SMA inner pin diameter (match input_unit)

% Unit Selection
input_unit = 'mm'; % mm or mils
c = 2.99792458e8; % Speed of light (m/s)

%% Unit Conversions (Inputs to meters for calculations)
if strcmpi(input_unit, 'mils')
    conv_factor = 2.54e-5;
elseif strcmpi(input_unit, 'mm')
    conv_factor = 1e-3;
else
    error('Invalid unit specified. Please use ''mils'' or ''mm''.');
end

dielectric_t = dielectric_t_input * conv_factor;
top_cu_t = t_top_input * conv_factor;
bot_cu_t = t_bottom_input * conv_factor;
Ls = Ls_input * conv_factor;
Ws = Ws_input * conv_factor;
pin_rad = (pin_dia_input / 2) * conv_factor;

%% Dimension Calculations
lambda0 = c / fr;

% Patch Width (W)
W = (c / (2 * fr)) * sqrt(2 / (er + 1));

% Effective Dielectric Constant
Ereff = ((er + 1) / 2) + (((er - 1) / 2) * (1 + 12 * (dielectric_t / W))^(-0.5));

% Length Extension (Delta L)
numerator = (Ereff + 0.3) * ((W / dielectric_t) + 0.264);
denominator = (Ereff - 0.258) * ((W / dielectric_t) + 0.8);
Delta_L = 0.412 * dielectric_t * (numerator / denominator);

% Effective Length (Leff) and Actual Length (L)
L_eff = c / (2 * fr * sqrt(Ereff));
L = L_eff - 2 * Delta_L;

%% Matching Calculations (x_feed)
k0 = 2 * pi / lambda0;

% Exact Conductance (G1) via numerical integration (From Balanis)
integral_fun1 = @(theta) (((sin(k0 * W / 2 .* cos(theta))) ./ cos(theta)).^2) .* (sin(theta)).^3;
I1 = integral(integral_fun1, 0, pi);
G1 = I1 / (120 * pi^2);

% Exact Mutual Conductance (G12) via numerical integration
bessel_fun = @(theta) besselj(0, k0 * L .* sin(theta));
integral_fun2 = @(theta) (((sin(k0 * W / 2 .* cos(theta))) ./ cos(theta)).^2) .* (sin(theta)).^3 .* bessel_fun(theta);
I2 = integral(integral_fun2, 0, pi);
G12 = I2 / (120 * pi^2);

R_edge = 1 / (2 * (G1 + G12));

if Z0 <= R_edge
    x_feed = (L / pi) * asin(sqrt(Z0 / R_edge));
else
    x_feed = L / 2; 
end

%% Ground Cutout Calculations
% Z0 = (60 / sqrt(er_coax)) * ln(sma_rad / pin_rad)
sma_rad = pin_rad * exp((Z0 * sqrt(er_coax)) / 60);
%sma_rad = 5e-3;

%% Format Output Units
if strcmpi(input_unit, 'mils')
    out_mult = 1 / 2.54e-5;
    unit_str = 'mils';
else
    out_mult = 1000;
    unit_str = 'mm';
end

%% Print Parameter List and Inputs
fprintf('\n========================================================\n');
fprintf('--- CST PARAMETER LIST VARIABLES (Units: %s) ---\n', unit_str);
fprintf('========================================================\n');
fprintf('W              = %.4f\n', W * out_mult);
fprintf('L              = %.4f\n', L * out_mult);
fprintf('dielectric_t   = %.4f\n', dielectric_t * out_mult);
fprintf('top_cu_t       = %.4f\n', top_cu_t * out_mult);
fprintf('bot_cu_t       = %.4f\n', bot_cu_t * out_mult);
fprintf('Ls             = %.4f\n', Ls * out_mult);
fprintf('Ws             = %.4f\n', Ws * out_mult);
fprintf('x_feed         = %.4f\n', x_feed * out_mult);
fprintf('pin_rad        = %.4f\n', pin_rad * out_mult);
fprintf('sma_rad       = %.4f\n', sma_rad * out_mult);
fprintf('\n========================================================\n');
fprintf('--- CST BRICK/CYLINDER DIALOG BOX INPUTS ---\n');
fprintf('========================================================\n');
fprintf('* Center-Referenced Model: X=0/Y=0 is Patch Center *\n\n');

fprintf('1. DIELECTRIC SUBSTRATE (Brick - Material: FR4)\n');
fprintf('   Xmin: -L/2 - Ls    Xmax: L/2 + Ls\n');
fprintf('   Ymin: -W/2 - Ws    Ymax: W/2 + Ws\n');
fprintf('   Zmin: bot_cu_t     Zmax: bot_cu_t + dielectric_t\n\n');

fprintf('2. GROUND PLANE (Bottom Copper Brick - Material: Copper/PEC)\n');
fprintf('   Xmin: -L/2 - Ls    Xmax: L/2 + Ls\n');
fprintf('   Ymin: -W/2 - Ws    Ymax: W/2 + Ws\n');
fprintf('   Zmin: 0            Zmax: bot_cu_t\n');
fprintf('   -> NOTE: Use Boolean Insert or Subtract to remove a hole of radius "sma_rad" at (x_feed, 0)!\n\n');

fprintf('3. RADIATING PATCH (Top Copper Brick - Material: Copper/PEC)\n');
fprintf('   Xmin: -L/2         Xmax: L/2\n');
fprintf('   Ymin: -W/2         Ymax: W/2\n');
fprintf('   Zmin: bot_cu_t + dielectric_t      Zmax: bot_cu_t + dielectric_t + top_cu_t\n\n');

fprintf('4. COAXIAL FEED PIN (Inner Conductor Cylinder - Material: Copper/PEC)\n');
fprintf('   Outer Radius: pin_rad\n');
fprintf('   Inner Radius: 0.0\n');
fprintf('   Center X:     x_feed\n');
fprintf('   Center Y:     0\n');
fprintf('   Zmin:         0\n');
fprintf('   Zmax:         bot_cu_t + dielectric_t + top_cu_t\n\n');

fprintf('5. SUBSTRATE PLUG (Fills the gap in the ground plane - Material: FR4)\n');
fprintf('   Outer Radius: sma_rad\n');
fprintf('   Inner Radius: pin_rad\n');
fprintf('   Center X:     x_feed\n');
fprintf('   Center Y:     0\n');
fprintf('   Zmin:         0\n');
fprintf('   Zmax:         bot_cu_t\n\n');