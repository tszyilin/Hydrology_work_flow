function [Status]=MHR_DesignCurvePlotData2012(a,ARI,MaxDur,dT,StnTitle,GrapherFile)

% function prepares depth-duration-ARI table for plotting curves in grapher. 
%
% MHR/MDR curve is of form:-  MDR =  AA + BB.Ln(ARI)
%                             where: AA= a(1)+ a(2)*(D^a(3)-1);
%                                    BB= a(4)+ a(5)*(D^a(6)-1);

%
% Build 2013 wjc meynink 21 Feb 2012
% Last mod wjcm 19 Aug 2013

% VARIABLES LIST
%
% a         - Coefficient vector [-]
% ARI       - Vector of individual ARI curves to be plotted [yrs]
% MinDur    - lower limit of duration for plot [d]
% MaxDur    - Upper limit of duration for plot [d]
% GrapherFile   - file used by grapher

Ncoef=length(a);
Nari=length(ARI);
a
ARI
pause

MinDur=1.0;

for j=1:Nari
    for i=1:(MaxDur-1)/dT+1
        D=MinDur+dT*(i-1);
        AA= a(1)+ a(2)*(D^a(3)-1);
        BB= a(4)+ a(5)*(D^a(6)-1);
        depth(i,j)=AA+BB*log(ARI(j));
        Gradient(i,j)=a(2)*a(3)*D^(a(3)-1)+a(5)*a(6)*D^(a(6)-1)*log(ARI(j));
        Storage(i,j)=depth(i,j)-Gradient(i,j)*D;
        DD(i)=D;
       
    end
end

fid=fopen(GrapherFile,'w')
fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' Multiday Design Rainfall Durations => 1 day');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',[' Station:- ' StnTitle]);
fprintf(fid,'%s\n','   ');
fprintf(fid,'%s\n',' Multiday Design Rainfall(MDR) is of the form:- ');
fprintf(fid,'%s\n',' MDR =  AA + BB.Ln(ARI)');
fprintf(fid,'%s\n','     where:  AA= a(1)+ a(2)*(D^a(3)-1)');
fprintf(fid,'%s\n','             BB= a(4)+ a(5)*(D^a(6)-1)');
fprintf(fid,'%s\n','    ');

fprintf(fid,'%s\n',[' Best fit MDR coefficients']);
[status]=FilePrintDec(fid,a(1),12,2,4,0);,[status]=FilePrintDec(fid,a(2),12,2,4,0);,[status]=FilePrintDec(fid,a(3),12,2,4,0);,[status]=FilePrintDec(fid,a(4),12,2,4,0);,[status]=FilePrintDec(fid,a(5),12,2,4,0);,[status]=FilePrintDec(fid,a(6),12,2,4,1);
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\','ARI(a) -->')
for i=1:Nari-1
    [status]=FilePrintDec(fid,ARI(i),27,10,13,0)
end
[status]=FilePrintDec(fid,ARI(Nari),27,10,13,1);    

fprintf(fid,'%s','Duration    Depth   Stor    Grad        ')
for j=1:Nari-2
            fprintf(fid,'%s','Depth   Stor    Grad        ')
end
          fprintf(fid,'%s\n','Depth   Stor    Grad        ')

fprintf(fid,'%s\','(Days)      (mm)    (mm)   (mm/d)       ')
for j=1:Nari-2
             fprintf(fid,'%s','(mm)    (mm)   (mm/d)       ')
end
           fprintf(fid,'%s\n','(mm)    (mm)   (mm/d)       ')

for i=1:(MaxDur-1)/dT+1
    [status]=FilePrintDec(fid,DD(i),7,0,2,0);
    for j=1:Nari-1
        fprintf(fid,'%s','    ');
        [status]=FilePrintDec(fid,depth(i,j),7,0,2,0);
        [status]=FilePrintDec(fid,Storage(i,j),7,0,2,0);
        [status]=FilePrintDec(fid,Gradient(i,j),7,0,2,0);
    end
    fprintf(fid,'%s','    ');
    [status]=FilePrintDec(fid,depth(i,Nari),7,0,2,0);
    [status]=FilePrintDec(fid,Storage(i,Nari),7,0,2,0);
    [status]=FilePrintDec(fid,Gradient(i,Nari),7,0,2,1);
end

% This for grapher plot data: Duration & depths only
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','            GRAPHER 10 MDR curves plot data');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\','ARI(a) -->')
for i=1:Nari-1
    [status]=FilePrintDec(fid,ARI(i),11,2,5,0)
end
[status]=FilePrintDec(fid,ARI(Nari),11,2,5,1);    

fprintf(fid,'%s','Duration    Depth       ')
for j=1:Nari-2
            fprintf(fid,'%s','Depth       ')
end
          fprintf(fid,'%s\n','Depth        ')

fprintf(fid,'%s\','(Days)      (mm)        ')
for j=1:Nari-2
             fprintf(fid,'%s','(mm)        ')
end
           fprintf(fid,'%s\n','(mm)       ')
fprintf(fid,'%s\n','    ');           

% fid=fopen(GrapherFile,'w')
for i=1:(MaxDur-1)/dT+1
    [status]=FilePrintDec(fid,DD(i),7,0,2,0);
    for j=1:Nari-1
        fprintf(fid,'%s','    ');
        [status]=FilePrintDec(fid,depth(i,j),7,0,2,0);
        
    end
    fprintf(fid,'%s','    ');
    [status]=FilePrintDec(fid,depth(i,Nari),7,0,2,1);
end

fclose(fid)

