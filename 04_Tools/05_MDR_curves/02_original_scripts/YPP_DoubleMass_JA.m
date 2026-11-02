function [ B2AadjF,Nc,Rab,Bdblm,Rdblm,DblMcummRatio,DimMaxDev ] = YPP_DoubleMass_JA(A_YPPpathfilePrefix,B_YPPpathfilePrefix,Syr,Eyr,dAB,ResultFile,RptType )

% Function extracts common days of record & determines basic common day stats

% VARIABLES LIST

% A_YPPpathfilePrefix  - Station A source files prefix, full path/name
% B_YPPpathfilePrefix  - Station b source files prefix, full path/name
% Syr,Eyr              - Start & end years of analysis (missing data will be filled with -1s)
% dAB                  - Daily rainfall often read at 0900 and recorded on that day
%                        when most likely fell yesterday. Runoff is usually logged
%                        at midnight on that day so todays rainall tends to relate
%                        to yesterdays runoff. For this situation set dAB to 1.0
% ResultFile           - Complete path & name of results file
% RptType              - 'Full', 'Summary', or 'None'

% Nc                  - No commonday valid records
% QBarA,QBarB         - Mean valid day totals at each Stn (inc dry days)
% Rab                 - Double Mass curve correlation
% QavCumm,QbvCumm     - Cummulative valid dat totals

[Qa]=YPP2MemArray(A_YPPpathfilePrefix,Syr,Eyr); % Make daily rainfall vector from YPP

[Qb]=YPP2MemArray(B_YPPpathfilePrefix,Syr,Eyr); % Make daily rainfall vector from YPP


NdddStart=datenum(Syr,1,1);
Offset=NdddStart-1;


m=(length(Qa));
m=int32(m-dAB);
k=0;
for i=1:m
    if Qa(i+dAB)>=0.0 && Qb(i)>=0.0 && (Qa(i+dAB)+Qb(i))>0
        k=k+1
        RunningDay(k)=double(i);
        
        Qav(k)=Qa(i);
        Qbv(k)=Qb(i);
    end
end
Nc=k
QBarA=mean(Qav);
QBarB=mean(Qbv);
B2AadjF=QBarA/QBarB;
R=corrcoef(Qav,Qbv);
Rab=R(1,2);
QavCumm=cumsum(Qav);
QbvCumm=cumsum(Qbv);
DblMcummRatio=QavCumm(Nc)/QbvCumm(Nc);

[A, Bdblm, Rdblm, Vx, Vy, Vyx]=BestFitLine (QavCumm,QbvCumm,1);
Zero=RunningDay(1)-1;
DimMaxDev=0;
for k=1:Nc
    Dev=abs(QavCumm(k)/B2AadjF-QbvCumm(k))/QbvCumm(Nc);
    if Dev>DimMaxDev
        DimMaxDev=Dev;
    end
end

% Extract station names automatically from file prefixes
[~, nameA, ~] = fileparts(A_YPPpathfilePrefix);
[~, nameB, ~] = fileparts(B_YPPpathfilePrefix);
nameA = regexprep(nameA, '[^a-zA-Z]', '');
nameB = regexprep(nameB, '[^a-zA-Z]', '');

% Now plot
plot(QavCumm, QbvCumm, 'b-', 'LineWidth', 0.75)  % Thinner blue line for data
hold on

% Set axis limits to start at 0 and cover max range from data
maxVal = max([max(QavCumm), max(QbvCumm)]);
axis([0 maxVal 0 maxVal])  % [xmin xmax ymin ymax]

% Plot x=y dashed line within these limits
plot([0 maxVal], [0 maxVal], 'k--')  % x = y dashed line

xlabel([nameA ' cumulative rainfall (mm)'])  % X-axis label
ylabel([nameB ' cumulative rainfall (mm)'])  % Y-axis label

% Prevent scientific notation on axes
ax = gca;
ax.XAxis.Exponent = 0;
ax.YAxis.Exponent = 0;

hold off

% Save the plot as a JPEG in the same folder with the same base name as ResultFile
[outputFolder, baseFileName, ~] = fileparts(ResultFile);
saveFileName = fullfile(outputFolder, [baseFileName '.jpg']);
saveas(gcf, saveFileName, 'jpeg');
if nargin>5
    
    fid=fopen(ResultFile,'w');
    fprintf(fid,'%s\n','      Hidden Valley Rainfall Assessment')
    fprintf(fid,'%s\n','    ')
    fprintf(fid,'%s\n',' Double Mass Curve Analysis')
    fprintf(fid,'%s\n','    ')
    fprintf(fid,'%s\n',[' Station A Source File:- ' A_YPPpathfilePrefix])
    fprintf(fid,'%s\n',[' Station B Source File:- ' B_YPPpathfilePrefix])
    fprintf(fid,'%s\n','   ')
    fprintf(fid,'%s\n',[' # Analysis Period:- ' num2str(Syr) '    ' num2str(Eyr)])
    fprintf(fid,'%s\n','   ')
    fprintf(fid,'%s\n',[' # Common day records:- ' num2str(Nc)])
    fprintf(fid,'%s\n',[' Common day correlation coefficient(-):- ' num2str(Rab)])
    fprintf(fid,'%s\n',[' Common day B2A adjustment Factor(-):- ' num2str(B2AadjF)])
    fprintf(fid,'%s\n',[' Double Mass correlation coefficient(-):- ' num2str(Rdblm)])
    fprintf(fid,'%s\n',[' Double Mass Cummulative totals Ratio(-):- ' num2str(DblMcummRatio)])
    fprintf(fid,'%s\n',[' Double Mass gradient(B2A)(mm/mm):- ' num2str(Bdblm)])
    fprintf(fid,'%s\n','   ')

    if strcmp(RptType,'Full')==1
        fprintf(fid,'%s\n','  ')        % page header
        fprintf(fid,'%s\n','Running      StartDate        Station A    Station B     Cumm StnA    Cumm StnB')
        fprintf(fid,'%s\n','Day                           (mm)         (mm)          (mm)         (mm)')
        fprintf(fid,'%s\n','  ')



        for j=1:Nc
            [status]=FilePrintDec(fid,RunningDay(j),12,0,5,0);
            [Nyyyy,Mth,Nday]=datevec(Offset+RunningDay(j));
            [status]=FilePrintDec(fid,Nday,3,0,1,0);
            [status]=FilePrintDec(fid,Mth,3,0,1,0);
            [status]=FilePrintDec(fid,Nyyyy,8,0,4,0);
            [status]=FilePrintDec(fid,Qav(j),12,0,6,0);
            [status]=FilePrintDec(fid,Qbv(j),12,0,6,0);
            [status]=FilePrintDec(fid,QavCumm(j),12,0,4,0);
            [status]=FilePrintDec(fid,QbvCumm(j),12,0,4,1);
        end
    end
fclose(fid)
end

        