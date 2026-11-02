function [Dcrit,Pe,ErrCode]= MDR_CriticalDuration(a,ARI,qmax)

% Function determines critical duration at a prescribed ARI that yields a
% Tangent gradient to match qmax

% Build 01 wjcm 03 Sept 2013 
% last mod wjcm 03/9/13 @ 2010hrs

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


     x1=1;         % Min Duration
    [y1]=local_Match(a,ARI,qmax,x1 );
    
    x3=250;   % Max duration
    [y3]=local_Match(a,ARI,qmax,x3 );
        
    if sign(y1)~=sign(y3);
          
        y2=100000;
        n1=0;
        while abs(y2)>0.001& n1<100;
            n1=n1+1;
            x2=sqrt(x1*x3);
            [y2]=local_Match(a,ARI,qmax,x2 );
            
            if sign(y1)==sign(y2);
                y1=y2;
                x1=x2;
            else
                y3=y2;
                x3=x2;
            end
        end
            
        Dcrit=x2;
         AA= a(1)+ a(2)*(Dcrit^a(3)-1);
        BB= a(4)+ a(5)*(Dcrit^a(6)-1);
        Pe=AA+BB*log(ARI);
        ErrCode=0.0;
    else
        disp('Starting out of range in MDR_CriticalDuration')
        if y1>0
            disp(' Critical duration is less than 1 day')
            ErrCode=-1
        else
            disp(['critical duration is greater than  ' num2str(x3)])
            ErrCode=1
            
        end
        pause
    end
  

function [Err]=local_Match(a,ARI,qmax,D )

AA= a(1)+ a(2)*(D^a(3)-1);
BB= a(4)+ a(5)*(D^a(6)-1);
Gradient=a(2)*a(3)*D^(a(3)-1)+a(5)*a(6)*D^(a(6)-1)*log(ARI);
Err=qmax-Gradient;

        