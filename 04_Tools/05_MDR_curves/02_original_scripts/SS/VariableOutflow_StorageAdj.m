function [Shat,Qhat,AlphaHat]=VariableOutflow_StorageAdj(Pe,qmax,Dcrit,Sdead,b,c)

% Function determines the increased storage depth/volume and decrease in
% outflow volume associated with a detention system where outflow rate
% increases with storage level. For example outflow over a rectangle
% spillway rather than a constant rate pit pump.
% The effects of dead storage are also accomadated.

% Build 01 wjcm 11 Aug 2013 
% last mod wjcm 14/8/13 @ 2010hrs

% VARIABLES LIST
%
% Pe          - Total MDR rainfall excess/runoff volume for duration Dcrit [mm,m^3]
% qmax        - Design maximum outflow rate ie q at h=hmax [mm/d,m^3/d]
% Dcrit       - Critical duration for outflow rate qmax [d]
% Sdead       - Dry Dead storage at start of the design event [mm,m^3]
% b           - spillway head exponent in q ~ h^b [-] For constant pump rate b=0, for Vnotch b=2.5
% c           - storage elevation exponent in S ~ h^c [-]  NB  h from noflow not base of storage
%
% Shat        - Adjusted(increased) storage for solution with variable outflow rate [mm, m^3]
%               NB this is the required total storage including the prescribed dead storage 
% Qhat        - Adjusted(decreased) total outflow depth/volume with variable outflow rate [mm, m^3]
% AlphaHat    - Discharge efficiency factor. 1 for constant q (ie pump in vertical walled sump)
%               Average discharge as fraction of tangent point discharge

Ddead=(Sdead/Pe)*Dcrit;
Dlive=Dcrit-Ddead;
Q=qmax*Dlive;
S=Pe-Q;
alphaS=1/(b/c+1);

% interval halving search for AlphaHat
    x1=0.95*alphaS;                          % Min possible total storage domination
    y1=local_AlphaFit(S,Q,alphaS,x1);
    
    x3=1.1;                             % Max possible total outflow domination
    y3=local_AlphaFit(S,Q,alphaS,x3);
    
    if sign(y1)~=sign(y3);
          
        y2=100000;
        n1=0;
        while abs(y2)>0.00001 & n1<100;
            n1=n1+1;
            x2=(x1+x3)/2;
            y2=local_AlphaFit(S,Q,alphaS,x2);
            if sign(y1)==sign(y2);
                y1=y2;
                x1=x2;
            else
                y3=y2;
                x3=x2;
            end
        end
            
        AlphaHat=x2;
        Qhat=x2*Q;
        Shat=S+Q-Qhat;
        
    else
        disp('Starting out of range in StorageDependantOutflowAdj')
        AlphaHat=-1;
         Qhat=-1;
         Shat=-1;
    end
       
        
function [AlphaError]=local_AlphaFit(S,Q,alphaS,AlphaHatGuess)      

Qhat=AlphaHatGuess*Q;
Shat=S+Q-Qhat;
AlphaHat=(Shat*alphaS+Qhat)/(S+Q);
AlphaError=AlphaHatGuess-AlphaHat;

        
  