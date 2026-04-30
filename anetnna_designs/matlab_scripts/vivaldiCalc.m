% Vivaldi Antenna Designer & Analyzer
close all; clear; clc;

% Toggles & Simulation Settings
runSimulation = true;   % Set to false to only generate and view the geometry
exportToCST   = false;  % Toggle for CST Microwave Studio COM automation

% Frequency Setup
f_min = 2e9;            % 2 GHz
f_max = 6e9;            % 6 GHz
f_center = 4e9;         % Center frequency for 3D radiation pattern
numPoints = 41;         % Number of frequency points for the sweep
freqVector = linspace(f_min, f_max, numPoints);

% Board Specs (JLC NP-140F)
copperThickness = 0.035e-3;      % 35 um (1 oz copper)
dielectricThickness = 1.53e-3;   % 1.53 mm core
er = 4.1;                        % Dielectric constant @ 1 GHz
lossTan = 0.013;                 % Loss tangent @ 1 GHz

% Define substrate
boardSubstrate = dielectric('Name', 'JLC_NP_140F', ...
                            'EpsilonR', er, ...
                            'LossTangent', lossTan, ...
                            'Thickness', dielectricThickness);

% Vivaldi Parameters
% Tune for S11, VSWR, etc.
Lgnd = 110e-3;          % Ground Plane Length
Wgnd = 80e-3;           % Ground Plane Width
Ltaper = 75e-3;         % Taper Length (Scaled for lower freq)
Wtaper = 70e-3;         % Aperture Width (Widened for 2 GHz cutoff)
s = 0.5e-3;             % Slot Line Width
d = 10e-3;              % Cavity Diameter
Ls = 8e-3;              % Cavity to Taper Spacing

% Widths adjusted for 1.53mm dielectric thickness
W1 = 3.0e-3;  % ~50 ohm line
W2 = 2.0e-3;  % Quarter-wave transformer step 1
W3 = 1.2e-3;  % Quarter-wave transformer step 2

% Lengths and stub radius scaled up for ~3-4 GHz center
L1 = 12e-3;
L2 = 6.5e-3;
L3 = 14e-3;
fp = 18e-3;   % Feed offset from edge
th = 90;      % Radial stub angle
bowtieRadius = 14e-3; % Scaled radial stub

% Calculate Opening Rate (Ka) for exponential taper
Ka = (1/Ltaper)*(log(Wtaper/s)/log(exp(1)));

% Build antenna
fprintf('Building Geometry...\n');
vAnt = vivaldi('TaperLength', Ltaper, ...
               'ApertureWidth', Wtaper, ...
               'OpeningRate', Ka, ...
               'SlotLineWidth', s, ...
               'CavityDiameter', d, ...
               'CavityToTaperSpacing', Ls, ...
               'GroundPlaneLength', Lgnd, ...
               'GroundPlaneWidth', Wgnd, ...
               'FeedOffset', -14e-3); % Explicitly placed to match cutout

% Push the base geometry into a PCB stack
vivaldiPCB = pcbStack(vAnt);

% Remove feed strip from top layer
topLayer = vivaldiPCB.Layers{1};
cutout = antenna.Rectangle('Length', 1e-3, 'Width', 4e-3, 'Center', [-0.014 0]);
topLayer = topLayer - cutout;

% Create matching circuit for bottom layer
patch1 = antenna.Rectangle('Length', L1, 'Width', W1, ...
    'Center', [-(Lgnd/2 - L1/2) -(Wgnd/2 - fp - W1/2)], ...
    'NumPoints', [10 2 10 2]);
patch2 = antenna.Rectangle('Length', L2, 'Width', W2, ...
    'Center', [-(Lgnd/2 - L1 - L2/2) -(Wgnd/2 - fp - W1/2)], ...
    'NumPoints', [5 2 5 2]);
patch3 = antenna.Rectangle('Length', W3, 'Width', L3, ...
    'Center', [-(Lgnd/2 - L1 - L2 - W3/2) -(Wgnd/2 - fp - W1/2 + W2/2 - L3/2)], ...
    'NumPoints', [2 10 2 10]);

% Create radial stub
Bowtie = em.internal.makebowtie(bowtieRadius, W3, th, [0 0 0], 'rounded', 20);
p = antenna.Polygon('Vertices', Bowtie');
p = rotateZ(p, -90);
radialStub = translate(p, [-(Lgnd/2 - L1 - L2 - W3/2) -(Wgnd/2 - fp - W1/2 + W2/2 - L3) 0]);

% Combine bottom layer traces
bottomLayer = patch1 + patch2 + patch3 + radialStub;

% Apply materials and layers to PCB stack
vivaldiPCB.BoardThickness = dielectricThickness + (2 * copperThickness);
vivaldiPCB.Layers = {topLayer, boardSubstrate, bottomLayer};

% Reassign feed port to the edge of the microstrip trace
vivaldiPCB.FeedLocations = [-(Lgnd/2) -(Wgnd/2 - fp - W1/2) 1 3];
vivaldiPCB.FeedDiameter = W1/2;

% Show Geometry
figure('Name', 'Antenna Geometry');
show(vivaldiPCB);
title('Custom Vivaldi Geometry');

% Sims & Plotting
if runSimulation
    fprintf('Running S-Parameter Sweep (This may take a minute)...\n');
    
    % S11 & VSWR
    figure('Name', 'Impedance Matching Metrics', 'Position', [100, 100, 800, 600]);
    
    subplot(2,1,1);
    S = sparameters(vivaldiPCB, freqVector);
    rfplot(S);
    title('S_{11} Return Loss');
    yline(-10, 'r--', '-10 dB Threshold', 'LineWidth', 1.5);
    grid on;
    
    subplot(2,1,2);
    vswr(vivaldiPCB, freqVector);
    title('Voltage Standing Wave Ratio (VSWR)');
    yline(2, 'r--', 'VSWR = 2.0 Threshold', 'LineWidth', 1.5);
    grid on;
    
    % Impedance
    fprintf('Calculating Impedance...\n');
    figure('Name', 'Impedance');
    impedance(vivaldiPCB, freqVector);
    grid on;
    
    % Radiation Pattern
    fprintf('Calculating 3D Radiation Pattern at %.2f GHz...\n', f_center/1e9);
    figure('Name', '3D Radiation Pattern');
    pattern(vivaldiPCB, f_center);
end

% CST export 
if exportToCST
    fprintf('Initializing CST Microwave Studio via COM Interface...\n');
    try
        % Launch CST
        cst = actxserver('CSTStudio.application');
        
        % Create new environment
        mws = invoke(cst, 'NewMWS');
        
        fprintf('CST successfully opened.\n');
        
        % Example of passing a parameter from MATLAB to CST's parameter list:
        % invoke(mws, 'StoreDoubleParameter', 'ApertureWidth', Wtaper*1000);
        
        % NOTE: To fully generate the complex exponential curves in CST from MATLAB,
        % you would write a series of strings containing CST VBA macro commands 
        % and execute them using: invoke(mws, 'AddToHistory', 'CommandName', vbaString);
        
    catch ME
        warning('Failed to connect to CST. Ensure it is installed and COM registered.');
        disp(ME.message);
    end
end