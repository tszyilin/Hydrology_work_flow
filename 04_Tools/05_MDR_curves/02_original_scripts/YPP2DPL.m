function [Status]= YPP2DPL(YPP_PathFilePrefix,StartYr,EndYr,DPL_PathFileName,RptType)

Status=0;  %Status=0 for no errors, and set to 1 if error occurs

% function prepares DPL file from series of YPP files
% RptType   1=long/full :- dd/mm/yyyy   rain;   2= short:- rain
fid0=fopen(DPL_PathFileName,'w');
if fid0==-1
    Status=1;
    fprintf('Error - file missing > %s\n',DPL_PathFileName);
else
    for Yr=StartYr:EndYr
        YPPFile=[YPP_PathFilePrefix num2str(Yr)];
        [DayRain]= YPPExtract (Yr,YPPFile,1);
        for mth=1:12;
            for dd=1:31;
                if DayRain(dd,mth)~=-2
                    if RptType == 1
                        z = [num2str(dd) '/' num2str(mth) '/' num2str(Yr) '         ' num2str(DayRain(dd,mth))];
                    else
                        z = [num2str(DayRain(dd,mth))];
                    end
                    fprintf(fid0,'%s\n',z);
                end
            end
        end
    end
    fclose(fid0);

    fprintf('%s\n',['All Done, File: ' DPL_PathFileName ' Created']);

end
fclose('all')

