function [Shat,Qhat,Dcrit,Pe]=VariableOutflowShatQhat_SqmaxTabsARI(a,P1onP24zero,Beta,b,c,Stab,qmaxTab,Sdead,ARI,StnTitle,ResultFile)

% Function determines Shat,Qhat pair for a precribed design ARI given the
% overflow spillway Surcharge-Storage Discharge curve(lookup table) by
% searching over qmax range for matching storage

% Build 01 wjcm 03 Sept 2013 
% last mod wjcm 03/9/13 @ 2010hrs

% VARIABLES LIST
%
% a             - MDR curve coefficient vector
% P1onP24zero
% Beta
% b             - spillway head exponent in q ~ h^b [-] For constant pump rate b=0, for Vnotch b=2.5
% c             - storage elevation exponent in S ~ h^c [-]  NB  h from noflow not base of storage
% Stab,qmaxTab  - Overflow spillway surcharge storage(mm) - discharge[mm/d] lookup table
% Sdead         - Dry Dead storage at start of the design event [mm,m^3]
%               - NB For spilling initial condition Dead storage is negative 
% ARI           - Prescribed average recurrence interval[yrs]

% Pe            - Total MDR rainfall excess/runoff volume for duration Dcrit [mm,m^3]
% qmax          - Design maximum outflow rate ie q at h=hmax [mm/d,m^3/d]
% Dcrit         - Critical duration for outflow rate qmax [d]
% Shat          - Adjusted(increased) storage for solution with variable outflow rate [mm, m^3]
%                 NB this is the required total storage including the prescribed dead storage 
% Qhat          - Adjusted(decreased) total outflow depth/volume with variable outflow rate [mm, m^3]
% AlphaHat      - Discharge efficiency factor. 1 for constant q (ie pump in vertical walled sump)
%               Average discharge as fraction of tangent point discharge



%Search for Shat,qmax combination at prescribed ARI interval halfing on
%qmax
n=length(ARI)
m=length(qmaxTab)

for j=1:n

    D=250
    Gradient=a(2)*a(3)*D^(a(3)-1)+a(5)*a(6)*D^(a(6)-1)*log(ARI(j));
    x1=1.01*Gradient;
        y1=local_qmax(a,b,c,Stab,qmaxTab,Sdead,ARI(j),x1);

        D=0.002
        Gradient=a(2)*a(3)*D^(a(3)-1)+a(5)*a(6)*D^(a(6)-1)*log(ARI(j));
        x3=0.99*Gradient;
        y3=local_qmax(a,b,c,Stab,qmaxTab,Sdead,ARI(j),x3);

        if sign(y1)~=sign(y3);

            y2=100000;
            n1=0
            while abs(y2)>0.00001& n1<100;
                n1=n1+1;
                x2=(x1+x3)/2;
                y2=local_qmax(a,b,c,Stab,qmaxTab,Sdead,ARI(j),x2);
               
                if sign(y1)==sign(y2);
                    y1=y2;
                    x1=x2;
                else
                    y3=y2;
                    x3=x2;
                end
            end

            qmax(j)=x2;
            [Dcrit(j),Pe(j)]= MDR_CriticalDuration(a,ARI(j),qmax(j));
            [Shat(j),Qhat(j),AlphaHat(j)]=VariableOutflow_StorageAdj(Pe(j),qmax(j),Dcrit(j),Sdead,b,c);
            Shatcrest(j)=Shat(j)-Sdead;
            Grad(j)=a(2)*a(3)*Dcrit(j)^(a(3)-1)+a(5)*a(6)*Dcrit(j)^(a(6)-1)*log(ARI(j));

        else

        end
end


fid=fopen(ResultFile,'w')
fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' MDR Curve Based Surcharge Storage Analysis');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',[' Location:- ' StnTitle]);
fprintf(fid,'%s\n','   ');
fprintf(fid,'%s\n',' Multiday Design Rainfall(MDR) is of the form:- ');
fprintf(fid,'%s\n',' MDR =  AA + BB.Ln(ARI)');
fprintf(fid,'%s\n','     where:  AA= a(1)+ a(2)*(D^a(3)-1)');
fprintf(fid,'%s\n','             BB= a(4)+ a(5)*(D^a(6)-1)');
fprintf(fid,'%s\n','    ');

fprintf(fid,'%s\n',[' Best fit MDR coefficients']);
[status]=FilePrintDec(fid,a(1),12,2,4,0);,[status]=FilePrintDec(fid,a(2),12,2,4,0);,[status]=FilePrintDec(fid,a(3),12,2,4,0);,[status]=FilePrintDec(fid,a(4),12,2,4,0);,[status]=FilePrintDec(fid,a(5),12,2,4,0);,[status]=FilePrintDec(fid,a(6),12,2,4,1);
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',['Spillway head exponent in q ~ h^b [-]:    ' num2str(b)  ]);
fprintf(fid,'%s\n',['Storage Elevation exponent in S ~ h^c [-]:    ' num2str(c) ]);
fprintf(fid,'%s\n',['Dry Dead storage at start of the design event [mm]:    ' num2str(Sdead)]);
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','    ');

fprintf(fid,'%s\n','ARI          Dcrit   Pe      Grad    Qmax    Qbar    Shat    Vhat    ')
fprintf(fid,'%s\n','(yrs)        (days)  (mm)    (mm/d)  (mm/d)  (mm/d)  (mm)    (mm)')
fprintf(fid,'%s\n','    ');

for j=1:n
        [status]=FilePrintDec(fid,ARI(j),12,0,7,0);
        [status]=FilePrintDec(fid,Dcrit(j),7,0,2,0);
        [status]=FilePrintDec(fid,Pe(j),7,0,2,0);
        [status]=FilePrintDec(fid,Grad(j),7,0,2,0);
        [status]=FilePrintDec(fid,qmax(j),7,0,2,0);
        [status]=FilePrintDec(fid,qmax(j)*AlphaHat(j),7,0,2,0);
        [status]=FilePrintDec(fid,Shatcrest(j),7,0,2,0);
        [status]=FilePrintDec(fid,Qhat(j),7,0,2,1);
    end
   
        
        function [Err]=local_qmax(a,b,c,Stab,qmaxTab,Sdead,ARI,qmaxtrial)
        
          
        [Dcrit,Pe]= MDR_CriticalDuration2014(a,ARI,qmaxtrial);
        [Shat]=VariableOutflow_StorageAdj(Pe,qmaxtrial,Dcrit,Sdead,b,c);
        [Sonqmax]=interp1(qmaxTab,Stab,qmaxtrial);
        Err=Sonqmax+Sdead-Shat;
        
        