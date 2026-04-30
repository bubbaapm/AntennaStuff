% Vivaldi Antenna Designer & Calculator
% Computes dimensions from target band + substrate, builds/sims in
% MATLAB Antenna Toolbox, and optionally exports full geometry to CST.
%
% WHAT EACH PARAMETER CONTROLS:
%   Aperture (Wap)    -> f_low cutoff. Hard min: Wap >= lambda_slot/2.
%                        Wider = lower cutoff, physically bigger board.
%   Taper (Lt)        -> Low-end match quality + forward gain/directivity.
%                        Longer = better S11 at f_low, narrower beam.
%   Opening rate (Ka) -> DERIVED from Wap/s/Lt, do not set independently.
%                        High Ka = wide beam, broad band, lower gain.
%                        Low  Ka = narrow beam, higher gain.
%   Slot (s)          -> Sets f_high ceiling (need s << lambda_high).
%                        Floor = PCB resolution (~0.1 mm for JLC).
%   Cavity (d)        -> Virtual short at slot end. ~0.2 * lambda_slot.
%                        Too small: S11 ripple at low end.
%                        Too large: cavity resonance, wastes board.
%   Ground margins    -> Small (~7% of lambda_slot) avoids edge diffraction
%                        without bloating board size.
%
% PHYSICS LIMITS (don't exceed these without understanding the tradeoff):
%   Surface waves: h < c / (4 * f_high * sqrt(er - 1))
%   Aperture min:  Wap >= lambda_slot / 2  at f_low
%   High er -> smaller board, narrower BW, more dispersive
%   High tan -> direct efficiency loss; critical for UWB designs
%
% TUNING GUIDE:
%   Bad S11 at low end  -> increase Lt or Wap (raise taperMul/apertureMul)
%   Bad S11 at high end -> narrow s, retune Ls
%   Mid-band ripple     -> adjust Ka by tweaking apertureMul ~+/-20%
%   Too narrow beam     -> increase Ka (raise apertureMul or lower taperMul)
%   Too wide beam/gain  -> lower Ka (lower apertureMul or raise taperMul)

close all; clear; clc;

%% Toggles
runSimulation = true;
exportToCST   = false;

%% Target Band
f_low    = 2e9;     % Lower cutoff [Hz]
f_high   = 6e9;     % Upper cutoff [Hz]
f_center = 4e9;     % Pattern / reference frequency [Hz]
numPoints = 41;

%% Substrate (JLC NP-140F)
er      = 4.1;        % Dielectric constant @ 1 GHz
lossTan = 0.013;      % Loss tangent @ 1 GHz
h       = 1.53e-3;    % Core thickness [m]
t_cu    = 0.035e-3;   % Copper thickness (1 oz) [m]

%% Slot Line Width
% Min: PCB resolution (~0.1 mm). Narrower s -> higher f_high ceiling but
% tighter manufacturing tolerance. 0.5 mm is reliable on JLC standard.
s = 0.5e-3;   % [m]

%% Tuning Multipliers (adjust these to explore the design space)
% After a sim, look at the S11 plot and use the guide above to pick which
% multiplier to change and in which direction.
apertureMul = 0.55;   % Wap = mul * lambda_slot. Range: 0.50 (tight) to 0.70
taperMul    = 0.75;   % Lt  = mul * lambda_slot. Range: 0.50 (compact) to 1.50
cavityMul   = 0.20;   % d   = mul * lambda_slot. Range: 0.15 to 0.30
marginMul   = 0.07;   % board margin per side. Range: 0.05 to 0.12

%% Constants & Derived Wavelengths
c = 2.99792458e8;
lambda_low    = c / f_low;
lambda_center = c / f_center;

% Slot line: most field is in air, er_eff ~ (er+1)/2
er_eff_slot = (er + 1) / 2;
lambda_slot = lambda_low / sqrt(er_eff_slot);   % guided lambda at f_low

% Microstrip effective er (for Ls sizing)
W_50       = msWidth(50, er, h);
er_eff_ms  = msEreff(er, h, W_50);
lambda_g_ms = lambda_center / sqrt(er_eff_ms);  % guided lambda at f_center

%% Vivaldi Dimension Calculations
Wap = apertureMul * lambda_slot;       % aperture width
Lt  = taperMul    * lambda_slot;       % taper length
Ka  = log(Wap / s) / Lt;              % opening rate (derived, not tunable directly)
d   = cavityMul   * lambda_slot;       % cavity diameter
Ls  = lambda_g_ms / 4;                % cavity-to-taper spacing (~lambda_g_ms/4)

margin = marginMul * lambda_slot;
Lgnd   = Lt + Ls + d + 2 * margin;
Wgnd   = Wap + 2 * margin;

% FeedOffset: X position of the excitation gap from the ground plane center.
% Must fall inside the straight slot section (between cavity right edge and
% taper start), NOT in solid metal and NOT past the aperture.
% Formula confirmed against MATLAB's own default vivaldi object:
%   default gives FeedOffset=-0.1045 = 0.15 - 0.243 - 0.023/2 exactly.
feedOffset = Lgnd/2 - Lt - Ls/2;   % midpoint of straight slot section

%% Sanity Checks
warns = {};
if s > (c / f_high) / 10
    warns{end+1} = sprintf('Slot %.2f mm > lambda_high/10 = %.2f mm — f_high reach limited', ...
        s*1e3, (c/f_high)/10*1e3);
end
if h > c / (4 * f_high * sqrt(er - 1))
    warns{end+1} = sprintf('h=%.2f mm exceeds surface wave limit %.2f mm at %.1f GHz', ...
        h*1e3, c/(4*f_high*sqrt(er-1))*1e3, f_high/1e9);
end
if Wap < lambda_slot / 2
    warns{end+1} = sprintf('Aperture %.2f mm < lambda_slot/2 = %.2f mm — f_low cutoff will be higher', ...
        Wap*1e3, lambda_slot/2*1e3);
end

%% Print Design Report
fprintf('\n==============================================\n');
fprintf(' VIVALDI DESIGN REPORT\n');
fprintf('==============================================\n');
fprintf(' Band     : %.2f – %.2f GHz  (fc = %.2f GHz)\n', f_low/1e9, f_high/1e9, f_center/1e9);
fprintf(' Substrate: er=%.2f, tan=%.4f, h=%.2fmm, t_cu=%.3fmm\n', er, lossTan, h*1e3, t_cu*1e3);
fprintf(' lambda_slot @ f_low : %.2f mm  (er_eff=%.3f)\n', lambda_slot*1e3, er_eff_slot);
fprintf(' lambda_g_ms @ f_ctr : %.2f mm  (er_eff=%.3f)\n', lambda_g_ms*1e3,  er_eff_ms);
fprintf('----------------------------------------------\n');
fprintf(' Aperture   Wap  = %.2f mm  (%.2f * lambda_slot)\n', Wap*1e3, apertureMul);
fprintf(' Taper      Lt   = %.2f mm  (%.2f * lambda_slot)\n', Lt*1e3,  taperMul);
fprintf(' Opening    Ka   = %.4f /mm  (derived)\n', Ka*1e-3);
fprintf(' Slot       s    = %.2f mm\n',  s*1e3);
fprintf(' Cavity     d    = %.2f mm  (%.2f * lambda_slot)\n', d*1e3,  cavityMul);
fprintf(' Cav-Taper  Ls   = %.2f mm  (lambda_g_ms/4)\n', Ls*1e3);
fprintf(' Ground     Lgnd = %.2f mm\n', Lgnd*1e3);
fprintf('            Wgnd = %.2f mm\n', Wgnd*1e3);
fprintf(' 50 ohm trace W  = %.2f mm\n', W_50*1e3);
fprintf(' FeedOffset      = %.2f mm  (mid straight slot, derived)\n', feedOffset*1e3);
fprintf('==============================================\n');
for k = 1:numel(warns)
    fprintf(' [!] %s\n', warns{k});
end
fprintf('\n');

%% Build Geometry
fprintf('Building geometry...\n');
vAnt = vivaldi('TaperLength',          Lt,  ...
               'ApertureWidth',        Wap, ...
               'OpeningRate',          Ka,  ...
               'SlotLineWidth',        s,   ...
               'CavityDiameter',       d,   ...
               'CavityToTaperSpacing', Ls,  ...
               'GroundPlaneLength',    Lgnd, ...
               'GroundPlaneWidth',     Wgnd, ...
               'FeedOffset',           feedOffset);

figure('Name', 'Vivaldi Geometry');
show(vAnt);
title(sprintf('Vivaldi %.1f–%.1f GHz | er=%.2f h=%.2fmm | %.0fx%.0f mm', ...
    f_low/1e9, f_high/1e9, er, h*1e3, Lgnd*1e3, Wgnd*1e3));

%% Simulation
if runSimulation
    freqVector = linspace(f_low, f_high, numPoints);

    fprintf('Running S-parameter sweep...\n');
    S      = sparameters(vAnt, freqVector);
    S11    = squeeze(S.Parameters(1,1,:));
    S11_dB = 20*log10(abs(S11));
    VSWR   = (1 + abs(S11)) ./ (1 - abs(S11));

    % Report bandwidth
    bw_mask = S11_dB <= -10;
    if any(bw_mask)
        f_bw = freqVector(bw_mask);
        fprintf(' -10 dB BW: %.3f – %.3f GHz\n', f_bw(1)/1e9, f_bw(end)/1e9);
    else
        fprintf(' No -10 dB bandwidth found — check parameters and tuning guide.\n');
    end

    figure('Name', 'S11 & VSWR', 'Position', [80 80 700 560]);

    subplot(2,1,1);
    plot(freqVector/1e9, S11_dB, 'b', 'LineWidth', 1.5);
    yline(-10, 'r--', '-10 dB', 'LineWidth', 1.5);
    xlabel('Frequency (GHz)'); ylabel('S_{11} (dB)');
    title('Return Loss'); xlim([f_low f_high]/1e9); grid on;

    subplot(2,1,2);
    plot(freqVector/1e9, VSWR, 'b', 'LineWidth', 1.5);
    yline(2, 'r--', 'VSWR = 2', 'LineWidth', 1.5);
    xlabel('Frequency (GHz)'); ylabel('VSWR');
    title('VSWR (ratio, not dB)'); xlim([f_low f_high]/1e9); ylim([1 15]); grid on;

    fprintf('Computing impedance...\n');
    figure('Name', 'Impedance');
    impedance(vAnt, freqVector);
    grid on;

    fprintf('Computing 3D pattern @ %.2f GHz...\n', f_center/1e9);
    figure('Name', '3D Radiation Pattern');
    pattern(vAnt, f_center);
end

%% CST Microwave Studio Export
% Coordinate convention: slot axis = X, aperture at +X board edge, Y = lateral.
%   z=0 = bottom of substrate, z=h = top of substrate, z=h+t_cu = top of copper.
%   Microstrip feed is on the bottom face (z = -t_cu to 0), running in Y direction
%   and crossing the slot (oriented along X) near the cavity end.
%
% Build order: substrate -> top copper (full) -> subtract cavity circle ->
%              subtract straight slot -> subtract exponential taper polygon ->
%              add bottom microstrip -> set port & boundaries.

if exportToCST
    fprintf('Connecting to CST Microwave Studio...\n');
    try
        cst = actxserver('CSTStudio.application');
    catch
        error('Could not open CST. Make sure CST Studio Suite is installed and COM-registered.');
    end
    mws = invoke(cst, 'NewMWS');
    n   = newline;

    % Geometry layout parameters (all in mm for CST)
    mm        = 1e3;             % m -> mm multiplier
    x_apert   =  Lgnd/2;        % aperture at the right board edge
    x_throat  =  x_apert - Lt;  % start of exponential taper
    x_cav     =  x_throat - Ls - d/2;   % cavity center

    % Inject parameters for reference / parametric study in CST
    p = {'Lgnd',   Lgnd*mm;   'Wgnd',  Wgnd*mm;
         'h',      h*mm;      't_cu',  t_cu*mm;
         'Lt',     Lt*mm;     'Wap',   Wap*mm;
         's',      s*mm;      'd_cav', d*mm;
         'Ls',     Ls*mm;     'W_50',  W_50*mm;
         'x_apert',  x_apert*mm;
         'x_throat', x_throat*mm;
         'x_cav',    x_cav*mm};
    for k = 1:size(p,1)
        invoke(mws, 'StoreDoubleParameter', p{k,1}, p{k,2});
    end
    invoke(mws, 'Rebuild');

    % Substrate material
    invoke(mws, 'AddToHistory', 'Material: Substrate', [ ...
        'With Material', n, '.Reset', n, '.Name "JLC_NP_140F"', n, ...
        '.Type "Normal"', n, ...
        sprintf('.Epsilon "%.4f"', er), n, ...
        sprintf('.TanD "%.4f"', lossTan), n, ...
        '.TanDModel "ConstTanD"', n, '.TanDFreq "1"', n, ...
        '.Create', n, 'End With']);

    % Substrate brick
    invoke(mws, 'AddToHistory', 'Build: Substrate', [ ...
        'With Brick', n, '.Reset', n, '.Name "Substrate"', n, ...
        '.Component "Vivaldi"', n, '.Material "JLC_NP_140F"', n, ...
        '.Xrange "-Lgnd/2", "Lgnd/2"', n, ...
        '.Yrange "-Wgnd/2", "Wgnd/2"', n, ...
        '.Zrange "0", "h"', n, '.Create', n, 'End With']);

    % Full top copper (slot will be cut below)
    invoke(mws, 'AddToHistory', 'Build: Top Copper', [ ...
        'With Brick', n, '.Reset', n, '.Name "TopCopper"', n, ...
        '.Component "Vivaldi"', n, '.Material "PEC"', n, ...
        '.Xrange "-Lgnd/2", "Lgnd/2"', n, ...
        '.Yrange "-Wgnd/2", "Wgnd/2"', n, ...
        '.Zrange "h", "h+t_cu"', n, '.Create', n, 'End With']);

    % --- Cut 1: circular cavity ---
    invoke(mws, 'AddToHistory', 'Cut: Cavity', [ ...
        'With Cylinder', n, '.Reset', n, '.Name "Cavity"', n, ...
        '.Component "Vivaldi"', n, '.Material "PEC"', n, ...
        sprintf('.OuterRadius "%.6f"', d/2*mm), n, ...
        '.InnerRadius "0"', n, '.Axis "z"', n, ...
        '.Zrange "h", "h+t_cu"', n, ...
        sprintf('.Xcenter "%.6f"', x_cav*mm), n, ...
        '.Ycenter "0"', n, '.Segments "36"', n, ...
        '.Create', n, 'End With']);
    invoke(mws, 'AddToHistory', 'Sub: Cavity', ...
        'Solid.Subtract "Vivaldi:TopCopper", "Vivaldi:Cavity"');

    % --- Cut 2: straight slot (cavity edge to taper start) ---
    invoke(mws, 'AddToHistory', 'Cut: Straight Slot', [ ...
        'With Brick', n, '.Reset', n, '.Name "StraightSlot"', n, ...
        '.Component "Vivaldi"', n, '.Material "PEC"', n, ...
        sprintf('.Xrange "%.6f", "%.6f"', (x_cav + d/2)*mm, x_throat*mm), n, ...
        sprintf('.Yrange "%.6f", "%.6f"', -s/2*mm, s/2*mm), n, ...
        '.Zrange "h", "h+t_cu"', n, '.Create', n, 'End With']);
    invoke(mws, 'AddToHistory', 'Sub: Straight Slot', ...
        'Solid.Subtract "Vivaldi:TopCopper", "Vivaldi:StraightSlot"');

    % --- Cut 3: exponential taper + aperture opening (polygon) ---
    % Polygon vertices: upper taper curve → right board edge → lower taper
    % curve → close at throat. Extruded in Z by t_cu and subtracted.
    Npts   = 60;
    x_t_m  = linspace(x_throat, x_apert, Npts);          % taper x-points [m]
    y_up_m = (s/2) .* exp(Ka .* (x_t_m - x_throat));    % upper taper [m]

    % Build closed polygon: upper curve → aperture edge → lower curve → close
    pX = [x_t_m,         x_apert,   x_apert,   fliplr(x_t_m)  ] .* mm;  % in mm
    pY = [y_up_m,         Wap/2,    -Wap/2,    -fliplr(y_up_m)] .* mm;

    % Write Polygon VBA (WCS at z=0; ExtrureCurve will place it at z=h)
    polyLines = "With Polygon" + n + ...
                ".Reset" + n + ...
                ".Name ""TaperSlot""" + n + ...
                ".Curve ""SlotCurve""" + n;
    polyLines = polyLines + sprintf('.Point "%.6f", "%.6f"' + n, pX(1), pY(1));
    for k = 2:numel(pX)
        polyLines = polyLines + sprintf('.LineTo "%.6f", "%.6f"' + n, pX(k), pY(k));
    end
    polyLines = polyLines + sprintf('.LineTo "%.6f", "%.6f"' + n, pX(1), pY(1));
    polyLines = polyLines + ".Create" + n + "End With";
    invoke(mws, 'AddToHistory', 'Curve: Taper Polygon', char(polyLines));

    % Cover the curve to create a face, then extrude
    invoke(mws, 'AddToHistory', 'Cover: Taper Polygon', ...
        'CoverCurve.CurveCover "SlotCurve:TaperSlot"');
    invoke(mws, 'AddToHistory', 'Extrude: Taper Slot', [ ...
        'With ExtrudeCurve', n, '.Reset', n, '.Name "TaperSlotSolid"', n, ...
        '.Component "Vivaldi"', n, '.Material "Vacuum"', n, ...
        '.Thickness "t_cu"', n, ...
        '.Twistangle "0"', n, '.Taperangle "0"', n, ...
        '.DeleteProfile "True"', n, ...
        '.Curve "SlotCurve:TaperSlot"', n, ...
        '.Create', n, 'End With']);
    % Translate from z=0 to z=h (top of substrate)
    invoke(mws, 'AddToHistory', 'Move: Taper Slot to Top Cu', [ ...
        'With Transform', n, '.Reset', n, ...
        '.Name "Vivaldi:TaperSlotSolid"', n, ...
        '.Vector "0", "0", "h"', n, ...
        '.UsePickedPoints "False"', n, ...
        '.Repetitions "1"', n, ...
        '.MultipleObjects "False"', n, ...
        '.Transform "Shape", "Translate"', n, 'End With']);
    invoke(mws, 'AddToHistory', 'Sub: Taper Slot', ...
        'Solid.Subtract "Vivaldi:TopCopper", "Vivaldi:TaperSlotSolid"');

    % --- Bottom microstrip feed (50 ohm, runs in Y direction, crosses slot) ---
    % Microstrip is centered on the slot axis at x_feed, width W_50, from
    % y=-Wgnd/2 to y=+Wgnd/2.  Radial stub / open end can be added in CST.
    x_feed = x_throat;  % feed crosses slot at the taper start
    invoke(mws, 'AddToHistory', 'Build: Microstrip', [ ...
        'With Brick', n, '.Reset', n, '.Name "Microstrip"', n, ...
        '.Component "Vivaldi"', n, '.Material "PEC"', n, ...
        sprintf('.Xrange "%.6f", "%.6f"', (x_feed - W_50/2)*mm, (x_feed + W_50/2)*mm), n, ...
        '.Yrange "-Wgnd/2", "Wgnd/2"', n, ...
        '.Zrange "-t_cu", "0"', n, '.Create', n, 'End With']);

    % --- Waveguide port at -Y face of the microstrip ---
    port_xmin = (x_feed - 3*W_50)*mm;
    port_xmax = (x_feed + 3*W_50)*mm;
    invoke(mws, 'AddToHistory', 'Port 1', [ ...
        'With Port', n, '.Reset', n, '.PortNumber "1"', n, ...
        '.NumberOfModes "1"', n, ...
        '.Orientation "ymin"', n, ...
        '.Coordinates "Free"', n, ...
        sprintf('.Xrange "%.6f", "%.6f"', port_xmin, port_xmax), n, ...
        '.Zrange "-t_cu", "h"', n, ...
        '.XrangeAdd "0", "0"', n, ...
        '.ZrangeAdd "0", "0"', n, ...
        '.SingleEnded "False"', n, ...
        '.Create', n, 'End With']);

    % --- Frequency range & open boundaries ---
    invoke(mws, 'AddToHistory', 'Frequency Range', ...
        sprintf('Solver.FrequencyRange "%.4f", "%.4f"', f_low/1e9, f_high/1e9));
    invoke(mws, 'AddToHistory', 'Boundaries', [ ...
        'With Boundary', n, ...
        '.Xmin "expanded open"', n, '.Xmax "expanded open"', n, ...
        '.Ymin "expanded open"', n, '.Ymax "expanded open"', n, ...
        '.Zmin "expanded open"', n, '.Zmax "expanded open"', n, ...
        'End With']);

    fprintf('CST geometry built. Inspect the port and mesh before solving.\n');
    fprintf('Note: add radial stub to the microstrip in CST for better mid/high-band matching.\n');
end

%% Local Functions
function W = msWidth(Z0, er, h)
    % Hammerstad-Jensen synthesis, accurate to <1% for er<=16
    A = (Z0/60)*sqrt((er+1)/2) + ((er-1)/(er+1))*(0.23 + 0.11/er);
    B = 377*pi / (2*Z0*sqrt(er));
    if A < 1.52
        WoH = 8*exp(A) / (exp(2*A) - 2);
    else
        WoH = (2/pi)*(B - 1 - log(2*B-1) + ...
              ((er-1)/(2*er))*(log(B-1) + 0.39 - 0.61/er));
    end
    W = WoH * h;
end

function ereff = msEreff(er, h, W)
    if W/h >= 1
        ereff = (er+1)/2 + ((er-1)/2)*(1 + 12*h/W)^(-0.5);
    else
        ereff = (er+1)/2 + ((er-1)/2)*((1 + 12*h/W)^(-0.5) + 0.04*(1-W/h)^2);
    end
end
