function [Status] = GetSiloGrid(StartYr,EndYr,ShortName,Save2Folder)

% GetSiloGrid function downloads annual grid files from the Qld Gov SILO
% website and saves them to the specified folder.
% SILO daily grid data files are available in netCDF format ie .nc 
% Each file has a year of daily data across the grid. Currently 1889-2018

% Build 01 wjc meynink 4 Feb 2019
% Last mod wjcm 4/02/19 @ 1010hrs
% 
% VARIABLES LIST
% 
% StartYr,EndYr - Start and End years of annual grid files to be downloaded 
% ShortName     - Each of climatic elements has a short name used to access it.
%                 Daily Rainfall(mm) = daily_rain
%                 Monthly Rain(mm) = monthly_rain
%                 Maximum Temp(deg C) = max_temp
%                 Minimum Temp(deg C) = min_temp
%                 Vapour pressure (hPa) = vp
% Save2Folder   - Local Folder to which the file is to be saved. Include trailing \.

for Year=StartYr:EndYr
    yyyy=num2str(Year);
    source = ['https://s3-ap-southeast-2.amazonaws.com/silo-open-data/annual/' ShortName '/'];
    filename = [yyyy '.' ShortName '.nc'];
    disp('  ')
    disp('  ')
    disp('  ')
    disp(['Please Wait Downloading  ' filename '  This will typically take 30 to 120secs depending on internet speed']);
    url=[source filename];
    Savefilename=[Save2Folder filename];
    OutFileName=websave(Savefilename, url);
    disp('  ')
    disp([filename ' has been saved to ' Save2Folder]);
    pause(3)
end
Status='DNL Complete'
