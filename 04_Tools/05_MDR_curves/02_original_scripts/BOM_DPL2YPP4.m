function [Status]=BOM_DPL2YPP4(DPLPathFile,StnName,YPPPathFilePrefix)

% function reads BOM(2010CD) Day Per Line(DPL) file data and converts to PSM YPP
% format
% Last mod wjcm 15/09/2015

% VARIABLES LIST

% DPLPathFile
% Nheader          - No header lines in source file
% DayC
% MthC
% YrC
% DataC
% StnName
% YPPPathFilePrefix - full path & name prefix ending with .
% DataType          - 'rain', 'flow', 'temp', 'evap' 
% Adj               - multiplicative adjustment/conversion factor

Status=0;  %Status=0 for no errors, and set to 1 if error occurs


Adj=1;

% read first line of 
oldyear=3000;
  for Mth=1:12;
      for Day=1:31;
          Daydat(Day,Mth)=-1;
      end
  end

  % read first line of file
fid0=fopen(DPLPathFile,'r');
% feof(fid0)
% pause
a=fgetl(fid0);                 % header line

% *******************************************************8
DayC=5;, MthC=4;, YrC=3;, DataC=6;, AccumC=7;
% *******************************************************

k=0;
while feof(fid0)==0
    % x(5)=-1
    dpldata=fgetl(fid0);
    [x,n]=LineOfDec(dpldata);
    if n>2
        k=k+1;
        Yr(k)=x(YrC);
        if k==1
            StartYr=Yr(k)
        end
        Mth(k)=x(MthC);
        Day(k)=x(DayC);
        if n==5
           Rain(k)=-1;
           Accum(k)=-1;
        else
            Rain(k)=x(DataC);
            if n==7
                Accum(k)=x(AccumC);
            else
                Accum(k)=0.0;
            end
        end
    end
end
ndat=k
EndYr=Yr(ndat)

disp([ num2str(k) ' Days of data have been read from BOM csv File'])
%pause

% Process Accumulations 
nacc=0
for k=1:ndat 
    if Accum(k)>1
        nacc=nacc+1;
        switch  Accum(k)
            case 2
                if Rain(k+1)>0 & Rain(k-Accum(k))>0
                    Rain(k-1)=Rain(k)/2;
                    Rain(k)=Rain(k)/2;
                elseif  Rain(k-Accum(k))>0
                    Rain(k-1)=Rain(k);
                    Rain(k)=0.0;
                else
                    Rain(k-1)=0.0;
                end
                
            case 3
               if Rain(k+1)>0 & Rain(k-Accum(k))>0
                   Rain(k-2)=Rain(k)/3; 
                   Rain(k-1)=Rain(k)/3;
                    Rain(k)=Rain(k)/3;
                elseif  Rain(k-Accum(k))>0
                    Rain(k-2)=Rain(k);
                    Rain(k-1)=0.0;
                    Rain(k)=0.0;
                else
                    Rain(k-1)=0.0;
                    Rain(k-2)=0.0;
               end 
                
            otherwise    % need nearby stn for manual allocation
                Rain(k)=-Rain(k);
                for j=1:Accum(k)-1
                    Rain(k-j)=-1;
                end
        end
    end
end
disp ([num2str(nacc) '  accumulations have been processed'])

%pause

for k=1:ndat
    %   x(Ndatmin)=-1;     
    currentyear=Yr(k);               % Check year location in row
    if oldyear==3000
        oldyear=currentyear;
    end
     
    
        
    if currentyear>oldyear  % save previous years data
        Year=num2str(oldyear);
        ['Saving YPP for year  ' num2str(oldyear)]
        
        YPPFilePathName=[YPPPathFilePrefix Year]
        
        status=YPP_Build(Daydat,oldyear,StnName,YPPFilePathName,'rain');
        
        oldyear=currentyear;
        % clear daily data array
        for AMth=1:12;
            for ADay=1:31;
                Daydat(ADay,AMth)=-1;
            end
        end
        NMth=Mth(k);                  % Check/insert month location in row
        Nday=Day(k);
        if Rain(k)>=0
            Daydat(Nday,NMth)=Rain(k)*Adj;
        else
            Daydat(Nday,NMth)=-1;
        end
        
    else % add line of data
        NMth=Mth(k);
        Nday=Day(k);
         if Rain(k)>=0
            Daydat(Nday,NMth)=Rain(k)*Adj;
        else
            Daydat(Nday,NMth)=-1;
        end
       
    end
end

% save final year of data
Year=num2str(oldyear);
YPPFilePathName=[YPPPathFilePrefix Year]

%YPPFilePathName=[YPPpathFilePrefix '.' Year];
status=YPP_Build(Daydat,oldyear,StnName,YPPFilePathName,'rain');

fclose(fid0);

%[Yield]=YPL_Extract('rain',YPPPathFilePrefix,4,StartYr,EndYr,StnName,2,'Full')
[Yield]=YPLfromYPP('rain',YPPPathFilePrefix,4,StartYr,EndYr,StnName,2,'Full')
