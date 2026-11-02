function [Yield]=YPLfromYPP(DataType,YPP_Prefix,Suffix,StartYr,EndYr,StnTitle,Xdat,RptType)

% function extracts monthly data from YPP files for station for all years
% between prescribed start & end years.
%
% VARIABLES LIST
%
% DataType   - Sets footer stats format. Options: evap flow rain sunshine temp wind
% YPP_Prefix - path/filename prefix for YPP source files
% Suffix - length of YPP file suffix 3 or 4 didgit ie .983 or .1983 for year 1983
% StartYr - First year of YPL data
% EndYr - Last Year of YPL data
% StnTitle - Station Title & general discription
% XDat          data type required  1 - daily totals
%                                   2 - monthly totals
%                                   3 - Daily max by months
%                                   4 - Annual total

% RptType - Output Flag 'Full' = Header + Stat summary as footer
%           'Raw'= monthly and ann tot per line
%           'None'

% last mod wjcm 17 Nov 2014 @ 1323 - added YPLarray output under 'Raw'


YPLFile=[YPP_Prefix 'ypl'];

fid=fopen(YPLFile,'w');

if strcmp(RptType,'Full')==1
    fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd');
    fprintf(fid,'%s\n','    ');
    
    switch DataType
    case 'rain'
        fprintf(fid,'%s\n','        Monthly and Annual Rainfall(mm) Summary');
        MthType='Tot';
    case 'flow'
        fprintf(fid,'%s\n','        Monthly and Annual Streamflow(mm) Summary');
        MthType='Tot';
    case 'temp'
        fprintf(fid,'%s\n','        Monthly and Annual Temperature(deg C) Summary');
        MthType='Ave';
    case 'evap'
        fprintf(fid,'%s\n','        Monthly and Annual Evaporation(mm) Summary');
        MthType='Tot';
    case 'wind'
        fprintf(fid,'%s\n','        Monthly and Annual Wind Speed(m/s) Summary');
        MthType='Ave';
    case 'sunshine'
        fprintf(fid,'%s\n','        Monthly and Annual Bright Sunshine(hrs) Summary');
        MthType='Ave';
    
    otherwise
end
    
    
    fprintf(fid,'%s\n','    ')
    fprintf(fid,'%s\n',[' Station:- ' StnTitle]);
    fprintf(fid,'%s\n','   ')
    fprintf(fid,'%s\n','Year    Jan     Feb     Mar     Apr     May     Jun     Jul     Aug     Sep     Oct     Nov     Dec      Ann')
    fprintf(fid,'%s\n','   ')
end


ss=fliplr(YPP_Prefix);
if ss(1)~=('.');
    YPP_Prefix=[YPP_Prefix '.'];
end

k=0;                     % year counter

for Nyr=StartYr:EndYr
    if Suffix==3
        if Nyr<2000
            extn=num2str(Nyr-1000);
        else
            if Nyr==2000;
                extn='000'
            else
                extn=['00' num2str(Nyr-2000)];
            end
        end
    else
        extn=num2str(Nyr);
    end
    
    k=k+1;    
    SourceFile=[YPP_Prefix extn]
    
    [DayRain]= YPPExtract (Nyr,SourceFile, Xdat)
    
    Year(k)=Nyr
    YrMth(k,1:12)=DayRain(1,1:12);
    %pause
    AnnTot=0;
    for mth=1:12;
        if DayRain(1,mth)>=0 & AnnTot>=0
            AnnTot=AnnTot+DayRain(1,mth);
        else
            AnnTot=-1;
        end
    end
    
    if Xdat==3
        if min(DayRain(1,1:12))<0
            AnnTot=-1
        else
            AnnTot=max(DayRain(1,1:12));
        end
    end
    YrMth(k,13)=AnnTot;
    
    [Fmat]=DecFormat(Nyr,7,0,2);
    fprintf(fid,Fmat,Nyr);
    for mth=1:12;
        [Fmat]=DecFormat(DayRain(1,mth),7,0,1);
        fprintf(fid,Fmat,DayRain(1,mth));
        % print to file
    end
    [Fmat]=DecFormat(AnnTot,8,2,1);
    fprintf(fid,[Fmat '\n'],AnnTot);      
    
end % Nyr loop

% Basic Statistics
if strcmp(RptType,'Full')==1
    fprintf(fid,'%s\n','   ');

    for j=1:13
        x=YrMth(1:k,j);
        x=x(x>=0);
        Xbar(j)=mean(x);
        Xsdev(j)=std(x);
        Sample(j)=max(size(x));
    end
    fprintf(fid,'%s\','Mean   ')
    for j=1:12
        [Fmat]=DecFormat(Xbar(j),7,0,1);
        fprintf(fid,Fmat,Xbar(j));
        % print to file
    end
    [Fmat]=DecFormat(Xbar(13),8,2,1);
    fprintf(fid,[Fmat '\n'],Xbar(13));   
    fprintf(fid,'%s\','SDev   ')    
    for j=1:12
        [Fmat]=DecFormat(Xsdev(j),7,0,1);
        fprintf(fid,Fmat,Xsdev(j));
        % print to file
    end
    [Fmat]=DecFormat(Xsdev(13),8,2,1);
    fprintf(fid,[Fmat '\n'],Xsdev(13));   

    fprintf(fid,'%s\','#Yrs   ')   
    for j=1:12
        [Fmat]=DecFormat(Sample(j),7,0,1);
        fprintf(fid,Fmat,Sample(j));
        % print to file
    end
    [Fmat]=DecFormat(Sample(13),8,2,1);
    fprintf(fid,[Fmat '\n'],Sample(13));  
    Yield=sum(Xbar(1:12))
    fprintf(fid,'%s\n','   ');
    fprintf(fid,'%s\n',['Mean Annual, based on Monthly means:- ' num2str(Yield)]);
else
    for i=1:k
        YPLarray(i,1)=Year(i)
        YPLarray(i,2:14)=YrMth(i,1:13)
    end
end
   
fclose(fid)
Status=[' Summary File Created' YPLFile ]


    