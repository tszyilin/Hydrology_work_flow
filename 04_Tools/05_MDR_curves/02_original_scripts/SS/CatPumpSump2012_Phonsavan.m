function [Status]=CatPumpSump2012_Phonsavan(CatName,CatA,FF,ResultFile)

% Function CatPumpSump4 determines pump-sump combinations that provide surcharge
% protection for events upto the prescribed ARI on a catchment composed of multiple subcatchments
% each with their own runoff characteristics.

% MDR curve is of form:-  MDR =  AA + BB.Ln(ARI)
%                             where: AA= a(1)+ a(2)*(D^a(3)-1);
%                                    BB= a(4)+ a(5)*(D^a(6)-1);
%
% The 0 to 24 hr rainfall as ratio Y of the 24hr total is given by
% an ATan interpolation function fitted to dPdD @ 24 hrs and the P1hr/P24hr ratio

%
% Build 06 wjc meynink 19 May 2012
% This version is extension of CatPumpSump5
% Last mod wjcm 19/05/2012

% VARIABLES LIST
%
% a           - Multiday design rainfall curve parameter array.
% P1onP24     - Ratio(-) of 1hr to 24hr design rainfall typically 0.3 to 0.4
% CatA        - Catchment Area(km^2)
% FF          - SubCatchment/Component fraction
% ILa         - Catchment initial loss factor(-), as fraction of initial Fo
% Fo          - Initial/starting deficit(mm)
% Emax        - Max deficit growth rate(mm/d)
% Lag         - Catchment(s) lag (days)
% ARI         - Design Average Recurrence interval(a)
% Dcmin,Dcmax - Critical Duration limits for analysis(d)

a=[72.3667   24.8533    0.7525   30.4423    3.6566    0.8344]
P1onP24=0.45
ARI=[2     5    10    20    50   100   200]
RainStn='Phonsavan Comp '
%ILa=[0.1 0.1 0.1 0.1]
% Dump Only +++++++++++++++++++++++++++++++++++++++++++++
%ILa=[0.1 0.1 0.1 ]    % Dump Only
%Fo=[15 15 15]
%Emax=[3.5 3.5 2.0]
%Lag=[0.2 30 2]
%Dcmin=1.0; Dcmax=128
% +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


% Eastern Pit above French Drain Final ++++++++++++++++++++++++++++++
%ILa=[0.1 0.1 0.1 ]    
%Fo=[3 15 15]
%Emax=[1.5 3.5 3.5]
%Lag=[0.1 30 0.2]
%Dcmin=1.0; Dcmax=128
%++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

% Eastern Pit above French Drain Initial Mine Development++++++++++++++++++++++++++++++
ILa=[0.1 0.1 0.1 ]    
Fo=[3 50 50]
Emax=[1.5 3.5 3.5]
Lag=[0.1 30 0.2]
Dcmin=1.0; Dcmax=128
%++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++





nFF=length(Lag)
m=length(P1onP24)
Nari=length(ARI);

if m<Nari
    P1onP24(m+1:Nari)=P1onP24(m)
end

fid=fopen(ResultFile,'w');
fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' PUMP-SUMP Capacity Curves at Prescribed ARI');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',[' Rainfall Station:- ' RainStn]);
fprintf(fid,'%s\n',' MDR curve is of form:-  MDR =  AA + BB.Ln(ARI) ');
fprintf(fid,'%s\n','     where ')
fprintf(fid,'%s\n','           AA= a(1)+ a(2)*(D^a(3)-1)');
fprintf(fid,'%s\n','           BB= a(4)+ a(5)*(D^a(6)-1)');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' Best fit coefficients(ARI weighted least squares on ratio)');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','     #                Value   ');
fprintf(fid,'%s\n',['   a(1)             ' num2str(a(1))]);
fprintf(fid,'%s\n',['   a(2)             ' num2str(a(2))]);
fprintf(fid,'%s\n',['   a(3)             ' num2str(a(3))]);
fprintf(fid,'%s\n',['   a(4)             ' num2str(a(4))]);
fprintf(fid,'%s\n',['   a(5)             ' num2str(a(5))]);
fprintf(fid,'%s\n',['   a(6)             ' num2str(a(6))]);
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' Contributing Catchment runoff and Response Characteristics');
fprintf(fid,'%s\n',[' Catchment/Sump Name:- ' CatName]);
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','Flow        Initial Deficit     Initial Loss       Max Deficit        Storage    ');
fprintf(fid,'%s\n','Frac(-)     Fo(mm)              as Frac Fo(-)      growth(mm/d)       Lag(d)  ');
fprintf(fid,'%s\n','    ');

for i=1:nFF
[status]=FilePrintDec(fid,FF(i),11,0,4,0);
[status]=FilePrintDec(fid,Fo(i),19,0,11,0);
[status]=FilePrintDec(fid,ILa(i),18,0,10,0);
[status]=FilePrintDec(fid,Emax(i),18,0,10,0);
[status]=FilePrintDec(fid,Lag(i),12,0,3,1);
end
fprintf(fid,'%s\n','    ');

fprintf(fid,'%s\n','  ');        % page header
fprintf(fid,'%s\n','ARI     Total     Total     Excess    Excess  Storage Runoff          Pump                Sump            Pumpout');
fprintf(fid,'%s\n','(a)     Duration  Rainfall  Duration  Depth   Attn    (Inflow)|-------Capacity-----|      Capacity        Sump');
fprintf(fid,'%s\n','        (d)       (mm)      (d)       (mm)    (-)     (mm)    (mm/d)  (m^3/hr) (L/s)     (mm)   (m^3)     (d) ');
fprintf(fid,'%s\n','  ');


for i=1:Nari;
    fprintf(fid,'%s\n','    ');
    
    dD=0.2
   
    m=floor((Dcmax-Dcmin)/dD);

% Full range of durations at prescribed ARI
jmin(i)=0
    for j=1:m
        D(j)=Dcmin+(j-1)*dD;
        for k=1:nFF
            [P(j),R(j),Qk(k),dQdDk(k),d2QdD2(k),Dek(k)]=MDR_Design_P_Pe_Q2012(a,P1onP24(i),ARI(i),D(j),ILa(k),Fo(k),Emax(k),Lag(k));
        end
        d2QdD2bar=sum(d2QdD2.*FF);
        De(j)=sum(Dek.*FF);
        if d2QdD2bar<0
            %De(j)=sum(Dek.*FF)
            QQpump(j)=sum(dQdDk.*FF);
            QQ(j)=sum(Qk.*FF);
            VVsump(j)=QQ(j)-QQpump(j)*De(j);
            PumpOut(j)=VVsump(j)/QQpump(j);
        else
            QQpump(j)=-1;
            VVsump(j)= -1;
            QQ(j)=-1;
            PumpOut(j)=-1;
            jmin(i)=j
        end
        
      
        
        PPhi(j)=QQ(j)/R(j);
        if PPhi(j)<0
            PPhi(j)=-1;
        end
    end
    Dmin(i)=D(jmin(i)+1)            
    for j=jmin(i)+1:m  
        %if VVsump(max(1,j-1))>0
            [status]=FilePrintDec(fid,ARI(i),8,0,4,0);
            [status]=FilePrintDec(fid,D(j),8,0,2,0);
            [status]=FilePrintDec(fid,P(j),8,0,2,0);
            [status]=FilePrintDec(fid,De(j),8,0,2,0);
            [status]=FilePrintDec(fid,R(j),8,0,2,0);
            [status]=FilePrintDec(fid,PPhi(j),8,0,2,0);
            [status]=FilePrintDec(fid,QQ(j),8,0,2,0);

            [status]=FilePrintDec(fid,QQpump(j),8,0,2,0);
            [status]=FilePrintDec(fid,CatA*QQpump(j)*1000/24,8,0,2,0);
            [status]=FilePrintDec(fid,CatA*QQpump(j)*1000/24/3.6,8,0,2,0);
            [status]=FilePrintDec(fid,VVsump(j),8,0,2,0);
            [status]=FilePrintDec(fid,CatA*VVsump(j)*1000,8,0,2,0);
            [status]=FilePrintDec(fid,PumpOut(j),8,0,2,1);
       % end
    end

end

%fclose(fid)
fprintf(fid,'%s\n','  ');
fprintf(fid,'%s\n','  ');
fprintf(fid,'%s\n','  ');
fprintf(fid,'%s\n',' Data for Duration LINE PLOTTING');
fprintf(fid,'%s\n','  ');        % page header
fprintf(fid,'%s\n','ARI     Total     Total     Excess    Excess  Storage Runoff          Pump                Sump');
fprintf(fid,'%s\n','(a)     Duration  Rainfall  Duration  Depth   Attn    (Inflow)|-------Capacity-----|      Capacity');
fprintf(fid,'%s\n','        (d)       (mm)      (d)       (mm)    (-)     (mm)    (mm/d)  (m^3/hr) (L/s)     (mm)   (m^3)');


D=[1 2 4 6 8 10 12 16 20 24 32 64 128]
M=length(D)

for j=1:M
    % Full range of ARI for prescribed duration
    if D(j)>=Dcmin && D(j)<=Dcmax
        'Dcmin <  D(j) < Dcmax'
        fprintf(fid,'%s\n','    ');
        for i=1:Nari
            if D(j)>=Dmin(i)
            [P(j),P24,dPdD(j)] = MDR_DesignRainfall5B(a,ARI(i),D(j))   

             for k=1:nFF
                [P(j),R(j),Qk(k),dQdDk(k),d2QdD2(k),Dek(k)]=MDR_Design_P_Pe_Q2012(a,P1onP24(i),ARI(i),D(j),ILa(k),Fo(k),Emax(k),Lag(k))
             end

            d2QdD2bar=sum(d2QdD2.*FF);
            De(j)=sum(Dek.*FF);
                if d2QdD2bar<0
                    %De(j)=sum(Dek.*FF)
                    QQpump(j)=sum(dQdDk.*FF);
                    QQ(j)=sum(Qk.*FF);
                    VVsump(j)=QQ(j)-QQpump(j)*De(j);
                    PPhi(j)=QQ(j)/R(j);
                    [status]=FilePrintDec(fid,ARI(i),8,0,4,0);
                        [status]=FilePrintDec(fid,D(j),8,0,2,0);
                        [status]=FilePrintDec(fid,P(j),8,0,2,0);
                        [status]=FilePrintDec(fid,De(j),8,0,2,0);
                        [status]=FilePrintDec(fid,R(j),8,0,2,0);
                        [status]=FilePrintDec(fid,PPhi(j),8,0,2,0);
                        [status]=FilePrintDec(fid,QQ(j),8,0,2,0);

                        [status]=FilePrintDec(fid,QQpump(j),8,0,2,0);
                        [status]=FilePrintDec(fid,CatA*QQpump(j)*1000/24,8,0,2,0);
                        [status]=FilePrintDec(fid,CatA*QQpump(j)*1000/24/3.6,8,0,2,0);
                        [status]=FilePrintDec(fid,VVsump(j),8,0,2,0);
                        [status]=FilePrintDec(fid,CatA*VVsump(j)*1000,8,0,2,0);
                        [status]=FilePrintDec(fid,PumpOut(j),8,0,2,1);
                else
                    QQpump(j)=-1;
                    VVsump(j)= -1;
                    QQ(j)=-1;
                   
                end

            end 


        end
    end
end



fclose(fid);

Status=['Result File:  ' ResultFile '  Created'];

