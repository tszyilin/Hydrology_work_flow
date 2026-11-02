function [Status]=YPP_Build(DayRain,Year,StnName,FilePathName,DataType)

% mod wjcm 12 Nov 07
% Last mod wjcm 7 Nov 2011

% VARIABLES LIST
%
% MthType   - ='Tot' for monthly totals = 'Ave' for monthly averages
        switch DataType
            case 'rain'
                MthType='Tot';
            case 'flow'
                MthType='Tot';
            case 'meanflow'
                MthType='Tot';
            case 'maxflow'
                MthType='Tot';
            case 'sunshine'
                MthType='Ave';
            case 'humidity'
                MthType='Ave';
            case 'temp'
                MthType='Ave';
            case 'evap'
                MthType='Tot';
            case 'solar'
                MthType='Ave';
            case 'wind'
                MthType='Ave';
            case 'ec'
                MthType='Ave';
            case 'minec'
                MthType='Ave';
            case 'meanec'
                MthType='Ave';
                case 'maxec'
                MthType='Ave';
            otherwise
        end

Ndec = 1;
Status='OK';
% Allow for possible negative temperatures
for mth=1:12
    for nd=1:31
        if DayRain(nd,mth)>=0;
            DayRain(nd,mth)=DayRain(nd,mth)+50;
        end
    end
end

% Set non existant days
if mod(Year,100) ~= 0 % Not a leap year
  if mod(Year,4) ~= 0, DayRain(29, 2) = -2; end
end

DayRain(30, 2) = -2;
DayRain(31, 2) = -2;  % Feb
DayRain(31, 4) = -2;  % Apr
DayRain(31, 6) = -2;  % Jun
DayRain(31, 9) = -2;  % Sep
DayRain(31, 11) = -2; % Nov

% Monthly Totals
for J = 1:12
    TotalMonth(J) = 0; DayMax(J) = 0; DayOfMax(J) = 0; DayMin(J) = 10^6; DayOfMin(J) = 0; Nvalid(J)=0;
    for M = 1:31
        if TotalMonth(J) ~= -1
        if DayRain(M, J) ~= -2 % Valid day
            if DayRain(M, J) ~= -1 %Valid data            ******************************************
                if DayRain(M, J) ~= -3 %Valid data
                Nvalid(J)=Nvalid(J)+1;
                end
                TotalMonth(J) = TotalMonth(J) + max(0,DayRain(M, J)); % check for accumulation ie -3
                % Set Day and Amount for Maximum
                if DayMax(J) < DayRain(M, J) & DayRain(max(1,M-1), J)~=-3 % Calculate Day and Amount for Maximum
                     DayMax(J) = DayRain(M, J); 
                     DayOfMax(J) = M;
                end
                if DayMin(J) > DayRain(M, J) & DayRain(max(1,M-1), J)~=-3 % Calculate Day and Amount for Maximum
                     DayMin(J) = DayRain(M, J); 
                     DayOfMin(J) = M;
                end
            else
                TotalMonth(J) = -1; DayMax(J) = -1;  DayMin(J) = -1; DayOfMax(J) = -1; DayOfMin(J) = -1;
                break;
            end
        end
        end
    end
end

% Annual Total
AnnualTotal = 0;
for J = 1:12
    if TotalMonth(J) >= 0 & AnnualTotal >= 0 % Monthly data OK
        AnnualTotal = AnnualTotal + TotalMonth(J);  % Calculate Annual Total
    else
        AnnualTotal = -1;
        break;
    end
end

fid = fopen(FilePathName,'w');
fprintf(fid, 'C\r\n'); %PRINT #9, "C"
fprintf(fid, 'C File Name:- %s\r\n', FilePathName); %PRINT #9, "C File Name:- " + FileName$
switch DataType
    case 'rain'
        fprintf(fid, 'C RAINFALL Station Name:- %s\r\n', StnName);
        MthType='Tot';
    case 'flow'
        fprintf(fid, 'C RUNOFF Station Name:- %s\r\n', StnName);
        MthType='Tot';
    case 'temp'
        fprintf(fid, 'C MAX DAILY TEMP. Station Name:- %s\r\n', StnName);
        MthType='Ave';
    case 'evap'
        fprintf(fid, 'C EVAPORATION Station Name:- %s\r\n', StnName);
        MthType='Tot';
    case 'wind'
        fprintf(fid, 'C WIND Station Name:- %s\r\n', StnName);
        MthType='Ave';
    otherwise
end
fprintf(fid, 'C                 -1 = missing data, -2 = non existant day, -3 = accumulated total\r\n'); 
fprintf(fid, 'C Year\r\n');
fprintf(fid, '%d\r\n', Year);
fprintf(fid, 'C Conversion Factor\r\n');
fprintf(fid, '1.0\r\n');
fprintf(fid, 'C\r\n');

fprintf(fid, 'Cd Jan    Feb    Mar    Apr    May    Jun    Jul    Aug    Sep    Oct    Nov    Dec\r\n'); 

for I = 1:31
    fprintf(fid, '%2d ', I); %PRINT #9, USING "## "; I%;
    for J = 1:12
        if DayRain(I,J)>0
            xx=DayRain(I,J)-50;
        else
            xx=DayRain(I,J);
        end
        [status]=FilePrintDec(fid,xx,6,0,1,max(0,J-11));
    end
   % if DayRain(I,J)>0
    %        xx=DayRain(I,12)-50;
     %   else
      %      xx=DayRain(I,12);
    %end
   % [status]=FilePrintDec(fid,xx,6,0,1,1);
    
    %fprintf(fid, '\r\n'); %PRINT #9,
end

if MthType == 'Tot'
    fprintf(fid, 'C Month Total\r\n'); %PRINT #9, "C Month Total"
    fprintf(fid, '   '); %PRINT #9, "   "; ' Space
    for I = 1:12
        if TotalMonth(I)<0
            xx=-1;
        else
            xx=TotalMonth(I)-Nvalid(I)*50;
        end
        fprintf(fid, '%5.1f  ', xx); %  PRINT #9, USING " ###.#"; TotalMonth(I%);
    end
    fprintf(fid, '\r\n'); %PRINT #9,
else
    fprintf(fid, 'C Month Ave  \r\n'); %PRINT #9, "C Month Total"
    fprintf(fid, '   '); %PRINT #9, "   "; ' Space
    for I = 1:12
        if TotalMonth(I)<0
            xx=-1;
        else
            xx=TotalMonth(I)/Nvalid(I)-50;
        end
        fprintf(fid, '%5.2f  ', xx); %  PRINT #9, USING " ###.#"; TotalMonth(I%);
    end
    fprintf(fid, '\r\n'); %PRINT #9,
end
    

fprintf(fid, 'C Daily Max\r\n'); %PRINT #9, "C Daily Max"
fprintf(fid, '   '); %PRINT #9, "   "; ' Space
for I = 1:12
    if DayMax(I)>0
        [status]=FilePrintDec(fid,DayMax(I)-50,6,0,1,0);
        %fprintf(fid, '%5.1f  ', DayMax(I)-50); %PRINT #9, USING " ###.#"; DayMax(I%);  
    else
        [status]=FilePrintDec(fid,-1,6,0,1,0);
        %fprintf(fid, '%5.1f  ', -1 );
    end
end
fprintf(fid, '\r\n'); % PRINT #9,

fprintf(fid, 'C Daily Min\r\n'); %PRINT #9, "C Day of Max"
fprintf(fid, '     '); %PRINT #9, "   "; ' Space
for I = 1:12
    if DayMin(I)>0
        [status]=FilePrintDec(fid,DayMin(I)-50,6,0,1,0);
        %fprintf(fid, '%5.1f  ', DayMax(I)-50); %PRINT #9, USING " ###.#"; DayMax(I%);  
    else
        [status]=FilePrintDec(fid,-1,6,0,1,0);
        %fprintf(fid, '%5.1f  ', -1 );
    end
end
fprintf(fid, '\r\n'); % PRINT #9,

if MthType=='Tot'
    fprintf(fid, 'C Annual Total\r\n'); %PRINT #9, "C Annual Total"
    if AnnualTotal >=0
        fprintf(fid, '%f\r\n', AnnualTotal-50*sum(Nvalid)); %PRINT #9, AnnualTotal
    else
        fprintf(fid, '%f\r\n', AnnualTotal)
    end
    fprintf(fid, 'C\r\n'); %PRINT #9, "C"
    fclose(fid);%CLOSE #9
    %'DO: LOOP WHILE INKEY$ = ""
else
    fprintf(fid, 'C Annual Ave  \r\n'); %PRINT #9, "C Annual Total"
    fprintf(fid, '%f\r\n', AnnualTotal/sum(Nvalid)-50); %PRINT #9, AnnualTotal
    fprintf(fid, 'C\r\n'); %PRINT #9, "C"
    fclose(fid);%CLOSE #9
end
    