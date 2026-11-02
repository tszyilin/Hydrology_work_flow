function [Dtotals]=YPP2MemArray(SourcePathFilePrefix,StartYr,EndYr)
% 
% Function YPP2MemARRAY converts a sequence of YPP files into an array
% which is returned to parent program of
% daily totals from startyr to endyr

Dat=1;
i=0;
% extract daily rainfall data
for Yr=StartYr:EndYr;
    YrFile=[SourcePathFilePrefix num2str(Yr)];
        
    [DayRain]= YPPExtract (Yr,YrFile, Dat);
    % pause
    for mth=1:12;
        for day=1:31;
            %DayRain(day,mth);
            if DayRain(day,mth)~=-2;
                i=i+1;
                Dtotals(i)=DayRain(day,mth);
                
            end
        end
   end
end

