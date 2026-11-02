function [dummy]=MDR_Build2012(RunPathFile)

% function extracts ranked multiday totals from an array of sequential
% daily totals
%
% The function YPP2ARRAY would normally have been used to build the array of daily
% totals and save them to an ASCII file 1 day per line. Hydrological data
% rules apply ie missing data = -1.
%
% Build 01 wjcm 8 aug 03
% mod wjcm 1110h 13/8/03
% mod wjcm 1010h 1310/10/04  - added Cv stat
% last mod wjcm 1231hrs 17/11/06  - added multiplicative adjustment factor
%                                   for depths
% last mod wjcm 2005 30/9/09 - added adj for missing data
%
% RUN FILE  - Ascii 1 item per line
% line 1  - Station Title
% line 2  - Source file of daily rainfall data
% DR_SourceFile            - FileType=1 YPPFilesPathNamePrefix, For historic YPP data filename prefix, 
%                                       Par1=Start year (1/1);  Par2=End year                                      year(31/12)
%                            FileType=2 synthetic or historic HydYr data DPL file name
%                                       Par1=Nheader lines,Par2=-1 not required   
%                            FileType=3 HydYr 365DPL file  (usually synthetic data, can be very long)  
%                                       Par1=Starting year offset; Par2= # yrs simulation
% line 3  - FileType
% line 4  - Par1
% line 5  - Par2
% line 6  - Partial series analysis Events per year, normally 1 but can be
%           set to any value =>1 or <1
% line 7  - Full Report File Path/Name (data on all maxima presented)
% line 8  - Curve Fitting File Path/Name (often preferable to fit curve to rarer data only eg greater than ARI=2)
% line 9  - Depth adjustment factor, multiplicative
% line 10  - 1st Multiday duration to be analysed
% line 11 - 2nd
%
% line n  - Last Multiday duration to be analysed

% open runfile and read all parameters
fid0=fopen(RunPathFile,'r');
StnTitle=fgetl(fid0);
SourceFile=fgetl(fid0)
FileType=str2num(fgetl(fid0));
Par1=fgetl(fid0);
%NStartYr=str2num(Par1);
%NdddStart=datenum(NStartYr,1,1);
Par2=fgetl(fid0);
%NEndYr=str2num(Par2);
%NdddEnd=datenum(NEndYr,12,31);

Nepy=fgetl(fid0);             % partial series events per year, may be fractional
Nepy=str2num(Nepy)

FullResultFile=fgetl(fid0);
CurveFitFile=fgetl(fid0);
a=fgetl(fid0);
Adj=str2num(a)


j=0;                         % multiday durations to be analysed 
while feof(fid0)==0;
   j=j+1;
   b=fgetl(fid0);
   MD(j)=str2num(b);
end
MD
Ndur=j                       % # of multiday durations to be analysed 
fclose(fid0);
disp([' Run data file has been read'])
pause


switch FileType

    case 1   % YPP historic data format
        NStartYr=str2num(Par1);
        NdddStart=datenum(NStartYr,1,1);
        NEndYr=str2num(Par2);
        NdddEnd=datenum(NEndYr,12,31);
        [RainData]=YPP2MemArray(SourceFile,NStartYr,NEndYr)
        Missing=length(RainData(RainData<0));
        Valid=length(RainData(RainData>=0))
        Ldata=length(RainData)
        ValidFrac=Valid/Ldata
        pause
        
    case 2   % DPL historic or synthetic
        disp([' Please wait - Reading DPL daily rainfall data file:  ' SourceFile])
fid0=fopen(SourceFile,'r')

i=0;
Missing=0;
while feof(fid0)==0;
   i=i+1;
   b=fgetl(fid0);
   RainData(i)=str2num(b);
      if RainData(i)==-1;
          Missing=Missing+1;
          RainData(i)=0;
      end

end
Ldata=i
ValidFrac=(Ldata-Missing)/Ldata;

disp(' Daily rainfall data loaded ')

        
    case 3   % 365 DPL synthetic
        
    otherwise
end

disp(' Daily rainfall data loaded ')

   Offset=0;

L=NdddEnd-NdddStart-1;   %+1   % days in record to be analysed

for i=1:L;,     Rain(i)=Adj*RainData(i+Offset);,   end

[NStartYr,mth,day]=datevec(NdddStart);

[NEndYr,m2,d2]=datevec(NdddStart+L-1);
Nyr = NEndYr - NStartYr + 1;
NEvents=ceil(Nyr*Nepy*ValidFrac) 


for j = 1:Ndur
    disp(['Selecting maxima for ' num2str(MD(j),4) ' days duration'])
    % Build/Rebuild CummRainfall Array
    CummRain=cumsum(Rain);
    CummRain2=cumsum(Rain);
 
    for NRank = 1:NEvents    
    CummRMax = 0;
    % Search for Nyr*Nepy MMaxima on Partial Series Basis
        for i = MD(j) + 1:L;
            R2=CummRain(i);
            R1=CummRain(i-MD(j));       
            CummR = R2 - R1;
            
            if CummR > CummRMax;
                CummRMax = CummR;
                Mmax = double(i) - MD(j);            % Pointer to start of Mmax period
                
            end
        end
                
    RMax(j, NRank) = CummRMax;
    MaxStart(j, NRank) = Mmax;
    
    % temporal pattern for multiday total
    R2=CummRain2(Mmax);
    M = Mmax - MD(j);
    TT=[];, RR=[];
    TT(1) = 0;, RR(1) = 0;
           for jj = 1 : MD(j);
        MM = Mmax + jj;
        R3=CummRain2(MM);
        RR(jj + 1) = R3 - R2;
        TT(jj + 1) = jj / MD(j);
        end
    R20(j, NRank)=interp1(TT, RR,.2)/ RMax(j, NRank);
    R40(j, NRank)=interp1(TT, RR,.4)/ RMax(j, NRank);
    R60(j, NRank) =interp1(TT, RR,.6)/ RMax(j, NRank);
    R80(j, NRank)=interp1(TT, RR,.8)/ RMax(j, NRank);
    
    % Multiday Antecedant Rainfall for period equal to duration
    if M < 1
        AntRMax(j, NRank) = -1;
    else
        R1=CummRain2(M);
        AntRMax(j, NRank) = R2 - R1;
    end
    
    % 30day Antecedant Rainfall
    M = Mmax - 30;
    if M < 1
        Ant30RMax(j, NRank) = -1;
    else
        R1=CummRain2(M);
        Ant30RMax(j, NRank) = R2 - R1;
    end

      % Now Remove Maxima from temp cumm file
    R=CummRain(Mmax);
    for i = Mmax : Mmax + MD(j);
        CummRain(i)=R;
    end
    M = Mmax + MD(j) + 1;
     
    for i = M : L;
        CummRain(i) = CummRain(i) - RMax(j, NRank);
    end
    
end   % NRank

end   %  j Multiday duration



% OUTPUT BY DAYS
FullResultFileDays=[FullResultFile '.Days'];
fid=fopen(FullResultFileDays,'w');
fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd')
fprintf(fid,'%s\n','    ')
fprintf(fid,'%s\n',' Historic Multiday Maxima Partial Series')
fprintf(fid,'%s\n',[' Av # Events per Year:- ' num2str(Nepy)])
fprintf(fid,'%s\n','    ')
fprintf(fid,'%s\n',[' Station:- ' StnTitle])
fprintf(fid,'%s\n','   ')
fprintf(fid,'%s\n',' Statistical Summary')
fprintf(fid,'%s\n',' Duration    Mean         SDev         Cv           Median       Skew         Sample')
fprintf(fid,'%s\n','  ') 


for j = 1:Ndur
    RR=[];
    for k = 1:NEvents;, RR(k) = RMax(j,k);, end
    XMean(j)=mean(RR);
    XSDev(j)=std(RR);
    Cv(j)=XSDev(j)/XMean(j);
    XSkew(j)=skewness(RR);
    XMedian(j)=median(RR);
    
    
    [status]=FilePrintDec(fid,MD(j),12,0,8,0);
    [status]=FilePrintDec(fid,XMean(j),12,0,6,0);
    [status]=FilePrintDec(fid,XSDev(j),12,0,6,0);
    [status]=FilePrintDec(fid,Cv(j),12,0,6,0);
    [status]=FilePrintDec(fid,XMedian(j),12,0,6,0);
    [status]=FilePrintDec(fid,XSkew(j),12,0,7,0);
    [status]=FilePrintDec(fid,NEvents,12,0,9,1);
end % j



for j = 1:Ndur;
    fprintf(fid,'%s\n','  ')        % page header
    fprintf(fid,'%s\n','Days      Rank      ARI        StartDate      Multiday     Antecedant Totals(mm)   Temporal Distrbn')
    fprintf(fid,'%s\n','                    (a)                       Total(mm)     MDR        30Day       20   40   60   80')
    fprintf(fid,'%s\n','  ')

    for NRank = 1:NEvents ;    
        Ndddd = MaxStart(j, NRank) + NdddStart;
        [Nyyyy,Mth,Nday]=datevec(Ndddd);
        [status]=FilePrintDec(fid,MD(j),8,0,4,0);
        [status]=FilePrintDec(fid,NRank,8,0,3,0);
        [status]=FilePrintDec(fid,((Nyr*ValidFrac + 1)/NRank),8,0,2,0);
        [status]=FilePrintDec(fid,Nday,3,0,1,0);
        [status]=FilePrintDec(fid,Mth,3,0,1,0);
        [status]=FilePrintDec(fid,Nyyyy,8,0,4,0);
        [status]=FilePrintDec(fid,RMax(j, NRank),8,0,2,0);
        [status]=FilePrintDec(fid,AntRMax(j, NRank),10,2,2,0);
        [status]=FilePrintDec(fid,Ant30RMax(j, NRank),10,2,2,0);
        [status]=FilePrintDec(fid,100*R20(j, NRank),5,2,1,0);
        [status]=FilePrintDec(fid,100*R40(j, NRank),4,1,1,0);
        [status]=FilePrintDec(fid,100*R60(j, NRank),4,1,1,0);
        [status]=FilePrintDec(fid,100*R80(j, NRank),4,1,1,1);
    end % NRank
end % j

fclose(fid);



% OUTPUT BY ARI
FullResultFileARI=[FullResultFile '.ARI'];
fid=fopen(FullResultFileARI,'w');
fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd')
fprintf(fid,'%s\n','    ')
fprintf(fid,'%s\n',' Historic Multiday Maxima Partial Series')
fprintf(fid,'%s\n',[' Av # Events per Year:- ' num2str(Nepy)])
fprintf(fid,'%s\n','    ')
fprintf(fid,'%s\n',[' Station:- ' StnTitle])
fprintf(fid,'%s\n','   ')
fprintf(fid,'%s\n',' Statistical Summary')
fprintf(fid,'%s\n',' Duration    Mean        SDev        Cv          Median      Skew        Sample')
fprintf(fid,'%s\n','  ')


for NRank = 1:NEvents;
%for j = 1:Ndur
    fprintf(fid,'%s\n','  ')        % page header
    fprintf(fid,'%s\n','Days     Rank    ARI      StartDate   Multiday     Antecedant Totals(mm)  Temporal Distrbn')
    fprintf(fid,'%s\n','                 (a)                  Total(mm)    MDR        30Day        20   40   60   80')
    fprintf(fid,'%s\n','  ')

    for j = 1:Ndur;   
 %   for NRank = 1:NEvents     
        Ndddd = MaxStart(j, NRank) + NdddStart;
        [Nyyyy,Mth,Nday]=datevec(Ndddd);
        [status]=FilePrintDec(fid,MD(j),8,0,4,0);
        [status]=FilePrintDec(fid,NRank,8,0,3,0);
        [status]=FilePrintDec(fid,((Nyr*ValidFrac + 1)/NRank),8,0,2,0);
        [status]=FilePrintDec(fid,Nday,3,0,1,0);
        [status]=FilePrintDec(fid,Mth,3,0,1,0);
        [status]=FilePrintDec(fid,Nyyyy,8,0,4,0);
        [status]=FilePrintDec(fid,RMax(j, NRank),8,0,2,0);
        [status]=FilePrintDec(fid,AntRMax(j, NRank),8,0,2,0);
        [status]=FilePrintDec(fid,Ant30RMax(j, NRank),8,0,2,0);
        [status]=FilePrintDec(fid,100*R20(j, NRank),4,1,1,0);
        [status]=FilePrintDec(fid,100*R40(j, NRank),4,1,1,0);
        [status]=FilePrintDec(fid,100*R60(j, NRank),4,1,1,0);
        [status]=FilePrintDec(fid,100*R80(j, NRank),4,1,1,1);
    end % j
end % NRank

fclose(fid);

'Start CurveFit File'
CurveFitFile

fid=fopen(CurveFitFile,'w');



for j=1:Ndur;
    for NRank = 1:NEvents ;    
        Ndddd = MaxStart(j, NRank) + NdddStart;
        [Nyyyy,Mth,Nday]=datevec(Ndddd);
        [status]=FilePrintDec(fid,MD(j),8,0,4,0);
        [status]=FilePrintDec(fid,NRank,8,0,3,0);
        [status]=FilePrintDec(fid,((Nyr*ValidFrac + 1)/NRank),8,0,2,0);
        [status]=FilePrintDec(fid,RMax(j, NRank),8,0,2,1);
    end % NRank
end %Ndur

fclose(fid);
