function [Status]=YPP_Comp_Build2017(StnListFile,StartYr,EndYr,StnName,CompPathFilePrefix)

% function YPP_Comp_Build builds a composite  set of daily rainfall YPP files from a
% list of candidate YPP files. 1=index stn  N= least reliable stn.

% Build 01 wjc meynink 12 Oct 05
% last mod wjcm 20/02/2017 @ 1346

% VARIABLES LIST
%
% StnListFile    - Ascii text file of candidate stn filenamePrefix(cols 1>50)
%                  and depth ratios (cols 51:60)
%                  Format - z:\zz\job314\data314\hydrometdata\RainYPP\061023.     1.00
%                           z:\zz\job314\data314\hydrometdata\RainYPP\061087.     0.9865
%                           etc

fid0=fopen(StnListFile,'r');
k=0;
while feof(fid0)==0
    k=k+1
    a=fgetl(fid0)
    L=length(a)
    SourcePathFilesPrefix{k}=wjcmtrim(a(1:105)) % Change here based on the input text file
    Ratio(k)=str2num(wjcmtrim(a(106:L)))        % Change here based on the input text file
end
pause

Nstn=length(Ratio)

for Yr=StartYr:EndYr
    YYr=num2str(Yr)
    AFile=[SourcePathFilesPrefix{1} YYr]
    %pause
    [CompRain]= YPPExtract (Yr,AFile,1)


    if Ratio(1)~1
        for Mth=1:12;
            for Nday=1:31;
                if CompRain(Nday,Mth)>0
                    CompRain(Nday,Mth)=Ratio(1)*CompRain(Nday,Mth);
                end
            end
        end
    end

    for j=2:Nstn
        BFile=[SourcePathFilesPrefix{j} YYr]
        [BDayRain]= YPPExtract (Yr,BFile,1)

    for Mth=1:12;
        for Nday=1:31;
            if CompRain(Nday,Mth)==-1 & BDayRain(Nday,Mth)>=0
                CompRain(Nday,Mth)=Ratio(j)*BDayRain(Nday,Mth);
            end
        end
    end
    end
    CompRain

    % save composite YPP
    FilePathName=[CompPathFilePrefix YYr];
    [Status]=YPP_Build(CompRain,Yr,StnName,FilePathName,'rain');

end

% Generate ypl summary
disp('Generating ypl summary' )
CompPathFilePrefix

[Status]=YPLfromYPP('rain',CompPathFilePrefix,4,StartYr,EndYr,StnName,2,'Full')


