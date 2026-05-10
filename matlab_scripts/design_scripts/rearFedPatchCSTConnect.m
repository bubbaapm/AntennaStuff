% Rear-Fed Rectangular Patch Antenna Calculator
close all; clear; clc;

%% Input Parameters
% Target Specifications
fr = 5e9;        % Resonant Frequency (Hz) (2.4GHz = 2.4e9)
er = 4.4;           % Dielectric Constant of the substrate (FR4 ~4.2-4.6)
Z0 = 50;            % Target characteristic impedance for matching (Ohms)

% Physical Dimensions (in mm or mils - all must match)
dielectric_t_input = 0.4284;    % Substrate thickness
t_top_input = 0.035;            % Top copper thickness
t_bottom_input = 0.0152;        % Bottom copper thickness

% Substrate extension past patch edges
Ls_input = 15;  % Length margin (X-axis)
Ws_input = 15;  % Width margin (Y-axis)

% Coax Feed Parameters
er_coax = 2.1;          % PTFE dielectric constant for SMA connector
pin_dia_input = 1.27;   % SMA inner pin diameter (match input_unit)

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

%% Format Output Units
if strcmpi(input_unit, 'mils')
    out_mult = 1 / 2.54e-5;
    unit_str = 'mils';
else
    out_mult = 1000;
    unit_str = 'mm';
end

%% CST Interfacing
disp('Starting CST');

% Launch CST
try
    cst = actxserver('CSTStudio.application');
catch
    error('Could not connect to CST. Make sure CST Studio Suite is installed.');
end

% Open a new Microwave Studio Environment
mws = invoke(cst, 'NewMWS');
disp('Project created. Injecting variables...');

% Inject Parameters
invoke(mws, 'StoreDoubleParameter', 'W', W * out_mult);
invoke(mws, 'StoreDoubleParameter', 'L', L * out_mult);
invoke(mws, 'StoreDoubleParameter', 'dielectric_t', dielectric_t * out_mult);
invoke(mws, 'StoreDoubleParameter', 'top_cu_t', top_cu_t * out_mult);
invoke(mws, 'StoreDoubleParameter', 'bot_cu_t', bot_cu_t * out_mult);
invoke(mws, 'StoreDoubleParameter', 'Ls', Ls * out_mult);
invoke(mws, 'StoreDoubleParameter', 'Ws', Ws * out_mult);
invoke(mws, 'StoreDoubleParameter', 'x_feed', x_feed * out_mult);
invoke(mws, 'StoreDoubleParameter', 'pin_rad', pin_rad * out_mult);
invoke(mws, 'StoreDoubleParameter', 'sma_rad', sma_rad * out_mult); 
invoke(mws, 'Rebuild');

disp('Variables injected. Building 3D Geometry...');

% Helper function for VBA formatting
n = newline;

vba_Material = [ ...
    'With Material', n, ...
    '    .Reset', n, ...
    '    .Name "JLC Prepreg 7628"', n, ...
    '    .Type "Normal"', n, ...
    '    .Epsilon "4.4"', n, ...
    '    .Create', n, ...
    'End With'];
invoke(mws, 'AddToHistory', 'Create JLC Prepreg Material', vba_Material);

vba_Substrate = [ ...
    'With Brick', n, ...
    '    .Reset', n, ...
    '    .Name "Substrate"', n, ...
    '    .Component "Antenna"', n, ...
    '    .Material "JLC Prepreg 7628"', n, ... 
    '    .Xrange "-L/2 - Ls", "L/2 + Ls"', n, ...
    '    .Yrange "-W/2 - Ws", "W/2 + Ws"', n, ...
    '    .Zrange "bot_cu_t", "bot_cu_t + dielectric_t"', n, ...
    '    .Create', n, ...
    'End With'];
invoke(mws, 'AddToHistory', 'Build Substrate', vba_Substrate);

% Build Ground Plane
vba_Ground = [ ...
    'With Brick', n, ...
    '    .Reset', n, ...
    '    .Name "Ground"', n, ...
    '    .Component "Antenna"', n, ...
    '    .Material "PEC"', n, ...  
    '    .Xrange "-L/2 - Ls", "L/2 + Ls"', n, ...
    '    .Yrange "-W/2 - Ws", "W/2 + Ws"', n, ...
    '    .Zrange "0", "bot_cu_t"', n, ...
    '    .Create', n, ...
    'End With'];
invoke(mws, 'AddToHistory', 'Build Ground Plane', vba_Ground);

% Build Patch
vba_Patch = [ ...
    'With Brick', n, ...
    '    .Reset', n, ...
    '    .Name "Patch"', n, ...
    '    .Component "Antenna"', n, ...
    '    .Material "PEC"', n, ...
    '    .Xrange "-L/2", "L/2"', n, ...
    '    .Yrange "-W/2", "W/2"', n, ...
    '    .Zrange "bot_cu_t + dielectric_t", "bot_cu_t + dielectric_t + top_cu_t"', n, ...
    '    .Create', n, ...
    'End With'];
invoke(mws, 'AddToHistory', 'Build Patch', vba_Patch);

% Build Inner Feed Pin
vba_Pin = [ ...
    'With Cylinder', n, ...
    '    .Reset', n, ...
    '    .Name "Feed_Pin"', n, ...
    '    .Component "Antenna"', n, ...
    '    .Material "PEC"', n, ...
    '    .OuterRadius "pin_rad"', n, ...
    '    .InnerRadius "0.0"', n, ...
    '    .Axis "z"', n, ...
    '    .Zrange "0", "bot_cu_t + dielectric_t + top_cu_t"', n, ...
    '    .Xcenter "x_feed"', n, ...
    '    .Ycenter "0"', n, ...
    '    .Create', n, ...
    'End With'];
invoke(mws, 'AddToHistory', 'Build Feed Pin', vba_Pin);

% Build Substrate Plug
vba_Plug = [ ...
    'With Cylinder', n, ...
    '    .Reset', n, ...
    '    .Name "Prepreg_Plug"', n, ...
    '    .Component "Antenna"', n, ...
    '    .Material "JLC Prepreg 7628"', n, ...
    '    .OuterRadius "sma_rad"', n, ...
    '    .InnerRadius "pin_rad"', n, ...
    '    .Axis "z"', n, ...
    '    .Zrange "0", "bot_cu_t"', n, ...
    '    .Xcenter "x_feed"', n, ...
    '    .Ycenter "0"', n, ...
    '    .Create', n, ...
    'End With'];
invoke(mws, 'AddToHistory', 'Build Prepreg Plug', vba_Plug);

% Perform Boolean Insert 
vba_Insert = 'Solid.Insert "Antenna:Ground", "Antenna:Prepreg_Plug"'; 
invoke(mws, 'AddToHistory', 'Boolean Insert Plug into Ground', vba_Insert);

disp('========================================================');
disp('SUCCESS! Full Antenna Geometry Built in CST.');
disp('========================================================');