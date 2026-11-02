function [amin,Status]=MDR_DesignCurveFit2022(ARIWgtPwr,DWgtPwr,SourceFile,ResultFile,StnTitle,NcolDur,NcolRank,NcolARI,NcolRain,ARImin,astart)

% function fits coefficients to multiday design rainfall data by the method of
% differential correction.
% Analyasis is on the basis of atmospheric storage and inflow. Single day events are largely seen as governed by storage
% while multiday events are driven by inflows.
%
% MDR curve is of form:-  MDR =  AA + BB.Ln(ARI)
%                             where: AA= a(1)+ a(2)*(D^a(3)-1);
%                                    BB= a(4)+ a(5)*(D^a(6)-1);

%
% Build 2012 wjc meynink 21 Feb 2012

% VARIABLES LIST
%
% ARIWgtPwr       - Weighting applied to point as power of ARI
% DWgtPwr         - Weighting applied to point as power of Duration
% SourceFile      - Ascii data file 1 row per point
% ResultFile      -
% StnTitle
% NcolDur,NcolRank,NcolARI,NcolRain - Source data file column locations
% ARImin          - Minimum ARI to be considered in fitting, typically 2yrs

% read in data
fid0=fopen(SourceFile,'r')
i=0;, j=0;

while feof(fid0)==0;
   j=j+1;
   b=fgetl(fid0);
   [x,n]=LineOfDec(b);
   if x(NcolARI)>=ARImin;
       i=i+1;
       Dur(i)=x(NcolDur);
       Rank(i)=x(NcolRank);
       ARI(i)=x(NcolARI);
       Y(i)=x(NcolRain);
      switch Dur(i)                % restricted sampling adjustment
          case 1
              Y(i)=1.10*Y(i);
          case 2
              Y(i)=1.07*Y(i);
          case 3
              Y(i)=1.02*Y(i);
          otherwise
      end

   end
end
M=i ;                                % total # data points
fclose(fid0)
disp(['data loaded, ' num2str(M) ' points'])
pause(1)
%**************************************************************************


% Find all fit duration
FitD(1)=1;
k=1;
for i=1:M
    if Dur(i)>FitD(k)
        k=k+1;
        FitD(k)=Dur(i);
    end
end
ND=k

R=[]
for kk=1:ND
   i=0
    Y1=[]
    ARI1=[]
    xx=[]
    for j=1:M
        if Dur(j)==FitD(kk)
            i=i+1;
            Dur1(i)=Dur(j);
            Y1(i)=Y(j);
            ARI1(i)=ARI(j);
            xx(i)=log(ARI1(i));
        end
    end
    M1=i

    % All duration max Fitting Parameter 1st Estimates
    %[A(kk),B(kk), R(kk), Vx, Vy, Vyx]=BestFitLine (xx,Y1,1) ;
    [AA1,BB1, R, Vx, Vy, Vyx]=BestFitLine (xx,Y1,1) ;

    % Now diff corr fit to ratio with ARI weighting
    %Stareting values
    bb(1)=AA1;
    bb(2)=BB1;
    bbmin=bb

    % ARI weighting factors
    ARIwgt=(ARI1.^ARIWgtPwr)
    ARIWgtTot=sum(ARIwgt)
    wgt=ARIwgt/ARIWgtTot

    Npar=2
    S2min=10000000; , S2NEW=0;
    K1=0
    Niter = 15;  % No iterations
    while K1 <=Niter  %&& S2NEW<S2min
        K1=K1+1
        S2NEW = 0
        for I = 1:M1
            FF = bb(1) + bb(2) * log(ARI1(I));
            Z(I) =FF/ Y1(I);  % Ratio

             R(I) =wgt(I)*( Z(I) - 1) ;         % Residual relative error
             S2NEW = S2NEW + R(I) * R(I);

             % Partial derivatives to follow here
             %   PD1:
             D(1, I) =wgt(I) / Y1(I);
             % PD2:
             D(2,I)=wgt(I)*(log(ARI1(I)))/Y1(I);
             % PD3:

        end

         if S2NEW<S2min
             S2min=S2NEW
             bbmin=bb
             pause(1)
         end

         for I = 1:Npar;
             for J = 1:Npar;
                 c(I, J) = 0;
                 for K = 1:M1;
                 c(I, J) = D(I, K) * D(J, K) + c(I, J);
                 end
             end
         end

         for I = 1:Npar;
             B1(I) = 0;
             for K = 1:M1;
                 B1(I) = D(I, K) * R(K) + B1(I);
             end
         end

         % now solve for corrections da

         dbb=c\B1';

        disp(['current value       correction'])
        adj=tanh(3*K1/Niter)
         for i = 1:Npar
             disp([num2str(bb(i)) '  ' num2str(-adj*dbb(i))])
             bb(i) = bb(i) -adj* dbb(i);
         end

         S2OLD = S2NEW
         S2 = sqrt(S2NEW / M)
         disp([' '])
         disp([' RMS ERROR =  ' num2str(S2)])
         disp([' Iteration #  ' num2str(K1)])
         % pause(1)
    end




    % Best fit data set
    %a=amin
    %pause
    for I = 1:M1
            %wgt=ARI(I)^WgtPwr/WgtTot

            % Expression to follow here
            Y1prd(I) = bbmin(1) + bbmin(2) * log(ARI1(I));
            dY1(I)=Y1(I)-Y1prd(I);
    end

    disp(['  1 Day Best Fit Dataset generated using bmin '])
    disp(bbmin)

    % Fit Statistics

    [NashEffbb(kk),rmsebb,Rsqbb,nBiasbb(kk),stdRatiobb]=NashSutcliff(Y1,Y1prd)

    A(kk)=bbmin(1);,B(kk)=bbmin(2);     % These are ARI wgted best fit on ratio coefficients
                                        % across durations 1 to kk

end


% *******************************************************************************************************

% Need best fit coefficients for A vs D based on ratio with weighted D

% Starting estimates
[AA, AB, R, Vx, Vy, Vyx]=BestFitLine (FitD,A,1);

    M1=ND
    S2min=1000000
    Npar=2
    Ao=A(1)
    aa(1)=AB
    aa(2)=1
    aamin=aa
    Z=[],   R=[],    D=[], Dwgt=[];

    % Point Density
    for i=2:ND-1
        Dens(i)=2/(FitD(i+1)-FitD(i-1))
    end
    Dens(1)=Dens(2)
    Dens(ND)=Dens(ND-1)

     % D weighting factors
    Dwgt=(FitD.^DWgtPwr)./sqrt(Dens)
    WgtTot=sum(Dwgt)
    Dwgt=Dwgt/WgtTot


    Niter = 15;  % No iterations
    for K1 = 1:Niter
        S2NEW = 0
        for I = 1:ND
            if FitD(I)==1
                Z(I)=Ao;
            else
                Z(I) = Ao + aa(1) *(FitD(I)^aa(2)-1);
            end


             R(I) = Dwgt(I)*(Z(I)/A(I)-1) ;         % Residual relative error
             S2NEW = S2NEW + R(I) * R(I);

             % Partial derivatives to follow here
             %   PD1:

             if FitD(I)==1
                 D(1,I)=0.0;
                 D(2,I)=0.0;
             else
                  D(1, I) =Dwgt(I)*(FitD(I)^aa(2)-1)/A(I);
                  D(2,I)=Dwgt(I)*aa(1) *(FitD(I)^aa(2)-1)*log(FitD(I))/A(I);
             end
             % PD3:
        end

         if S2NEW<S2min
             S2min=S2NEW
             aamin=aa
             pause(1)
         end

         for I = 1:Npar;
             for J = 1:Npar;
                 c(I, J) = 0;
                 for K = 1:ND-1;
                 c(I, J) = D(I, K) * D(J, K) + c(I, J);
                 end
             end
         end

         for I = 1:Npar;
             B1(I) = 0;
             for K = 1:ND-1;
                 B1(I) = D(I, K) * R(K) + B1(I);
             end
         end

         % now solve for corrections da

         daa=c\B1';

        disp(['current value       correction'])
        adj=tanh(2*K1/Niter)
         for i = 1:Npar
             disp([num2str(aa(i)) '  ' num2str(-adj*daa(i))])
             aa(i) = aa(i) -adj* daa(i);
         end

         S2OLD = S2NEW
         S2 = sqrt(S2NEW / M)
         disp([' '])
         disp(['A(I) = Ao + aa(1) *(FitD(I)^aa(2)-1)'])
         disp([' RMS ERROR =  ' num2str(S2)])
         disp([' Iteration #  ' num2str(K1)])
         pause(1)
    end

    % Best fit data set
    %a=amin
    %pause
    Y1prd=[];

    A1=aamin(1), A2=aamin(2);

    if A2>1
        A2=1;
        A1=AB;
    end
    for I = 1:ND
            %wgt=ARI(I)^WgtPwr/WgtTot

            % Expression to follow here
            Y1prd(I) = Ao + A1*(FitD(I)^A2-1);
    end


    disp(['  1 Day Best Fit Dataset generated using aamin '])
    disp(aamin)

    % Fit Statistics
    [NashEffbb,rmsebb,Rsqbb,nBiasbb,stdRatiobb]=NashSutcliff(A,Y1prd)


plot(FitD,A,FitD,Y1prd)
disp( ' Aobs vs D  &  Aprd vs D    have been plotted')
Ao,A1,A2
pause

% *******************************************************************************************************
% Need best fit coefficients for B vs D based on ratio with weighted D

% Starting estimates


[AB, BB, R, Vx, Vy, Vyx]=BestFitLine (FitD,B,1)

    M1=ND
    S2min=1000000
    Npar=2
    Bo=B(1)
    aa(1)=BB
    aa(2)=1
    aamin=aa
    Z=[],   R=[],    D=[];


    Niter = 20;  % No iterations
    for K1 = 1:Niter
        S2NEW = 0
        for I = 1:ND
            if FitD(I)==1
                Z(I)=Bo;
            else
                Z(I) = Bo + aa(1) *(FitD(I)^aa(2)-1);
            end


             R(I) = Dwgt(I)*(Z(I)/B(I)-1) ;         % Residual relative error
             S2NEW = S2NEW + R(I) * R(I);

             % Partial derivatives to follow here
             %   PD1:

             if FitD(I)==1
                 D(1,I)=0.0;
                 D(2,I)=0.0;
             else
                  D(1, I) =Dwgt(I)*(FitD(I)^aa(2)-1)/B(I);
                  D(2,I)=Dwgt(I)*aa(1) *(FitD(I)^aa(2)-1)*log(FitD(I))/B(I);
             end
             % PD3:
        end

        if S2NEW<S2min
             S2min=S2NEW
             aamin=aa
             pause(1)
         end

         for I = 1:Npar;
             for J = 1:Npar;
                 c(I, J) = 0;
                 for K = 1:ND-1;
                 c(I, J) = D(I, K) * D(J, K) + c(I, J);
                 end
             end
         end

         for I = 1:Npar;
             B1(I) = 0;
             for K = 1:ND-1;
                 B1(I) = D(I, K) * R(K) + B1(I);
             end
         end

         % now solve for corrections da

         daa=c\B1';

        disp(['current value       correction'])
        adj=tanh(4*(K1/Niter))^2
         for i = 1:Npar
             disp([num2str(aa(i)) '  ' num2str(-adj*daa(i))])
             aa(i) = aa(i) -adj* daa(i);
         end

         S2OLD = S2NEW
         S2 = sqrt(S2NEW / M)
         disp([' '])
         disp(['B(I) = Bo + aa(1) *(FitD(I)^aa(2)-1)'])
         disp([' RMS ERROR =  ' num2str(S2)])
         disp([' Iteration #  ' num2str(K1)])
         pause(1)
    end

    % Best fit data set
    %a=amin
    %pause
    Bb1=aamin(1), Bb2=aamin(2);
    disp(  '  Bo,Bb1,Bb2  3 parameter fit version')
    Bo,Bb1,Bb2
pause(20)






    if Bb2>1 | S2OLD==NaN                % Fix Bb2 to 1 & refit
        % This a straight line fit through the centroid
        Dbar=sum(Dwgt.*FitD)
        Bbar=sum(Dwgt.*B)
        Bb1=(Bbar-B(1))/(Dbar-1)
        Bbo=B(1)
        Bb2=1.00

        pause(3)
    end







    Y1prd=[];
    for I = 1:ND
            %wgt=ARI(I)^WgtPwr/WgtTot

            % Expression to follow here
            Y1prd(I) = Bo + Bb1*(FitD(I)^Bb2-1);
    end


    disp(['  Best Fit Dataset  B vs D   generated using aamin '])

    % Fit Statistics

    [NashEffbb,rmsebb,Rsqbb,nBiasbb,stdRatiobb]=NashSutcliff(B,Y1prd)



plot(FitD,B,FitD,Y1prd)

disp( ' Bobs vs D  &  Bprd vs D    have been plotted')
Bo,Bb1,Bb2
pause


% ***********************************************************************************************************
disp(' Design coefficients')
aaa(1)=Ao, aaa(2)=A1, aaa(3)=A2;
aaa(4)=Bo, aaa(5)=Bb1, aaa(6)=Bb2;

disp(aaa)

Yprd=[]
for I=1:M
    AA=Ao + A1 *(Dur(I)^A2-1);
    BB=Bo + Bb1*(Dur(I)^Bb2-1);

    Yprd(I)=AA+BB*log(ARI(I));
end

[NashEff,rmse,Rsq,nBias,stdRatio]=NashSutcliff(Y,Yprd)

pause(10)
% ***********************************************************************************************************



% OUTPUT BY DAYS
fid=fopen(ResultFile,'w');
fprintf(fid,'%s\n','            PSM AUSTRALIA Pty Ltd');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' Historic/Synthetic Rainfall Multiday Maxima Partial Series Model');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',[' Station:- ' StnTitle]);
fprintf(fid,'%s\n','   ');
fprintf(fid,'%s\n',' Multiday Design Rainfall(MDR) is of the form:- ');
fprintf(fid,'%s\n',' MDR=  AA + BB.Ln(ARI)');
fprintf(fid,'%s\n','           where: AA= a(1)+ a(2)*(D^a(3)-1)');
fprintf(fid,'%s\n','                  BB= a(4)+ a(5)*(D^a(6)-1)');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',[' Best fit coefficients(nonlinear least squares on ratio)  ']);
fprintf(fid,'%s\n',['     with:     ARI power wgt:-       ' num2str(ARIWgtPwr)]');
fprintf(fid,'%s\n',['               Duration power wgt:-  ' num2str(DWgtPwr)]');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','   Coefficient            Fit ');
fprintf(fid,'%s\','     a(1)             ');
[status]=FilePrintDec(fid,aaa(1),12,2,4,1);
fprintf(fid,'%s\','     a(2)             ');
[status]=FilePrintDec(fid,aaa(2),12,2,4,1);
fprintf(fid,'%s\','     a(3)             ');
[status]=FilePrintDec(fid,aaa(3),12,2,4,1);
fprintf(fid,'%s\','     a(4)             ');
[status]=FilePrintDec(fid,aaa(4),12,2,4,1);
fprintf(fid,'%s\','     a(5)             ');
[status]=FilePrintDec(fid,aaa(5),12,2,4,1);
fprintf(fid,'%s\','     a(6)             ');
[status]=FilePrintDec(fid,aaa(6),12,2,4,1);

fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',' MODEL FIT STATISTICS (unweighted)');
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n','    Statistic             Range            Target                Fit   ');
fprintf(fid,'%s\n',['   Efficiency         -inf   1.00          1.00               ' num2str(NashEff)]);
fprintf(fid,'%s\n',['   Correlation R^2    -1.00  1.00          1.00               ' num2str(Rsq)]);
fprintf(fid,'%s\n',['   Normalized Bias    -inf   inf           0.00               ' num2str(nBias)]);
fprintf(fid,'%s\n','    ');
fprintf(fid,'%s\n',['   Total # data points Fitted = ' num2str(M)]);
fprintf(fid,'%s\n','    ');


    fprintf(fid,'%s\n','  ')        % page header
    fprintf(fid,'%s\n','Days     Rank     ARI       Observed       Predicted');
    fprintf(fid,'%s\n','                  (a)       Multiday       Multiday ');
    fprintf(fid,'%s\n','                            Total(mm)      Total(mm)');
    fprintf(fid,'%s\n','  ');

    for i = 1:M ;
        [status]=FilePrintDec(fid,Dur(i),8,0,4,0);
        [status]=FilePrintDec(fid,Rank(i),8,0,3,0);
        [status]=FilePrintDec(fid,ARI(i),8,0,2,0);
        [status]=FilePrintDec(fid,Y(i),9,1,2,0);
        [status]=FilePrintDec(fid,Yprd(i),13,5,2,1);
    end


fclose(fid);
Status=[' Result File ' ResultFile ' created'];



