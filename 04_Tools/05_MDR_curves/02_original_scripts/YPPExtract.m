function [DayRain]= YPPExtract (Year,SourceFile, Dat)

% function YPPExtract extracts required data from YPP data file
%
% Ver1 rev A  wjc meynink 15 Mar 90
% Mod wjcm 16 Mar 90 @ 0857
% Matlab translation 13 jul 03
% last mod twm 1255h 22/10/04
%
% VARIABLES LIST
%
% SourceFile        Pat & name of YPP file
% Dat          data type required  1 - daily totals
%                                  2 - monthly totals
%                                  3 - Daily max by months
%                                  4 - Annual total
% DayRain       array (mth,day) of daily data


fid=fopen(SourceFile,'r');

%'SourceFile'
%SourceFile
%pause
DayRain = InitDayRainToMissingData (Year);
if fid == -1        % data file missing
    warning('SourceFile=''%s'' not found!', SourceFile);
    return;
end

%
% files exists, so lets process it...
%
z = GetNextNonCommentLine (fid);

[x,n]=LineOfDec(z);
if n~=1 | Year ~= x(1)
%     fclose(fid);
%     warning ('YPPExtract: Filename and data YEAR maybe a miss match');
%     return;
end

z = GetNextNonCommentLine (fid);

[x,n]=LineOfDec(z);
if n==1
    Adjmm=x(1);
else
    fclose (fid);
    warning ('YPPExtract: mm depth conversion factor may not be specified');
    return;
end

z = GetNextNonCommentLine (fid);

switch Dat
    case 1  %daily totals
        for day=1:31
            [x,n]=LineOfDec(z);
            for mth=1:12
                if x(mth+1)>=0
                    DayRain(day,mth)=Adjmm*x(mth+1);
                else
                    DayRain(day,mth)=x(mth+1);
                end
            end
            z=fgetl(fid);
        end
        
    case 2  % monthly totals
        for j=1:31, z=fgetl(fid); end;   % step through daily data and header
        z=fgetl(fid);                  % C Total                
        [x,n]=LineOfDec(z);
        for mth=1:12
            if x(mth)>=0
                DayRain(1,mth)=Adjmm*x(mth);
            else
                DayRain(1,mth)=x(mth);
            end
        end
                       
    case 3 % daily max by months
        for j=1:33, z=fgetl(fid); end    % step through daily data monthly totals header and data and max header
        z=fgetl(fid);
        [x,n]=LineOfDec(z);
        for mth=1:12
            if x(mth)>=0
                DayRain(1,mth)=Adjmm*x(mth);
            else
                DayRain(1,mth)=x(mth);
            end
        end
        
    case 4 % annual total
        for j=1:37, z=fgetl(fid); end;  % step through daily data monthly totals header and data and max header
        z=fgetl(fid);
        [x,n]=LineOfDec(z);
        if x(1)>=0
            DayRain(1,1)=Adjmm*x(1);
        else
            DayRain(1,1)=x(1);
        end
        
                
    otherwise  % Dat not specified
        error ('YPPExtract: Dat not specified');
end
fclose(fid);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
function z = GetNextNonCommentLine (fid)
Chr1='C';
while ~feof(fid) & Chr1=='C'
    z=fgetl(fid);
    z=wjcmtrim(z);
    Chr1=upper(z(1));
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
function DayRain = InitDayRainToMissingData (year)
% setup data for missing year
DayRain = ones(31,12) * -1;

% Set non existant days
if ~IsLeapYear(year)
    DayRain(29, 2) = -2;
end

DayRain(30:31, 2) = -2;     % Feb
DayRain(31, 4) = -2;        % Apr
DayRain(31, 6) = -2;        % Jun
DayRain(31, 9) = -2;        % Sep
DayRain(31, 11) = -2;       % Nov
