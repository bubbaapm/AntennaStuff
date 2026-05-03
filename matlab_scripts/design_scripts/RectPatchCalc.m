% Rectangular Patch Antenna Calculator
% Includes CST Parameter List generation and Dialog Box formulas
close all; clear; clc;

%% 1. Input Parameters
% --- Target Specifications ---
fr = 5.35e9;        % Resonant Frequency (Hz) e.g. 2.4e9 = 2.5 GHz
er = 4.4;           % Dielectric Constant of the substrate
Z0 = 50;            % Target characteristic impedance for matching (Ohms)

% --- Physical Dimensions ---
dielectric_t_input = 0.4284;    % Substrate thickness
t_top_input = 0.035;            % Top copper thickness
t_bottom_input = 0.0152;        % Bottom copper thickness

% Margin: How far the substrate extends past the patch edges
Ls_input = dielectric_t_input * 6;  % Length margin (X-axis)
Ws_input = dielectric_t_input * 6;  % Width margin (Y-axis)

% --- Unit Selection ---
% Enter 'mils' or 'mm' for dimensions above
input_unit = 'mm';
calculate_inset_feed = true;  % Set true to calculate the matching cut depth (y0)

% Speed of light (m/s)
c = 2.99792e8; 

%% 2. Unit Conversions (Inputs to meters for calculations)
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

%% 3. Core Antenna Dimension Calculations
% Standard Patch Width (W)
W = (c / (2 * fr)) * sqrt(2 / (er + 1));

% Effective Width (Weff) incorporating TOP copper thickness
if (W / dielectric_t) >= (1 / (2 * pi))
    W_calc = W + (1.25 * top_cu_t / pi) * (1 + log(2 * dielectric_t / top_cu_t));
else
    W_calc = W + (1.25 * top_cu_t / pi) * (1 + log(4 * pi * W / top_cu_t));
end

% Effective Dielectric Constant (Ereff)
Ereff = ((er + 1) / 2) + (((er - 1) / 2) * (1 + 12 * (dielectric_t / W_calc))^(-0.5));

% Length Extension (Delta L)
numerator = (Ereff + 0.3) * ((W_calc / dielectric_t) + 0.264);
denominator = (Ereff - 0.258) * ((W_calc / dielectric_t) + 0.8);
Delta_L = 0.412 * dielectric_t * (numerator / denominator);

% Effective Length (Leff) and Actual Length (L)
L_eff = c / (2 * fr * sqrt(Ereff));
L = L_eff - 2 * Delta_L;

%% 4. Feed Matching Calculation (y0)
% Input resistance at the edge
Rin_0 = 90 * (er^2 / (er - 1)) * (L / W)^2; 

% Inset / Coax Pin distance from the edge (X = 0)
if Z0 <= Rin_0
    y0 = (L / pi) * acos(sqrt(Z0 / Rin_0));
else
    y0 = 0; 
end

%% 5. Formatting Output to match user unit choice
if strcmpi(input_unit, 'mils')
    out_mult = 1 / 2.54e-5;
    unit_str = 'mils';
else
    out_mult = 1000;
    unit_str = 'mm';
end

%% 6. Print CST Parameter List & Dialog Box Inputs
fprintf('\n========================================================\n');
fprintf('--- CST PARAMETER LIST VARIABLES (Units: %s) ---\n', unit_str);
fprintf('========================================================\n');
fprintf('Enter these exact names and values into the CST Parameter List:\n\n');

fprintf('W              = %.4f\n', W * out_mult);
fprintf('L              = %.4f\n', L * out_mult);
fprintf('dielectric_t   = %.4f\n', dielectric_t * out_mult);
fprintf('top_cu_t       = %.4f\n', top_cu_t * out_mult);
fprintf('bot_cu_t       = %.4f\n', bot_cu_t * out_mult);
fprintf('Ls             = %.4f\n', Ls * out_mult);
fprintf('Ws             = %.4f\n', Ws * out_mult);
fprintf('y0             = %.4f\n', y0 * out_mult);

fprintf('\n========================================================\n');
fprintf('--- CST BRICK DIALOG BOX INPUTS ---\n');
fprintf('========================================================\n');
fprintf('Copy & paste these exact variables into the 3D brick properties.\n');
fprintf('Origin: X=0 at RIGHT Patch Edge, Y=0 at Patch Center, Z=0 at Bottom of Ground\n\n');

fprintf('1. GROUND PLANE (Bottom Copper Brick)\n');
fprintf('   Xmin: -L - Ls      Xmax: Ls\n');
fprintf('   Ymin: -W/2 - Ws    Ymax: W/2 + Ws\n');
fprintf('   Zmin: 0                    Zmax: bot_cu_t\n\n');

fprintf('2. DIELECTRIC SUBSTRATE (Brick)\n');
fprintf('   Xmin: -L - Ls      Xmax: Ls\n');
fprintf('   Ymin: -W/2 - Ws    Ymax: W/2 + Ws\n');
fprintf('   Zmin: bot_cu_t                Zmax: bot_cu_t + dielectric_t\n\n');

fprintf('3. RADIATING PATCH (Top Copper Brick)\n');
fprintf('   Xmin: -L                   Xmax: 0\n');
fprintf('   Ymin: -W/2                 Ymax: W/2\n');
fprintf('   Zmin: bot_cu_t + dielectric_t            Zmax: bot_cu_t + dielectric_t + top_cu_t\n\n');

fprintf('4. COAXIAL FEED LOCATION (If using rear feed - Cylinder Tool)\n');
fprintf('   Center X: -y0\n');
fprintf('   Center Y: 0\n');
fprintf('   Zmin:     0\n');
fprintf('   Zmax:     bot_cu_t + dielectric_t + top_cu_t\n\n');