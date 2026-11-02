function [Status]=MDR240hr_DesignCurveData2012(a,P1onP24zero,ARI,GrapherFile,StnTitle,FoSo)

% function prepares 0 to 120hour depth-duration-ARI table for plotting curves in grapher. 
% Analyasis is on the basis of atmospheric storage and inflow. Single day events are largely seen as governed by storage 
% while multiday events are driven by inflows.
%
% MDR curve is of form:-  MDR =  AA + BB.Ln(ARI)
%                             where: AA= a(1)+ a(2)*(D^a(3)-1);
%                                    BB= a(4)+ a(5)*(D^a(6)-1);
%
% Build 2012 wjc meynink 21 Feb 2012
% Last mod wjcm 2/3/2012
%
% VARIABLES LIST
%
% a            - Coefficient vector defining MDR curves
% ARI          - Vector of individual ARI curves to be plotted
% Alpha,Beta   - Coefficients defining Ratio of 1 hour rainfall to 24 hour rainfall at same freq.
%                PR=1/24+Alpha*exp(Beta*Ln(ARI))
% GrapherFile  - file used by grapher

% 1st day interpolation parameters

Nari=length(ARI);

for i=1:20, Dur(i+1)=i/10;, end

for i=21:35, Dur(i+1)=2+(i-20)/4;, end

for i=36:46, Dur(i+1)=6+(i-37)/2;, end

for i=47:276, Dur(i+1)=10+(i-46);, end
Ndur=277;

for j=1:Nari
    depth(1,j)=0.0;
    % Ratio=1/24+Alpha*exp(Beta*log(ARI(j)))
    for i=2:Ndur
      [depth(i,j)]=MDR_DesignRainfall2012(a,P1onP24zero,ARI(j),Dur(i)/24);
      FoS=max(1,(1+(FoSo-1)*(sqrt(120)-sqrt(Dur(i)))/sqrt(120)));
      depth(i,j)=FoS*depth(i,j);
    end
end

fid=fopen(GrapherFile,'w')
fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' Design Rainfall 0 -240 hours based on Multiday Maxima Partial Series Model with 0-24hr interpolation');
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
fprintf(fid,'%s\n',[' Short Duration Declining Factor of Safety:- ' num2str(FoSo)  ]);
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\','ARI(a) -->')
for i=1:Nari-1
    [status]=FilePrintDec(fid,ARI(i),24,10,10,0)
end
[status]=FilePrintDec(fid,ARI(Nari),24,10,10,1);    

fprintf(fid,'%s','Duration      Rain      Intensity      ')
for j=1:Nari-2
         fprintf(fid,'%s','Rain      Intensity      ')
end
        fprintf(fid,'%s\n','Rain      Intensity     ')

fprintf(fid,'%s\','(Hours)       (mm)      (mm/hr)        ')
for j=1:Nari-2
         fprintf(fid,'%s','(mm)      (mm/hr)        ')
end
        fprintf(fid,'%s\n','(mm)      (mm/hr)       ')


for i=2:20
    [status]=FilePrintDec2(fid,Dur(i),13,0,5,0);
    for j=1:Nari-1
        [status]=FilePrintDec2(fid,depth(i,j),9,0,6,0);
        [status]=FilePrintDec2(fid,depth(i,j)/Dur(i),14,0,8,0);
    end
    [status]=FilePrintDec2(fid,depth(i,Nari),9,0,6,0);
    [status]=FilePrintDec2(fid,depth(i,Nari)/Dur(i),14,0,8,1);
    
end
        
for i=21:Ndur
    [status]=FilePrintDec2(fid,Dur(i),13,0,5,0);
    for j=1:Nari-1
        [status]=FilePrintDec2(fid,depth(i,j),9,0,6,0);
        [status]=FilePrintDec2(fid,depth(i,j)/Dur(i),14,0,8,0);
    end
    [status]=FilePrintDec2(fid,depth(i,Nari),9,0,6,0);
    [status]=FilePrintDec2(fid,depth(i,Nari)/Dur(i),14,0,8,1);
    
end
fclose(fid)


